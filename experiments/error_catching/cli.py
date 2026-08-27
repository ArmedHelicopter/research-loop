"""python -m experiments.error_catching.cli --task E001"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.error_catching.render import load_task, render_audit_prompt
from experiments.error_catching.score import parse_output, score_audit, load_label
from experiments.sep_of_powers.run_contrast import LLMUnavailable, chat_complete, discover_llm

TASK_DIR = ROOT / "data" / "tasks" / "error_catching"
LABEL_DIR = ROOT / "data" / "labels" / "error_catching"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--task", default="E001")
    args = p.parse_args(argv)
    task = load_task(TASK_DIR / f"{args.task}.json")
    prompt = render_audit_prompt(task)
    try:
        cfg = discover_llm()
        call = chat_complete(cfg, prompt, max_tokens=800, temperature=0.0)
        raw = call["text"]
    except LLMUnavailable as exc:
        print(f"LLM unavailable: {exc}", file=sys.stderr)
        return 2
    try:
        parsed = parse_output(raw)
    except Exception as exc:  # noqa: BLE001
        parsed = {"parse_error": str(exc)}
    label = load_label(LABEL_DIR / f"{args.task}.json")
    scored = score_audit(task, label, raw)
    print(json.dumps({"status": parsed.get("audit_verdict"), "recommended_status": parsed.get("recommended_status"), "score": scored, "raw_output": raw}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
