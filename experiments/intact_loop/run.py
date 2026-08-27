"""Sequence auditor then proposer on one public trajectory. No token cap."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from experiments.error_catching.score import parse_output
from experiments.intact_loop.render import (
    load_intact_task,
    render_intact_audit_prompt,
    render_intact_successor_prompt,
)
from experiments.intact_loop.score import score_intact
from experiments.sep_of_powers.run_contrast import chat_complete, discover_llm

ROOT = Path(__file__).resolve().parents[2]
TASK_DIR = ROOT / "data" / "tasks" / "intact"
LABEL_DIR = ROOT / "data" / "labels" / "intact"


def run_intact(task_id: str, *, max_tokens: int = 800, temperature: float = 0.0) -> dict[str, Any]:
    cfg = discover_llm()
    task = load_intact_task(TASK_DIR / f"{task_id}.json")
    label = json.loads((LABEL_DIR / f"{task_id}.json").read_text(encoding="utf-8"))
    audit_prompt = render_intact_audit_prompt(task)
    audit_call = chat_complete(cfg, audit_prompt, max_tokens=max_tokens, temperature=temperature)
    try:
        audit_public = parse_output(audit_call["text"])
    except (json.JSONDecodeError, ValueError):
        audit_public = {"audit_verdict": None, "recommended_status": None, "notes": audit_call["text"][:400]}
    succ_prompt = render_intact_successor_prompt(task, audit_public)
    succ_call = chat_complete(cfg, succ_prompt, max_tokens=max_tokens, temperature=temperature)
    events = score_intact(task, label, audit_call["text"], succ_call["text"])
    return {
        "model": cfg["model"],
        "task_id": task_id,
        "audit_verdict": audit_public.get("audit_verdict") or audit_public.get("verdict"),
        "recommended_status": audit_public.get("recommended_status"),
        "successor_raw": succ_call["text"],
        "admission": _first_admission(succ_call["text"]),
        "events": events,
        "prompt_tokens": audit_call["prompt_tokens"] + succ_call["prompt_tokens"],
        "completion_tokens": audit_call["completion_tokens"] + succ_call["completion_tokens"],
        "uncapped": True,
    }


def _first_admission(raw: str) -> str | None:
    try:
        out = parse_output(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    items = out.get("successors") or []
    if items and isinstance(items, list) and isinstance(items[0], dict):
        return items[0].get("admission")
    return out.get("admission")
