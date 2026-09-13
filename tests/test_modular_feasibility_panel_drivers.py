"""Synthetic two-benchmark Q5.1/Q5.2 Docker driver checks."""
from dataclasses import replace
from hashlib import sha256
import os
from pathlib import Path

import pytest

from research_loop.modular import panel_plan, panel_runner
from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.experiments import scenario as base_scenario
from research_loop.modular.feasibility_panel_drivers import feasibility_panel_injection, freeze_feasibility_panel_bundle, install_drivers
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_plan import compile_train_panel, executable_arms, obligation_grids
from research_loop.modular.panel_receipts import PanelReceiptVerifier
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError

SPLIT = "7" * 64
IMAGE = "research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349"


def _task(name):
    identity = DataIdentity(name, "f-" + name, name + ":f", "synthetic-v1", SPLIT, "train")
    if name == "blade":
        return BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": "public", "research_question": "public feasibility", "data_schema": [{"name": "x", "dtype": "float"}]})
    return DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id, "question": "public feasibility", "source_kind": "synthetic", "dataset": [{"name": "x", "columns": [{"name": "x"}]}]})


def _branches(opposite):
    directions = ("increase", "decrease") if opposite else ("increase", "increase")
    return [{"hypothesis_id": "h" + str(index), "mechanism_key": "m" + str(index), "mechanism": "public mechanism", "intervention": "same public intervention", "elimination_condition": "public falsifier", "predictions": [{"prediction_id": "p" + str(index), "discriminator_id": "d", "observable": "x", "direction": direction, "value_range": None, "failure_condition": "public failure"}]} for index, direction in enumerate(directions, 1)]


def _item(task, csv: Path, *, branches=None, failing=False):
    program = "from pathlib import Path\nassert Path('/input/data_csv').read_text().strip() == 'x\\n1'\n" if not failing else "raise SystemExit(3)\n"
    artifacts = {"data_csv": {"sha256": sha256(csv.read_bytes()).hexdigest(), "byte_count": len(csv.read_bytes())}}
    row = {"source_id": task.identity.group_id, "program": program, "program_sha256": sha256(program.replace("\n", os.linesep).encode()).hexdigest(), "image": IMAGE,
        "inputs": artifacts, "closure": {"data_version": "public-v1", "minimum_artifact_digest": "a" * 64, "negative_control_id": "public-control", "execution_units": 1, "token_units": 0},
        "stage_contracts": {stage: {"source_id": task.identity.group_id, "contract_id": "public-" + stage} for stage in ("data", "minimal_run", "discriminating_measurement", "independent_result")},
        "measurement_contract": {"source": task.identity.group_id, "observable": "x", "registered": True}}
    if branches is not None: row["branches"] = branches
    return row


class _Authority:
    def __init__(self, *, bad_boolean=False): self.bad_boolean = bad_boolean
    def verify_stage(self, subject):
        row = subject.data(); stage = row["stage"]
        status = "passed" if row["execution_status"] == "succeeded" or stage == "data" else "failed"
        classifications = {"h1": "consistent", "h2": "failed"} if stage == "discriminating_measurement" and row["prediction_plan_digest"] else None
        return FrozenRecord.from_dict({"schema": "verified-feasibility-stage-v1", "subject_digest": subject.content_hash,
            "authorities": ["synthetic-a", "synthetic-b"], "signature_verified": "true" if self.bad_boolean else True,
            "status": status, "independent_source_group": "independent-synthetic" if stage == "independent_result" else None,
            "classifications": classifications})


def _compile(tmp_path, monkeypatch):
    csv = tmp_path / "data.csv"; csv.write_text("x\n1", encoding="utf-8")
    tasks = {name: _task(name) for name in ("blade", "discoverybench")}
    bundles = {}
    for task in tasks.values():
        q51 = {name: _item(task, csv) for name in ("subjective", "data", "minimal_run", "measurement", "independent")}
        q52 = {"zero_exit_same_prediction": _item(task, csv, branches=_branches(False)), "negative_control": _item(task, csv, branches=_branches(True))}
        bundles[task.content_hash] = freeze_feasibility_panel_bundle(task, q51=q51, q52=q52)
    def inject(spec, variant, *, inputs):
        body = base_scenario(spec, variant, inputs=inputs).data(); body["controller_input"] = dict(feasibility_panel_injection(spec.experiment_id, variant, task=inputs.task, evidence=inputs.evidence)); return FrozenRecord.from_dict(body)
    monkeypatch.setattr(panel_plan, "scenario", inject)
    broker = DockerExecutionBroker([tmp_path])
    resolver = lambda _task, _bundle: {"data_csv": csv}
    local = dict(panel_runner.DRIVERS); install_drivers(local, broker=broker, input_resolver=resolver, authority=_Authority()); monkeypatch.setattr(panel_runner, "DRIVERS", local)
    package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([task.identity for task in tasks.values()]), changes={"prompt": {"instructions": "synthetic"}}, search_cost=0)
    control = FrozenRecord.from_dict({"control": "fixed"}); grids = obligation_grids(("Q5.1", "Q5.2"), baseline_digest="f" * 64, p0_control=control)
    packages = {arm.content_hash: package for grid in grids.values() for arm in executable_arms(grid).values()}
    compiled = compile_train_panel(stage="feasibility", scope_ids=("Q5.1", "Q5.2"), tasks=tuple(tasks.values()), evidence_by_task=bundles, budget=FrozenRecord.from_dict({"calls": 2}), baseline_digest="f" * 64, p0_control=control, packages_by_arm=packages, scorer=FrozenRecord.from_dict({"scorer": "none"}), acceptance_criteria=FrozenRecord.from_dict({"engineering": True}))
    return compiled, tasks, broker, resolver


