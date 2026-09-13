"""Train-only adapted measurements and deterministic, non-promoting selection.

Every score is authenticated against both actual journals. Selection is a
development decision; it cannot grant scientific validity, deploy a package,
lease validation data, or remove safe candidates from combination experiments.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
from typing import Iterable, Mapping

from evaluation.modular.linked_scoring import derive_linked_score_input, verify_linked_adapted_receipt
from evaluation.modular.scoring_service import ScorerConfig
from research_loop.modular.benchmark_cell import LinkedBenchmarkCellResult, verify_linked_benchmark_cell
from research_loop.modular.contracts import FrozenRecord, PublicTask
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.panel_receipts import FrozenPanel, ScientificScorerReceipt
from research_loop.ontology import ContractError


@dataclass(frozen=True)
class FrozenTrainSelectionRule:
    record: FrozenRecord

    def __post_init__(self) -> None:
        body = self.record.data()
        fields = {"schema", "coverage_id", "baseline_arm", "tie_break_order", "minimum_mean_improvement",
                  "maximum_benchmark_regression", "aggregation", "missing_policy"}
        if set(body) != fields or body["schema"] != "train-adapted-selection-rule-v1":
            raise ContractError("invalid frozen training selection rule")
        arms = body["tie_break_order"]
        if (not isinstance(arms, list) or not arms or any(not isinstance(arm, str) or not arm for arm in arms)
                or len(set(arms)) != len(arms) or body["baseline_arm"] not in arms
                or not isinstance(body["coverage_id"], str)):
            raise ContractError("training selection needs unique complete arm tie order and baseline")
        for name in ("minimum_mean_improvement", "maximum_benchmark_regression"):
            value = body[name]
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ContractError("training selection thresholds must be finite unit values")
        if (body["aggregation"] != "paired_cell_mean_then_equal_group_then_equal_benchmark"
                or body["missing_policy"] != "inconclusive_without_imputation"):
            raise ContractError("training selection requires the fixed grouped and missing-data policies")

    @classmethod
    def create(cls, *, coverage_id: str, baseline_arm: str, tie_break_order: Iterable[str],
               minimum_mean_improvement: float = 0, maximum_benchmark_regression: float = 0) -> "FrozenTrainSelectionRule":
        return cls(FrozenRecord.from_dict({"schema": "train-adapted-selection-rule-v1", "coverage_id": coverage_id,
            "baseline_arm": baseline_arm, "tie_break_order": list(tie_break_order),
            "minimum_mean_improvement": minimum_mean_improvement, "maximum_benchmark_regression": maximum_benchmark_regression,
            "aggregation": "paired_cell_mean_then_equal_group_then_equal_benchmark",
            "missing_policy": "inconclusive_without_imputation"}))


def measure_and_select_train(*, panel: FrozenPanel, rule: FrozenTrainSelectionRule,
                             results: Iterable[LinkedBenchmarkCellResult],
                             tasks: Mapping[str, PublicTask], scenarios: Mapping[tuple, FrozenRecord],
                             packages: Mapping[str, CandidatePackage],
                             linked_inputs: Mapping[tuple, FrozenRecord],
                             scores: Iterable[ScientificScorerReceipt], config: ScorerConfig,
                             execution_authority_keys: Mapping[str, bytes],
                             scoring_authority_keys: Mapping[str, bytes]) -> FrozenRecord:
    """Authenticate the complete panel, then select only within its train scope.

    Failure rows are measured as failures, never zero-valued semantic scores.
    Any failed row makes selection inconclusive under this frozen policy.
    Multiple Q panels must be processed separately to retain per-Q obligations.
    """
    if not isinstance(panel, FrozenPanel) or panel.domain != "train":
        raise ContractError("adapted training selection cannot access validation panels")
    if not isinstance(rule, FrozenTrainSelectionRule) or panel.scope_ids != (rule.record.data()["coverage_id"],):
        raise ContractError("training measurement must bind exactly one registered Q")
    policy = rule.record.data()
    if panel.acceptance_criteria.data().get("train_adapted_selection") != policy:
        raise ContractError("selection rule was not frozen in the executed panel")
    if not isinstance(config, ScorerConfig) or any(cell.scorer_digest != config.digest for cell in panel.cells):
        raise ContractError("training selection scorer configuration drift")
    arms = set(cell.arm_id for cell in panel.cells)
    if arms != set(policy["tie_break_order"]):
        raise ContractError("selection tie order must cover every frozen executable arm")
    package_by_arm = {}
    for arm in arms:
        arm_packages = {cell.package_digest for cell in panel.cells if cell.arm_id == arm}
        if len(arm_packages) != 1:
            raise ContractError("one selected arm must identify one frozen package across tasks")
        package_by_arm[arm] = next(iter(arm_packages))
    rows = tuple(results)
    expected = {cell.key: cell for cell in panel.cells}
    actual = {row.cell.key: row for row in rows}
    if len(actual) != len(rows) or set(actual) != set(expected):
        raise ContractError("training selection requires every frozen cell exactly once")
    trace_paths, trace_digests, observations = set(), set(), []
    successful = set()
    for key in sorted(expected):
        cell, result = expected[key], actual[key]
        if result.cell != cell:
            raise ContractError("training result is not the exact frozen cell")
        try:
            task, scenario, package = tasks[cell.task_digest], scenarios[key], packages[cell.package_digest]
        except KeyError as exc:
            raise ContractError("training measurement lacks original task, scenario or package") from exc
        verify_linked_benchmark_cell(result, task=task, scenario=scenario, package=package)
        paths = [result.mechanism.runtime.trace_path]
        digests = [result.mechanism.runtime.trace_digest]
        if result.solver is not None:
            paths.append(result.solver.session.sidecar / "trace.jsonl")
            digests.append(result.receipt.data()["solver_trace_digest"])
        if any(path.resolve() in trace_paths for path in paths) or any(value in trace_digests for value in digests):
            raise ContractError("one journal cannot be reused as multiple training cells")
        trace_paths.update(path.resolve() for path in paths)
        trace_digests.update(digests)
        if result.status == "linked_succeeded":
            successful.add(key)
        observations.append({"cell_key": list(key), "status": result.status,
                             "linked_receipt_digest": result.receipt.content_hash})
    scored = tuple(scores)
    by_score = {row.cell_key: row for row in scored}
    if len(by_score) != len(scored) or set(by_score) != successful or set(linked_inputs) != successful:
        raise ContractError("signed inputs and scores must exactly cover successful linked cells")
    metrics, score_digests = {}, {}
    for key in sorted(successful):
        body = verify_linked_adapted_receipt(by_score[key], authority_keys=scoring_authority_keys,
            config=config, panel=panel, cell=expected[key], linked_input=linked_inputs[key],
            execution_authority_keys=execution_authority_keys).data()
        if body["linked_receipt_digest"] != actual[key].receipt.content_hash:
            raise ContractError("authenticated score does not bind the current verified journals")
        # An authenticated but internally inconsistent issuer must not swap the
        # scored candidate while retaining real journal digests in its envelope.
        source_body = linked_inputs[key].data()["body"]
        source_body.pop("authority")
        cell = expected[key]
        current = derive_linked_score_input(panel=panel, result=actual[key], task=tasks[cell.task_digest],
            scenario=scenarios[key], package=packages[cell.package_digest])
        if FrozenRecord.from_dict(source_body).content_hash != current.content_hash:
            raise ContractError("authenticated evaluator input differs from the current executed material")
        metric = body["metric"]
        if (metric["direction"] != "higher_better" or metric["value_range"] != [0.0, 1.0]
                or metric["scale"] != "unit" or type(metric["value"]) not in (int, float)
                or not math.isfinite(metric["value"]) or not 0 <= metric["value"] <= 1):
            raise ContractError("authenticated metric does not match the frozen training scale")
        metrics[key] = float(metric["value"])
        score_digests[key] = by_score[key].receipt.content_hash
    measurement = {"schema": "train-adapted-measurement-v1", "panel_digest": panel.digest,
        "scope_id": policy["coverage_id"], "split_digest": panel.split_digest,
        "candidate_catalogue_digest": panel.candidate_digest, "scorer_digest": config.digest,
        "selection_rule_digest": rule.record.content_hash, "acceptance_criteria_digest": panel.acceptance_criteria.content_hash,
        "required_benchmarks": list(panel.required_benchmarks), "observations": observations,
        "score_receipts": [{"cell_key": list(key), "receipt_digest": score_digests[key], "value": metrics[key]}
                           for key in sorted(metrics)],
        "expected_cells": len(expected), "successful_cells": len(successful), "failed_cells": len(expected) - len(successful),
        "scientific_validity": "not_measured", "calibration": "not_measured", "acceptance_verified": False,
        "selection_scope": "train_only", "mechanism_effect": "not_measured"}
    measurement_record = FrozenRecord.from_dict(measurement)
    selection = _selection(panel, policy, metrics, package_by_arm) if successful == set(expected) else {
        "status": "inconclusive", "reason": "incomplete successful paired outcomes", "selected_arm": None,
        "selected_package_digest": None, "grouped_differences": []}
    return FrozenRecord.from_dict({"schema": "train-adapted-selection-v1", "measurement": measurement,
        "measurement_digest": measurement_record.content_hash, "selection_rule": policy, **selection,
        "combination_candidates_retained": list(policy["tie_break_order"]), "combination_pruning_authorized": False,
        "scientific_validity": "not_measured", "acceptance_verified": False, "deployment_authorized": False})


def _selection(panel: FrozenPanel, policy: dict, metrics: Mapping[tuple, float], packages: dict) -> dict:
    # Difference pairs have identical Q/benchmark/task/group/replicate/variant.
    baseline = {key[:-1]: value for key, value in metrics.items() if key[-1] == policy["baseline_arm"]}
    effects = []
    for arm in policy["tie_break_order"]:
        grouped = defaultdict(list)
        for cell in panel.cells:
            if cell.arm_id == arm:
                grouped[(cell.identity.benchmark, cell.identity.group_id)].append(metrics[cell.key] - baseline[cell.key[:-1]])
        group_rows = [{"benchmark": key[0], "group_id": key[1], "paired_cells": len(values),
                       "mean_difference": math.fsum(values) / len(values)} for key, values in sorted(grouped.items())]
        benchmark_rows = [{"benchmark": benchmark, "groups": sum(row["benchmark"] == benchmark for row in group_rows),
                           "mean_difference": _mean(row["mean_difference"] for row in group_rows if row["benchmark"] == benchmark)}
                          for benchmark in panel.required_benchmarks]
        difference = _mean(row["mean_difference"] for row in benchmark_rows)
        eligible = (arm == policy["baseline_arm"] or (difference >= policy["minimum_mean_improvement"]
                    and all(row["mean_difference"] >= -policy["maximum_benchmark_regression"] for row in benchmark_rows)))
        effects.append({"arm_id": arm, "package_digest": packages[arm], "groups": group_rows,
                        "benchmarks": benchmark_rows, "mean_difference": difference, "eligible_for_train_selection": eligible})
    eligible = [row for row in effects if row["eligible_for_train_selection"]]
    # max returns the first equal value; input order was frozen before execution.
    chosen = max(eligible, key=lambda row: row["mean_difference"])
    return {"status": "selected_for_validation", "reason": "frozen training criterion; no validation observed",
            "selected_arm": chosen["arm_id"], "selected_package_digest": chosen["package_digest"],
            "grouped_differences": effects, "uncertainty": "not_estimated; training selection is not significance evidence"}


def _mean(values: Iterable[float]) -> float:
    values = tuple(values)
    if not values:
        raise ContractError("missing paired source group or benchmark")
    return math.fsum(values) / len(values)
