"""Two-benchmark execution checks for Q2.2/Q6.4 semantic panel drivers."""
from dataclasses import replace
from pathlib import Path

import pytest

from research_loop.modular import panel_runner
from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_plan import compile_train_panel, executable_arms, obligation_grids
from research_loop.modular.panel_receipts import PanelReceiptVerifier
from research_loop.modular.p0_panel import fixed_control_design
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.semantic_panel_drivers import (
    freeze_semantic_panel_bundle,
    install_drivers,
    semantic_panel_injection,
)
from research_loop.ontology import ContractError


SPLIT = "6" * 64
AUDIT_KEYS = {"semantic-a": b"a" * 32, "semantic-b": b"b" * 32}
P0_CONTROL = FrozenRecord.from_dict({"p0": "fixed semantic scorer source"})


def _task(name):
    identity = DataIdentity(name, "sem-" + name, name + ":sem", "synthetic-v1", SPLIT, "train")
    if name == "blade":
        return BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": "public",
            "research_question": "Synthetic public semantic question", "data_schema": [{"name": "x", "dtype": "float"}]})
    return DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id, "question": "Synthetic public semantic question",
        "source_kind": "synthetic", "dataset": [{"name": "x", "columns": [{"name": "x"}]}]})


def _answer(task, raw_answer, *, evidence="Public source supports inspecting this submitted answer."):
    return {"source_id": task.identity.group_id, "raw_answer": raw_answer, "public_evidence": {"pub-1": evidence}}


def _bundle(task, p0_grid):
    q22 = {
        "affirm": _answer(task, "The registered programme is complete."),
        "negate": _answer(task, "The registered programme is not complete."),
        "quote": _answer(task, "A report quotes: 'the registered programme is complete'."),
        "counterfactual": _answer(task, "If a future measurement succeeded, the registered programme would be complete."),
        "local": _answer(task, "One local component is complete while the registered programme remains unresolved."),
    }
    q64 = {
        "negation": {"first": _answer(task, "The registered programme is not complete."),
                     "second": _answer(task, "The registered programme is not complete according to a second public answer."),
                     "legacy_diagnostic": {"status": "legacy-unmodified", "record_digest": "a" * 64}},
        "quotation": {"first": _answer(task, "A report quotes: 'the registered programme is complete'."),
                      "second": _answer(task, "A second report quotes: 'the registered programme is complete'."),
                      "legacy_diagnostic": {"status": "legacy-unmodified", "record_digest": "b" * 64}},
        "alternative": {"first": _answer(task, "A candidate alternative analysis is required before completion can be considered."),
                        "second": _answer(task, "A second candidate alternative analysis is required before completion can be considered."),
                        "legacy_diagnostic": {"status": "legacy-unmodified", "record_digest": "c" * 64}},
    }
    return freeze_semantic_panel_bundle(task, q22=q22, q64=q64, p0_fixed_control=p0_grid)


def _compile(monkeypatch):
    tasks = {name: _task(name) for name in ("blade", "discoverybench")}
    control = P0_CONTROL
    grids = obligation_grids(("Q2.2", "Q6.4"), baseline_digest="s" * 64, p0_control=control)
    bundles = {task.content_hash: _bundle(task, grids["Q2.2"]) for task in tasks.values()}
    local = dict(panel_runner.DRIVERS); install_drivers(local, expected_p0_control_digest=control.content_hash); monkeypatch.setattr(panel_runner, "DRIVERS", local)
    package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([task.identity for task in tasks.values()]),
        changes={"prompt": {"instructions": "synthetic semantic evaluation"}}, search_cost=0)
    packages = {arm.content_hash: package for grid in grids.values() for arm in executable_arms(grid).values()}
    compiled = compile_train_panel(stage="semantic-panel", scope_ids=("Q2.2", "Q6.4"), tasks=tuple(tasks.values()),
        evidence_by_task=bundles, budget=FrozenRecord.from_dict({"calls": 5}), baseline_digest="s" * 64, p0_control=control,
        packages_by_arm=packages, scorer=FrozenRecord.from_dict({"scorer": "external-not-invoked"}),
        acceptance_criteria=FrozenRecord.from_dict({"engineering": True}))
    return compiled, tasks


