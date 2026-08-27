"""Run frozen n=16 true-lock A/B contrast."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from experiments.sep_of_powers.aggregate import _mean, paired_diff_ci
from experiments.sep_of_powers.run_contrast import LLMUnavailable, chat_complete, discover_llm
from experiments.true_lock.render import load_task, render_arm_a, render_lock_prompt, render_observe_prompt
from experiments.true_lock.score import hash_rule, load_label, parse_output, score_output

ROOT = Path(__file__).resolve().parents[2]
TASK_DIR = ROOT / "data" / "tasks" / "true_lock"
LABEL_DIR = ROOT / "data" / "labels" / "true_lock"
OUT_DIR = ROOT / "results" / "true_lock"
MAX_TOKENS = 800
TEMPERATURE = 0.0
N_REQUIRED = 16


def list_task_ids() -> list[str]:
    return sorted(p.stem for p in TASK_DIR.glob("LCK*.json"))


def run_arm_a(cfg: dict[str, str], task: dict[str, Any]) -> dict[str, Any]:
    prompt = render_arm_a(task)
    call = chat_complete(cfg, prompt, max_tokens=MAX_TOKENS, temperature=TEMPERATURE)
    return {
        "arm": "A",
        "task_id": task["id"],
        "raw_output": call["text"],
        "lock_hash": None,
        "prompt_tokens": call["prompt_tokens"],
        "completion_tokens": call["completion_tokens"],
        "elapsed_s": call["elapsed_s"],
    }


def run_arm_b(cfg: dict[str, str], task: dict[str, Any]) -> dict[str, Any]:
    lock_prompt = render_lock_prompt(task)
    lock_call = chat_complete(cfg, lock_prompt, max_tokens=MAX_TOKENS, temperature=TEMPERATURE)
    try:
        committed = str(parse_output(lock_call["text"]).get("decision_rule") or "").strip()
    except (json.JSONDecodeError, ValueError, TypeError):
        committed = ""
    digest = hash_rule(committed) if committed else None
    observe_prompt = render_observe_prompt(task, committed_rule=committed or "(empty)")
    obs_call = chat_complete(cfg, observe_prompt, max_tokens=MAX_TOKENS, temperature=TEMPERATURE)
    return {
        "arm": "B",
        "task_id": task["id"],
        "raw_output": obs_call["text"],
        "lock_hash": digest,
        "committed_rule": committed,
        "prompt_tokens": lock_call["prompt_tokens"] + obs_call["prompt_tokens"],
        "completion_tokens": lock_call["completion_tokens"] + obs_call["completion_tokens"],
        "elapsed_s": lock_call["elapsed_s"] + obs_call["elapsed_s"],
    }


def score_run(run: dict[str, Any]) -> dict[str, Any]:
    task = load_task(TASK_DIR / f"{run['task_id']}.json")
    label = load_label(LABEL_DIR / f"{run['task_id']}.json")
    scored = score_output(task, label, run["raw_output"], lock_hash=run.get("lock_hash"))
    scored.update(
        {
            "arm": run["arm"],
            "prompt_tokens": run["prompt_tokens"],
            "completion_tokens": run["completion_tokens"],
            "elapsed_s": run["elapsed_s"],
        }
    )
    return scored


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_arm: dict[str, dict[str, dict[str, Any]]] = {"A": {}, "B": {}}
    for row in rows:
        by_arm[row["arm"]][row["id"]] = row
    ids = sorted(by_arm["A"])
    if set(ids) != set(by_arm["B"]):
        raise ValueError("unpaired tasks")
    viol_a = [int(by_arm["A"][i]["protocol_violation"]) for i in ids]
    viol_b = [int(by_arm["B"][i]["protocol_violation"]) for i in ids]
    disc_a = [int(by_arm["A"][i]["discrimination_correct"]) for i in ids]
    disc_b = [int(by_arm["B"][i]["discrimination_correct"]) for i in ids]
    keep_ids = [i for i in ids if not by_arm["A"][i]["hold_out_item"]]
    over_a = [int(by_arm["A"][i]["over_reject"]) for i in keep_ids]
    over_b = [int(by_arm["B"][i]["over_reject"]) for i in keep_ids]
    viol = paired_diff_ci(viol_a, viol_b)
    disc = paired_diff_ci(disc_a, disc_b)

    def rate(key: str, arm: str) -> float:
        return _mean([int(by_arm[arm][i][key]) for i in ids])

    return {
        "n_tasks": len(ids),
        "violation_rate_A": _mean(viol_a),
        "violation_rate_B": _mean(viol_b),
        "violation_B_minus_A": viol,
        "discrimination_A": _mean(disc_a),
        "discrimination_B": _mean(disc_b),
        "discrimination_B_minus_A": disc,
        "goal_complete_A": rate("goal_complete", "A"),
        "goal_complete_B": rate("goal_complete", "B"),
        "invalid_as_positive_A": rate("invalid_as_positive", "A"),
        "invalid_as_positive_B": rate("invalid_as_positive", "B"),
        "threshold_change_A": rate("threshold_change", "A"),
        "threshold_change_B": rate("threshold_change", "B"),
        "over_reject_A": _mean(over_a),
        "over_reject_B": _mean(over_b),
        "h_lock_supported": (not viol["includes_0"]) and viol["point"] < 0 and disc["ci95_lo"] >= -0.10,
        "h_ceremony": disc["ci95_lo"] < -0.10,
    }


def run_study() -> dict[str, Any]:
    cfg = discover_llm()
    ids = list_task_ids()
    if len(ids) != N_REQUIRED:
        raise SystemExit(f"need n={N_REQUIRED}, got {len(ids)}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    rows: list[dict[str, Any]] = []
    raw_runs: list[dict[str, Any]] = []
    token_sum = 0
    for task_id in ids:
        task = load_task(TASK_DIR / f"{task_id}.json")
        for runner in (run_arm_a, run_arm_b):
            run = runner(cfg, task)
            raw_runs.append({k: v for k, v in run.items() if k != "committed_rule"})
            rows.append(score_run(run))
            token_sum += run["prompt_tokens"] + run["completion_tokens"]
    summary = summarize(rows)
    elapsed = time.time() - t0
    results = {"scores": rows, "summary": summary}
    manifest = {
        "requested_model": cfg["model"],
        "base_url": cfg["base_url"],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "n_tasks": len(ids),
        "seeds": [0],
        "wall_time_s": elapsed,
        "prompt_tokens": sum(r["prompt_tokens"] for r in raw_runs),
        "completion_tokens": sum(r["completion_tokens"] for r in raw_runs),
        "generation_tokens": token_sum,
        "policy_signature_gpu_ready_used": False,
        "task_ids": ids,
        "spec": "docs/SPEC_TRUE_LOCK.md",
        "n40_kill_rules_rewritten": False,
        "kwok_verifier_used": False,
    }
    (OUT_DIR / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT_DIR / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT_DIR / "raw_outputs.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in raw_runs), encoding="utf-8"
    )
    return {"ok": True, "tokens": token_sum, "summary": summary, "model": cfg["model"]}


def main() -> int:
    try:
        payload = run_study()
    except LLMUnavailable as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0
