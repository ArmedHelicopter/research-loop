"""Amended workflow: gold_rule withheld; AND break; status vocab."""

import json
from pathlib import Path

from experiments.workflow_v2.render import load_task, render_arm_a, render_audit_prompt, render_lock_prompt, render_ptv_prompt
from experiments.workflow_v2.score import hash_rule, load_label, score_pair

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "data" / "tasks" / "workflow_v2"
LABELS = ROOT / "data" / "labels" / "workflow_v2"


def test_n16_mixed_and_no_gold_in_prompts():
    paths = sorted(TASKS.glob("W*.json"))
    assert len(paths) == 16
    hold = 0
    for path in paths:
        task = load_task(path)
        label = load_label(LABELS / path.name)
        assert "locked_rule" not in task
        assert task["checklist"]
        if label["gold_status"] in {"withdrawn", "invalid"}:
            hold += 1
        prompts = [
            render_arm_a(task),
            render_lock_prompt(task),
            render_ptv_prompt(task, committed_rule="r"),
            render_audit_prompt(task, record_json="{}"),
        ]
        for p in prompts:
            assert label["gold_rule"] not in p
            assert "gold_status" not in p
            assert "gold_rule" not in p
        assert task["new_observation"] not in render_lock_prompt(task)
    assert hold == 8


def test_and_break_when_valid_despite_failed_check():
    task = load_task(TASKS / "W001.json")
    label = load_label(LABELS / "W001.json")
    exec_raw = json.dumps(
        {
            "status": "withdrawn",
            "decision_rule": "keep",
            "declared_program_complete": False,
            "notes": "",
        },
        ensure_ascii=False,
    )
    audit = json.dumps(
        {
            "checks": [{"item": task["checklist"][0], "pass": False}, {"item": task["checklist"][1], "pass": True}],
            "audit_verdict": "valid",
        },
        ensure_ascii=False,
    )
    got = score_pair(task, label, exec_raw, lock_hash=hash_rule("keep"), audit_raw=audit, audit_raw_2=audit)
    assert got["and_break"] is True
    assert got["protocol_violation"] is False


def test_off_vocab_is_shared_violation():
    task = load_task(TASKS / "W001.json")
    label = load_label(LABELS / "W001.json")
    raw = json.dumps(
        {
            "status": "in_progress",
            "decision_rule": "keep",
            "declared_program_complete": False,
            "notes": "",
        },
        ensure_ascii=False,
    )
    got = score_pair(task, label, raw)
    assert got["status_off_vocab"] is True
    assert got["protocol_violation"] is True
    assert got["discrimination_correct"] is False
