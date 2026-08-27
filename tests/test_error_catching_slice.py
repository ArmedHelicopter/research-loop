"""Drive shipped error-catching renderer and scorer."""

import json
from pathlib import Path

from experiments.error_catching.render import load_task, render_audit_prompt
from experiments.error_catching.score import load_label, score_audit

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "data" / "tasks" / "error_catching"
LABELS = ROOT / "data" / "labels" / "error_catching"


def test_error_catching_prompts_omit_gold_fields():
    assert list(TASKS.glob("E*.json"))
    for path in TASKS.glob("E00*.json"):
        task = load_task(path)
        prompt = render_audit_prompt(task)
        label_text = (LABELS / path.name).read_text(encoding="utf-8")
        for banned in ("gold_status", "gold_reason", "violation_if"):
            assert banned not in prompt
        assert label_text.strip() not in prompt


def test_known_defective_record_not_scored_as_clean_proceed():
    task = load_task(TASKS / "E001.json")
    label = load_label(LABELS / "E001.json")
    raw = json.dumps(
        {
            "audit_verdict": "valid",
            "recommended_status": "proceed",
            "notes": "调度无优势",
        },
        ensure_ascii=False,
    )
    result = score_audit(task, label, raw)
    assert result["scored_as_clean_proceed_or_complete"] is True
    assert result["caught_defect"] is False


def test_invalid_withdrawn_is_caught():
    task = load_task(TASKS / "E001.json")
    label = load_label(LABELS / "E001.json")
    raw = json.dumps(
        {
            "audit_verdict": "invalid",
            "recommended_status": "withdrawn",
            "notes": "量尺不一致",
        },
        ensure_ascii=False,
    )
    result = score_audit(task, label, raw)
    assert result["caught_defect"] is True
    assert result["scored_as_clean_proceed_or_complete"] is False
