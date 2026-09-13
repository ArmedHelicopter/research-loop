"""Two-benchmark train-panel checks for caller-bound Q2.5/Q2.6 drivers."""
from pathlib import Path

from research_loop.modular import panel_plan, panel_runner
from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.experiments import registry, scenario as base_scenario
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_plan import compile_train_panel, executable_arms, obligation_grids
from research_loop.modular.polarity_goal_panel_drivers import freeze_polarity_goal_bundle, install_drivers, polarity_goal_injection
from research_loop.modular.runtime import AuditVerifier

SPLIT = "5" * 64


def _task(name):
    identity = DataIdentity(name, "pg-" + name, name + ":pg", "synthetic-v1", SPLIT, "train")
    if name == "blade": return BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": "public", "research_question": "PG public", "data_schema": [{"name": "x", "dtype": "float"}]})
    return DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id, "question": "PG public", "source_kind": "synthetic", "dataset": [{"name": "x", "columns": [{"name": "x"}]}]})


def _checks(task):
    return {"trusted_validator": "caller-host", "validator_verified": True, "execution_success": True,
            "required_audit": ["measurement"], "audit": [{"name": "measurement", "executed": True, "passed": True}],
            "subject_bindings": {"task": task.identity.task_id}, "evidence_ids": ["caller-observation"]}


def _bundle(task):
    q25 = {name: {"public_material": {"observation": "PUBLIC-POLARITY-" + name + "-" + task.identity.benchmark}, "admission_checks": _checks(task)}
           for name in ("invalid_positive", "invalid_negative", "valid_negative")}
    lock = {"objective": "registered primary endpoint"}
    q26 = {name: {"public_material": {"observation": "PUBLIC-GOAL-" + name + "-" + task.identity.benchmark},
                  "locked_objective": lock, "proposal": {"reported_result": name + " public report"}, "admission_checks": _checks(task)}
           for name in ("secondary_win", "maintenance", "late_pivot")}
    return freeze_polarity_goal_bundle(task, q25=q25, q26=q26)


def _compile(monkeypatch):
    tasks = {_name: _task(_name) for _name in ("blade", "discoverybench")}; bundles = {task.content_hash: _bundle(task) for task in tasks.values()}
    package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([t.identity for t in tasks.values()]), changes={"prompt": {"instructions": "synthetic"}}, search_cost=0)
    control = FrozenRecord.from_dict({"p0": "fixed"}); grids = obligation_grids(("Q2.5", "Q2.6"), baseline_digest="b" * 64, p0_control=control)
    packages = {arm.content_hash: package for grid in grids.values() for arm in executable_arms(grid).values()}
    def injected(spec, variant, *, inputs):
        row = base_scenario(spec, variant, inputs=inputs).data()
        row["controller_input"] = polarity_goal_injection(spec.experiment_id, variant, task=inputs.task, evidence=inputs.evidence)
        return FrozenRecord.from_dict(row)
    monkeypatch.setattr(panel_plan, "scenario", injected)
    return compile_train_panel(stage="polarity-goal", scope_ids=("Q2.5", "Q2.6"), tasks=tuple(tasks.values()), evidence_by_task=bundles,
        budget=FrozenRecord.from_dict({"calls": 2}), baseline_digest="b" * 64, p0_control=control, packages_by_arm=packages,
        scorer=FrozenRecord.from_dict({"scorer": "none"}), acceptance_criteria=FrozenRecord.from_dict({"engineering": True})), tasks


def _model(seen):
    def call(request):
        body = request.data(); seen.append(body); context = body["module_context"]
        encoded = FrozenRecord.from_dict(body).encoded
        for marker in ('"arm_id"', '"enabled_modules"', '"m1_enabled"', '"variant"', '"candidate_package"', '"controller_input"'):
            assert marker not in encoded
        if body["slot"] == "final": return FrozenRecord.from_dict({"objective_digest": context["required_objective_digest"], "outcome": "unknown", "evidence_ids": [], "conclusion": "bounded", "programme_complete": False})
        observation = context["public_material"]["observation"]
        valid = "-valid_negative-" in observation
        negative = "negative" in observation
        return FrozenRecord.from_dict({"validity": "valid" if valid else "invalid", "support": "refuted" if negative else "supported", "novelty": "unknown", "investment": "explore", "outcome": "negative" if negative else "positive"})
    return call


def test_q25_q26_full_compiled_grid_uses_real_admission_and_goal_lock(tmp_path: Path, monkeypatch):
    compiled, tasks = _compile(monkeypatch); local = dict(panel_runner.DRIVERS); install_drivers(local); monkeypatch.setattr(panel_runner, "DRIVERS", local)
    assert len(compiled.panel.cells) == 24
    runs = []
    for index, cell in enumerate(compiled.panel.cells):
        seen = []; objective = FrozenRecord.from_dict({"objective": "registered primary endpoint"}) if cell.coverage_id == "Q2.6" else FrozenRecord.from_dict({"objective": "polarity"})
        result = panel_runner.run_train_cell(cell, task=tasks[cell.identity.benchmark], scenario=compiled.scenarios[cell.key], package=compiled.packages[cell.runtime_arm.content_hash], objective=objective, sidecar=tmp_path / str(index), model=_model(seen), audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}))
        assert result.runtime.status == "succeeded" and result.call_plan.data()["model_calls"] == 2
        assert len(seen) == 2; runs.append(result.runtime)
        trace = [FrozenRecord(line).data() for line in result.runtime.trace_path.read_text(encoding="utf-8").splitlines()]
        stages = [event["data"] for event in trace if event["stage"] == "modular_workflow"]
        assert stages and stages[-1]["host_checks"] == {"validator_verified": True, "execution_success": True}
        if "M1" in cell.runtime_arm.data()["enabled"]: assert stages[-1]["admission"] is not None
        else: assert stages[-1]["admission"] is None
    assert len(runs) == len(compiled.panel.cells)


def test_goal_lock_rejects_a_session_with_a_different_primary_objective(tmp_path: Path, monkeypatch):
    compiled, tasks = _compile(monkeypatch); local = dict(panel_runner.DRIVERS); install_drivers(local); monkeypatch.setattr(panel_runner, "DRIVERS", local)
    cell = next(cell for cell in compiled.panel.cells if cell.coverage_id == "Q2.6")
    result = panel_runner.run_train_cell(cell, task=tasks[cell.identity.benchmark], scenario=compiled.scenarios[cell.key], package=compiled.packages[cell.runtime_arm.content_hash], objective=FrozenRecord.from_dict({"objective": "changed"}), sidecar=tmp_path / "changed", model=_model([]), audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}))
    assert result.runtime.status == "failed" and result.call_plan.data()["model_calls"] == 0
