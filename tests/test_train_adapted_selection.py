"""Actual journal/signature/selection chain with synthetic data and transports."""
from dataclasses import replace
import hashlib
import json
import subprocess

import pytest

from evaluation.modular.linked_scoring import LinkedAdaptedScoringService, LinkedExecutionAuthority, issue_linked_score_input
from evaluation.modular.scoring_service import FrozenBenchmarkRubricEndpoint, FrozenRubricTransport, ScorerConfig
from research_loop.modular.benchmark_cell import run_benchmark_cell
from research_loop.modular.benchmarks import DockerExecutionBroker
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_plan import compile_train_panel, executable_arms, obligation_grids
from research_loop.modular.train_selection import FrozenTrainSelectionRule, measure_and_select_train, _selection
from research_loop.ontology import ContractError

from test_modular_benchmark_cell import IMAGE, _audit, _model
from test_modular_panel_runner import public_task


EXEC = LinkedExecutionAuthority("synthetic-executor", b"e" * 32)
SCORER = LinkedExecutionAuthority("synthetic-scorer", b"s" * 32)


def material(tmp_path, *, failure=False, tie=False, regression=False):
    tasks = [public_task(name) for name in ("discoverybench", "blade")]
    control = FrozenRecord.from_dict({"synthetic": True})
    arms = executable_arms(obligation_grids(("Q3.1",), baseline_digest="b" * 64, p0_control=control)["Q3.1"])
    packages = {arm.content_hash: CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze(task.identity for task in tasks),
                changes={"prompt": {"instructions": "Synthetic package " + name}}, search_cost=0) for name, arm in arms.items()}
    config = ScorerConfig.create(benchmark="core_pair", evaluator_id="synthetic-evaluator", version="v1", rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest())
    rule = FrozenTrainSelectionRule.create(coverage_id="Q3.1", baseline_arm="0", tie_break_order=("0", "1"))
    compiled = compile_train_panel(stage="synthetic-train-selection", scope_ids=("Q3.1",), tasks=tasks,
        evidence_by_task={task.content_hash: control for task in tasks}, budget=control, baseline_digest="b" * 64,
        p0_control=control, packages_by_arm=packages, scorer=config.record,
        acceptance_criteria=FrozenRecord.from_dict({"train_adapted_selection": rule.record.data()}))
    data = tmp_path / "public.csv"; data.write_text("x\n1\n3\n", encoding="utf-8")
    calls = []
    def resolve(handle, benchmark):
        return FrozenRecord.from_dict({"schema": "train-only-rubric-reference-v1", "split": "train", "benchmark": benchmark,
            "task_handle_digest": hashlib.sha256(handle.encode()).hexdigest(), "identity_digest": handle,
            "task_context": {"question": "synthetic"}, "references": [{"synthetic": "reference"}]})
    def evaluate(request):
        body = request.data(); calls.append(body)
        candidate = json.loads(body["prompt"].split("ANONYMOUS_CANDIDATE=", 1)[1])
        value = float(candidate["answer"])
        if body["benchmark"] == "blade":
            return FrozenRecord.from_dict({"cvars": value * 2, "transform": value * 2, "model": value * 2, "reason": "synthetic"})
        return FrozenRecord.from_dict({"context": 1, "variable_f1": value, "relation": 1, "reason": "synthetic"})
    endpoint = FrozenBenchmarkRubricEndpoint(resolver=resolve, evaluator=evaluate, evaluator_id="synthetic-evaluator", evaluator_version="v1")
    handles = {FrozenRecord.from_dict(task.identity.data()).content_hash: FrozenRecord.from_dict(task.identity.data()).content_hash for task in tasks}
    service = LinkedAdaptedScoringService(config=config, evaluator=FrozenRubricTransport(endpoint),
        execution_authority_keys={EXEC.authority_id: EXEC.key}, task_handles=handles, scorer_authority=SCORER)
    rows, inputs, scores = [], {}, []
    for index, cell in enumerate(compiled.panel.cells):
        def model(request):
            if request.data()["slot"] == "final_answer":
                candidate = _model([])(request).data()
                value = .5 if tie or cell.arm_id == "0" else 1
                if regression and cell.arm_id == "1" and cell.identity.benchmark == "blade": value = 0
                candidate["conclusion"] = str(value)
                return FrozenRecord.from_dict(candidate)
            return _model([])(request)
        broken = failure and index == 0
        def runner(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 1 if broken else 0, b"2.0\n", b"synthetic failure" if broken else b"")
        package = compiled.packages[cell.runtime_arm.content_hash]
        row = run_benchmark_cell(cell=cell, task=compiled.tasks[cell.task_digest], scenario=compiled.scenarios[cell.key],
            package=package, objective=FrozenRecord.from_dict({"panel_digest": compiled.panel.digest}),
            mechanism_sidecar=tmp_path / str(index) / "mechanism", solver_sidecar=tmp_path / str(index) / "solver",
            public_inputs={"public_csv": data}, image=IMAGE, broker=DockerExecutionBroker([tmp_path], runner=runner),
            model=model, audit_verifier=_audit())
        rows.append(row)
        if row.status == "linked_succeeded":
            source = issue_linked_score_input(panel=compiled.panel, result=row, task=compiled.tasks[cell.task_digest],
                scenario=compiled.scenarios[cell.key], package=package, authority=EXEC)
            inputs[cell.key] = source
            scores.append(service.score_linked(panel=compiled.panel, cell=cell, linked_input=source))
    args = dict(panel=compiled.panel, rule=rule, results=rows, tasks=compiled.tasks, scenarios=compiled.scenarios,
        packages={package.digest: package for package in packages.values()}, linked_inputs=inputs, scores=scores, config=config,
        execution_authority_keys={EXEC.authority_id: EXEC.key}, scoring_authority_keys={SCORER.authority_id: SCORER.key})
    return args, calls


