"""Render coupled intact-loop prompts. Must never read data/labels."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from experiments.error_catching.render import render_audit_prompt
from experiments.iteration_admission import ALLOWED_SOURCES
from experiments.iteration_admission.render import render_successor_prompt

BANNED = ("gold_status", "gold_reason", "label", "verdict", "violation_if", "gold_events")
TASK_REQUIRED = (
    "id",
    "title",
    "program_question",
    "locked_rule",
    "checklist",
    "defective_record",
    "allowed_sources",
    "docket_snapshot",
)


def load_intact_task(path: Path) -> dict[str, Any]:
    task = json.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in TASK_REQUIRED if k not in task]
    if missing:
        raise ValueError(f"{path} missing {missing}")
    blob = json.dumps(task, ensure_ascii=False)
    for banned in BANNED:
        if banned in task or f'"{banned}"' in blob:
            raise ValueError(f"{path} leaks {banned}")
    return task


def as_audit_task(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": task["id"],
        "title": task["title"],
        "locked_rule": task["locked_rule"],
        "checklist": task["checklist"],
        "defective_record": task["defective_record"],
    }


def as_iteration_task(task: dict[str, Any], audit_public: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": task["id"],
        "title": task["title"],
        "program_question": task["program_question"],
        "docket_snapshot": task["docket_snapshot"],
        "allowed_sources": list(ALLOWED_SOURCES),
        "round_result": {
            "prior_record_status": task["defective_record"].get("status"),
            "audit_verdict": audit_public.get("audit_verdict") or audit_public.get("verdict"),
            "recommended_status": audit_public.get("recommended_status"),
            "notes": audit_public.get("notes"),
        },
    }


def render_intact_audit_prompt(task: dict[str, Any]) -> str:
    return render_audit_prompt(as_audit_task(task))


def render_intact_successor_prompt(task: dict[str, Any], audit_public: dict[str, Any]) -> str:
    return render_successor_prompt(as_iteration_task(task, audit_public))
