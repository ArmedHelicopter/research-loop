"""Paired bootstrap on task-level 0/1 scores. One generation per task per arm."""

from __future__ import annotations

import random
from typing import Any


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def paired_diff_ci(
    arm_a: list[int],
    arm_b: list[int],
    *,
    n_boot: int = 5000,
    seed: int = 0,
    alpha: float = 0.05,
) -> dict[str, float]:
    if len(arm_a) != len(arm_b) or not arm_a:
        raise ValueError("arms must be non-empty and aligned by task")
    diffs = [b - a for a, b in zip(arm_a, arm_b)]
    point = _mean(diffs)
    rng = random.Random(seed)
    n = len(diffs)
    boots = []
    for _ in range(n_boot):
        sample = [diffs[rng.randrange(n)] for _ in range(n)]
        boots.append(_mean(sample))
    boots.sort()
    lo_i = int(alpha / 2 * n_boot)
    hi_i = int((1 - alpha / 2) * n_boot) - 1
    return {
        "n": float(n),
        "point": point,
        "ci95_lo": boots[lo_i],
        "ci95_hi": boots[hi_i],
        "includes_0": boots[lo_i] <= 0.0 <= boots[hi_i],
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_arm: dict[str, list[dict[str, Any]]] = {"A": [], "B": []}
    for row in rows:
        by_arm[row["arm"]].append(row)
    ids = sorted({r["id"] for r in rows})
    a = {r["id"]: r for r in by_arm["A"]}
    b = {r["id"]: r for r in by_arm["B"]}
    missing = [i for i in ids if i not in a or i not in b]
    if missing:
        raise ValueError(f"unpaired tasks: {missing}")
    viol_a = [int(a[i]["protocol_violation"]) for i in ids]
    viol_b = [int(b[i]["protocol_violation"]) for i in ids]
    disc_a = [int(a[i]["discrimination_correct"]) for i in ids]
    disc_b = [int(b[i]["discrimination_correct"]) for i in ids]
    viol = paired_diff_ci(viol_a, viol_b)
    disc = paired_diff_ci(disc_a, disc_b)
    return {
        "n_tasks": len(ids),
        "violation_rate_A": _mean(viol_a),
        "violation_rate_B": _mean(viol_b),
        "violation_B_minus_A": viol,
        "discrimination_A": _mean(disc_a),
        "discrimination_B": _mean(disc_b),
        "discrimination_B_minus_A": disc,
    }
