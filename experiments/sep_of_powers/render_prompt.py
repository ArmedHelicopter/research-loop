"""Render the public face of a task. Must never read data/labels."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TASK_REQUIRED = (
    "id",
    "title",
    "program_question",
    "stage_question",
    "hypotheses",
    "locked_rule",
    "artifacts_summary",
    "new_observation",
)


def load_task(path: Path) -> dict[str, Any]:
    task = json.loads(path.read_text(encoding="utf-8"))
    missing = [key for key in TASK_REQUIRED if key not in task]
    if missing:
        raise ValueError(f"{path} missing fields: {missing}")
    for banned in ("gold_status", "gold_reason", "label", "verdict"):
        if banned in task:
            raise ValueError(f"{path} leaks hidden field {banned}")
    return task


def render_prompt(task: dict[str, Any], *, arm: str) -> str:
    hypotheses = "\n".join(f"- {h}" for h in task["hypotheses"])
    arm_text = {
        "A": (
            "你是单一科研 agent。读完观察后给出判定。"
            "输出 JSON，字段：status, hypothesis_fates, decision_rule, "
            "declared_program_complete, notes。"
        ),
        "B": (
            "角色隔离。先只根据 locked_rule 复述将使用的判定规则并停住；"
            "观察全文只在规则字节提交之后提供。最终 JSON 的 decision_rule "
            "必须与锁定文本一致。禁止宣告 programme 完成。"
            "输出 JSON，字段：status, hypothesis_fates, decision_rule, "
            "declared_program_complete, notes。"
        ),
    }[arm]
    return f"""{arm_text}

programme 问题（不可改写成已完成）：
{task["program_question"]}

本阶段问题：
{task["stage_question"]}

竞争假说：
{hypotheses}

已锁定的判定规则：
{task["locked_rule"]}

已有工件摘要：
{task["artifacts_summary"]}

新观察：
{task["new_observation"]}
"""