def test_complete_signed_two_benchmark_panel_selects_train_only_and_retains_combinations(tmp_path):
    args, calls = material(tmp_path)
    result = measure_and_select_train(**args).data()
    assert result["status"] == "selected_for_validation" and result["selected_arm"] == "1"
    assert result["measurement"]["expected_cells"] == result["measurement"]["successful_cells"] == 12
    assert len(calls) == 12
    assert result["combination_candidates_retained"] == ["0", "1"]
    assert result["combination_pruning_authorized"] is False
    assert result["acceptance_verified"] is result["deployment_authorized"] is False
    assert result["measurement"]["mechanism_effect"] == result["scientific_validity"] == "not_measured"
    effect = result["grouped_differences"][1]
    assert effect["mean_difference"] == .5
    assert {row["benchmark"] for row in effect["benchmarks"]} == {"discoverybench", "blade"}


@pytest.mark.parametrize("flag", ["tie", "regression"])
def test_frozen_tie_order_and_per_benchmark_regression_guard(tmp_path, flag):
    args, _ = material(tmp_path, **{flag: True})
    result = measure_and_select_train(**args).data()
    assert result["selected_arm"] == "0"
    assert result["combination_candidates_retained"] == ["0", "1"]


def test_failed_execution_is_unscored_retained_and_prevents_selection(tmp_path):
    args, calls = material(tmp_path, failure=True)
    result = measure_and_select_train(**args).data()
    assert result["status"] == "inconclusive" and result["selected_arm"] is None
    assert result["measurement"]["failed_cells"] == 1 and result["measurement"]["successful_cells"] == len(calls) == 11
    assert result["grouped_differences"] == []


@pytest.mark.parametrize("mutation", ["missing_score", "duplicate_result", "signature", "rule", "validation", "current_journal", "signed_foreign_candidate"])
def test_missing_drifted_or_unauthenticated_inputs_cannot_select(tmp_path, mutation):
    args, _ = material(tmp_path)
    if mutation == "missing_score": args["scores"] = args["scores"][1:]
    elif mutation == "duplicate_result": args["results"] = [*args["results"], args["results"][0]]
    elif mutation == "signature":
        score = args["scores"][0]; envelope = score.receipt.data(); envelope["mac"] = "0" * 64
        args["scores"][0] = replace(score, receipt=FrozenRecord.from_dict(envelope))
    elif mutation == "rule":
        args["rule"] = FrozenTrainSelectionRule.create(coverage_id="Q3.1", baseline_arm="0", tie_break_order=("1", "0"))
    elif mutation == "validation":
        panel = args["panel"]
        args["panel"] = replace(panel, domain="validation", cells=tuple(replace(cell, identity=replace(cell.identity, domain="validation")) for cell in panel.cells))
    elif mutation == "signed_foreign_candidate":
        score = args["scores"][0]
        body = args["linked_inputs"][score.cell_key].data()["body"]
        body["candidate"]["answer"] = "An answer that was never produced by the solver"
        body["candidate_digest"] = FrozenRecord.from_dict(body["candidate"]).content_hash
        source = EXEC.issue(body)
        args["linked_inputs"][score.cell_key] = source
        scored = score.receipt.data()["body"]
        scored["linked_input_digest"] = source.content_hash
        scored["candidate_digest"] = body["candidate_digest"]
        args["scores"][0] = replace(score, receipt=SCORER.issue(scored))
    else:
        row = args["results"][0]
        path = row.solver.session.sidecar / "trace.jsonl"
        path.write_text(path.read_text(encoding="utf-8").replace("The synthetic", "A changed synthetic"), encoding="utf-8")
        # The final fixture answer is numeric: alter actual program response.
        path.write_text(path.read_text(encoding="utf-8").replace("calculate the public", "alter the public"), encoding="utf-8")
    with pytest.raises(ContractError): measure_and_select_train(**args)


def test_group_weighting_is_not_biased_by_many_tasks_in_one_source(tmp_path):
    args, _ = material(tmp_path)
    panel = args["panel"]
    metrics = {cell.key: 0 if cell.arm_id == "0" else 1 for cell in panel.cells}
    # Three cells in the existing source group versus one independent group;
    # duplicating a within-group task must not triple its group weight.
    cells = list(panel.cells)
    for original in tuple(panel.cells):
        if original.variant != panel.cells[0].variant: continue
        other = replace(original, identity=replace(original.identity, task_id="independent", group_id="independent-group"))
        cells.append(other); metrics[other.key] = 0
    # Only the grouping estimator is exercised here; full panel shape is checked
    # separately in the signed integration tests above.
    class GroupFixture:
        required_benchmarks = panel.required_benchmarks
    fixture = GroupFixture(); fixture.cells = cells
    effects = _selection(fixture, args["rule"].record.data(), metrics, {"0": "base", "1": "candidate"})
    assert effects["grouped_differences"][1]["mean_difference"] == .5
