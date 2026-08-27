"""Drive shipped intact-loop render/score. Gold stays out of prompts."""

import json
from pathlib import Path

from experiments.intact_loop.render import (
    load_intact_task,
    render_intact_audit_prompt,
    render_intact_successor_prompt,
)
from experiments.intact_loop.score import score_intact

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "data" / "tasks" / "intact" / "L001.json"
LABEL = ROOT / "data" / "labels" / "intact" / "L001.json"


def test_intact_prompts_omit_gold_fields():
    task = load_intact_task(TASK)
    label_text = LABEL.read_text(encoding="utf-8")
    audit = render_intact_audit_prompt(task)
    dummy_audit = {"audit_verdict": "invalid", "recommended_status": "withdrawn", "notes": "unit mismatch"}
    succ = render_intact_successor_prompt(task, dummy_audit)
    for prompt in (audit, succ):
        for banned in ("gold_status", "gold_reason", "violation_if"):
            assert banned not in prompt
        assert label_text.strip() not in prompt
    assert task["defective_record"]["notes"] in audit
    assert "invalid" in succ


def test_known_defective_record_not_clean_proceed_after_audit():
    task = load_intact_task(TASK)
    label = json.loads(LABEL.read_text(encoding="utf-8"))
    bad_audit = json.dumps(
        {
            "audit_verdict": "valid",
            "recommended_status": "proceed",
            "notes": "调度无优势",
        },
        ensure_ascii=False,
    )
    ok_succ = json.dumps(
        {
            "successors": [
                {
                    "question": "用匹配量尺重跑比较",
                    "source": "failed gates",
                    "admission": "proposed",
                }
            ],
            "challenger_skipped": False,
            "declared_program_complete": False,
            "notes": "",
        },
        ensure_ascii=False,
    )
    result = score_intact(task, label, bad_audit, ok_succ)
    assert result["scored_as_clean_proceed_or_complete"] is True
    assert result["defect_held_out"] is False
