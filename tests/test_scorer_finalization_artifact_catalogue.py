import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluation.modular.scorer_process import read_headless_client_observations
from evaluation.modular.scoring_service import ScorerConfig
from research_loop.modular.artifact_catalogue import ArtifactCatalogue, source_snapshot
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.scorer_finalization_artifact_catalogue import (
    register_admission_headless_scorer_finalization_observations,
    verify_admission_headless_scorer_finalization_observation_catalogues,
)
from research_loop.ontology import ContractError, canonical


_PROVIDER = {"kind": "grok-headless-frozen-evaluator-v1", "configuration_digest": "a" * 64}


class _Config:
    def __init__(self, scorer):
        self.record = FrozenRecord.from_dict({"scorer": scorer.record.data(), "evaluator_provider": _PROVIDER})

    def data(self):
        return self.record.data()


def _cell(identity, label):
    body = {"identity": identity.data(), "label": label}
    return SimpleNamespace(identity=identity, key=(label,), data=lambda: body)


def _write_observations(path, *, scorer, panel_digest, provider=_PROVIDER, rejected=False):
    source = hashlib.sha256((Path(__file__).parents[1] / "evaluation/modular/scorer_process.py").read_bytes()).hexdigest()
    base = {"schema": "headless-evaluator-client-observation-v1", "attempt_id": "attempt-1", "nonce": "n" * 32,
            "panel_digest": panel_digest, "scorer_config_digest": scorer.record.content_hash,
            "evaluator_provider": provider, "request_sha256": hashlib.sha256(b'{}\n').hexdigest(),
            "producer_source_sha256": source,
            "text_representation": "python_text_write_input_and_decoded_read_output"}
    response = canonical({"closure": {"body": {"nonce": "n" * 32}, "mac": "not-authority"}})
    events = [
        {**base, "status": "requested", "request_text": "{}\n"},
        {**base, "status": "response_received", "response_text": response,
         "response_sha256": hashlib.sha256(response.encode()).hexdigest(), "response_utf8_bytes": len(response.encode())},
        ({**base, "status": "rejected", "error_type": "ContractError",
          "response_sha256": hashlib.sha256(response.encode()).hexdigest(), "score_eligible": False}
         if rejected else
         {**base, "status": "authenticated", "closure_digest": FrozenRecord.from_dict(json.loads(response)["closure"]).content_hash,
          "response_sha256": hashlib.sha256(response.encode()).hexdigest()}),
    ]
    previous = None; rows = []
    for sequence, event in enumerate(events, 1):
        row = {"schema": "headless-evaluator-client-journal-v1", "sequence": sequence, "previous": previous, "event": event}
        row["digest"] = FrozenRecord.from_dict(row).content_hash
        previous = row["digest"]; rows.append(row)
    path.write_text("".join(canonical(row) + "\n" for row in rows), encoding="utf-8")
    return rows


def _gate(rows, *, score_eligible=False):
    response = next(row["event"]["response_text"] for row in rows
                    if row["event"]["status"] == "response_received")
    return {"schema": "ordinary-headless-evaluator-final-gate-v1",
            "status": "eligible" if score_eligible else "inconclusive",
            "score_eligible": score_eligible,
            "closure": json.loads(response)["closure"]}


def _no_closure_gate():
    return {"schema": "ordinary-headless-evaluator-final-gate-v1", "status": "inconclusive",
            "score_eligible": False, "closure": None}


def _inputs(tmp_path, *, provider=_PROVIDER):
    scorer = ScorerConfig.create(benchmark="core_pair", evaluator_id="synthetic", version="v1", rubric_digest="c" * 64)
    identities = (DataIdentity("blade", "b", "g", "v1", "split", "train"),
                  DataIdentity("discoverybench", "d", "g", "v1", "split", "train"))
    panel = SimpleNamespace(digest="p" * 64, obligation_id="triple:M1+M4+M7",
                            cells=(_cell(identities[1], "d"), _cell(identities[0], "b")))
    journal = tmp_path / "client.jsonl"
    rows = _write_observations(Path(str(journal) + ".headless-evaluator-client.jsonl"),
                               scorer=scorer, panel_digest=panel.digest, provider=provider)
    root = tmp_path / "run"; root.mkdir()
    (root / "controller-attempt.json").write_text(canonical({"schema": "attempt", "cells": []}), encoding="utf-8")
    return root, _Config(scorer), panel, SimpleNamespace(config=scorer, evaluator_provider=provider, journal_path=journal), rows


