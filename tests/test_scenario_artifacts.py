"""Focused producer/reader checks for Q6 scenario sidecar artifacts."""
from pathlib import Path
from dataclasses import replace
import hashlib
import os
import sqlite3

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.scenarios_improvement import (
    inspect_scenario_artifact_failure, run_improvement_scenario,
    verify_scenario_artifacts,
)
from research_loop.ontology import ContractError
from test_modular_improvement_scenarios import controls, task_for


def _directory_link(target, link):
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def _remove_directory_link(link):
    # Remove only the link itself; never recursively traverse its target.
    if os.name == "nt":
        assert link.is_junction()
        link.rmdir()
    else:
        assert link.is_symlink()
        link.unlink()


def test_linked_parent_is_rejected_before_scenario_directory_creation(tmp_path):
    outside = tmp_path / "outside"; outside.mkdir()
    link = tmp_path / "alias"; _directory_link(outside, link)
    calls = []
    try:
        with pytest.raises(ContractError, match="linked"):
            _run(link / "attempt", "Q6.1", "change_rule", lambda request: calls.append(request))
        assert not list(outside.iterdir()) and not calls
    finally:
        _remove_directory_link(link)


@pytest.mark.parametrize("nested", [False, True])
def test_reader_rejects_link_before_opening_retained_outputs(tmp_path, monkeypatch, nested):
    result, args = _run(tmp_path / "run", "Q6.6", "promote")
    root = args["sidecar"]
    outside = tmp_path / "outside"; outside.mkdir()
    (outside / "not-a-scenario.txt").write_bytes(b"outside retained scope")
    parent = root / "extra" if nested else root
    parent.mkdir(exist_ok=True)
    link = parent / "alias"; _directory_link(outside, link)
    original_bytes, original_text = Path.read_bytes, Path.read_text
    def deny_artifact_read(path, original, *args, **kwargs):
        if path.is_relative_to(root) or path.is_relative_to(outside):
            raise AssertionError("reader opened output before checking every path")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_bytes", lambda p: deny_artifact_read(p, original_bytes))
    monkeypatch.setattr(Path, "read_text", lambda p, *a, **k: deny_artifact_read(p, original_text, *a, **k))
    try:
        with pytest.raises(ContractError, match="linked"):
            verify_scenario_artifacts(result, **args)
    finally:
        _remove_directory_link(link)


def test_callback_link_preserves_original_error_and_incomplete_prefix(tmp_path):
    outside = tmp_path / "outside"; outside.mkdir()
    root = tmp_path / "run"; link = root / "alias"
    error = RuntimeError("original callback failure")
    def callback(_request):
        _directory_link(outside, link)
        raise error
    try:
        with pytest.raises(RuntimeError) as caught:
            _run(root, "Q6.1", "change_rule", callback)
        assert caught.value is error
        assert "scenario artifact closure failure: ContractError" in error.__notes__
        assert (root / "scenario-artifacts.jsonl").is_file()
        assert not (root / "scenario-closure.json").exists()
        assert not list(outside.iterdir())
    finally:
        _remove_directory_link(link)


def test_actual_return_gate_requires_original_closure(tmp_path, monkeypatch):
    from research_loop.modular.scenario_artifacts import ScenarioArtifactWriter
    close = ScenarioArtifactWriter.close
    def incomplete(writer, **kwargs):
        close(writer, **kwargs)
        (writer.root / "scenario-closure.json").unlink()
    monkeypatch.setattr(ScenarioArtifactWriter, "close", incomplete)
    with pytest.raises(ContractError, match="missing"):
        _run(tmp_path / "run", "Q6.2", "fixed")
    assert (tmp_path / "run" / "scenario-result.json").is_file()


def test_validation_is_rejected_before_scenario_directory_creation(tmp_path):
    task = task_for("blade")
    from research_loop.modular.contracts import PublicTask
    task = PublicTask.create(replace(task.identity, domain="validation"), task.payload.data())
    with pytest.raises(ContractError, match="training"):
        run_improvement_scenario("Q6.1", "change_rule", task=task, frozen_controls=controls(task), sidecar=tmp_path / "run")
    assert not (tmp_path / "run").exists()


