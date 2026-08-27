"""Run frozen n=16 A/B audit contrast. Labels read only at scoring time."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from experiments.audit_contrast.render import load_task, render_prompt
from experiments.audit_contrast.score import load_label, score_output
from experiments.sep_of_powers.aggregate import paired_diff_ci, _mean
from experiments.sep_of_powers.run_contrast import LLMUnavailable, chat_complete, discover_llm

ROOT = Path(__file__).resolve().parents[2]
TASK_DIR = ROOT / "data" / "tasks" / "audit_contrast"
LABEL_DIR = ROOT / "data" / "labels" / "audit_contrast"
OUT_DIR = ROOT / "results" / "audit_contrast"
MAX_TOKENS = 800
TEMPERATURE = 0.0
N_REQUIRED = 16


def list_task_ids() -> list[str]:
    return sorted(p.stem for p in TASK_DIR.glob("A*.json"))


def run_arm(cfg: dict[str, str], task: dict[str, Any], arm: str) -> dict[str, Any]:
    prompt = render_prompt(task, arm=arm)
    call = chat_complete(cfg, prompt, max_tokens=MAX_TOKENS, temperature=TEMPERATURE)
    return {
        "arm": arm,
        "task_id": task["id"],
        "raw_output": call["text"],
        "prompt_tokens": call["prompt_tokens"],
        "completion_tokens": call["completion_tokens"],
        "elapsed_s": call["elapsed_s"],
    }


def score_run(run: dict[str, Any]) -> dict[str, Any]:
    task = load_task(TASK_DIR / f"{run['task_id']}.json")
    label = load_label(LABEL_DIR / f"{run['task_id']}.json")
    scored = score_output(task, label, run["raw_output"])
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
    missing = [i for i in ids if i not in by_arm["B"]]
    if missing or set(ids) != set(by_arm["B"]):
        raise ValueError(f"unpaired tasks: {missing}")
    correct_a = [int(by_arm["A"][i]["item_correct"]) for i in ids]
    correct_b = [int(by_arm["B"][i]["item_correct"]) for i in ids]
    hold_ids = [i for i in ids if by_arm["A"][i]["hold_out_item"]]
    keep_ids = [i for i in ids if not by_arm["A"][i]["hold_out_item"]]
    over_a = [int(by_arm["A"][i]["over_reject"]) for i in keep_ids]
    over_b = [int(by_arm["B"][i]["over_reject"]) for i in keep_ids]
    miss_a = [int(by_arm["A"][i]["miss"]) for i in hold_ids]
    miss_b = [int(by_arm["B"][i]["miss"]) for i in hold_ids]
    correct = paired_diff_ci(correct_a, correct_b)
    over = paired_diff_ci(over_a, over_b)
    return {
        "n_tasks": len(ids),
        "n_hold": len(hold_ids),
        "n_keep": len(keep_ids),
        "item_correct_A": _mean(correct_a),
        "item_correct_B": _mean(correct_b),
        "item_correct_B_minus_A": correct,
        "over_reject_A": _mean(over_a),
        "over_reject_B": _mean(over_b),
        "over_reject_B_minus_A": over,
        "miss_A": _mean(miss_a),
        "miss_B": _mean(miss_b),
        "h_audit_supported": (not correct["includes_0"]) and correct["point"] > 0 and over["ci95_lo"] <= 0.10,
        "h_ceremony": over["ci95_lo"] > 0.10,
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
        for arm in ("A", "B"):
            run = run_arm(cfg, task, arm)
            raw_runs.append(run)
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
        "spec": "docs/SPEC_AUDIT.md",
        "n40_kill_rules_rewritten": False,
    }
    (OUT_DIR / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUT_DIR / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUT_DIR / "raw_outputs.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in raw_runs),
        encoding="utf-8",
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
