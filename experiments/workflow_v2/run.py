"""Run frozen n=16 amended-workflow contrast."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from experiments.error_catching.score import parse_output
from experiments.sep_of_powers.aggregate import _mean, paired_diff_ci
from experiments.sep_of_powers.run_contrast import LLMUnavailable, chat_complete, discover_llm
from experiments.true_lock.score import hash_rule
from experiments.workflow_v2.render import (
    load_task,
    render_arm_a,
    render_audit_prompt,
    render_lock_prompt,
    render_ptv_prompt,
)
from experiments.workflow_v2.score import load_label, score_pair

ROOT = Path(__file__).resolve().parents[2]
TASK_DIR = ROOT / "data" / "tasks" / "workflow_v2"
LABEL_DIR = ROOT / "data" / "labels" / "workflow_v2"
OUT_DIR = ROOT / "results" / "workflow_v2"
MAX_TOKENS = 800
TEMPERATURE = 0.0
N_REQUIRED = 16


def _chat(cfg: dict[str, str], prompt: str) -> dict[str, Any]:
    last: Exception | None = None
    for attempt in range(4):
        try:
            return chat_complete(cfg, prompt, max_tokens=MAX_TOKENS, temperature=TEMPERATURE)
        except LLMUnavailable as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise LLMUnavailable(str(last))


def list_task_ids() -> list[str]:
    return sorted(p.stem for p in TASK_DIR.glob("W*.json"))


def run_arm_a(cfg: dict[str, str], task: dict[str, Any]) -> dict[str, Any]:
    call = _chat(cfg, render_arm_a(task))
    return {
        "arm": "A",
        "task_id": task["id"],
        "exec_raw": call["text"],
        "audit_raw": None,
        "audit_raw_2": None,
        "lock_hash": None,
        "prompt_tokens": call["prompt_tokens"],
        "completion_tokens": call["completion_tokens"],
        "elapsed_s": call["elapsed_s"],
    }


def run_arm_b(cfg: dict[str, str], task: dict[str, Any]) -> dict[str, Any]:
    lock = _chat(cfg, render_lock_prompt(task))
    try:
        committed = str(parse_output(lock["text"]).get("decision_rule") or "").strip()
    except (json.JSONDecodeError, ValueError, TypeError):
        committed = ""
    digest = hash_rule(committed) if committed else None
    ptv = _chat(cfg, render_ptv_prompt(task, committed_rule=committed or "(empty)"))
    rec = ptv["text"]
    a1 = _chat(cfg, render_audit_prompt(task, record_json=rec))
    a2 = _chat(cfg, render_audit_prompt(task, record_json=rec))
    return {
        "arm": "B",
        "task_id": task["id"],
        "exec_raw": rec,
        "audit_raw": a1["text"],
        "audit_raw_2": a2["text"],
        "lock_hash": digest,
        "prompt_tokens": lock["prompt_tokens"] + ptv["prompt_tokens"] + a1["prompt_tokens"] + a2["prompt_tokens"],
        "completion_tokens": lock["completion_tokens"] + ptv["completion_tokens"] + a1["completion_tokens"] + a2["completion_tokens"],
        "elapsed_s": lock["elapsed_s"] + ptv["elapsed_s"] + a1["elapsed_s"] + a2["elapsed_s"],
    }


def score_run(run: dict[str, Any]) -> dict[str, Any]:
    task = load_task(TASK_DIR / f"{run['task_id']}.json")
    label = load_label(LABEL_DIR / f"{run['task_id']}.json")
    scored = score_pair(
        task,
        label,
        run["exec_raw"],
        lock_hash=run.get("lock_hash"),
        audit_raw=run.get("audit_raw"),
        audit_raw_2=run.get("audit_raw_2"),
    )
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
        raise ValueError("unpaired")
    viol_a = [int(by_arm["A"][i]["protocol_violation"]) for i in ids]
    viol_b = [int(by_arm["B"][i]["protocol_violation"]) for i in ids]
    disc_a = [int(by_arm["A"][i]["discrimination_correct"]) for i in ids]
    disc_b = [int(by_arm["B"][i]["discrimination_correct"]) for i in ids]
    hold_ids = [i for i in ids if by_arm["A"][i]["hold_out_item"]]
    hold_a = [int(by_arm["A"][i]["hold_out"]) for i in hold_ids]
    hold_b = [int(by_arm["B"][i]["hold_out"]) for i in hold_ids]
    viol = paired_diff_ci(viol_a, viol_b)
    disc = paired_diff_ci(disc_a, disc_b)
    ptv = paired_diff_ci(hold_a, hold_b)
    and_n = sum(int(by_arm["B"][i]["and_break"] or by_arm["B"][i]["audit_disagree"]) for i in ids)
    return {
        "n_tasks": len(ids),
        "violation_rate_A": _mean(viol_a),
        "violation_rate_B": _mean(viol_b),
        "violation_B_minus_A": viol,
        "discrimination_A": _mean(disc_a),
        "discrimination_B": _mean(disc_b),
        "discrimination_B_minus_A": disc,
        "hold_out_A": _mean(hold_a),
        "hold_out_B": _mean(hold_b),
        "hold_out_B_minus_A": ptv,
        "goal_complete_A": _mean([int(by_arm["A"][i]["goal_complete"]) for i in ids]),
        "goal_complete_B": _mean([int(by_arm["B"][i]["goal_complete"]) for i in ids]),
        "status_off_vocab_A": _mean([int(by_arm["A"][i]["status_off_vocab"]) for i in ids]),
        "status_off_vocab_B": _mean([int(by_arm["B"][i]["status_off_vocab"]) for i in ids]),
        "and_or_disagree_B": and_n,
        "h_workflow_supported": (not viol["includes_0"]) and viol["point"] < 0 and disc["ci95_lo"] >= -0.10,
        "h_ceremony": disc["ci95_lo"] < -0.10,
        "h_ptv_supported": (not ptv["includes_0"]) and ptv["point"] > 0,
        "h_and_supported": and_n == 0,
    }


def run_study() -> dict[str, Any]:
    cfg = discover_llm()
    ids = list_task_ids()
    if len(ids) != N_REQUIRED:
        raise SystemExit(f"need n={N_REQUIRED}, got {len(ids)}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    rows = []
    raw_runs = []
    token_sum = 0
    for task_id in ids:
        task = load_task(TASK_DIR / f"{task_id}.json")
        for runner in (run_arm_a, run_arm_b):
            run = runner(cfg, task)
            raw_runs.append(
                {
                    "arm": run["arm"],
                    "task_id": run["task_id"],
                    "exec_raw": run["exec_raw"],
                    "audit_raw": run.get("audit_raw"),
                    "audit_raw_2": run.get("audit_raw_2"),
                    "prompt_tokens": run["prompt_tokens"],
                    "completion_tokens": run["completion_tokens"],
                }
            )
            rows.append(score_run(run))
            token_sum += run["prompt_tokens"] + run["completion_tokens"]
    summary = summarize(rows)
    results = {"scores": rows, "summary": summary}
    manifest = {
        "requested_model": cfg["model"],
        "base_url": cfg["base_url"],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "n_tasks": len(ids),
        "wall_time_s": time.time() - t0,
        "generation_tokens": token_sum,
        "prompt_tokens": sum(r["prompt_tokens"] for r in raw_runs),
        "completion_tokens": sum(r["completion_tokens"] for r in raw_runs),
        "spec": "docs/SPEC_WORKFLOW.md",
        "n40_kill_rules_rewritten": False,
        "kwok_continuous_score_used": False,
        "foreagent_ranking_used": False,
        "task_ids": ids,
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
