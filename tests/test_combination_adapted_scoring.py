"""Synthetic Docker coverage for the signed M4+M5 adapted-scoring seam."""
from dataclasses import replace
import hashlib
import runpy

import pytest

from evaluation.modular.combination_scoring import (CombinationAdaptedScoringService, derive_combination_score_input,
    issue_combination_score_input, verify_combination_adapted_receipt, verify_combination_score_input)
from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from evaluation.modular.scoring_service import FrozenBenchmarkRubricEndpoint, FrozenRubricTransport, ScorerConfig
from research_loop.modular.combination_contrasts import estimate_grouped_contrast
from research_loop.modular.combination_panels import CombinationPanelVerifier, compile_combination_catalogue
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError, canonical

EXEC = LinkedExecutionAuthority("combination-execution", b"e" * 32)
SCORER = LinkedExecutionAuthority("combination-scorer", b"s" * 32)


def _setup(tmp_path):
    panel_helpers = runpy.run_path("tests/test_modular_combination_panels.py")
    driver_helpers = runpy.run_path("tests/test_modular_combination_benchmark_driver.py")
    tasks, packages, _scorer, _criteria = panel_helpers["_inputs"]()
    config = ScorerConfig.create(benchmark="core_pair", evaluator_id="combination-test-evaluator",
        version="v1", rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest())
    criteria = FrozenRecord.from_dict({"criterion": "synthetic train adapted score", "contrast_analysis": {
        "schema": "frozen-combination-contrast-analysis-v1", "direction": "higher_better", "value_range": [0.0, 1.0],
        "scale": "unit", "missing_policy": "incomplete_reject", "group_weighting": "task_replicate_mean_then_equal_group_mean"}})
    catalogue = compile_combination_catalogue(stage="combination-adapted-score", tasks=tasks, baseline_digest="a" * 64,
        packages_by_arm=packages, scorer=config.record, acceptance_criteria=criteria)
    panel = catalogue.panels["pair:M4+M5"]
    rows, results = [], []
    for cell in panel.cells:
        result = driver_helpers["_run"](panel, cell, catalogue, tmp_path / cell.identity.benchmark / cell.arm_id,
            driver_helpers["_model"]([]))
        assert result.runtime.status == "succeeded"
        rows.append(result.runtime); results.append(result)
    return panel, catalogue, config, tuple(rows), tuple(results)


def _service(panel, config, calls):
    handles = {hashlib.sha256(canonical(cell.identity.data()).encode()).hexdigest():
               "handle-" + cell.identity.benchmark for cell in panel.cells}
    def resolver(handle, benchmark):
        return FrozenRecord.from_dict({"schema": "train-only-rubric-reference-v1", "split": "train", "benchmark": benchmark,
            "task_handle_digest": hashlib.sha256(handle.encode()).hexdigest(),
            "identity_digest": next(key for key, value in handles.items() if value == handle), "task_context": "synthetic public task",
            "references": [{"synthetic": True}]})
    def evaluator(request):
        body = request.data(); calls.append(body)
        assert all(marker not in body["prompt"] for marker in ("M4", "M5", "pair:M4+M5", "package_digest", "joint_mechanism"))
        return FrozenRecord.from_dict(({"cvars": 2, "transform": 2, "model": 2} if body["benchmark"] == "blade"
            else {"context": 1, "variable_f1": 1, "relation": 1}) | {"reason": "synthetic engineering scorer"})
    endpoint = FrozenBenchmarkRubricEndpoint(resolver=resolver, evaluator=evaluator,
        evaluator_id="combination-test-evaluator", evaluator_version="v1")
    return CombinationAdaptedScoringService(config=config, evaluator=FrozenRubricTransport(endpoint),
        execution_authority_keys={EXEC.authority_id: EXEC.key}, task_handles=handles, scorer_authority=SCORER)


