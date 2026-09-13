"""Two-benchmark behavior checks for caller-bound Q2.5/Q2.6 drivers."""
from dataclasses import replace
from pathlib import Path

from research_loop.modular import panel_plan, panel_runner
from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.experiments import scenario as base_scenario
from research_loop.modular.modules.admission import AuditItem, EvidenceAdmission, ScientificState
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_plan import compile_train_panel, executable_arms, obligation_grids
from research_loop.modular.panel_receipts import PanelReceiptVerifier
from research_loop.modular.polarity_goal_panel_drivers import admission_subject, freeze_polarity_goal_bundle, install_drivers, polarity_goal_injection
from research_loop.modular.runtime import AuditAuthority, AuditVerifier

SPLIT = "5" * 64
KEYS = {"authority-a": b"a" * 32, "authority-b": b"b" * 32}


def _task(name):
    identity = DataIdentity(name, "pg-" + name, name + ":pg", "synthetic-v1", SPLIT, "train")
    if name == "blade":
        return BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": "public", "research_question": "PG public", "data_schema": [{"name": "x", "dtype": "float"}]})
    return DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id, "question": "PG public", "source_kind": "synthetic", "dataset": [{"name": "x", "columns": [{"name": "x"}]}]})


def _signed_item(task, *, experiment, observation, state, outcome, locked=None, proposal=None):
    public = {"source_id": task.identity.group_id, "observation": observation}
    subject = admission_subject(task, experiment_id=experiment, public_material=public,
                                locked_objective=locked, proposal=proposal)
    receipts = [AuditAuthority(name, key).issue_material(identity=task.identity, subject_digest=subject.content_hash,
        execution_success=True, state=state, outcome=outcome, audit=[AuditItem("measurement", True, True)]).data()
        for name, key in KEYS.items()]
    item = {"public_material": public, "admission_receipts": receipts}
    if experiment == "Q2.6":
        item.update({"locked_objective": locked, "proposal": proposal})
    return item


def _bundle(task):
    q25 = {
        "invalid_positive": _signed_item(task, experiment="Q2.5", observation="Public source reports an apparent increase.",
            state=ScientificState("invalid", "supported", "unknown", "explore"), outcome="positive"),
        "invalid_negative": _signed_item(task, experiment="Q2.5", observation="Public source reports a refuting observation.",
            state=ScientificState("invalid", "refuted", "unknown", "explore"), outcome="negative"),
        "valid_negative": _signed_item(task, experiment="Q2.5", observation="Public source reports the registered effect was not observed.",
            state=ScientificState("valid", "refuted", "unknown", "explore"), outcome="negative"),
    }
    locked = {"objective": "registered primary endpoint"}
    secondary = FrozenRecord.from_dict({"objective": "secondary endpoint"}).content_hash
    q26 = {
        "secondary_win": _signed_item(task, experiment="Q2.6", observation="A source describes a secondary endpoint result.",
            locked=locked, proposal={"source_id": task.identity.group_id, "statement": "The report discusses an endpoint."},
            state=ScientificState("valid", "supported", "unknown", "explore"), outcome="positive"),
        "maintenance": _signed_item(task, experiment="Q2.6", observation="A source supports retaining the registered endpoint.",
            locked=locked, proposal={"source_id": task.identity.group_id, "statement": "The report discusses the registered endpoint."},
            state=ScientificState("valid", "supported", "unknown", "explore"), outcome="positive"),
        "late_pivot": _signed_item(task, experiment="Q2.6", observation="A source suggests revising the endpoint after review.",
            locked=locked, proposal={"source_id": task.identity.group_id, "statement": "The report suggests a later revision."},
            state=ScientificState("valid", "supported", "unknown", "explore"), outcome="positive"),
    }
    return freeze_polarity_goal_bundle(task, q25=q25, q26=q26), secondary


def _compile(monkeypatch):
    tasks = {name: _task(name) for name in ("blade", "discoverybench")}
    made = {task.content_hash: _bundle(task) for task in tasks.values()}
    bundles = {digest: bundle for digest, (bundle, _secondary) in made.items()}
    secondary = {task.identity.group_id: made[task.content_hash][1] for task in tasks.values()}
    package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([t.identity for t in tasks.values()]), changes={"prompt": {"instructions": "synthetic"}}, search_cost=0)
    control = FrozenRecord.from_dict({"p0": "fixed"}); grids = obligation_grids(("Q2.5", "Q2.6"), baseline_digest="b" * 64, p0_control=control)
    packages = {arm.content_hash: package for grid in grids.values() for arm in executable_arms(grid).values()}
    compiled = compile_train_panel(stage="polarity-goal", scope_ids=("Q2.5", "Q2.6"), tasks=tuple(tasks.values()), evidence_by_task=bundles,
        budget=FrozenRecord.from_dict({"calls": 2}), baseline_digest="b" * 64, p0_control=control, packages_by_arm=packages,
        scorer=FrozenRecord.from_dict({"scorer": "none"}), acceptance_criteria=FrozenRecord.from_dict({"engineering": True}))
    return compiled, tasks, secondary