def test_registers_per_identity_non_authorizing_text_observations(tmp_path):
    root, config, panel, service, rows = _inputs(tmp_path)
    receipt = register_admission_headless_scorer_finalization_observations(
        root=root, config=config, panel=panel, service=service, evaluator_gate=_gate(rows))
    assert receipt.data()["authorization"] == "none"
    assert len(receipt.data()["catalogues"]) == 2
    verify_admission_headless_scorer_finalization_observation_catalogues(
        root=root, config=config, panel=panel, service=service, evaluator_gate=_gate(rows), receipt=receipt)
    run_id = FrozenRecord.from_dict(receipt.data()["attempt"]).content_hash
    for anchor in receipt.data()["catalogues"]:
        catalogue = ArtifactCatalogue(Path(anchor["path"]), identity=DataIdentity.parse(anchor["identity"]),
                                      run_id=run_id,
                                      experiment_id="admission-prediction-exploration:scorer-finalization-observations",
                                      lock_digest=config.record.content_hash)
        assert FrozenRecord.from_dict(anchor["seal"]).content_hash == anchor["seal_digest"]
        catalogue.verify(FrozenRecord.from_dict(anchor["seal"]))
        records = catalogue.records()
        body = Path(anchor["path"]).read_text(encoding="utf-8")
        assert "response_text" not in body and "request_text" not in body
        assert len(records) == len(rows) == len(anchor["record_digests"])
        assert all(record.data()["module"] is None and record.data()["coverage"] == "uncovered"
                   and record.data()["parents"] == []
                   and record.data()["payload"]["canonical"]["panel_member_association"] == {
                       "kind": "panel_member", "identity": anchor["identity"]}
                   for record in records)


def test_rejects_observation_provider_drift_before_any_catalogue(tmp_path):
    root, config, panel, service, rows = _inputs(tmp_path, provider={**_PROVIDER, "configuration_digest": "b" * 64})
    with pytest.raises(ContractError):
        register_admission_headless_scorer_finalization_observations(root=root, config=config, panel=panel, service=service, evaluator_gate=_gate(rows))
    assert not (root / "scorer-finalization-observations").exists()


def test_reader_chain_is_rechecked_before_projection(tmp_path):
    root, config, panel, service, rows = _inputs(tmp_path)
    path = Path(str(service.journal_path) + ".headless-evaluator-client.jsonl")
    path.write_text(path.read_text(encoding="utf-8").replace('"attempt-1"', '"changed"', 1), encoding="utf-8")
    with pytest.raises(ContractError):
        register_admission_headless_scorer_finalization_observations(root=root, config=config, panel=panel, service=service, evaluator_gate=_gate(rows))
    assert not (root / "scorer-finalization-observations").exists()


def test_rejected_terminal_is_catalogued_without_score_authority(tmp_path):
    root, config, panel, service, rows = _inputs(tmp_path)
    _write_observations(Path(str(service.journal_path) + ".headless-evaluator-client.jsonl"),
                        scorer=service.config, panel_digest=panel.digest, rejected=True)
    receipt = register_admission_headless_scorer_finalization_observations(
        root=root, config=config, panel=panel, service=service, evaluator_gate=_no_closure_gate())
    assert receipt.data()["closure_binding"]["status"] == "no_closure_ineligible"
    for anchor in receipt.data()["catalogues"]:
        rows = [json.loads(line)["descriptor"] for line in Path(anchor["path"]).read_text(encoding="utf-8").splitlines()]
        terminal = rows[-1]
        assert terminal["status"] == "rejected"
        assert terminal["payload"]["canonical"]["authorization"] == "none"
        assert terminal["payload"]["canonical"]["scientific_status"] == "not_measured"


def test_readback_rejects_changed_original_journal(tmp_path):
    root, config, panel, service, rows = _inputs(tmp_path)
    receipt = register_admission_headless_scorer_finalization_observations(
        root=root, config=config, panel=panel, service=service, evaluator_gate=_gate(rows))
    path = Path(str(service.journal_path) + ".headless-evaluator-client.jsonl")
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ContractError):
        verify_admission_headless_scorer_finalization_observation_catalogues(
            root=root, config=config, panel=panel, service=service, evaluator_gate=_gate(rows), receipt=receipt)


def test_readback_rejects_original_changed_during_descriptor_reads(tmp_path, monkeypatch):
    root, config, panel, service, rows = _inputs(tmp_path)
    receipt = register_admission_headless_scorer_finalization_observations(
        root=root, config=config, panel=panel, service=service, evaluator_gate=_gate(rows))
    original = ArtifactCatalogue.records
    changed = False
    def racing_records(catalogue):
        nonlocal changed
        records = original(catalogue)
        if not changed:
            changed = True
            path = Path(str(service.journal_path) + ".headless-evaluator-client.jsonl")
            path.write_bytes(path.read_bytes() + b" ")
        return records
    monkeypatch.setattr(ArtifactCatalogue, "records", racing_records)
    with pytest.raises(ContractError):
        verify_admission_headless_scorer_finalization_observation_catalogues(
            root=root, config=config, panel=panel, service=service, evaluator_gate=_gate(rows), receipt=receipt)

