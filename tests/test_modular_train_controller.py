"""Synthetic public end-to-end test for the trusted Q3.1 controller."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluation.modular.custody import CustodyStore, InventoryItem
from evaluation.modular.train_io import TrainPacketExporter
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.model_port import CodexModelPort, FrozenBaseContextPolicy, audit_base_context
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_plan import executable_arms, obligation_grids
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.train_controller import FrozenTrainControllerConfig, run_q31_train_panel, run_train_panel
from research_loop.ontology import ContractError


def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()


SCENARIO = {"type": "object", "properties": {"question": {"type": "string"}, "budget_units": {"type": "integer"}, "branches": {"type": "array", "items": {"type": "object", "properties": {"hypothesis_id": {"type": "string"}, "mechanism_key": {"type": "string"}, "mechanism": {"type": "string"}, "intervention": {"type": "string"}, "elimination_condition": {"type": "string"}, "predictions": {"type": "array", "items": {"type": "object", "properties": {"prediction_id": {"type": "string"}, "discriminator_id": {"type": "string"}, "observable": {"type": "string"}, "direction": {"type": "string"}, "value_range": {"type": "null"}, "failure_condition": {"type": "string"}}, "required": ["prediction_id", "discriminator_id", "observable", "direction", "value_range", "failure_condition"], "additionalProperties": False}}}, "required": ["hypothesis_id", "mechanism_key", "mechanism", "intervention", "elimination_condition", "predictions"], "additionalProperties": False}}}, "required": ["question", "budget_units", "branches"], "additionalProperties": False}
FINAL = {"type": "object", "properties": {"objective_digest": {"type": "string"}, "outcome": {"type": "string", "enum": ["unknown"]}, "evidence_ids": {"type": "array", "items": {"type": "string"}}, "conclusion": {"type": "string"}, "programme_complete": {"type": "boolean", "enum": [False]}}, "required": ["objective_digest", "outcome", "evidence_ids", "conclusion", "programme_complete"], "additionalProperties": False}
REVIEW = {"type": "object", "properties": {"assessment": {"type": "string", "enum": ["accept", "concern", "unknown"]}, "evidence_refs": {"type": "array", "items": {"type": "string"}}, "counterexamples": {"type": "array", "items": {"type": "string"}}, "uncertainty": {"type": "string"}}, "required": ["assessment", "evidence_refs", "counterexamples", "uncertainty"], "additionalProperties": False}


def snapshot_and_custody(root: Path) -> tuple[Path, CustodyStore]:
    snapshot = root / "public-snapshot"
    discovery = snapshot / "discovery" / "upstream" / "discoverybench" / "synth" / "train" / "family_1_1"
    blade = snapshot / "scienceagent" / "work" / "BLADE" / "blade_bench" / "datasets" / "fish"
    discovery.mkdir(parents=True); blade.mkdir(parents=True)
    (discovery / "metadata_1.json").write_text(json.dumps({"queries": [{"question": "public discovery question"}], "datasets": [{"name": "data.csv", "columns": [{"name": "x"}]}]}), encoding="utf-8")
    (discovery / "data.csv").write_text("x\n1\n", encoding="utf-8")
    (blade / "info.json").write_text(json.dumps({"research_questions": ["public blade question"], "data_desc": {"dataset_description": "public instruction"}}), encoding="utf-8")
    (blade / "data.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    store = CustodyStore(root / "custody.json")
    store.inventory([
        InventoryItem("discoverybench", "synth:train:family_1_1", "discoverybench:family", "synth/train", "synth/train/family_1_1", tuple(sha(p) for p in (discovery / "metadata_1.json", discovery / "data.csv")), "exposed"),
        InventoryItem("blade", "fish", "blade:fish", "unsplit", "fish", tuple(sha(p) for p in (blade / "info.json", blade / "data.csv")), "exposed"),
    ])
    store.split(seed="synthetic")
    return snapshot, store


def model_port(root: Path, monkeypatch, *, max_calls: int = 24, valid_plan: bool = True, schemas=None) -> CodexModelPort:
    home = root / "user" / ".codex"; home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home.parent)); monkeypatch.setenv("USERPROFILE", str(home.parent)); monkeypatch.setenv("CODEX_HOME", str(home))
    (home / "config.toml").write_text('[mcp_servers.fixture]\nenabled=true\n', encoding="utf-8")
    cli = root / "codex.exe"; cli.write_bytes(b"fixture cli")
    cwd = root / "reviewed-empty-cwd"; cwd.mkdir()
    raw = json.dumps([{"type": "message", "id": "fixture", "role": "developer", "content": [{"type": "input_text", "text": "reviewed public fixture context"}]}])
    def probe(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stdout=raw, stderr="")
    candidate = audit_base_context(cli, cwd, root / "context-audit", config_overrides=('mcp_servers.fixture.enabled=false',), context_probe_runner=probe)
    policy_data = json.loads(candidate.read_text(encoding="utf-8"))
    policy_data.update(status="REVIEWED", review={"reviewer": "fixture reviewer", "reviewed_at": "2026-09-12T00:00:00Z", "rationale": "no-paid fixture audit", "source_completeness": "fixture source inventory"})
    reviewed = root / "reviewed-policy.json"; reviewed.write_text(json.dumps(policy_data), encoding="utf-8")
    policy = FrozenBaseContextPolicy(reviewed, sha(reviewed))
    fixed_test_env = os.environ.get("PYTEST_CURRENT_TEST", "")
    def transport(argv, **kwargs):
        request = json.loads(kwargs["input"].split("\n", 1)[1])
        if request["slot"] == "scenario":
            directions = ["increase", "decrease", "increase"] if valid_plan else ["increase", "increase", "increase"]
            output = {"question": "public", "budget_units": 3, "branches": [{"hypothesis_id": f"h{i}", "mechanism_key": f"m{i}", "mechanism": "public mechanism", "intervention": "public intervention", "elimination_condition": "public disagreement", "predictions": [{"prediction_id": f"p{i}", "discriminator_id": "shared", "observable": "public observable", "direction": directions[i], "value_range": None, "failure_condition": "does not " + directions[i]}]} for i in range(3)]}
        elif request["slot"] == "final":
            output = {"objective_digest": request["module_context"]["required_objective_digest"], "outcome": "unknown", "evidence_ids": [], "conclusion": "synthetic engineering result", "programme_complete": False}
        elif request["slot"] == "analysis_program":
            output = {"analysis": "calculate the public x mean", "program": "import csv\nwith open('/input/public_csv', newline='') as f:\n rows=list(csv.DictReader(f))\nprint(sum(float(r['x']) for r in rows)/len(rows))"}
        elif request["slot"] == "final_answer":
            output = {"objective_digest": request["module_context"]["required_objective_digest"], "outcome": "unknown", "evidence_ids": [], "conclusion": "synthetic benchmark answer", "programme_complete": False}
        elif request["slot"] == "reconstructed":
            output = {"mechanism_judgment": {"decision": "unknown", "reason": "synthetic mechanism judgment", "evidence_ids": []}}
        else:
            output = {"assessment": "concern", "evidence_refs": ["synthetic-public-observation"], "counterexamples": [], "uncertainty": "synthetic transport review"}
        Path(argv[argv.index("-o") + 1]).write_text(json.dumps(output), encoding="utf-8")
        usage = {"input_tokens": 1, "cached_input_tokens": 0, "cache_write_input_tokens": 0, "output_tokens": 1, "reasoning_output_tokens": 0}
        return SimpleNamespace(returncode=0, stdout=json.dumps({"type": "turn.completed", "usage": usage}), stderr="")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", fixed_test_env)
    return CodexModelPort(cli, root / "model", max_calls=max_calls, max_tokens=200,
        schema_by_slot=schemas or {"scenario": SCENARIO, "final": FINAL}, process_runner=transport,
        context_probe_runner=probe, frozen_base_context=policy)


def config(store: CustodyStore, snapshot: Path, root: Path) -> FrozenTrainControllerConfig:
    packets = TrainPacketExporter(store, snapshot, root / "pre-export").export(["discoverybench:synth:train:family_1_1", "blade:fish"])
    tasks = [packet.task for packet in packets]
    manifest = TrainingManifest.freeze([task.identity for task in tasks])
    package = CandidatePackage.create(parent_digest=None, manifest=manifest, changes={"prompt": {"instructions": "public train package"}}, search_cost=0)
    control = FrozenRecord.from_dict({"source": "synthetic", "always_enabled": True})
    grids = obligation_grids(("Q3.1",), baseline_digest="a" * 64, p0_control=control)
    arms = {arm.content_hash: package.record.data() for grid in grids.values() for arm in executable_arms(grid).values()}
    return FrozenTrainControllerConfig(FrozenRecord.from_dict({"schema": "q31-train-controller-v1", "engineering_scope": "train_only_q3_1_engineering", "stage": "synthetic-q31", "scope_ids": ["Q3.1"], "item_ids": ["discoverybench:synth:train:family_1_1", "blade:fish"], "evidence_by_task": {task.content_hash: {"observations": []} for task in tasks}, "budget": {"model_calls": 2, "execution_limit": 0}, "baseline_digest": "a" * 64, "p0_control": control.data(), "packages_by_arm": arms, "scorer": {"identity": "not-configured"}, "acceptance_criteria": {"scope": "engineering-only"}, "replicates": ["r1"], "model": "gpt-5.6-luna", "effort": "low", "max_calls": 24, "max_tokens": 200, "schemas": {"scenario": SCENARIO, "final": FINAL}}))


def test_actual_custody_export_port_runner_and_receipt_are_engineering_only(tmp_path: Path, monkeypatch) -> None:
    snapshot, custody = snapshot_and_custody(tmp_path)
    result = run_q31_train_panel(config(custody, snapshot, tmp_path), custody=custody, snapshot_root=snapshot,
        export_root=tmp_path / "export", run_root=tmp_path / "run", model=model_port(tmp_path, monkeypatch),
        audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}))
    assert len(result.packets) == 2 and len(result.runtimes) == len(result.compiled.panel.cells) == 12
    assert result.verdict.decision == "engineering_verified" and not result.verdict.scientific_verified
    assert result.receipt.data()["execution_status"] == "engineering_complete"
    assert result.receipt.data()["model_policy_sha256"]
    assert all(runtime.status == "succeeded" for runtime in result.runtimes)
    attempt = json.loads((tmp_path / "run" / "controller-attempt.json").read_text(encoding="utf-8"))
    assert attempt["compiled_manifest"]["panel_digest"] == result.compiled.panel.digest
    assert len(attempt["cell_plan"]) == len(attempt["runtime_receipts"]) == 12
    for runtime in result.runtimes:
        events = [json.loads(line) for line in runtime.trace_path.read_text(encoding="utf-8").splitlines()]
        final_request = next(event["data"]["request"] for event in events if event["stage"] == "model_request" and event["data"]["request"]["slot"] == "final")
        final_response = next(event["data"]["response"] for event in events if event["stage"] == "model_response" and event["data"]["request_digest"] == FrozenRecord.from_dict(final_request).content_hash)
        assert final_response["objective_digest"] == final_request["module_context"]["required_objective_digest"]
    assert all(runtime.trace_path.exists() for runtime in result.runtimes)


@pytest.mark.parametrize("coverage,slots,expected_cells", [
    ("Q1.3", ("representation_initial", "representation_next", "final"), 16),
    ("Q1.4", ("support_initial", "support_rechecked", "final"), 12),
])
def test_support_drivers_reach_production_controller_without_registry_patch(tmp_path, monkeypatch, coverage, slots, expected_cells):
    from test_modular_support_panel_drivers import _bundle, _admit
    snapshot, custody = snapshot_and_custody(tmp_path)
    base = config(custody, snapshot, tmp_path).data()
    packets = TrainPacketExporter(custody, snapshot, tmp_path / "support-material").export(base["item_ids"])
    control = FrozenRecord.from_dict(base["p0_control"])
    grids = obligation_grids((coverage,), baseline_digest=base["baseline_digest"], p0_control=control)
    package = next(iter(base["packages_by_arm"].values()))
    schemas = {slot: FINAL if slot == "final" else REVIEW for slot in slots}
    frozen = FrozenTrainControllerConfig(FrozenRecord.from_dict({**base, "schema": "train-panel-controller-v1",
        "engineering_scope": "train_only_panel_engineering", "stage": "synthetic-support-controller",
        "scope_ids": [coverage], "evidence_by_task": {packet.task.content_hash: _bundle(packet.task).data() for packet in packets},
        "packages_by_arm": {arm.content_hash: package for grid in grids.values() for arm in executable_arms(grid).values()},
        "budget": {"model_calls": 3, "execution_limit": 0}, "max_calls": expected_cells * 3, "schemas": schemas}))
    admissions = []
    def caller_admit(task, record):
        receipt = _admit(task, record)
        admissions.append(receipt["record_digest"])
        return receipt
    model = model_port(tmp_path, monkeypatch, max_calls=expected_cells * 3, schemas=schemas)
    result = run_train_panel(frozen, custody=custody, snapshot_root=snapshot,
        export_root=tmp_path / "export", run_root=tmp_path / "run", model=model,
        audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}), history_admission_port=caller_admit)
    assert result.receipt.data()["execution_status"] == "engineering_complete"
    assert len(result.runtimes) == expected_cells and len(model.ledger["calls"]) == expected_cells * 3
    assert admissions and all(runtime.status == "succeeded" for runtime in result.runtimes)


@pytest.mark.parametrize("coverage,slots", [
    ("Q1.6", ("initial", "invalidation", "final")),
    ("Q1.7", ("initial", "reconstructed", "final")),
])
def test_withdrawal_drivers_reach_custody_controller_with_caller_admission(tmp_path, monkeypatch, coverage, slots):
    from test_modular_withdrawal_panel_drivers import bundle, admission
    from research_loop.modular.experiments import registry
    snapshot, custody = snapshot_and_custody(tmp_path)
    base = config(custody, snapshot, tmp_path).data()
    packets = TrainPacketExporter(custody, snapshot, tmp_path / "withdrawal-material").export(base["item_ids"])
    grids = obligation_grids((coverage,), baseline_digest=base["baseline_digest"], p0_control=FrozenRecord.from_dict(base["p0_control"]))
    package = next(iter(base["packages_by_arm"].values()))
    expected_cells = 2 * len(registry()[coverage].variants) * len(executable_arms(grids[coverage]))
    judgment = {"type": "object", "properties": {"mechanism_judgment": {
        "type": "object", "properties": {"decision": {"type": "string", "enum": ["positive", "negative", "unknown"]},
            "reason": {"type": "string"}, "evidence_ids": {"type": "array", "items": {"type": "string"}}},
        "required": ["decision", "reason", "evidence_ids"], "additionalProperties": False}},
        "required": ["mechanism_judgment"], "additionalProperties": False}
    schemas = {slot: FINAL if slot == "final" else judgment if slot == "reconstructed" else REVIEW for slot in slots}
    frozen = FrozenTrainControllerConfig(FrozenRecord.from_dict({**base, "schema": "train-panel-controller-v1",
        "engineering_scope": "train_only_panel_engineering", "stage": "synthetic-withdrawal-controller", "scope_ids": [coverage],
        "evidence_by_task": {packet.task.content_hash: bundle(packet.task).data() for packet in packets},
        "packages_by_arm": {arm.content_hash: package for arm in executable_arms(grids[coverage]).values()},
        "budget": {"model_calls": 3, "execution_limit": 0}, "max_calls": expected_cells * 3, "schemas": schemas}))
    port = model_port(tmp_path, monkeypatch, max_calls=expected_cells * 3, schemas=schemas)
    admitted = []
    def caller(task, record):
        admitted.append(record.content_hash)
        return admission(task, record)
    result = run_train_panel(frozen, custody=custody, snapshot_root=snapshot,
        export_root=tmp_path / "export", run_root=tmp_path / "run", model=port,
        audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}), history_admission_port=caller)
    assert result.receipt.data()["execution_status"] == "engineering_complete"
    assert len(result.runtimes) == expected_cells and len(port.ledger["calls"]) == expected_cells * 3
    assert admitted and all(row.status == "succeeded" for row in result.runtimes)


def test_q43_closed_driver_runs_through_custody_export_and_frozen_policy(tmp_path: Path, monkeypatch) -> None:
    snapshot, custody = snapshot_and_custody(tmp_path)
    frozen = config(custody, snapshot, tmp_path)
    task_package = next(iter(frozen.data()["packages_by_arm"].values()))
    control = FrozenRecord.from_dict(frozen.data()["p0_control"])
    grids = obligation_grids(("Q4.3",), baseline_digest="a" * 64, p0_control=control)
    packages = {arm.content_hash: task_package for grid in grids.values() for arm in executable_arms(grid).values()}
    schemas = {slot: REVIEW for slot in ("mechanism_initial", "measurement_initial", "mechanism_revision", "measurement_revision")}
    schemas["final"] = FINAL
    q43 = FrozenTrainControllerConfig(FrozenRecord.from_dict({**frozen.data(), "schema": "train-panel-controller-v1",
        "engineering_scope": "train_only_panel_engineering", "stage": "synthetic-q43", "scope_ids": ["Q4.3"],
        "packages_by_arm": packages, "budget": {"model_calls": 5, "execution_limit": 0}, "max_calls": 48, "schemas": schemas}))
    port = model_port(tmp_path, monkeypatch, max_calls=48, schemas=schemas)
    result = run_train_panel(q43, custody=custody, snapshot_root=snapshot, export_root=tmp_path / "q43-export",
        run_root=tmp_path / "q43-run", model=port, audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}))
    assert len(result.runtimes) == len(result.compiled.panel.cells) == 8
    assert result.verdict.decision == "engineering_verified" and len(port.ledger["calls"]) == 40
    attempt = json.loads((tmp_path / "q43-run" / "controller-attempt.json").read_text(encoding="utf-8"))
    assert attempt["scope_ids"] == ["Q4.3"] and attempt["expected_cells"] == 8 and attempt["expected_model_calls"] == 40


def test_rejects_config_drift_reused_root_and_unreviewed_policy(tmp_path: Path, monkeypatch) -> None:
    snapshot, custody = snapshot_and_custody(tmp_path)
    frozen = config(custody, snapshot, tmp_path)
    with pytest.raises(ContractError, match="call capacity"):
        bad = FrozenTrainControllerConfig(FrozenRecord.from_dict({**frozen.data(), "max_calls": 2}))
        run_q31_train_panel(bad, custody=custody, snapshot_root=snapshot, export_root=tmp_path / "export-a", run_root=tmp_path / "bad", model=model_port(tmp_path, monkeypatch, max_calls=2), audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}))
    root = tmp_path / "reuse"
    root.mkdir()
    with pytest.raises(FileExistsError):
        run_q31_train_panel(frozen, custody=custody, snapshot_root=snapshot, export_root=tmp_path / "export-b", run_root=root, model=model_port(tmp_path / "second", monkeypatch), audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}))
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({"schema": "frozen-base-context-policy-v2", "status": "UNQUALIFIED", "review": {}, "audit_path": "missing", "audit_sha256": "0" * 64, "binding": {}}), encoding="utf-8")
    with pytest.raises(ContractError, match="unqualified"):
        FrozenBaseContextPolicy(candidate, sha(candidate)).data()


def test_rejects_non_train_allowlist_and_evidence_task_mismatch_before_model(tmp_path: Path, monkeypatch) -> None:
    snapshot, custody = snapshot_and_custody(tmp_path)
    frozen = config(custody, snapshot, tmp_path)
    wrong_allowlist = FrozenTrainControllerConfig(FrozenRecord.from_dict({**frozen.data(), "item_ids": ["blade:absent", "discoverybench:synth:train:family_1_1"]}))
    with pytest.raises(ContractError, match="not in custody train export"):
        run_q31_train_panel(wrong_allowlist, custody=custody, snapshot_root=snapshot, export_root=tmp_path / "bad-export", run_root=tmp_path / "bad-allowlist", model=model_port(tmp_path / "bad-a", monkeypatch), audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}))
    broken = frozen.data(); broken["evidence_by_task"] = {"0" * 64: {"observations": []}}
    with pytest.raises(ContractError, match="evidence records"):
        run_q31_train_panel(FrozenTrainControllerConfig(FrozenRecord.from_dict(broken)), custody=custody, snapshot_root=snapshot, export_root=tmp_path / "wrong-evidence", run_root=tmp_path / "bad-evidence", model=model_port(tmp_path / "bad-b", monkeypatch), audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}))


def test_failed_cells_keep_the_complete_denominator_and_are_not_completed(tmp_path: Path, monkeypatch) -> None:
    snapshot, custody = snapshot_and_custody(tmp_path)
    result = run_q31_train_panel(config(custody, snapshot, tmp_path), custody=custody, snapshot_root=snapshot,
        export_root=tmp_path / "export", run_root=tmp_path / "run", model=model_port(tmp_path, monkeypatch, valid_plan=False),
        audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}))
    assert len(result.runtimes) == len(result.compiled.panel.cells) == 12
    assert result.receipt.data()["execution_status"] == "execution_incomplete"
    assert result.verdict.failures == 6 and all(runtime.trace_path.exists() for runtime in result.runtimes)


def test_refuses_a_reused_ledger_before_export_or_run_side_effects(tmp_path: Path, monkeypatch) -> None:
    snapshot, custody = snapshot_and_custody(tmp_path)
    port = model_port(tmp_path, monkeypatch)
    prior = FrozenRecord.from_dict({"schema": "public-model-request-v1", "task": {"identity": {"domain": "train"}},
        "lock_digest": "fixture", "objective": {}, "slot": "scenario", "instruction": "public", "context": {}, "module_context": {}, "execution_feedback": []})
    port(prior)
    with pytest.raises(ContractError, match="fresh empty model ledger"):
        run_q31_train_panel(config(custody, snapshot, tmp_path), custody=custody, snapshot_root=snapshot,
            export_root=tmp_path / "export", run_root=tmp_path / "run", model=port,
            audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}))
    assert not (tmp_path / "export").exists() and not (tmp_path / "run").exists()