def _semantic_response(raw):
    if "not complete" in raw:
        polarity, scope = "negated", "programme"
    elif "quotes:" in raw:
        polarity, scope = "quoted", "programme"
    elif raw.startswith("If "):
        polarity, scope = "counterfactual", "programme"
    elif "local component" in raw:
        polarity, scope = "affirmed", "local"
    elif "alternative analysis" in raw:
        polarity, scope = "unknown", "none"
    else:
        polarity, scope = "affirmed", "programme"
    abstained = polarity == "unknown"
    return {"polarity": polarity, "scope": scope, "evidence_refs": [] if abstained else ["pub-1"], "abstained": abstained,
        "rationale": "Synthetic model interpretation of the submitted public answer.",
        "alternative_analysis": {"status": "considered", "rationale": "An alternative is retained for external assessment.",
            "candidate_specifications": [{"specification_id": "alt-1", "link": "public-link", "function": "compare explanation"}]}}


def _model(seen, *, malformed_slot=None):
    def call(request):
        body = request.data(); seen.append(body)
        encoded = FrozenRecord.from_dict(body).encoded
        # Controller labels and historical diagnostics must never reach either
        # semantic judge, alternative judge, or final candidate request.
        for marker in ('"variant"', '"arm_id"', '"enabled_modules"', '"expected"', '"truth"', '"legacy_diagnostic"', '"controller_input"'):
            assert marker not in encoded
        if body["slot"] == malformed_slot:
            return FrozenRecord.from_dict({"malformed": True})
        context = body["module_context"]
        if body["slot"].endswith("alternative_analysis") or body["slot"] == "alternative_analysis":
            return FrozenRecord.from_dict({"scientific_acceptability": "unknown", "rationale": "Synthetic external assessment is not a calibration claim."})
        if body["slot"] == "final":
            return FrozenRecord.from_dict({"objective_digest": context["required_objective_digest"], "outcome": "unknown", "evidence_ids": [],
                "conclusion": "Synthetic train-only candidate retained without a scientific claim.", "programme_complete": False})
        return FrozenRecord.from_dict(_semantic_response(context["semantic_request"]["raw_answer"]))
    return call


def _run(compiled, tasks, cell, sidecar, *, malformed_slot=None):
    seen = []
    result = panel_runner.run_train_cell(cell, task=tasks[cell.identity.benchmark], scenario=compiled.scenarios[cell.key],
        package=compiled.packages[cell.runtime_arm.content_hash], objective=FrozenRecord.from_dict({"objective": "semantic test"}),
        sidecar=sidecar, model=_model(seen, malformed_slot=malformed_slot), audit_verifier=AuditVerifier(AUDIT_KEYS))
    return result, seen


def _workflow_stage(result):
    return next(FrozenRecord(line).data()["data"] for line in result.runtime.trace_path.read_text(encoding="utf-8").splitlines()
                if FrozenRecord(line).data()["stage"] == "modular_workflow")


def test_full_two_benchmark_grid_runs_real_semantic_and_alternative_calls(tmp_path: Path, monkeypatch):
    compiled, tasks = _compile(monkeypatch)
    assert len(compiled.panel.cells) == 16
    assert {cell.runtime_arm.data()["baseline_digest"] for cell in compiled.panel.cells} == {"s" * 64}
    runtimes, q22_scores, q64_scores = [], {}, {}
    for index, cell in enumerate(compiled.panel.cells):
        result, seen = _run(compiled, tasks, cell, tmp_path / str(index)); runtimes.append(result.runtime)
        assert result.runtime.status == "succeeded"
        expected_calls = 3 if cell.coverage_id == "Q2.2" else 5
        assert result.call_plan.data()["model_calls"] == expected_calls == len(seen)
        stage = _workflow_stage(result)
        if cell.coverage_id == "Q2.2": q22_scores[(cell.identity.benchmark, cell.variant)] = stage["semantic_score"]
        else: q64_scores[(cell.identity.benchmark, cell.variant)] = stage
    assert all(q22_scores[(benchmark, "affirm")]["programme_completion_claim"] is True for benchmark in tasks)
    assert all(q22_scores[(benchmark, variant)]["programme_completion_claim"] is False
               for benchmark in tasks for variant in ("negate", "quote", "counterfactual", "local"))
    assert all(stage["first_score"]["semantics_digest"] == stage["second_score"]["semantics_digest"] == stage["semantics_digest"]
               for stage in q64_scores.values())
    assert all(stage["legacy_role"] == "diagnostic_only_not_used_for_scoring" for stage in q64_scores.values())
    verdict = PanelReceiptVerifier().verify(compiled.panel, tuple(runtimes))
    assert verdict.engineering_verified is True and verdict.observed_cells == 16