def _model(seen):
    def call(request):
        body = request.data(); seen.append(body); encoded = FrozenRecord.from_dict(body).encoded
        for marker in ('"variant"', '"arm_id"', '"enabled_modules"', '"stage_success"'):
            assert marker not in encoded
        if body["slot"] == "subjective": return FrozenRecord.from_dict({"feasibility": "unknown", "rationale": "public synthetic assessment"})
        return FrozenRecord.from_dict({"objective_digest": body["module_context"]["required_objective_digest"], "outcome": "unknown", "evidence_ids": [], "conclusion": "train-only synthetic", "programme_complete": False})
    return call


def test_full_grid_executes_public_docker_and_retains_m4_m7_controls(tmp_path, monkeypatch):
    compiled, tasks, _broker, _resolver = _compile(tmp_path, monkeypatch); runs = []
    for index, cell in enumerate(compiled.panel.cells):
        seen = []; result = panel_runner.run_train_cell(cell, task=tasks[cell.identity.benchmark], scenario=compiled.scenarios[cell.key], package=compiled.packages[cell.runtime_arm.content_hash], objective=FrozenRecord.from_dict({"objective": "public feasibility"}), sidecar=tmp_path / "runs" / str(index), model=_model(seen), audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}))
        runs.append(result.runtime); assert result.call_plan.data()["model_calls"] == 2 and result.call_plan.data()["execution_attempts"] == 1 and len(seen) == 2
        assert result.runtime.status == "succeeded"
    assert len(compiled.panel.cells) == 36
    assert PanelReceiptVerifier().verify(compiled.panel, tuple(runs)).observed_cells == 36


def test_bad_hash_and_nonboolean_authority_do_not_promote_stage(tmp_path, monkeypatch):
    compiled, tasks, broker, resolver = _compile(tmp_path, monkeypatch); cell = next(item for item in compiled.panel.cells if item.coverage_id == "Q5.1" and "M7" in item.runtime_arm.data()["enabled"])
    body = compiled.scenarios[cell.key].data(); body["controller_input"]["bundle"]["q51"][cell.variant]["inputs"]["data_csv"]["sha256"] = "0" * 64
    bundle = FrozenRecord.from_dict(body["controller_input"]["bundle"]); body["controller_input"]["bundle"] = bundle.data(); body["base"]["evidence"] = bundle.content_hash
    scenario = FrozenRecord.from_dict(body); changed = replace(cell, scenario_digest=scenario.content_hash); seen = []
    result = panel_runner.run_train_cell(changed, task=tasks[changed.identity.benchmark], scenario=scenario, package=compiled.packages[changed.runtime_arm.content_hash], objective=FrozenRecord.from_dict({"objective": "public feasibility"}), sidecar=tmp_path / "hash", model=_model(seen), audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}))
    assert result.runtime.status == "failed" and result.call_plan.data()["model_calls"] == 0 and result.call_plan.data()["execution_attempts"] == 0
    local = dict(panel_runner.DRIVERS); install_drivers(local, broker=broker, input_resolver=resolver, authority=_Authority(bad_boolean=True)); monkeypatch.setattr(panel_runner, "DRIVERS", local)
    seen = []; result = panel_runner.run_train_cell(cell, task=tasks[cell.identity.benchmark], scenario=compiled.scenarios[cell.key], package=compiled.packages[cell.runtime_arm.content_hash], objective=FrozenRecord.from_dict({"objective": "public feasibility"}), sidecar=tmp_path / "boolean", model=_model(seen), audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}))
    assert result.runtime.status == "failed" and result.call_plan.data()["execution_attempts"] == 1
