"""Private evaluator entry point. Only this separate process opens label files."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .agent import Agent
from .ontology import ContractError, STATUSES, canonical, digest
from .store import Store


def private_labels(path: Path) -> tuple[dict[str, str], str]:
    path = path.resolve()
    # Private files must stay outside the exported public runner directory.
    public_root = Path(__file__).resolve().parents[1]
    if path.is_relative_to(public_root):
        raise ContractError("keep evaluator labels outside the agent workspace")
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or not value or any(
        not isinstance(key, str) or not isinstance(status, str) or status not in STATUSES
        for key, status in value.items()
    ):
        raise ContractError("labels must map task IDs to expected statuses")
    return value, hashlib.sha256(raw).hexdigest()


def evaluate(store: Store, trial_key: str, labels_path: Path) -> dict[str, Any]:
    """Deterministic local scoring: no provider is called anywhere in this path.

    Independence of the score is structural, not provider-based: the private evaluator
    runs as a separate process that alone opens the label file and only compares sealed
    run records against pre-committed labels. There is therefore no model scorer whose
    identity could collide with the executor. The receipt records the shared executor
    identity under ``provider`` (paired arms must match), and each run's full per-role
    ``providers`` mapping is committed through ``run_hashes``.
    """
    agent = Agent(store)
    store.verify_journal()
    trial = agent.trial(trial_key)
    labels, commitment = private_labels(labels_path)
    if commitment != trial["label_commitment"]:
        raise ContractError("private labels changed after trial lock")
    if set(labels) != {t["id"] for t in trial["tasks"]}:
        raise ContractError("labels must cover exactly the frozen paired task set")
    hashes: dict[str, str] = {}
    metrics: dict[str, dict[str, Any]] = {}
    providers = set()
    for arm in ("baseline", "candidate"):
        agent.version(trial[arm])
        metric = {"n": len(labels), "errors": 0, "protocol_violations": 0, "overreject": 0,
                  "calls": 0, "input_tokens": 0, "output_tokens": 0, "elapsed_s": 0.0}
        for task in trial["tasks"]:
            run_id = f"{trial_key}:{task['id']}:{arm}"
            run = store.get("run", run_id)
            store.verify_seal("run", run_id, run)
            if (run["phase"] != "evaluation" or run["version"] != trial[arm]
                    or run["task_hash"] != digest(task) or run["task"] != task
                    or run["state"] != "closed" or not run["usage"]["complete"]):
                raise ContractError("incomplete or mismatched paired run")
            providers.add(run["provider"])
            hashes[run_id] = digest(run)
            expected = labels[task["id"]]
            metric["errors"] += int(run["status"] != expected)
            metric["protocol_violations"] += int(bool(run["protocol_violations"]))
            metric["overreject"] += int(
                expected in {"proceed", "closed_negative"} and run["status"] in {"invalid", "withdrawn"})
            for key in ("calls", "input_tokens", "output_tokens", "elapsed_s"):
                metric[key] += run["usage"][key]
        metrics[arm] = metric
    if len(providers) != 1:
        raise ContractError("paired arms must use exactly the same backend and model settings")
    baseline, candidate = metrics["baseline"], metrics["candidate"]
    criteria = trial["criteria"]
    checks = {
        "fewer_errors": baseline["errors"] - candidate["errors"] >= criteria["min_error_reduction"],
        "no_more_protocol_violations": candidate["protocol_violations"] <= baseline["protocol_violations"],
        "no_more_overreject": candidate["overreject"] <= baseline["overreject"],
        "token_budget": (candidate["input_tokens"] + candidate["output_tokens"]
                         <= criteria["max_token_ratio"] * (baseline["input_tokens"] + baseline["output_tokens"])),
        "call_budget": candidate["calls"] <= criteria["max_call_ratio"] * baseline["calls"],
    }
    receipt = {"trial": trial_key, "trial_hash": digest(trial), "run_hashes": hashes,
               "metrics": metrics, "checks": checks, "eligible": all(checks.values()),
               "evaluator": trial["evaluator"], "provider": next(iter(providers)),
               "evidence_level": "engineering_fixture" if next(iter(providers)).startswith("fixture:") else "pilot",
               "scientific_effectiveness_proven": False}
    # No per-task labels or correctness signals return to the agent/reflection path.
    with store.transaction():
        store.put("evaluation", trial_key, receipt)
        store.event("trial_evaluated", {"trial": trial_key, "receipt_hash": digest(receipt),
                                      "eligible": receipt["eligible"]})
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--commit", action="store_true", help="return only a pre-run label commitment")
    parser.add_argument("--db")
    parser.add_argument("--trial")
    args = parser.parse_args()
    try:
        if args.commit:
            _, commitment = private_labels(args.labels)
            print(canonical({"label_commitment": commitment}))
        else:
            if not args.db or not args.trial:
                raise ContractError("--db and --trial required")
            store = Store(args.db)
            try:
                print(canonical(evaluate(store, args.trial, args.labels)))
            finally:
                store.close()
    except (ContractError, OSError, ValueError) as exc:
        parser.exit(2, f"Evaluation rejected: {exc}\n")


if __name__ == "__main__":
    main()