def _model(seen, secondary_by_task, *, mismatched_receipt=False):
    def call(request):
        body = request.data(); seen.append(body); context = body["module_context"]
        encoded = FrozenRecord.from_dict(body).encoded
        for marker in ('"arm_id"', '"enabled_modules"', '"m1_enabled"', '"variant"', '"candidate_package"', '"controller_input"', '"admission_receipts"'):
            assert marker not in encoded
        if body["slot"] == "final":
            assessment = context["assessment"]
            goal = assessment.get("selected_objective_digest", context["required_objective_digest"])
            outcome = "negative" if assessment["outcome"] == "negative" else "positive"
            if context["permitted_outcomes"] == ["unknown"]:
                outcome = "unknown"
            return FrozenRecord.from_dict({"objective_digest": goal, "outcome": outcome, "evidence_ids": [],
                                           "conclusion": "synthetic train-only response", "programme_complete": False})
        observation = context["public_material"]["observation"]
        if "registered effect was not observed" in observation:
            state, outcome = ("valid", "refuted"), "negative"
        elif "refuting" in observation:
            state, outcome = ("invalid", "refuted"), "negative"
        else:
            state, outcome = ("invalid", "supported"), "positive"
        if "locked_objective" in context:
            state, outcome = ("valid", "supported"), "positive"
            selected = context["required_objective_digest"]
            if "secondary endpoint" in observation:
                selected = secondary_by_task[context["public_material"]["source_id"]]
            elif "revising" in observation:
                selected = FrozenRecord.from_dict({"objective": "late pivot"}).content_hash
            response = {"validity": state[0], "support": state[1], "novelty": "unknown", "investment": "explore",
                        "outcome": outcome, "selected_objective_digest": selected}
        else:
            response = {"validity": state[0], "support": state[1], "novelty": "unknown", "investment": "explore", "outcome": outcome}
        if mismatched_receipt:
            response["validity"] = "invalid" if response["validity"] == "valid" else "valid"
        return FrozenRecord.from_dict(response)
    return call


def _run(compiled, tasks, secondary, cell, sidecar, *, mismatched_receipt=False):
    seen = []
    objective = FrozenRecord.from_dict({"objective": "registered primary endpoint"}) if cell.coverage_id == "Q2.6" else FrozenRecord.from_dict({"objective": "polarity"})
    result = panel_runner.run_train_cell(cell, task=tasks[cell.identity.benchmark], scenario=compiled.scenarios[cell.key],
        package=compiled.packages[cell.runtime_arm.content_hash], objective=objective, sidecar=sidecar,
        model=_model(seen, secondary, mismatched_receipt=mismatched_receipt), audit_verifier=AuditVerifier(KEYS))
    return result, seen


def _workflow_stages(result):
    return [FrozenRecord(line).data()["data"] for line in result.runtime.trace_path.read_text(encoding="utf-8").splitlines()
            if FrozenRecord(line).data()["stage"] == "modular_workflow"]


