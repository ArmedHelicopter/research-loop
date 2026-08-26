"""CLI: python -m experiments.sep_of_powers.cli --task T001 --arm A"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.sep_of_powers.render_prompt import load_task
from experiments.sep_of_powers.run_contrast import (
    LLMUnavailable,
    discover_llm,
    run_arm_a,
    run_arm_b,
    score_run,
)

TASK_DIR = ROOT / "data" / "tasks" / "pilot"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--task", required=True)
    p.add_argument("--arm", required=True, choices=("A", "B"))
    p.add_argument("--max-tokens", type=int, default=800)
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--score", action="store_true")
    args = p.parse_args(argv)
    try:
        cfg = discover_llm()
    except LLMUnavailable as exc:
        print(f"LLM unavailable: {exc}", file=sys.stderr)
        return 2
    task = load_task(TASK_DIR / f"{args.task}.json")
    if args.arm == "A":
        run = run_arm_a(cfg, task, max_tokens=args.max_tokens, temperature=args.temperature)
    else:
        run = run_arm_b(cfg, task, max_tokens=args.max_tokens, temperature=args.temperature)
    payload: dict = {
        "model": cfg["model"],
        "arm": run["arm"],
        "task_id": run["task_id"],
        "raw_output": run["raw_output"],
        "decision_rule_present": True,
        "lock_hash": run.get("lock_hash"),
        "prompt_tokens": run["prompt_tokens"],
        "completion_tokens": run["completion_tokens"],
    }
    try:
        from experiments.sep_of_powers.score import parse_output

        parsed = parse_output(run["raw_output"])
        payload["status"] = parsed.get("status")
        payload["decision_rule"] = parsed.get("decision_rule")
    except Exception as exc:  # noqa: BLE001
        payload["status"] = None
        payload["decision_rule"] = None
        payload["parse_error"] = str(exc)
    if args.score:
        payload["score"] = score_run(run)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
