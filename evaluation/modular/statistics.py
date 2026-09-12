"""Paired, source-cluster contrasts; descriptive estimates do not promote a package."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from statistics import mean
from typing import Any

from research_loop.modular.contracts import ContractError, FrozenRecord


def estimate_contrast(rows: list[dict[str, Any]], coefficients: dict[str, float], *,
                      seed: int = 0, resamples: int = 2000, alpha: float = 0.05,
                      min_groups: int = 2) -> FrozenRecord:
    """Compute each paired contrast, average within source, bootstrap sources.

    Each row identifies benchmark/group/task/replicate/arm/score. All arms must be
    present exactly once per task replicate. A source with many queries is one
    independent resampling unit, and only one benchmark may enter each estimate.
    """
    if (not rows or not coefficients or type(seed) is not int or type(resamples) is not int
            or resamples < 100 or type(min_groups) is not int or min_groups < 2
            or type(alpha) not in (int, float) or not math.isfinite(alpha) or not 0 < alpha < 1):
        raise ContractError("invalid contrast or sampling configuration")
    if any(type(c) not in (int, float) or not math.isfinite(c) for c in coefficients.values()):
        raise ContractError("contrast coefficients must be finite numbers")
    if not math.isclose(sum(coefficients.values()), 0.0, abs_tol=1e-12):
        raise ContractError("difference contrast coefficients must sum to zero")
    if all(c == 0 for c in coefficients.values()):
        raise ContractError("zero contrast is uninformative")
    pairs: dict[tuple, dict[str, float]] = defaultdict(dict)
    benchmarks = set()
    required = {"benchmark", "group_id", "task_id", "replicate", "arm", "score"}
    for row in rows:
        if not isinstance(row, dict) or set(row) != required:
            raise ContractError("unexpected or missing score row fields")
        if any(not isinstance(row[k], str) or not row[k] for k in required - {"score"}):
            raise ContractError("score identity fields must be nonempty strings")
        score = row["score"]
        if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ContractError("score must be a finite normalized number")
        if row["arm"] not in coefficients:
            raise ContractError("unregistered arm in contrast")
        benchmarks.add(row["benchmark"])
        key = (row["group_id"], row["task_id"], row["replicate"])
        if row["arm"] in pairs[key]:
            raise ContractError("duplicate task/replicate/arm score")
        pairs[key][row["arm"]] = float(score)
    if len(benchmarks) != 1:
        raise ContractError("incompatible benchmarks cannot be pooled")
    grouped: dict[str, list[float]] = defaultdict(list)
    for key, scores in pairs.items():
        if set(scores) != set(coefficients):
            raise ContractError("incomplete paired arms; missing results cannot be dropped")
        grouped[key[0]].append(sum(coefficients[arm] * scores[arm] for arm in coefficients))
    cluster_values = [mean(grouped[group]) for group in sorted(grouped)]
    effect = mean(cluster_values)
    result = {"schema": "source-cluster-contrast-v1", "benchmark": next(iter(benchmarks)),
              "coefficients": coefficients, "source_groups": len(grouped), "paired_units": len(pairs),
              "effect": effect, "interval": None, "alpha": alpha, "seed": seed,
              "resamples": resamples, "status": "insufficient_independent_groups",
              "promotes": False}
    if len(cluster_values) >= min_groups:
        rng = random.Random(seed)
        samples = sorted(mean(rng.choices(cluster_values, k=len(cluster_values))) for _ in range(resamples))
        lo = max(0, math.floor(alpha / 2 * resamples))
        hi = min(resamples - 1, math.ceil((1 - alpha / 2) * resamples) - 1)
        result.update(interval=[samples[lo], samples[hi]], status="descriptive_estimate")
    return FrozenRecord.from_dict(result)