def test_full_grid_exercises_polarity_goal_pivots_and_real_m1_gate(tmp_path: Path, monkeypatch):
    compiled, tasks, secondary = _compile(monkeypatch)
    assert len(compiled.panel.cells) == 24
    assert {cell.runtime_arm.data()["baseline_digest"] for cell in compiled.panel.cells} == {"b" * 64}
    assert {compiled.packages[cell.runtime_arm.content_hash].digest for cell in compiled.panel.cells} == {next(iter(compiled.packages.values())).digest}
    runs = []
    observed = {}
    for index, cell in enumerate(compiled.panel.cells):
        result, seen = _run(compiled, tasks, secondary, cell, tmp_path / str(index))
        runs.append(result.runtime); observed[(cell.coverage_id, cell.variant, "M1" in cell.runtime_arm.data()["enabled"])] = result
        assert result.call_plan.data()["model_calls"] == 2 and len(seen) == 2
        stages = _workflow_stages(result); assert len(stages) == 1
        stage = stages[0]
        if "M1" in cell.runtime_arm.data()["enabled"]:
            assert stage["admission"] is not None and stage["receipt_digest"]
            assert "host_checks" not in FrozenRecord.from_dict(stage).encoded
        else:
            assert stage["admission"] is None
        if cell.coverage_id == "Q2.6":
            assert stage["selected_goal_digest"]
    # Valid negative evidence is admitted exactly like a positive claim would be;
    # both invalid polarity directions are rejected by M1 while their controls run.
    assert observed[("Q2.5", "invalid_positive", True)].runtime.status == "succeeded"
    assert observed[("Q2.5", "invalid_negative", True)].runtime.status == "succeeded"
    assert observed[("Q2.5", "valid_negative", True)].runtime.status == "blocked"
    assert observed[("Q2.5", "invalid_positive", False)].runtime.status == "blocked"
    # Model-selected secondary and late objective pivots reach M1 and are rejected;
    # the M1-off arm retains their responses for the ordinary final controller gate.
    assert observed[("Q2.6", "secondary_win", True)].runtime.status == "failed"
    assert observed[("Q2.6", "late_pivot", True)].runtime.status == "failed"
    assert observed[("Q2.6", "maintenance", True)].runtime.status == "blocked"
    assert observed[("Q2.6", "secondary_win", False)].runtime.status == "blocked"
    verdict = PanelReceiptVerifier().verify(compiled.panel, tuple(runs))
    assert verdict.engineering_verified is True and verdict.observed_cells == 24 and sum(row.status == "failed" for row in runs) == 4


def test_m1_requires_the_model_judgement_to_match_the_verified_receipt(tmp_path: Path, monkeypatch):
    compiled, tasks, secondary = _compile(monkeypatch); local = dict(panel_runner.DRIVERS); install_drivers(local); monkeypatch.setattr(panel_runner, "DRIVERS", local)
    cell = next(c for c in compiled.panel.cells if c.coverage_id == "Q2.5" and c.variant == "valid_negative" and "M1" in c.runtime_arm.data()["enabled"])
    result, seen = _run(compiled, tasks, secondary, cell, tmp_path / "mismatch", mismatched_receipt=True)
    assert result.runtime.status == "succeeded" and result.call_plan.data()["model_calls"] == 2 and len(seen) == 2
    stage = _workflow_stages(result)[0]
    assert stage["admission"]["receipt_match"] is False
    assert stage["admission"]["disposition"]["admitted"] is False


def test_only_the_m1_arm_invokes_evidence_admission_after_common_receipt_verification(tmp_path: Path, monkeypatch):
    compiled, tasks, secondary = _compile(monkeypatch); local = dict(panel_runner.DRIVERS); install_drivers(local); monkeypatch.setattr(panel_runner, "DRIVERS", local)
    original = EvidenceAdmission.decide; calls = []
    def tracked(**kwargs):
        calls.append(kwargs["identity"].task_id)
        return original(**kwargs)
    monkeypatch.setattr(EvidenceAdmission, "decide", staticmethod(tracked))
    controls = [c for c in compiled.panel.cells if c.coverage_id == "Q2.5" and c.variant == "valid_negative"]
    off = next(c for c in controls if "M1" not in c.runtime_arm.data()["enabled"])
    on = next(c for c in controls if "M1" in c.runtime_arm.data()["enabled"])
    off_result, off_seen = _run(compiled, tasks, secondary, off, tmp_path / "off")
    assert off_result.call_plan.data()["model_calls"] == 2 and len(off_seen) == 2 and calls == []
    on_result, on_seen = _run(compiled, tasks, secondary, on, tmp_path / "on")
    assert on_result.call_plan.data()["model_calls"] == 2 and len(on_seen) == 2 and calls == [on.identity.task_id]


