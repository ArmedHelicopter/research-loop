"""Frozen grouped estimators for already-verified combination journals.

The results are descriptive estimation records only.  They are never signed
scientific claims, acceptance decisions, confidence intervals, or tests.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable

from research_loop.modular.combination_panels import CombinationPanel, CombinationPanelVerifier
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.panel_receipts import RuntimeReceipt, ScientificScorerReceipt
from research_loop.ontology import ContractError


def _mean(values: list[float]) -> float:
    if not values: raise ContractError("missing metric values")
    return sum(values) / len(values)


def estimate_grouped_contrast(panel: CombinationPanel, *, runtime: Iterable[RuntimeReceipt],
                              scorer_receipts: Iterable[ScientificScorerReceipt], verifier: CombinationPanelVerifier) -> FrozenRecord:
    """Estimate preregistered contrasts after actual journal/scorer verification.

    ``verifier`` is an object dependency, never a caller-supplied ``verified``
    boolean. Missing, failed, duplicate, foreign or drifted metrics reject the
    whole estimate under the frozen incomplete policy.
    """
    if not isinstance(panel, CombinationPanel) or not isinstance(verifier, CombinationPanelVerifier):
        raise ContractError("typed panel and combination verifier required")
    analysis = panel.acceptance_criteria.data().get("contrast_analysis")
    if (not isinstance(analysis, dict) or set(analysis) != {"schema", "direction", "value_range", "scale", "missing_policy", "group_weighting"}
            or analysis["schema"] != "frozen-combination-contrast-analysis-v1"
            or analysis["missing_policy"] != "incomplete_reject"
            or analysis["group_weighting"] != "task_replicate_mean_then_equal_group_mean"):
        raise ContractError("panel lacks frozen grouped contrast analysis policy")
    if not isinstance(analysis["value_range"], list):
        raise ContractError("frozen metric range must be a two-value list")
    direction, value_range, scale = analysis["direction"], tuple(analysis["value_range"]), analysis["scale"]
    if (not isinstance(direction, str) or direction not in {"higher_better", "lower_better"}
            or not isinstance(scale, str) or not scale or len(value_range) != 2
            or any(type(x) not in {int, float} or not math.isfinite(x) for x in value_range)
            or value_range[0] >= value_range[1]):
        raise ContractError("metric direction, finite range and analysis scale are frozen requirements")
    rows, scored = tuple(runtime), tuple(scorer_receipts)
    verdict = verifier.verify(panel, rows, scorer_receipts=scored)
    if not verdict.engineering_verified:
        raise ContractError("combination journals were not verified")
    expected = {cell.key: cell for cell in panel.cells}
    if any(row.status != "succeeded" for row in rows):
        raise ContractError("incomplete policy rejects failed or blocked combination cells")
    scored_by_key = {row.cell_key: row for row in scored}
    if set(scored_by_key) != set(expected):
        raise ContractError("metrics require one independently verified scorer receipt per cell")
    runtime_by_key = {row.cell_key: row for row in rows}
    evidence = FrozenRecord.from_dict({"panel_digest": panel.digest,
        "runtime": [{"cell_key": list(row.cell_key), "trace_digest": row.trace_digest}
                    for row in sorted(rows, key=lambda value: value.cell_key)],
        "scorer": [{"cell_key": list(row.cell_key), "receipt_digest": row.receipt.content_hash}
                   for row in sorted(scored, key=lambda value: value.cell_key)]})
    by_key = {}
    for key, receipt in scored_by_key.items():
        body = receipt.receipt.data()
        metric = body.get("metric")
        if (not isinstance(metric, dict) or set(metric) != {"value", "direction", "value_range", "scale"}
                or metric["direction"] != direction or metric["value_range"] != list(value_range) or metric["scale"] != scale):
            raise ContractError("authenticated scorer receipt lacks this frozen numeric metric")
        if type(metric["value"]) not in {int, float} or not math.isfinite(metric["value"]) or not value_range[0] <= metric["value"] <= value_range[1]:
            raise ContractError("authenticated scorer metric is outside the frozen finite range")
        if body.get("runtime_trace_digest") != runtime_by_key[key].trace_digest:
            raise ContractError("scorer metric does not bind verified runtime")
        by_key[key] = metric
    if panel.estimand == "interaction_on_scale" and panel.interaction_status == "not_identifiable":
        return FrozenRecord.from_dict({"schema": "frozen-grouped-combination-estimate-v1", "panel_digest": panel.digest,
            "input_evidence": evidence.data(), "input_evidence_digest": evidence.content_hash,
            "estimand": panel.estimand, "status": "not_identifiable", "missing_policy": "incomplete_reject",
            "direction": direction, "value_range": list(value_range), "scale": scale,
            "scientific_status": "estimation_only_not_acceptance", "benchmark_estimates": {}})
    arm_values: dict[tuple[str, str, str, str], dict[str, float]] = defaultdict(dict)
    for cell in panel.cells:
        arm_values[(cell.identity.benchmark, cell.identity.group_id, cell.identity.task_id, cell.replicate)][cell.arm_id] = float(by_key[cell.key]["value"])
    contrast_by_group: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    coefficients = panel.design.data().get("contrast")
    for (benchmark, group, _task, _replicate), values in arm_values.items():
        if panel.estimand == "interaction_on_scale":
            if not isinstance(coefficients, dict) or set(coefficients) != set(values): raise ContractError("frozen factorial contrast is incomplete")
            contrast_by_group[(benchmark, group, "interaction")].append(sum(float(coefficients[arm]) * values[arm] for arm in values))
        else:
            if "full" not in values: raise ContractError("LOO panel lacks full arm")
            for arm, value in values.items():
                if arm != "full": contrast_by_group[(benchmark, group, arm)].append(values["full"] - value)
    benchmark_groups: dict[tuple[str, str], list[float]] = defaultdict(list)
    group_detail = {}
    for (benchmark, group, component), values in sorted(contrast_by_group.items()):
        group_detail[f"{component}:{benchmark}:{group}"] = {"task_replicate_contrasts": len(values), "mean": _mean(values)}
        benchmark_groups[(component, benchmark)].append(_mean(values))
    estimates_by_component = {component: {benchmark: {"independent_groups": len(values), "mean": _mean(values)}
        for (name, benchmark), values in sorted(benchmark_groups.items()) if name == component}
        for component in sorted({name for name, _benchmark in benchmark_groups})}
    if panel.estimand == "leave_one_out_at_full":
        unavailable = {item["id"] for item in panel.structurally_unavailable}
        all_components = [row["id"] for row in panel.design.data()["cells"] if row["id"] != "full"]
        estimates = {component: ({"status": "not_identifiable", "benchmark_estimates": {}} if component in unavailable
            else {"status": "estimated", "benchmark_estimates": estimates_by_component.get(component, {})}) for component in all_components}
    else:
        estimates = estimates_by_component["interaction"]
    return FrozenRecord.from_dict({"schema": "frozen-grouped-combination-estimate-v1", "panel_digest": panel.digest,
        "input_evidence": evidence.data(), "input_evidence_digest": evidence.content_hash,
        "estimand": panel.estimand, "status": "estimated", "missing_policy": "incomplete_reject",
        "direction": direction, "value_range": list(value_range), "scale": scale,
        "group_detail": group_detail, "benchmark_estimates": estimates,
        "significance": "not_computed_no_frozen_alpha_or_minimum_groups",
        "scientific_status": "estimation_only_not_acceptance"})
