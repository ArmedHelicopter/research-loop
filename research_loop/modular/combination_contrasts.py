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
                              scorer_receipts: Iterable[ScientificScorerReceipt], verifier: CombinationPanelVerifier,
                              direction: str, value_range: tuple[float, float], scale: str) -> FrozenRecord:
    """Estimate preregistered contrasts after actual journal/scorer verification.

    ``verifier`` is an object dependency, never a caller-supplied ``verified``
    boolean. Missing, failed, duplicate, foreign or drifted metrics reject the
    whole estimate under the frozen incomplete policy.
    """
    if not isinstance(panel, CombinationPanel) or not isinstance(verifier, CombinationPanelVerifier):
        raise ContractError("typed panel and combination verifier required")
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
    if panel.interaction_status == "not_identifiable":
        return FrozenRecord.from_dict({"schema": "frozen-grouped-combination-estimate-v1", "panel_digest": panel.digest,
            "estimand": panel.estimand, "status": "not_identifiable", "missing_policy": "incomplete_reject",
            "direction": direction, "value_range": list(value_range), "scale": scale,
            "scientific_status": "estimation_only_not_acceptance", "benchmark_estimates": {}})
    arm_values: dict[tuple[str, str, str, str], dict[str, float]] = defaultdict(dict)
    for cell in panel.cells:
        arm_values[(cell.identity.benchmark, cell.identity.group_id, cell.identity.task_id, cell.replicate)][cell.arm_id] = float(by_key[cell.key]["value"])
    contrast_by_group: dict[tuple[str, str], list[float]] = defaultdict(list)
    coefficients = panel.design.data().get("contrast")
    for (benchmark, group, _task, _replicate), values in arm_values.items():
        if panel.estimand == "interaction_on_scale":
            if not isinstance(coefficients, dict) or set(coefficients) != set(values): raise ContractError("frozen factorial contrast is incomplete")
            contrast = sum(float(coefficients[arm]) * values[arm] for arm in values)
        else:
            if "full" not in values: raise ContractError("LOO panel lacks full arm")
            contrast = _mean([values["full"] - value for arm, value in values.items() if arm != "full"])
        contrast_by_group[(benchmark, group)].append(contrast)
    benchmark_groups: dict[str, list[float]] = defaultdict(list)
    group_detail = {}
    for (benchmark, group), values in sorted(contrast_by_group.items()):
        group_detail[f"{benchmark}:{group}"] = {"task_replicate_contrasts": len(values), "mean": _mean(values)}
        benchmark_groups[benchmark].append(_mean(values))
    estimates = {benchmark: {"independent_groups": len(values), "mean": _mean(values)}
                 for benchmark, values in sorted(benchmark_groups.items())}
    return FrozenRecord.from_dict({"schema": "frozen-grouped-combination-estimate-v1", "panel_digest": panel.digest,
        "estimand": panel.estimand, "status": "estimated", "missing_policy": "incomplete_reject",
        "direction": direction, "value_range": list(value_range), "scale": scale,
        "group_detail": group_detail, "benchmark_estimates": estimates,
        "significance": "not_computed_no_frozen_alpha_or_minimum_groups",
        "scientific_status": "estimation_only_not_acceptance"})