def test_forged_or_malformed_authority_material_fails_before_any_model_call(tmp_path: Path, monkeypatch):
    compiled, tasks, secondary = _compile(monkeypatch); local = dict(panel_runner.DRIVERS); install_drivers(local); monkeypatch.setattr(panel_runner, "DRIVERS", local)
    original = next(c for c in compiled.panel.cells if c.coverage_id == "Q2.5")
    scenario_body = compiled.scenarios[original.key].data()
    bundle_body = scenario_body["controller_input"]["bundle"]
    receipt = bundle_body["q25"][original.variant]["admission_receipts"][0]
    receipt["body"]["execution_success"] = "true"  # signature is now forged, not a host fact.
    bad_bundle = FrozenRecord.from_dict(bundle_body)
    scenario_body["base"]["evidence"] = bad_bundle.content_hash
    scenario_body["controller_input"] = {"schema": "polarity-goal-controller-v2", "bundle": bad_bundle.data()}
    bad_scenario = FrozenRecord.from_dict(scenario_body)
    bad_cell = replace(original, scenario_digest=bad_scenario.content_hash)
    seen = []
    result = panel_runner.run_train_cell(bad_cell, task=tasks[bad_cell.identity.benchmark], scenario=bad_scenario,
        package=compiled.packages[bad_cell.runtime_arm.content_hash], objective=FrozenRecord.from_dict({"objective": "polarity"}),
        sidecar=tmp_path / "forged", model=_model(seen, secondary), audit_verifier=AuditVerifier(KEYS))
    assert result.runtime.status == "failed" and result.call_plan.data()["model_calls"] == 0 and not seen


def test_goal_lock_rejects_a_session_with_a_different_primary_objective_before_model_call(tmp_path: Path, monkeypatch):
    compiled, tasks, secondary = _compile(monkeypatch); local = dict(panel_runner.DRIVERS); install_drivers(local); monkeypatch.setattr(panel_runner, "DRIVERS", local)
    cell = next(c for c in compiled.panel.cells if c.coverage_id == "Q2.6")
    seen = []
    result = panel_runner.run_train_cell(cell, task=tasks[cell.identity.benchmark], scenario=compiled.scenarios[cell.key],
        package=compiled.packages[cell.runtime_arm.content_hash], objective=FrozenRecord.from_dict({"objective": "changed"}),
        sidecar=tmp_path / "changed", model=_model(seen, secondary), audit_verifier=AuditVerifier(KEYS))
    assert result.runtime.status == "failed" and result.call_plan.data()["model_calls"] == 0 and not seen


def test_material_signatures_cannot_move_to_a_changed_task_payload(tmp_path, monkeypatch):
    from research_loop.modular.contracts import PublicTask
    compiled, tasks, secondary = _compile(monkeypatch)
    original = next(c for c in compiled.panel.cells if c.coverage_id == "Q2.5")
    task = tasks[original.identity.benchmark]
    payload = task.payload.data(); payload["question"] = "different public scientific question"
    changed = PublicTask(task.identity, FrozenRecord.from_dict(payload))
    body = compiled.scenarios[original.key].data()
    prior = body["controller_input"]["bundle"]
    bundle = freeze_polarity_goal_bundle(changed, q25=prior["q25"], q26=prior["q26"])
    body["controller_input"] = dict(polarity_goal_injection("Q2.5", original.variant,
        task=FrozenRecord.from_dict(changed.data()), evidence=bundle))
    body["base"]["task"] = changed.content_hash; body["base"]["evidence"] = bundle.content_hash
    scenario = FrozenRecord.from_dict(body)
    cell = replace(original, task_digest=changed.content_hash, scenario_digest=scenario.content_hash)
    seen = []
    result = panel_runner.run_train_cell(cell, task=changed, scenario=scenario,
        package=compiled.packages[cell.runtime_arm.content_hash], objective=FrozenRecord.from_dict({"objective": "polarity"}),
        sidecar=tmp_path / "changed-payload", model=_model(seen, secondary), audit_verifier=AuditVerifier(KEYS))
    assert result.runtime.status == "failed" and not seen


def test_valid_negative_receipt_does_not_permit_flipping_the_final_polarity(tmp_path, monkeypatch):
    compiled, tasks, secondary = _compile(monkeypatch)
    cell = next(c for c in compiled.panel.cells if c.coverage_id == "Q2.5" and c.variant == "valid_negative"
                and "M1" in c.runtime_arm.data()["enabled"])
    seen = []; callback = _model(seen, secondary)
    def flip(request):
        response = callback(request).data()
        if request.data()["slot"] == "final": response["outcome"] = "positive"
        return FrozenRecord.from_dict(response)
    result = panel_runner.run_train_cell(cell, task=tasks[cell.identity.benchmark], scenario=compiled.scenarios[cell.key],
        package=compiled.packages[cell.runtime_arm.content_hash], objective=FrozenRecord.from_dict({"objective": "polarity"}),
        sidecar=tmp_path / "flip", model=flip, audit_verifier=AuditVerifier(KEYS))
    assert result.runtime.status == "failed" and len(seen) == 2
