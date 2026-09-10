"""隔离评价进程：标签不进入公开模型运行器。"""
import argparse
import hashlib
import itertools
import json
from collections import Counter
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def score(tasks, labels, rows, reviews):
    task_map = {t["id"]: t for t in tasks}
    if len(tasks) != 32 or len(task_map) != 32 or set(labels) != set(task_map):
        raise ValueError("fixed 32-item task/label identity mismatch")
    families = Counter(t["family"] for t in tasks)
    if len(families) != 8 or set(families.values()) != {4}:
        raise ValueError("fixed eight-family design mismatch")
    for family in families:
        if Counter(labels[t["id"]]["status"] for t in tasks if t["family"] == family) != Counter(
            ["proceed", "closed_negative", "inconclusive", "withdrawn"]):
            raise ValueError("family status balance mismatch")
    by_key = {(r["task_id"], r["arm"]): r for r in rows}
    if len(by_key) != len(rows):
        raise ValueError("duplicate task-arm output")
    details, metrics = [], {}
    for arm in ("A", "B"):
        counts = Counter()
        for task in tasks:
            key = (task["id"], arm)
            result = by_key.get(key, {})
            value = result.get("final", {}).get("decision")
            expected = labels[task["id"]]["status"]
            status = value.get("status") if value else None
            refs = value.get("evidence_ids", []) if value else []
            valid_refs = bool(refs) and set(refs) <= {e["id"] for e in task["evidence"]}
            required_refs = set(labels[task["id"]]["critical_evidence_ids"]) <= set(refs)
            exact = status == expected
            # Reviews are frozen independent arithmetic annotations, never model audit flags.
            review = reviews.get(task["id"] + ":" + arm, {})
            reason_ok = review.get("reason_consistent") is True
            usable = exact and valid_refs and required_refs and reason_ok
            counts["exact_status"] += exact
            counts["correct_usable"] += usable
            counts["false_release"] += status == "proceed" and expected != "proceed"
            counts["overreject"] += expected in {"proceed", "closed_negative", "inconclusive"} and status in {
                "invalid", "withdrawn", None}
            counts[expected + "_usable"] += usable
            details.append({"task_id": task["id"], "family": task["family"], "arm": arm,
                            "expected": expected, "status": status, "exact": exact,
                            "valid_refs": valid_refs, "required_refs": required_refs,
                            "reason_consistent": reason_ok, "usable": usable,
                            "before_status": result.get("before", {}).get("status")})
        metrics[arm] = dict(counts)
    family_diffs = {f: sum((1 if d["arm"] == "B" else -1) * d["usable"]
                           for d in details if d["family"] == f) for f in families}
    observed = sum(family_diffs.values())
    p = sum(sum(s * d for s, d in zip(signs, family_diffs.values())) >= observed
            for signs in itertools.product((-1, 1), repeat=8)) / 256
    gates = {"B_min_usable": metrics["B"]["correct_usable"] >= 28,
             "B_zero_false_release": metrics["B"]["false_release"] == 0,
             "B_negative_retained": metrics["B"].get("closed_negative_usable", 0) >= 7,
             "B_inconclusive_retained": metrics["B"].get("inconclusive_usable", 0) >= 7,
             "no_more_overreject": metrics["B"]["overreject"] <= metrics["A"]["overreject"],
             "increment_at_least_four": observed >= 4, "conditional_sign_flip_p": p <= .05}
    return {"metrics": metrics, "family_diffs": family_diffs, "conditional_sign_flip_p": p,
            "gates": gates, "quality_pass": all(gates.values()), "details": details,
            "review_count": len(reviews), "expected_review_count": 64}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("tasks", "labels", "results", "reviews", "output", "label_commitment"):
        p.add_argument("--" + key.replace("_", "-"), required=True)
    a = p.parse_args()
    if hashlib.sha256(Path(a.labels).read_bytes()).hexdigest() != a.label_commitment:
        raise ValueError("sealed labels changed")
    rows = [json.loads(line) for line in Path(a.results).read_text(encoding="utf-8").splitlines()]
    result = score(load(a.tasks), load(a.labels), rows, load(a.reviews))
    Path(a.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