def test_malformed_semantic_response_keeps_a_failed_cell_in_the_full_denominator(tmp_path: Path, monkeypatch):
    compiled, tasks = _compile(monkeypatch); runtimes = []
    for index, cell in enumerate(compiled.panel.cells):
        bad = "semantic_judgement" if (cell.coverage_id, cell.variant, cell.identity.benchmark) == ("Q2.2", "affirm", "blade") else None
        result, seen = _run(compiled, tasks, cell, tmp_path / str(index), malformed_slot=bad); runtimes.append(result.runtime)
        if bad:
            assert result.runtime.status == "failed" and result.call_plan.data()["model_calls"] == 1 and len(seen) == 1
    verdict = PanelReceiptVerifier().verify(compiled.panel, tuple(runtimes))
    assert verdict.engineering_verified is True and verdict.observed_cells == 16
    assert sum(runtime.status == "failed" for runtime in runtimes) == 1


def test_bad_source_or_label_cue_is_rejected_before_any_semantic_model_call(tmp_path: Path, monkeypatch):
    compiled, tasks = _compile(monkeypatch)
    cell = next(item for item in compiled.panel.cells if item.coverage_id == "Q2.2" and item.variant == "affirm")
    scenario_body = compiled.scenarios[cell.key].data(); bundle = scenario_body["controller_input"]["bundle"]
    bundle["q22"]["affirm"]["source_id"] = "wrong-source"
    bad_bundle = FrozenRecord.from_dict(bundle); scenario_body["controller_input"] = {"schema": "semantic-panel-controller-v2",
        "bundle": bad_bundle.data(), "p0_fixed_control": scenario_body["controller_input"]["p0_fixed_control"]}
    scenario_body["base"]["evidence"] = bad_bundle.content_hash
    scenario = FrozenRecord.from_dict(scenario_body); bad_cell = replace(cell, scenario_digest=scenario.content_hash)
    result, seen = _run(replace(compiled, scenarios={**compiled.scenarios, bad_cell.key: scenario}), tasks, bad_cell, tmp_path / "bad-source")
    assert result.runtime.status == "failed" and result.call_plan.data()["model_calls"] == 0 and not seen
    task = tasks[cell.identity.benchmark]
    row = _answer(task, "A submitted answer")
    row["expected_truth"] = "affirmed"
    with pytest.raises(ContractError):
        freeze_semantic_panel_bundle(task, q22={**{name: _answer(task, "A submitted answer") for name in ("affirm", "negate", "quote", "counterfactual", "local")}, "affirm": row},
            q64=_bundle(task, fixed_control_design("s" * 64, P0_CONTROL.content_hash)).data()["q64"],
            p0_fixed_control=fixed_control_design("s" * 64, P0_CONTROL.content_hash))


def test_projection_rejects_different_p0_grid_and_noncanonical_caller_bundle(tmp_path: Path, monkeypatch):
    compiled, tasks = _compile(monkeypatch)
    cell = next(item for item in compiled.panel.cells if item.coverage_id == "Q2.2" and item.variant == "affirm")
    task = tasks[cell.identity.benchmark]; bundle = _bundle(task, compiled.panel.legal_arm_grids["Q2.2"])
    different = fixed_control_design("s" * 64, FrozenRecord.from_dict({"p0": "different actual control"}).content_hash)
    with pytest.raises(ContractError, match="P0 control"):
        semantic_panel_injection("Q2.2", "affirm", task=FrozenRecord.from_dict(task.data()), evidence=bundle,
            p0_fixed_control=different)
    expanded = FrozenRecord.from_dict({**bundle.data(), "unexpected": "controller label"})
    with pytest.raises(ContractError, match="canonical closed reconstruction"):
        semantic_panel_injection("Q2.2", "affirm", task=FrozenRecord.from_dict(task.data()), evidence=expanded,
            p0_fixed_control=compiled.panel.legal_arm_grids["Q2.2"])
    # A hand-edited scenario cannot swap to a second actual-control record.
    scenario_body = compiled.scenarios[cell.key].data()
    scenario_body["controller_input"]["p0_fixed_control"] = different.data()
    scenario = FrozenRecord.from_dict(scenario_body); changed = replace(cell, scenario_digest=scenario.content_hash)
    seen = []
    result = panel_runner.run_train_cell(changed, task=task, scenario=scenario,
        package=compiled.packages[changed.runtime_arm.content_hash], objective=FrozenRecord.from_dict({"objective": "semantic test"}),
        sidecar=tmp_path / "different-p0", model=_model(seen), audit_verifier=AuditVerifier(AUDIT_KEYS))
    assert result.runtime.status == "failed" and result.call_plan.data()["model_calls"] == 0 and not seen