def test_real_docker_grid_derives_signs_scores_and_estimates_four_arm_contrast(tmp_path):
    panel, catalogue, config, runtime, results = _setup(tmp_path); calls = []; service = _service(panel, config, calls)
    inputs, scores = {}, []
    for result in results:
        cell = result.cell; source = issue_combination_score_input(panel=panel, result=result, task=catalogue.tasks[cell.task_digest],
            scenario=catalogue.scenarios[cell.key], package=catalogue.packages[cell.runtime_arm.content_hash], authority=EXEC)
        assert derive_combination_score_input(panel=panel, result=result, task=catalogue.tasks[cell.task_digest],
            scenario=catalogue.scenarios[cell.key], package=catalogue.packages[cell.runtime_arm.content_hash]).data()["candidate"] == source.data()["body"]["candidate"]
        score = service.score_combination(panel=panel, cell=cell, score_input=source)
        verify_combination_adapted_receipt(score, authority_keys={SCORER.authority_id: SCORER.key}, config=config, panel=panel,
            cell=cell, score_input=source, execution_authority_keys={EXEC.authority_id: EXEC.key})
        inputs[cell.key] = source; scores.append(score)
    verifier = CombinationPanelVerifier(scorer_verifier=lambda score, cell, checked: verify_combination_adapted_receipt(
        score, authority_keys={SCORER.authority_id: SCORER.key}, config=config, panel=checked, cell=cell,
        score_input=inputs[cell.key], execution_authority_keys={EXEC.authority_id: EXEC.key}))
    assert all(score.receipt.data()["body"]["scorer_digest"] == next(cell.scorer_digest for cell in panel.cells if cell.key == score.cell_key)
               and score.receipt.data()["body"]["runtime_trace_digest"] == next(row.trace_digest for row in runtime if row.cell_key == score.cell_key)
               for score in scores)
    assert verifier.verify(panel, runtime, scorer_receipts=scores).engineering_verified is True
    contrast = estimate_grouped_contrast(panel, runtime=runtime, scorer_receipts=scores, verifier=verifier).data()
    assert contrast["status"] == "estimated" and all(value["mean"] == 0.0 for value in contrast["benchmark_estimates"].values())
    assert len(calls) == 8


def test_signed_source_and_score_binding_tampering_and_missing_or_failed_cells_are_rejected(tmp_path):
    panel, catalogue, config, runtime, results = _setup(tmp_path); calls = []; service = _service(panel, config, calls)
    result = results[0]; cell = result.cell
    source = issue_combination_score_input(panel=panel, result=result, task=catalogue.tasks[cell.task_digest],
        scenario=catalogue.scenarios[cell.key], package=catalogue.packages[cell.runtime_arm.content_hash], authority=EXEC)
    for field, value in (("design_digest", "0" * 64), ("joint_mechanism_digest", "0" * 64), ("executed_program_sha256", "0" * 64), ("task_digest", "0" * 64)):
        forged = source.data(); forged["body"][field] = value
        with pytest.raises(ContractError, match="signature"):
            verify_combination_score_input(FrozenRecord.from_dict(forged), authority_keys={EXEC.authority_id: EXEC.key}, panel=panel, cell=cell)
    score = service.score_combination(panel=panel, cell=cell, score_input=source)
    forged_score = score.receipt.data(); forged_score["body"]["runtime_trace_digest"] = "0" * 64
    with pytest.raises(ContractError, match="signature"):
        verify_combination_adapted_receipt(replace(score, receipt=FrozenRecord.from_dict(forged_score)), authority_keys={SCORER.authority_id: SCORER.key},
            config=config, panel=panel, cell=cell, score_input=source, execution_authority_keys={EXEC.authority_id: EXEC.key})
    verifier = CombinationPanelVerifier()
    with pytest.raises(ContractError, match="coverage mismatch"):
        verifier.verify(panel, runtime[:-1])
    with pytest.raises(ContractError, match="coverage mismatch"):
        estimate_grouped_contrast(panel, runtime=runtime[:-1], scorer_receipts=(), verifier=verifier)
    failed = replace(results[0], runtime=replace(results[0].runtime, status="failed", output_digest=None, failure_reason="synthetic"))
    with pytest.raises(ContractError):
        derive_combination_score_input(panel=panel, result=failed, task=catalogue.tasks[cell.task_digest],
            scenario=catalogue.scenarios[cell.key], package=catalogue.packages[cell.runtime_arm.content_hash])
