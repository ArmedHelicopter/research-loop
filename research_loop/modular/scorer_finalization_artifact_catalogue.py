"""Project non-authorizing scorer-finalization text observations into catalogues."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Mapping

from evaluation.modular.scorer_process import read_headless_client_observations
from research_loop.modular.artifact_catalogue import ArtifactCatalogue, source_snapshot
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.ontology import ContractError, canonical

_SCHEMA = "admission-headless-scorer-finalization-observation-projection-v1"
_EXPERIMENT = "admission-prediction-exploration:scorer-finalization-observations"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _reference(kind: str, value: Mapping[str, Any]) -> dict[str, Any]:
    frozen = FrozenRecord.from_dict(value)
    return {"kind": kind, "digest": frozen.content_hash, "canonical": frozen.data()}


def _snapshot(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ContractError("scorer finalization observation original is unavailable") from exc
    return {"path": str(path.resolve()), "sha256": _sha(raw), "bytes": len(raw)}


def _panel_binding(panel) -> dict[str, Any]:
    cells = [cell.data() for cell in sorted(panel.cells, key=lambda item: item.key)]
    return {"schema": "admission-headless-scorer-finalization-panel-binding-v1",
            "panel_digest": panel.digest, "obligation_id": panel.obligation_id,
            "cells": cells}


def _event_projection(event: Mapping[str, Any], *, observation_digest: str,
                      journal_snapshot: Mapping[str, Any], attempt: Mapping[str, Any],
                      panel_member: DataIdentity) -> dict[str, Any]:
    # Deliberately omit request_text and response_text. The original append-only
    # journal retains them; this catalogue contains only digest-bound metadata.
    status = event["status"]
    selected = {name: event[name] for name in (
        "attempt_id", "nonce", "panel_digest", "scorer_config_digest",
        "evaluator_provider", "request_sha256", "producer_source_sha256",
        "text_representation")}
    if status == "response_received":
        selected.update(response_sha256=event["response_sha256"],
                        response_utf8_bytes=event["response_utf8_bytes"])
    elif status == "authenticated":
        selected.update(closure_digest=event["closure_digest"],
                        response_sha256=event["response_sha256"])
    elif status == "rejected":
        selected.update(error_type=event["error_type"], response_sha256=event["response_sha256"],
                        score_eligible=False)
    return {"schema": _SCHEMA, "observation_digest": observation_digest,
            "status": status, "event": selected, "observation_journal": dict(journal_snapshot),
            "attempt": dict(attempt), "panel_member_association": {
                "kind": "panel_member", "identity": panel_member.data()}, "authorization": "none",
            "scientific_status": "not_measured"}


def _attempt_prefix(root: Path, *, create: bool) -> dict[str, Any]:
    original = root / "controller-attempt.json"
    prefix = root / "scorer-finalization-observations" / "controller-attempt-prefix.json"
    if create:
        raw = original.read_bytes()
        prefix.parent.mkdir(parents=True, exist_ok=True)
        try:
            with prefix.open("xb") as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        except FileExistsError:
            if prefix.read_bytes() != raw:
                raise ContractError("scorer finalization attempt prefix already differs")
    return _snapshot(prefix)


def _closure_binding(*, evaluator_gate: Mapping[str, Any], rows: tuple[Mapping[str, Any], ...]) -> dict[str, Any]:
    """Bind the retained final gate to this journal's final terminal event.

    An ineligible gate without a captured closure may still project rejected or
    incomplete client observations.  A captured closure, including a valid
    partial closure, must be the exact closure authenticated by the last
    journal attempt; an eligible gate may never use a rejected or unbound tail.
    """
    if (not isinstance(evaluator_gate, Mapping)
            or type(evaluator_gate.get("score_eligible")) is not bool):
        raise ContractError("admission evaluator final gate is malformed")
    closure = evaluator_gate.get("closure")
    if closure is None:
        if evaluator_gate["score_eligible"]:
            raise ContractError("eligible evaluator final gate lacks a closure")
        return {"schema": "admission-headless-scorer-finalization-closure-binding-v1",
                "status": "no_closure_ineligible", "closure_digest": None,
                "score_eligible": False}
    try:
        closure_digest = FrozenRecord.from_dict(closure).content_hash
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        raise ContractError("admission evaluator final gate closure is malformed") from exc
    terminal = rows[-1]["event"]
    if (terminal["status"] != "authenticated"
            or terminal["closure_digest"] != closure_digest):
        raise ContractError("admission evaluator final gate closure differs from journal terminal")
    return {"schema": "admission-headless-scorer-finalization-closure-binding-v1",
            "status": "authenticated_exact", "closure_digest": closure_digest,
            "score_eligible": evaluator_gate["score_eligible"]}


def _validated_observations(*, root: Path, config, panel, service, evaluator_gate: Mapping[str, Any], create_attempt_prefix: bool):
    root = Path(root)
    if (not isinstance(config.record, FrozenRecord) or not isinstance(service.config.record, FrozenRecord)
            or not isinstance(service.evaluator_provider, dict)):
        raise ContractError("typed admission scorer finalization inputs required")
    scorer = service.config.record
    if scorer.data() != config.data()["scorer"]:
        raise ContractError("service scorer configuration differs from frozen admission config")
    observation_path = Path(str(service.journal_path) + ".headless-evaluator-client.jsonl")
    before = _snapshot(observation_path)
    rows = read_headless_client_observations(observation_path)
    after = _snapshot(observation_path)
    if before != after or not rows:
        raise ContractError("scorer finalization observation journal changed or is absent")
    scorer_source = source_snapshot(Path(__file__).parents[2] / "evaluation" / "modular" / "scorer_process.py")
    binding = _panel_binding(panel)
    expected_provider = config.data().get("evaluator_provider")
    if (expected_provider != service.evaluator_provider
            or any(row["event"]["panel_digest"] != panel.digest
                   or row["event"]["scorer_config_digest"] != scorer.content_hash
                   or row["event"]["evaluator_provider"] != expected_provider
                   or row["event"]["producer_source_sha256"] != scorer_source["sha256"]
                   for row in rows)):
        raise ContractError("scorer finalization observations differ from frozen admission bindings")
    closure_binding = _closure_binding(evaluator_gate=evaluator_gate, rows=rows)
    controller = _attempt_prefix(root, create=create_attempt_prefix)
    attempt = {"schema": "admission-headless-scorer-finalization-attempt-binding-v1",
               "controller_attempt_prefix": controller, "observation_journal": before}
    refs = (
        _reference("frozen_scorer_config", scorer.data()),
        _reference("frozen_evaluator_provider", expected_provider),
        _reference("frozen_panel", binding),
        _reference("controller_attempt_prefix", attempt),
    )
    identities = tuple(sorted({cell.identity for cell in panel.cells},
                              key=lambda value: canonical(value.data())))
    if not identities or any(identity.domain != "train" for identity in identities):
        raise ContractError("admission finalization observations require actual TRAIN panel members")
    return root, scorer, rows, before, attempt, refs, identities, closure_binding


def _catalogue_path(root: Path, identity: DataIdentity) -> Path:
    return root / "scorer-finalization-observations" / FrozenRecord.from_dict(identity.data()).content_hash / "artifacts.jsonl"


def register_admission_headless_scorer_finalization_observations(*, root: Path, config,
        panel, service, evaluator_gate: Mapping[str, Any]) -> FrozenRecord:
    """Register one non-authorizing projection per observed event and task identity.

    The source journal remains the original text evidence.  This bridge verifies
    its chain, text digests, current scorer-process source hash, exact frozen
    scorer configuration/provider, panel, and final-gate closure binding before
    it writes any descriptor.  It never treats an observation as a score,
    closure authority, or a semantic
    parent of a task artifact.
    """
    root, _, rows, before, attempt, refs, identities, closure_binding = _validated_observations(
        root=root, config=config, panel=panel, service=service, evaluator_gate=evaluator_gate,
        create_attempt_prefix=True)
    run_id = FrozenRecord.from_dict(attempt).content_hash
    source = source_snapshot(Path(__file__))
    anchors = []
    for identity in identities:
        catalogue = ArtifactCatalogue(_catalogue_path(root, identity), identity=identity,
            run_id=run_id, experiment_id=_EXPERIMENT,
            lock_digest=config.record.content_hash, producer_source=source)
        if catalogue.records():
            raise ContractError("scorer finalization observation catalogue already exists")
        descriptors = []
        for row in rows:
            event = row["event"]
            status = "rejected" if event["status"] == "rejected" else "produced"
            descriptors.append(catalogue.append(
                kind=f"admission_scorer_finalization_{event['status']}_observation",
                module=None, coverage="uncovered", status=status,
                payload=_event_projection(event, observation_digest=row["digest"],
                                          journal_snapshot=before, attempt=attempt, panel_member=identity),
                producer_source=source, config_refs=refs,
                checks=(_reference("observation_chain_row", {"schema": "headless-evaluator-client-chain-row-v1",
                    "sequence": row["sequence"], "digest": row["digest"],
                    "previous": row["previous"]}),)))
        seal = catalogue.seal()
        anchors.append({"identity": identity.data(), "path": str(catalogue.path.resolve()),
                        "record_digests": [record.content_hash for record in descriptors],
                        "seal": seal.data(), "seal_digest": seal.content_hash})
    # A second byte snapshot makes a changing source journal fail closed rather
    # than certifying a projection of an earlier, now-stale prefix.
    if _snapshot(Path(str(service.journal_path) + ".headless-evaluator-client.jsonl")) != before:
        raise ContractError("scorer finalization observation journal changed during catalogue projection")
    return FrozenRecord.from_dict({"schema": "admission-headless-scorer-finalization-observation-catalogues-v1",
        "attempt": attempt, "panel_digest": panel.digest, "closure_binding": closure_binding,
        "catalogues": anchors, "authorization": "none", "scientific_status": "not_measured"})


def verify_admission_headless_scorer_finalization_observation_catalogues(*, root: Path,
        config, panel, service, evaluator_gate: Mapping[str, Any], receipt: FrozenRecord) -> None:
    """Re-read originals and require exact, sealed non-authorizing projections."""
    if not isinstance(receipt, FrozenRecord):
        raise ContractError("frozen scorer finalization observation receipt required")
    root, _, rows, before, attempt, refs, identities, closure_binding = _validated_observations(
        root=root, config=config, panel=panel, service=service, evaluator_gate=evaluator_gate,
        create_attempt_prefix=False)
    body = receipt.data()
    if (set(body) != {"schema", "attempt", "panel_digest", "closure_binding", "catalogues", "authorization", "scientific_status"}
            or body["schema"] != "admission-headless-scorer-finalization-observation-catalogues-v1"
            or body["attempt"] != attempt or body["panel_digest"] != panel.digest
            or body["closure_binding"] != closure_binding
            or body["authorization"] != "none" or body["scientific_status"] != "not_measured"
            or not isinstance(body["catalogues"], list) or len(body["catalogues"]) != len(identities)):
        raise ContractError("scorer finalization observation receipt binding differs")
    run_id = FrozenRecord.from_dict(attempt).content_hash
    source = source_snapshot(Path(__file__))
    anchors = {canonical(anchor.get("identity")): anchor for anchor in body["catalogues"] if isinstance(anchor, dict)}
    if len(anchors) != len(identities):
        raise ContractError("scorer finalization observation identities differ")
    for identity in identities:
        anchor = anchors.get(canonical(identity.data()))
        path = _catalogue_path(root, identity)
        if (anchor is None or set(anchor) != {"identity", "path", "record_digests", "seal", "seal_digest"}
                or anchor["path"] != str(path.resolve()) or not isinstance(anchor["record_digests"], list)):
            raise ContractError("scorer finalization observation catalogue anchor differs")
        catalogue = ArtifactCatalogue(path, identity=identity, run_id=run_id,
            experiment_id=_EXPERIMENT, lock_digest=config.record.content_hash, producer_source=source)
        seal = FrozenRecord.from_dict(anchor["seal"])
        if seal.content_hash != anchor["seal_digest"]:
            raise ContractError("scorer finalization observation seal digest differs")
        catalogue.verify(seal)
        records = catalogue.records()
        expected = []
        for row in rows:
            event = row["event"]
            status = "rejected" if event["status"] == "rejected" else "produced"
            expected.append({"kind": f"admission_scorer_finalization_{event['status']}_observation",
                "status": status, "payload": _event_projection(event, observation_digest=row["digest"],
                    journal_snapshot=before, attempt=attempt, panel_member=identity), "check": _reference("observation_chain_row",
                    {"schema": "headless-evaluator-client-chain-row-v1", "sequence": row["sequence"],
                     "digest": row["digest"], "previous": row["previous"]})})
        if len(records) != len(expected) or anchor["record_digests"] != [record.content_hash for record in records]:
            raise ContractError("scorer finalization observation records differ")
        for record, item in zip(records, expected, strict=True):
            descriptor = record.data()
            if (descriptor["kind"] != item["kind"] or descriptor["module"] is not None
                    or descriptor["coverage"] != "uncovered" or descriptor["parents"] != []
                    or descriptor["status"] != item["status"]
                    or descriptor["payload"]["canonical"] != item["payload"]
                    or descriptor["config_refs"] != list(refs) or descriptor["checks"] != [item["check"]]
                    or descriptor["producer_source"] != source
                    or descriptor["cost"] != {"known": False, "units": None}
                    or descriptor["optimizer_visible"] is not False
                    or descriptor["scientific_validated"] is not False):
                raise ContractError("scorer finalization observation projection differs")
        # Verify the caller-provided seal again after all descriptor reads.
        catalogue.verify(seal)
    if (_snapshot(Path(str(service.journal_path) + ".headless-evaluator-client.jsonl")) != before
            or _snapshot(root / "scorer-finalization-observations" / "controller-attempt-prefix.json")
            != attempt["controller_attempt_prefix"]):
        raise ContractError("scorer finalization originals changed during catalogue verification")