def test_callback_subclass_is_rejected_consistently_at_producer_and_reader(tmp_path):
    class DerivedRecord(FrozenRecord):
        pass
    root = tmp_path / "run"
    with pytest.raises(ContractError, match="must return FrozenRecord"):
        _run(root, "Q6.1", "change_rule", lambda _: DerivedRecord('{"reply":"typed subclass"}'))
    task = task_for("blade")
    report = inspect_scenario_artifact_failure(task=task, frozen_controls=controls(task), sidecar=root,
                                              experiment_id="Q6.1", variant="change_rule")
    assert report.data()["storage_integrity_verified"] and not report.data()["acceptance_eligible"]


def _run(root: Path, experiment: str, variant: str, callback=None):
    task = task_for("blade")
    args = dict(task=task, frozen_controls=controls(task), sidecar=root,
                experiment_id=experiment, variant=variant)
    result = run_improvement_scenario(callback=callback, **args)
    return result, args


@pytest.mark.parametrize(("experiment", "variant", "sidecars"), [
    ("Q6.1", "self_activate", {"runtime.sqlite", "active.json"}),
    ("Q6.2", "automatic_train", {"optimizer.sqlite"}),
    ("Q6.5", "unprotected", {"shadow-runtime.sqlite", "shadow-deployment.json"}),
    ("Q6.6", "rollback", {"runtime.sqlite", "deployment.json"}),
])
def test_actual_offline_scenario_outputs_are_sealed_and_read_without_rerun(tmp_path, monkeypatch,
                                                                              experiment, variant, sidecars):
    calls = []
    def callback(request):
        calls.append(request)
        if request.data()["kind"] == "train_candidate_proposal":
            return FrozenRecord.from_dict({"changes": {"memory": {"mode": "automatic", "lesson": "fixture"}}})
        return FrozenRecord.from_dict({"reply": request.data()["kind"]})
    result, args = _run(tmp_path / "run", experiment, variant, callback)
    root = args["sidecar"]
    assert sidecars <= {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    assert result.callback_payloads == tuple(calls)
    terminal = FrozenRecord((root / "scenario-terminal.json").read_text(encoding="utf-8").strip()).data()
    assert terminal["status"] == "succeeded" and terminal["fixture_only"] is True
    assert all(set(v) == {"sha256", "bytes"} for v in terminal["files"].values())
    before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    monkeypatch.setattr("research_loop.modular.scenarios_improvement.ExecutionRuntime", lambda *a, **k: (_ for _ in ()).throw(AssertionError("reader activated runtime")))
    assert verify_scenario_artifacts(result, **args).data()["status"] == "succeeded"
    assert before == {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_failed_callback_keeps_sealed_prefix_and_is_not_accepted(tmp_path):
    error = ContractError("fixture callback stopped")
    calls = 0
    def callback(_request):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise error
        return FrozenRecord.from_dict({"reply": "first retained callback"})
    with pytest.raises(ContractError) as caught:
        _run(tmp_path / "run", "Q6.5", "sealed_calibrated", callback)
    assert caught.value is error
    task = task_for("blade"); root = tmp_path / "run"
    terminal = FrozenRecord((root / "scenario-terminal.json").read_text(encoding="utf-8").strip()).data()
    assert terminal["status"] == "failed" and terminal["result_digest"] is None
    assert "shadow-runtime.sqlite" in terminal["files"]
    before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    report = inspect_scenario_artifact_failure(task=task, frozen_controls=controls(task), sidecar=root,
                                               experiment_id="Q6.5", variant="sealed_calibrated").data()
    assert report["storage_integrity_verified"] and not report["acceptance_eligible"]
    assert before == {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("returned", [None, {"not": "frozen"}])
def test_first_callback_opportunity_and_invalid_return_are_retained(tmp_path, returned):
    root = tmp_path / "run"
    with pytest.raises(ContractError):
        _run(root, "Q6.1", "change_rule", lambda _request: returned)
    rows = [FrozenRecord(line).data()["descriptor"] for line in (root / "scenario-artifacts.jsonl").read_text(encoding="utf-8").splitlines()]
    request = next(row for row in rows if row["kind"] == "scenario_callback_request")
    outcome = next(row for row in rows if row["kind"] == "scenario_callback_return")
    assert request["payload"]["canonical"]["kind"] == "privilege_attempt"
    assert outcome["payload"]["canonical"]["returned_type"] == type(returned).__name__
    assert outcome["status"] == "rejected"


def test_throwing_first_callback_keeps_request_and_failure_outcome(tmp_path):
    root = tmp_path / "run"; error = RuntimeError("fixture callback failure")
    with pytest.raises(RuntimeError) as caught:
        _run(root, "Q6.1", "change_rule", lambda _request: (_ for _ in ()).throw(error))
    assert caught.value is error
    rows = [FrozenRecord(line).data()["descriptor"] for line in (root / "scenario-artifacts.jsonl").read_text(encoding="utf-8").splitlines()]
    outcome = next(row for row in rows if row["kind"] == "scenario_callback_return")
    assert outcome["status"] == "failed" and outcome["payload"]["canonical"]["error"] == str(error)


def test_failed_malformed_runtime_bytes_are_retained_without_success_parse(tmp_path):
    root = tmp_path / "run"; error = RuntimeError("stop after malformed sidecar"); calls = 0
    def callback(_request):
        nonlocal calls
        calls += 1
        if calls == 2:
            (root / "shadow-runtime.sqlite").write_bytes(b"partial sqlite bytes")
            raise error
        return FrozenRecord.from_dict({"reply": "first"})
    with pytest.raises(RuntimeError):
        _run(root, "Q6.5", "sealed_calibrated", callback)
    terminal = FrozenRecord((root / "scenario-terminal.json").read_text(encoding="utf-8").strip()).data()
    assert terminal["status"] == "failed" and terminal["files"]["shadow-runtime.sqlite"]["bytes"] > 0
    report = inspect_scenario_artifact_failure(task=task_for("blade"), frozen_controls=controls(task_for("blade")),
                                               sidecar=root, experiment_id="Q6.5", variant="sealed_calibrated")
    assert report.data()["storage_integrity_verified"]


def test_failed_reader_requires_every_sealed_blob(tmp_path):
    root = tmp_path / "run"; calls = 0
    def callback(_request):
        nonlocal calls
        calls += 1
        if calls == 2: raise RuntimeError("stop")
        return FrozenRecord.from_dict({"reply": "first"})
    with pytest.raises(RuntimeError):
        _run(root, "Q6.5", "sealed_calibrated", callback)
    blob = next((root / "scenario-blobs").iterdir()); blob.unlink()
    task = task_for("blade")
    with pytest.raises(ContractError):
        inspect_scenario_artifact_failure(task=task, frozen_controls=controls(task), sidecar=root,
                                          experiment_id="Q6.5", variant="sealed_calibrated")


def _read_record(path):
    return FrozenRecord(path.read_text(encoding="utf-8").strip())


def _write_record(path, body):
    path.write_bytes((FrozenRecord.from_dict(body).encoded + "\n").encode("utf-8"))


def _reseal(root, *, result=None, mutate=None, omit=None):
    """An attacker repairs every storage hash, preserving semantic falsifications.

    Use the real catalogue reader to prove rejection is not a broken outer seal.
    This intentionally does not use the scenario writer or its storage helpers.
    """
    from research_loop.modular.artifact_catalogue import ArtifactCatalogue
    from research_loop.modular.contracts import DataIdentity
    path = root / "scenario-artifacts.jsonl"
    descriptors = [FrozenRecord(line).data()["descriptor"] for line in path.read_text(encoding="utf-8").splitlines()]
    if result is not None:
        _write_record(root / "scenario-result.json", result.record.data())
    ignored = {"scenario-artifacts.jsonl", "scenario-artifacts.jsonl.seal.json", "scenario-terminal.json",
               "scenario-closure.json", "scenario-file-manifest.json"}
    files = {p.name: {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
             for p in sorted(root.iterdir()) if p.is_file() and p.name not in ignored}
    blobs = root / "scenario-blobs"
    blobs.mkdir(exist_ok=True)
    for blob in blobs.iterdir():
        blob.unlink()
    items = [{"file": name, "blob": "scenario-blobs/" + value["sha256"], **value} for name, value in files.items()]
    for item in items:
        (root / item["blob"]).write_bytes((root / item["file"]).read_bytes())
    _write_record(root / "scenario-file-manifest.json", {"schema": "m9-scenario-file-manifest-v1", "files": items, "fixture_only": True})
    terminal = _read_record(root / "scenario-terminal.json").data()
    terminal["files"] = files
    if result is not None:
        terminal["result_digest"] = result.record.content_hash
    _write_record(root / "scenario-terminal.json", terminal)

    def snapshot(name):
        raw = (root / name).read_bytes()
        return {"file": name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}

    entries, parent = [], None
    for body in descriptors:
        kind = body["kind"]
        if omit is not None and omit(body):
            continue
        payload = body["payload"]["canonical"]
        if kind in {"scenario_result", "scenario_terminal", "scenario_file_manifest"}:
            payload = snapshot(payload["file"])
        elif kind == "scenario_sidecar":
            payload = next(item for item in items if item["file"] == payload["file"])
        if mutate:
            mutate(body, payload)
        frozen = FrozenRecord.from_dict(payload)
        body["payload"] = {"canonical": frozen.data(), "digest": frozen.content_hash,
                           "bytes": len(frozen.encoded.encode()), "encoding": "canonical_json"}
        body["parents"] = [parent] if parent else []
        descriptor = FrozenRecord.from_dict(body)
        entries.append(FrozenRecord.from_dict({"schema": "artifact-catalogue-entry-v2", "sequence": len(entries),
            "previous": entries[-1].content_hash if entries else None, "descriptor_digest": descriptor.content_hash,
            "descriptor": descriptor.data()}))
        parent = descriptor.content_hash
    path.write_text("".join(entry.encoded + "\n" for entry in entries), encoding="utf-8")
    first = entries[0].data()["descriptor"]
    seal = {"schema": "artifact-catalogue-seal-v1", "count": len(entries), "head": entries[-1].content_hash,
            "binding": first["binding"]}
    _write_record(root / "scenario-artifacts.jsonl.seal.json", seal)
    _write_record(root / "scenario-closure.json", {"schema": "m9-scenario-closure-v1", "catalogue_seal": seal,
                                                   "terminal": snapshot("scenario-terminal.json")})
    ArtifactCatalogue(path, identity=DataIdentity.parse(first["identity"]), **first["binding"],
                      producer_source=first["producer_source"]).verify(FrozenRecord.from_dict(seal))


@pytest.mark.parametrize("experiment,variant", [
    ("Q6.1", "change_rule"), ("Q6.1", "read_validation"), ("Q6.1", "forge_receipt"),
    ("Q6.2", "fixed"), ("Q6.2", "manual_train"), ("Q6.2", "automatic_train"),
    ("Q6.5", "sealed_calibrated"), ("Q6.6", "promote"), ("Q6.6", "drift"),
    ("Q6.6", "offline"), ("Q6.6", "duplicate"),
])
def test_other_frozen_variants_have_independent_success_readers(tmp_path, experiment, variant):
    result, args = _run(tmp_path / "run", experiment, variant)
    assert verify_scenario_artifacts(result, **args).data()["scientific_validated"] is False


@pytest.mark.parametrize("mutation", ["receipt_missing", "receipt_substituted", "package", "active", "extra_table"])
def test_rehashed_runtime_state_cannot_change_registered_operation(tmp_path, mutation):
    result, args = _run(tmp_path / "run", "Q6.6", "rollback")
    root = args["sidecar"]
    with sqlite3.connect(root / "runtime.sqlite") as db:
        if mutation == "receipt_missing":
            db.execute("DELETE FROM used_receipts")
        elif mutation == "receipt_substituted":
            db.execute("UPDATE used_receipts SET id=? WHERE id=(SELECT id FROM used_receipts LIMIT 1)", ("f" * 64,))
        elif mutation == "package":
            db.execute("UPDATE packages SET record=? WHERE digest=?", (FrozenRecord.from_dict({"forged": True}).encoded,
                       result.record.data()["detail"]["baseline_digest"]))
        elif mutation == "active":
            db.execute("UPDATE state SET active_digest=?", (result.record.data()["detail"]["next_workflow"]["active_digest"],))
        else:
            db.execute("CREATE TABLE extra (claim TEXT)")
    _reseal(root)
    with pytest.raises(ContractError, match="sqlite"):
        verify_scenario_artifacts(result, **args)


@pytest.mark.parametrize("name,field", [("deployment.json", "memory_view"),
    ("deployment.json.previous", "package"), ("deployment.json", "memory_digest")])
def test_rehashed_deployment_pairs_require_full_expected_package(tmp_path, name, field):
    result, args = _run(tmp_path / "run", "Q6.6", "rollback")
    root = args["sidecar"]; body = _read_record(root / name).data()
    body[field] = "f" * 64 if field == "memory_digest" else {"unexpected": "changed"}
    raw = FrozenRecord.from_dict(body).encoded.encode()
    (root / name).write_bytes(raw)
    (root / (name + ".sha256")).write_bytes((hashlib.sha256(raw).hexdigest() + "\n").encode())
    _reseal(root)
    with pytest.raises(ContractError, match="deployment"):
        verify_scenario_artifacts(result, **args)


@pytest.mark.parametrize("mutation", ["scientific", "fixture_integer", "callback_bool", "baseline", "receipt_claim"])
def test_rehashed_result_cannot_promote_or_redefine_operation(tmp_path, mutation):
    result, args = _run(tmp_path / "run", "Q6.6", "promote")
    body = result.record.data()
    if mutation == "scientific": body["detail"]["scientific_validated"] = True
    elif mutation == "fixture_integer": body["fixture_only"] = 1
    elif mutation == "callback_bool": body["callback_count"] = True
    elif mutation == "baseline": body["detail"]["baseline_digest"] = "f" * 64
    else: body["detail"]["activation"]["online"] = 1
    result = replace(result, record=FrozenRecord.from_dict(body))
    _reseal(args["sidecar"], result=result)
    with pytest.raises(ContractError):
        verify_scenario_artifacts(result, **args)


def _failed(root, *, returned=False):
    task = task_for("blade")
    args = dict(task=task, frozen_controls=controls(task), sidecar=root, experiment_id="Q6.6", variant="promote")
    def callback(_):
        if returned: return None
        raise RuntimeError("retained failure")
    with pytest.raises((ContractError, RuntimeError)):
        run_improvement_scenario(callback=callback, **args)
    assert inspect_scenario_artifact_failure(**args).data()["storage_integrity_verified"] is True
    return args


@pytest.mark.parametrize("failed", [True, False])
@pytest.mark.parametrize("mutation", ["omitted_sidecar", "optimizer_visible", "checks"])
def test_rehashed_descriptors_must_be_consumed_with_exact_metadata(tmp_path, failed, mutation):
    root = tmp_path / "run"
    result, args = (None, _failed(root)) if failed else _run(root, "Q6.6", "promote")
    def change(body, payload):
        if body["kind"] == "scenario_sidecar":
            if mutation == "optimizer_visible": body["optimizer_visible"] = True
            if mutation == "checks": body["checks"] = [{"kind": "validation", "canonical": {"approved": True},
                "digest": FrozenRecord.from_dict({"approved": True}).content_hash}]
    _reseal(root, mutate=change, omit=(lambda body: body["kind"] == "scenario_sidecar") if mutation == "omitted_sidecar" else None)
    with pytest.raises(ContractError):
        if failed: inspect_scenario_artifact_failure(**args)
        else: verify_scenario_artifacts(result, **args)


@pytest.mark.parametrize("mutation", ["produced_status", "outcome_fields", "terminal_error", "extra_blob", "nested_blob"])
def test_failed_storage_reader_rejects_rehashed_outcome_or_blob_inventory(tmp_path, mutation):
    root = tmp_path / "run"; args = _failed(root)
    if mutation == "terminal_error":
        body = _read_record(root / "scenario-terminal.json").data(); body["error"] = "different failure"
        _write_record(root / "scenario-terminal.json", body)
    def change(body, payload):
        if body["kind"] == "scenario_callback_return":
            if mutation == "produced_status": body["status"] = "produced"
            elif mutation == "outcome_fields": payload["raw_content_available"] = True
    _reseal(root, mutate=change)
    if mutation == "extra_blob": (root / "scenario-blobs" / ("f" * 64)).write_bytes(b"unlisted")
    if mutation == "nested_blob": (root / "scenario-blobs" / "nested").mkdir()
    with pytest.raises(ContractError):
        inspect_scenario_artifact_failure(**args)


def test_rejected_callback_prefix_is_read_as_storage_only(tmp_path):
    args = _failed(tmp_path / "run", returned=True)
    assert inspect_scenario_artifact_failure(**args).data()["stage_semantics_verified"] is False


@pytest.mark.parametrize("variant", ["automatic_train", "manual_train"])
def test_coherent_optimizer_and_result_substitution_cannot_override_callback_or_variant(tmp_path, variant):
    from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
    proposal = FrozenRecord.from_dict({"changes": {"memory": {"mode": "callback-original"}}})
    result, args = _run(tmp_path / "run", "Q6.2", variant, lambda _: proposal)
    body = result.record.data(); detail = body["detail"]
    substitute = CandidatePackage.create(parent_digest=detail["baseline_digest"],
        manifest=TrainingManifest.freeze((args["task"].identity,)),
        changes={"memory": {"mode": "unauthorized-substitute"}}, search_cost=2)
    with sqlite3.connect(args["sidecar"] / "optimizer.sqlite") as db:
        db.execute("DELETE FROM candidates WHERE digest=?", (detail["candidate_digest"],))
        db.execute("INSERT INTO candidates VALUES (?, ?)", (substitute.digest, substitute.record.encoded))
        db.execute("UPDATE comparisons SET candidate=?", (substitute.digest,))
    detail.update(candidate_digest=substitute.digest, candidate_changes=substitute.record.data()["changes"])
    result = replace(result, record=FrozenRecord.from_dict(body))
    _reseal(args["sidecar"], result=result)
    with pytest.raises(ContractError, match="sqlite"):
        verify_scenario_artifacts(result, **args)


def test_coherent_baseline_result_state_and_deployment_substitution_is_rejected(tmp_path):
    from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
    result, args = _run(tmp_path / "run", "Q6.1", "self_activate")
    root = args["sidecar"]
    substitute = CandidatePackage.create(parent_digest=None,
        manifest=TrainingManifest.freeze((args["task"].identity,)), changes={"memory": {"mode": "on"}}, search_cost=2)
    with sqlite3.connect(root / "runtime.sqlite") as db:
        db.execute("DELETE FROM packages")
        db.execute("INSERT INTO packages VALUES (?, ?)", (substitute.digest, substitute.record.encoded))
        db.execute("UPDATE state SET active_digest=?", (substitute.digest,))
    deployed = {"schema": "modular-file-deployment-v1", "active_digest": substitute.digest,
        "package": substitute.record.data(), "memory_view": substitute.record.data()["changes"]["memory"],
        "memory_digest": substitute.memory_digest}
    raw = FrozenRecord.from_dict(deployed).encoded.encode()
    (root / "active.json").write_bytes(raw)
    (root / "active.json.sha256").write_bytes((hashlib.sha256(raw).hexdigest() + "\n").encode())
    body = result.record.data(); body["detail"]["baseline_digest"] = substitute.digest
    result = replace(result, record=FrozenRecord.from_dict(body))
    _reseal(root, result=result)
    with pytest.raises(ContractError, match="sqlite"):
        verify_scenario_artifacts(result, **args)


def test_rehashed_shadow_receipt_identity_matters_not_just_count(tmp_path):
    result, args = _run(tmp_path / "run", "Q6.5", "unprotected")
    with sqlite3.connect(args["sidecar"] / "shadow-runtime.sqlite") as db:
        db.execute("UPDATE used_receipts SET id=? WHERE id=(SELECT id FROM used_receipts LIMIT 1)", ("e" * 64,))
    _reseal(args["sidecar"])
    with pytest.raises(ContractError, match="sqlite"):
        verify_scenario_artifacts(result, **args)
