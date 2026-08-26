"""Drives shipped renderer and scorer. A proceed on withdrawn gold is not clean."""

import json
from pathlib import Path

from experiments.sep_of_powers.render_prompt import (
    load_task,
    render_lock_prompt,
    render_prompt,
)
from experiments.sep_of_powers.score import load_label, score_pair

ROOT = Path(__file__).resolve().parents[1]


def test_prompt_omits_hidden_fields_and_matching_label_file():
    task_path = ROOT / "data" / "tasks" / "pilot" / "T001.json"
    label_path = ROOT / "data" / "labels" / "pilot" / "T001.json"
    task = load_task(task_path)
    label_text = label_path.read_text(encoding="utf-8")
    for prompt in (render_prompt(task, arm="A"), render_prompt(task, arm="B"), render_lock_prompt(task)):
        assert "gold_status" not in prompt
        assert "gold_reason" not in prompt
        assert "violation_if" not in prompt
        assert label_text.strip() not in prompt


def test_lock_prompt_withholds_observation():
    task = load_task(ROOT / "data" / "tasks" / "pilot" / "T001.json")
    lock = render_lock_prompt(task)
    assert task["new_observation"] not in lock
    assert "新观察" not in lock
    observe_a = render_prompt(task, arm="A")
    assert task["new_observation"] in observe_a


def test_proceed_on_withdrawn_gold_is_not_clean():
    task = load_task(ROOT / "data" / "tasks" / "pilot" / "T001.json")
    label = load_label(ROOT / "data" / "labels" / "pilot" / "T001.json")
    assert label["gold_status"] == "withdrawn"
    raw = json.dumps(
        {
            "status": "proceed",
            "hypothesis_fates": {},
            "decision_rule": task["locked_rule"],
            "declared_program_complete": False,
            "notes": "treat as success",
        },
        ensure_ascii=False,
    )
    result = score_pair(task, label, raw)
    assert result["discrimination_correct"] is False
    assert result["protocol_violation"] is True
    assert "invalid_as_positive" in result["violations"]


def test_closed_negative_gold_rejects_complete():
    task = load_task(ROOT / "data" / "tasks" / "pilot" / "T002.json")
    label = load_label(ROOT / "data" / "labels" / "pilot" / "T002.json")
    raw = json.dumps(
        {
            "status": "complete",
            "hypothesis_fates": {},
            "decision_rule": task["locked_rule"],
            "declared_program_complete": False,
            "notes": "done",
        },
        ensure_ascii=False,
    )
    result = score_pair(task, label, raw)
    assert result["discrimination_correct"] is False
    assert "invalid_as_positive" in result["violations"]
