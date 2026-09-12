"""Synthetic public end-to-end test for the trusted Q3.1 controller."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluation.modular.custody import CustodyStore, InventoryItem
from evaluation.modular.train_io import TrainPacketExporter
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.model_port import CodexModelPort, FrozenBaseContextPolicy
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_plan import executable_arms, obligation_grids
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.train_controller import FrozenTrainControllerConfig, run_q31_train_panel
from research_loop.ontology import ContractError


def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()


SCENARIO = {"type": "object", "properties": {"question": {"type": "string"}, "budget_units": {"type": "integer"}, "branches": {"type": "array", "items": {"type": "object", "properties": {"hypothesis_id": {"type": "string"}, "mechanism_key": {"type": "string"}, "mechanism": {"type": "string"}, "intervention": {"type": "string"}, "elimination_condition": {"type": "string"}, "predictions": {"type": "array", "items": {"type": "object", "properties": {"prediction_id": {"type": "string"}, "discriminator_id": {"type": "string"}, "observable": {"type": "string"}, "direction": {"type": "string"}, "value_range": {"type": "null"}, "failure_condition": {"type": "string"}}, "required": ["prediction_id", "discriminator_id", "observable", "direction", "value_range", "failure_condition"], "additionalProperties": False}}}, "required": ["hypothesis_id", "mechanism_key", "mechanism", "intervention", "elimination_condition", "predictions"], "additionalProperties": False}}}, "required": ["question", "budget_units", "branches"], "additionalProperties": False}
FINAL = {"type": "object", "properties": {"objective_digest": {"type": "string"}, "outcome": {"type": "string", "enum": ["unknown"]}, "evidence_ids": {"type": "array", "items": {"type": "string"}}, "conclusion": {"type": "string"}, "programme_complete": {"type": "boolean", "enum": [False]}}, "required": ["objective_digest", "outcome", "evidence_ids", "conclusion", "programme_complete"], "additionalProperties": False}


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


def model_port(root: Path, *, max_calls: int = 24) -> CodexModelPort:
    def probe(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps([{"role": "developer", "content": [{"type": "input_text", "text": "synthetic public fixture"}]}]), stderr="")
    def transport(argv, **kwargs):
        request = json.loads(kwargs["input"].split("\n", 1)[1])
        if request["slot"] == "scenario":
            output = {"question": "public", "budget_units": 3, "branches": [{"hypothesis_id": f"h{i}", "mechanism_key": f"m{i}", "mechanism": "public mechanism", "intervention": "public intervention", "elimination_condition": "public disagreement", "predictions": [{"prediction_id": f"p{i}", "discriminator_id": "shared", "observable": "public observable", "direction": "increase", "value_range": None, "failure_condition": "does not increase"}]} for i in range(3)]}
        else:
            output = {"objective_digest": FrozenRecord.from_dict(request["objective"]).content_hash, "outcome": "unknown", "evidence_ids": [], "conclusion": "synthetic engineering result", "programme_complete": False}
        Path(argv[argv.index("-o") + 1]).write_text(json.dumps(output), encoding="utf-8")
        usage = {"input_tokens": 1, "cached_input_tokens": 0, "cache_write_input_tokens": 0, "output_tokens": 1, "reasoning_output_tokens": 0}
        return SimpleNamespace(returncode=0, stdout=json.dumps({"type": "turn.completed", "usage": usage}), stderr="")
    return CodexModelPort(sys.executable, root / "model", max_calls=max_calls, max_tokens=200,
        schema_by_slot={"scenario": SCENARIO, "final": FINAL}, process_runner=transport,
        context_probe_runner=probe, allow_mock_context=True)


def config(store: CustodyStore, snapshot: Path, root: Path) -> FrozenTrainControllerConfig:
    packets = TrainPacketExporter(store, snapshot, root / "pre-export").export(["discoverybench:synth:train:family_1_1", "blade:fish"])
    tasks = [packet.task for packet in packets]
    manifest = TrainingManifest.freeze([task.identity for task in tasks])
    package = CandidatePackage.create(parent_digest=None, manifest=manifest, changes={"prompt": {"instructions": "public train package"}}, search_cost=0)
    control = FrozenRecord.from_dict({"source": "synthetic", "always_enabled": True})
    grids = obligation_grids(("Q3.1",), baseline_digest="a" * 64, p0_control=control)
    arms = {arm.content_hash: package.record.data() for grid in grids.values() for arm in executable_arms(grid).values()}
    return FrozenTrainControllerConfig(FrozenRecord.from_dict({"schema": "q31-train-controller-v1", "engineering_scope": "train_only_q3_1_engineering", "stage": "synthetic-q31", "scope_ids": ["Q3.1"], "item_ids": ["discoverybench:synth:train:family_1_1", "blade:fish"], "evidence_by_task": {task.content_hash: {"observations": []} for task in tasks}, "budget": {"model_calls": 2, "execution_limit": 0}, "baseline_digest": "a" * 64, "p0_control": control.data(), "packages_by_arm": arms, "scorer": {"identity": "not-configured"}, "acceptance_criteria": {"scope": "engineering-only"}, "replicates": ["r1"], "model": "gpt-5.6-luna", "effort": "low", "max_calls": 24, "max_tokens": 200, "schemas": {"scenario": SCENARIO, "final": FINAL}}))


def test_actual_custody_export_port_runner_and_receipt_are_engineering_only(tmp_path: Path) -> None:
    snapshot, custody = snapshot_and_custody(tmp_path)
    result = run_q31_train_panel(config(custody, snapshot, tmp_path), custody=custody, snapshot_root=snapshot,
        export_root=tmp_path / "export", run_root=tmp_path / "run", model=model_port(tmp_path),
        audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}))
    assert len(result.packets) == 2 and len(result.runtimes) == len(result.compiled.panel.cells) == 12
    assert result.verdict.decision == "engineering_verified" and not result.verdict.scientific_verified
    assert all(runtime.trace_path.exists() for runtime in result.runtimes)


def test_rejects_config_drift_reused_root_and_unreviewed_policy(tmp_path: Path) -> None:
    snapshot, custody = snapshot_and_custody(tmp_path)
    frozen = config(custody, snapshot, tmp_path)
    with pytest.raises(ContractError, match="call capacity"):
        bad = FrozenTrainControllerConfig(FrozenRecord.from_dict({**frozen.data(), "max_calls": 2}))
        run_q31_train_panel(bad, custody=custody, snapshot_root=snapshot, export_root=tmp_path / "export-a", run_root=tmp_path / "bad", model=model_port(tmp_path, max_calls=2), audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}))
    root = tmp_path / "reuse"
    root.mkdir()
    with pytest.raises(FileExistsError):
        run_q31_train_panel(frozen, custody=custody, snapshot_root=snapshot, export_root=tmp_path / "export-b", run_root=root, model=model_port(tmp_path / "second"), audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}))
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({"schema": "frozen-base-context-policy-v2", "status": "UNQUALIFIED", "review": {}, "audit_path": "missing", "audit_sha256": "0" * 64, "binding": {}}), encoding="utf-8")
    with pytest.raises(ContractError, match="unqualified"):
        FrozenBaseContextPolicy(candidate, sha(candidate)).data()


def test_rejects_non_train_allowlist_and_evidence_task_mismatch_before_model(tmp_path: Path) -> None:
    snapshot, custody = snapshot_and_custody(tmp_path)
    frozen = config(custody, snapshot, tmp_path)
    wrong_allowlist = FrozenTrainControllerConfig(FrozenRecord.from_dict({**frozen.data(), "item_ids": ["blade:absent", "discoverybench:synth:train:family_1_1"]}))
    with pytest.raises(ContractError, match="not in custody train export"):
        run_q31_train_panel(wrong_allowlist, custody=custody, snapshot_root=snapshot, export_root=tmp_path / "bad-export", run_root=tmp_path / "bad-allowlist", model=model_port(tmp_path / "bad-a"), audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}))
    broken = frozen.data(); broken["evidence_by_task"] = {"0" * 64: {"observations": []}}
    with pytest.raises(ContractError, match="evidence records"):
        run_q31_train_panel(FrozenTrainControllerConfig(FrozenRecord.from_dict(broken)), custody=custody, snapshot_root=snapshot, export_root=tmp_path / "wrong-evidence", run_root=tmp_path / "bad-evidence", model=model_port(tmp_path / "bad-b"), audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}))