def test_payload_controller_cell_and_package_binding_fail_before_model_call(tmp_path: Path, monkeypatch):
    compiled, tasks = _compile(monkeypatch)
    cell = next(item for item in compiled.panel.cells if item.coverage_id == "Q2.2" and item.variant == "affirm")
    original = tasks[cell.identity.benchmark]
    # The identity is unchanged, so this catches the payload digest rather than
    # merely a public identifier mismatch.
    changed_payload = {**original.payload.data(), "changed_public_packet": "different source-bound task"}
    changed_task = PublicTask(original.identity, FrozenRecord.from_dict(changed_payload))
    payload_scenario_body = compiled.scenarios[cell.key].data(); payload_scenario_body["base"]["task"] = changed_task.content_hash
    payload_scenario = FrozenRecord.from_dict(payload_scenario_body)
    payload_cell = replace(cell, task_digest=changed_task.content_hash, scenario_digest=payload_scenario.content_hash)
    seen = []
    result = panel_runner.run_train_cell(payload_cell, task=changed_task, scenario=payload_scenario,
        package=compiled.packages[payload_cell.runtime_arm.content_hash], objective=FrozenRecord.from_dict({"objective": "semantic test"}),
        sidecar=tmp_path / "payload", model=_model(seen), audit_verifier=AuditVerifier(AUDIT_KEYS))
    assert result.runtime.status == "failed" and result.call_plan.data()["model_calls"] == 0 and not seen
    controller_body = compiled.scenarios[cell.key].data(); controller_body["controller_input"]["unexpected"] = "controller cue"
    controller_scenario = FrozenRecord.from_dict(controller_body); controller_cell = replace(cell, scenario_digest=controller_scenario.content_hash)
    result, seen = _run(replace(compiled, scenarios={**compiled.scenarios, controller_cell.key: controller_scenario}), tasks,
        controller_cell, tmp_path / "controller")
    assert result.runtime.status == "failed" and result.call_plan.data()["model_calls"] == 0 and not seen
    # Runner-level cell/scenario and package checks happen before a RunSession
    # can issue a model request.
    seen = []
    with pytest.raises(ContractError):
        panel_runner.run_train_cell(replace(cell, variant="negate"), task=original, scenario=compiled.scenarios[cell.key],
            package=compiled.packages[cell.runtime_arm.content_hash], objective=FrozenRecord.from_dict({"objective": "semantic test"}),
            sidecar=tmp_path / "cell", model=_model(seen), audit_verifier=AuditVerifier(AUDIT_KEYS))
    assert not seen
    wrong_package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([task.identity for task in tasks.values()]),
        changes={"prompt": {"instructions": "different frozen package"}}, search_cost=0)
    with pytest.raises(ContractError):
        panel_runner.run_train_cell(cell, task=original, scenario=compiled.scenarios[cell.key], package=wrong_package,
            objective=FrozenRecord.from_dict({"objective": "semantic test"}), sidecar=tmp_path / "package",
            model=_model(seen), audit_verifier=AuditVerifier(AUDIT_KEYS))
    assert not seen


def test_missing_trusted_p0_control_configuration_fails_before_model_call(tmp_path: Path, monkeypatch):
    compiled, tasks = _compile(monkeypatch)
    # A P0 grid in caller material cannot authenticate itself: integration must
    # configure the trusted compiled-control digest on the driver.
    local = dict(panel_runner.DRIVERS); install_drivers(local); monkeypatch.setattr(panel_runner, "DRIVERS", local)
    cell = next(item for item in compiled.panel.cells if item.coverage_id == "Q2.2" and item.variant == "affirm")
    result, seen = _run(compiled, tasks, cell, tmp_path / "missing-trusted-p0")
    assert result.runtime.status == "failed" and result.call_plan.data()["model_calls"] == 0 and not seen