def test_rejects_valid_but_different_gate_closure_before_projection(tmp_path):
    root, config, panel, service, rows = _inputs(tmp_path)
    different = FrozenRecord.from_dict({"body": {"nonce": "z" * 32}, "mac": "different"}).data()
    gate = {**_gate(rows), "closure": different}
    with pytest.raises(ContractError):
        register_admission_headless_scorer_finalization_observations(
            root=root, config=config, panel=panel, service=service, evaluator_gate=gate)
    assert not (root / "scorer-finalization-observations").exists()


def test_success_gate_cannot_bind_a_rejected_journal_terminal(tmp_path):
    root, config, panel, service, _ = _inputs(tmp_path)
    rows = _write_observations(Path(str(service.journal_path) + ".headless-evaluator-client.jsonl"),
                               scorer=service.config, panel_digest=panel.digest, rejected=True)
    with pytest.raises(ContractError):
        register_admission_headless_scorer_finalization_observations(
            root=root, config=config, panel=panel, service=service,
            evaluator_gate=_gate(rows, score_eligible=True))
    assert not (root / "scorer-finalization-observations").exists()


def test_partial_authenticated_closure_is_retained_but_ineligible(tmp_path):
    root, config, panel, service, rows = _inputs(tmp_path)
    gate = _gate(rows, score_eligible=False)
    receipt = register_admission_headless_scorer_finalization_observations(
        root=root, config=config, panel=panel, service=service, evaluator_gate=gate)
    assert receipt.data()["closure_binding"] == {
        "schema": "admission-headless-scorer-finalization-closure-binding-v1",
        "status": "authenticated_exact",
        "closure_digest": FrozenRecord.from_dict(gate["closure"]).content_hash,
        "score_eligible": False}
    verify_admission_headless_scorer_finalization_observation_catalogues(
        root=root, config=config, panel=panel, service=service, evaluator_gate=gate, receipt=receipt)


def _rechain_and_reseal(path, mutate):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    previous = None; rebuilt = []
    for sequence, entry in enumerate(rows):
        descriptor = entry["descriptor"]
        mutate(descriptor)
        frozen = FrozenRecord.from_dict(descriptor)
        rebuilt_entry = FrozenRecord.from_dict({"schema": "artifact-catalogue-entry-v2", "sequence": sequence,
            "previous": previous, "descriptor_digest": frozen.content_hash, "descriptor": frozen.data()})
        rebuilt.append(rebuilt_entry); previous = rebuilt_entry.content_hash
    path.write_text("".join(entry.encoded + "\n" for entry in rebuilt), encoding="utf-8")
    seal = FrozenRecord.from_dict({"schema": "artifact-catalogue-seal-v1", "count": len(rebuilt),
        "head": previous, "binding": rows[0]["descriptor"]["binding"]})
    path.with_name(path.name + ".seal.json").write_text(seal.encoded + "\n", encoding="utf-8")
    return seal


@pytest.mark.parametrize("field", ("producer_source", "cost", "optimizer_visible"))
def test_readback_rejects_rehashed_resealed_descriptor_metadata_drift(tmp_path, field):
    root, config, panel, service, rows = _inputs(tmp_path)
    receipt = register_admission_headless_scorer_finalization_observations(
        root=root, config=config, panel=panel, service=service, evaluator_gate=_gate(rows))
    body = receipt.data(); anchors = []
    for anchor in body["catalogues"]:
        path = Path(anchor["path"])
        def mutate(descriptor):
            if field == "producer_source":
                descriptor[field] = source_snapshot(Path(__file__).parents[1] / "evaluation/modular/scorer_process.py")
            elif field == "cost":
                descriptor[field] = {"known": True, "units": 0}
            else:
                descriptor[field] = True
        seal = _rechain_and_reseal(path, mutate)
        anchors.append({**anchor, "seal": seal.data(), "seal_digest": seal.content_hash,
                        "record_digests": [FrozenRecord(line).data()["descriptor_digest"]
                                           for line in path.read_text(encoding="utf-8").splitlines()]})
    forged = FrozenRecord.from_dict({**body, "catalogues": anchors})
    with pytest.raises(ContractError):
        verify_admission_headless_scorer_finalization_observation_catalogues(
            root=root, config=config, panel=panel, service=service,
            evaluator_gate=_gate(rows), receipt=forged)
