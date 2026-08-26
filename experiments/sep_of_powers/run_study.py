"""Run the frozen n=40 A/B contrast and write scored artifacts."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.sep_of_powers.aggregate import summarize
from experiments.sep_of_powers.render_prompt import load_task
from experiments.sep_of_powers.run_contrast import (
    discover_llm,
    list_task_ids,
    run_arm_a,
    run_arm_b,
    score_run,
)

OUT_DIR = ROOT / "results" / "sep_of_powers"
MAX_TOKENS = 800
TEMPERATURE = 0.0


def _run_one(cfg, task_id: str, arm: str) -> dict:
    task = load_task(ROOT / "data" / "tasks" / "pilot" / f"{task_id}.json")
    if arm == "A":
        run = run_arm_a(cfg, task, max_tokens=MAX_TOKENS, temperature=TEMPERATURE)
    else:
        run = run_arm_b(cfg, task, max_tokens=MAX_TOKENS, temperature=TEMPERATURE)
    scored = score_run(run)
    return {
        "run": {
            "arm": run["arm"],
            "task_id": run["task_id"],
            "raw_output": run["raw_output"],
            "decision_rule": scored.get("status") is not None,
            "lock_hash": run.get("lock_hash"),
            "prompt_tokens": run["prompt_tokens"],
            "completion_tokens": run["completion_tokens"],
            "elapsed_s": run["elapsed_s"],
        },
        "score": scored,
    }


def main() -> int:
    cfg = discover_llm()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ids = list_task_ids()
    if len(ids) < 40:
        raise SystemExit(f"need n>=40, got {len(ids)}")
    t0 = time.time()
    rows = []
    raw_runs = []
    token_sum = 0
    for task_id in ids:
        for arm in ("A", "B"):
            packed = _run_one(cfg, task_id, arm)
            raw_runs.append(packed["run"])
            rows.append(packed["score"])
            token_sum += packed["run"]["prompt_tokens"] + packed["run"]["completion_tokens"]
            if token_sum > 100_000_000:
                raise SystemExit("token cap 1e8 exceeded")
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
        "token_cap": 100_000_000,
        "policy_signature_gpu_ready_used": False,
        "task_ids": ids,
    }
    (OUT_DIR / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT_DIR / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "tokens": token_sum, "summary": summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
