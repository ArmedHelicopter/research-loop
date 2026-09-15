"""Project non-authorizing scorer-finalization text observations into catalogues."""
from __future__ import annotations

import hashlib
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
                      journal_snapshot: Mapping[str, Any], attempt: Mapping[str, Any]) -> dict[str, Any]:
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
            "attempt": dict(attempt), "authorization": "none",
            "scientific_status": "not_measured"}


def register_admission_headless_scorer_finalization_observations(*, root: Path, config,
        panel, service) -> FrozenRecord:
    """Register one non-authorizing projection per observed event and task identity.

    The source journal remains the original text evidence.  This bridge verifies
    its chain, text digests, current scorer-process source hash, exact frozen
    scorer configuration/provider, and panel before it writes any descriptor.
    It never treats an observation as a score, closure authority, or a semantic
    parent of a task artifact.
    """
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
    controller = _snapshot(root / "controller-attempt.json")
    attempt = {"schema": "admission-headless-scorer-finalization-attempt-binding-v1",
               "controller_attempt": controller, "observation_journal": before}
    run_id = FrozenRecord.from_dict(attempt).content_hash
    refs = (
        _reference("frozen_scorer_config", scorer.data()),
        _reference("frozen_evaluator_provider", expected_provider),
        _reference("frozen_panel", binding),
        _reference("controller_attempt_prefix", attempt),
    )
    identities = tuple(sorted({cell.identity for cell in panel.cells},
                              key=lambda value: canonical(value.data())))
    records = []
    source = source_snapshot(Path(__file__))
    for identity in identities:
        identity.require_train()
        key = FrozenRecord.from_dict(identity.data()).content_hash
        catalogue = ArtifactCatalogue(root / "scorer-finalization-observations" / key / "artifacts.jsonl",
            identity=identity, run_id=run_id, experiment_id=_EXPERIMENT,
            lock_digest=config.record.content_hash, producer_source=source)
        if catalogue.records():
            raise ContractError("scorer finalization observation catalogue already exists")
        for row in rows:
            event = row["event"]
            status = "rejected" if event["status"] == "rejected" else "produced"
            records.append(catalogue.append(
                kind=f"admission_scorer_finalization_{event['status']}_observation",
                module=None, coverage="uncovered", status=status,
                payload=_event_projection(event, observation_digest=row["digest"],
                                          journal_snapshot=before, attempt=attempt),
                producer_source=source, config_refs=refs,
                checks=(_reference("observation_chain_row", {"schema": "headless-evaluator-client-chain-row-v1",
                    "sequence": row["sequence"], "digest": row["digest"],
                    "previous": row["previous"]}),)))
        catalogue.seal()
    return FrozenRecord.from_dict({"schema": "admission-headless-scorer-finalization-observation-catalogues-v1",
        "attempt": attempt, "panel_digest": panel.digest,
        "catalogues": [{"identity": identity.data(),
                         "path": str((root / "scorer-finalization-observations" /
                                      FrozenRecord.from_dict(identity.data()).content_hash / "artifacts.jsonl").resolve()),
                         "record_digests": [record.content_hash for record in records
                                            if record.data()["identity"] == identity.data()]}
                        for identity in identities],
        "authorization": "none", "scientific_status": "not_measured"})
