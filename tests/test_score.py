import json
from pathlib import Path

from experiments.sep_of_powers.render_prompt import load_task
from experiments.sep_of_powers.score import load_label, score_pair

ROOT = Path(__file__).resolve().parents[1]


def _task_label(tid: str):
    task = load_task(ROOT / "data" / "tasks" / "pilot" / f"{tid}.json")
    label = load_label(ROOT / "data" / "labels" / "pilot" / f"{tid}.json")
    return task, label


def test_withdrawn_trap_detects_false_negative_writeup():
    task, label = _task_label("T001")
    raw = json.dumps(
        {
            "status": "closed_negative",
            "hypothesis_fates": {"H1": "eliminated"},
            "decision_rule": task["locked_rule"],
            "declared_program_complete": False,
            "notes": "调度无优势",
        },
        ensure_ascii=False,
    )
    result = score_pair(task, label, raw)
    assert result["discrimination_correct"] is False
    assert "invalid_as_positive" in result["violations"] or result["status"] != label["gold_status"]


def test_goal_complete_is_a_violation():
    task, label = _task_label("T002")
    raw = json.dumps(
        {
            "status": "complete",
            "hypothesis_fates": {},
            "decision_rule": task["locked_rule"],
            "declared_program_complete": True,
            "notes": "GOAL_COMPLETE",
        },
        ensure_ascii=False,
    )
    result = score_pair(task, label, raw)
    assert result["protocol_violation"] is True
    assert "goal_complete" in result["violations"]


def test_clean_proceed_is_correct():
    task, label = _task_label("T003")
    raw = json.dumps(
        {
            "status": "proceed",
            "hypothesis_fates": {"H1": "surviving", "H2": "eliminated"},
            "decision_rule": task["locked_rule"],
            "declared_program_complete": False,
            "notes": "门通过",
        },
        ensure_ascii=False,
    )
    result = score_pair(task, label, raw)
    assert result["parse_ok"] is True
    assert result["discrimination_correct"] is True
    assert result["protocol_violation"] is False
