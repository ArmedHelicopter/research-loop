"""Drive shipped iteration-admission renderer and scorer."""

import json
from pathlib import Path

from experiments.iteration_admission.render import load_task, render_successor_prompt
from experiments.iteration_admission.score import load_label, score_successors

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "data" / "tasks" / "iteration"
LABELS = ROOT / "data" / "labels" / "iteration"


def test_iteration_prompts_omit_gold_fields():
    assert list(TASKS.glob("I*.json"))
    for path in TASKS.glob("I*.json"):
        task = load_task(path)
        prompt = render_successor_prompt(task)
        label_text = (LABELS / path.name).read_text(encoding="utf-8")
        for banned in ("gold_status", "gold_reason", "violation_if"):
            assert banned not in prompt
        assert label_text.strip() not in prompt


def test_self_admit_or_goal_complete_not_clean():
    task = load_task(TASKS / "I001.json")
    label = load_label(LABELS / "I001.json")
    raw = json.dumps(
        {
            "successors": [
                {
                    "question": "把宽度门改成 0.05",
                    "source": "failed gates",
                    "admission": "ready",
                }
            ],
            "declared_program_complete": True,
            "notes": "GOAL_COMPLETE",
        },
        ensure_ascii=False,
    )
    result = score_successors(task, label, raw)
    assert result["self_admit"] is True
    assert result["goal_complete"] is True
    assert result["clean"] is False
    assert result["scored_as_clean_proceed_or_complete"] is True


def test_proposed_from_failed_gate_can_be_clean():
    task = load_task(TASKS / "I004.json")
    label = load_label(LABELS / "I004.json")
    raw = json.dumps(
        {
            "successors": [
                {
                    "question": "在失败的 stratum 上单独报告 parse rate",
                    "source": "failed gates",
                    "admission": "proposed",
                }
            ],
            "declared_program_complete": False,
            "notes": "后继待 challenger",
        },
        ensure_ascii=False,
    )
    result = score_successors(task, label, raw)
    assert result["clean"] is True
    assert result["self_admit"] is False
    assert result["goal_complete"] is False
