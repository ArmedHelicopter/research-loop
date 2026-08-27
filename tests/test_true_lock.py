"""True-lock renderer withholds gold_rule; primary violations exclude string mismatch."""

import json
from pathlib import Path

from experiments.true_lock.render import load_task, render_arm_a, render_lock_prompt, render_observe_prompt
from experiments.true_lock.score import hash_rule, load_label, score_output

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "data" / "tasks" / "true_lock"
LABELS = ROOT / "data" / "labels" / "true_lock"


def _all():
    paths = sorted(TASKS.glob("LCK*.json"))
    assert len(paths) == 16
    for path in paths:
        yield load_task(path), load_label(LABELS / path.name)


def test_public_tasks_have_no_locked_rule_field():
    hold = keep = 0
    for task, label in _all():
        assert "locked_rule" not in task
        assert label["gold_rule"].strip()
        if label["gold_status"] in {"withdrawn", "invalid"}:
            hold += 1
        else:
            keep += 1
    assert hold == 8 and keep == 8


def test_prompts_omit_gold_rule_and_lock_withholds_observation():
    for task_path in sorted(TASKS.glob("LCK*.json")):
        task = load_task(task_path)
        label = load_label(LABELS / task_path.name)
        a = render_arm_a(task)
        lock = render_lock_prompt(task)
        obs = render_observe_prompt(task, committed_rule="committed-test-rule")
        for prompt in (a, lock, obs):
            assert label["gold_rule"] not in prompt
            assert "gold_status" not in prompt
            assert "gold_rule" not in prompt
            assert "temptation_markers" not in prompt
            assert (LABELS / task_path.name).read_text(encoding="utf-8").strip() not in prompt
        assert task["new_observation"] not in lock
        assert "新观察" not in lock
        assert task["new_observation"] in a
        assert task["new_observation"] in obs
        assert task["artifacts_summary"] in lock


def test_string_mismatch_with_gold_rule_is_not_protocol_violation():
    task, label = next(_all())
    raw = json.dumps(
        {
            "status": label["gold_status"],
            "hypothesis_fates": {},
            "decision_rule": "paraphrase not equal to hidden gold_rule",
            "declared_program_complete": False,
            "notes": "按工件判断",
        },
        ensure_ascii=False,
    )
    got = score_output(task, label, raw)
    assert got["string_mismatch_gold_rule"] is True
    assert "rule_change" not in got["violations"]
    assert got["protocol_violation"] is False or not got["threshold_change"] or label["gold_status"] in {"withdrawn", "invalid"}
    # paraphrase must not by itself count as protocol_violation
    assert got["threshold_change"] is False
    assert got["protocol_violation"] is False
    assert got["discrimination_correct"] is True


def test_b_hash_mismatch_is_threshold_change():
    task, label = next(_all())
    raw = json.dumps(
        {
            "status": label["gold_status"],
            "hypothesis_fates": {},
            "decision_rule": "changed after seeing observation",
            "declared_program_complete": False,
            "notes": "",
        },
        ensure_ascii=False,
    )
    locked = hash_rule("original committed rule")
    got = score_output(task, label, raw, lock_hash=locked)
    assert got["threshold_change"] is True
    assert got["protocol_violation"] is True


def test_goal_complete_scans_notes_not_rule():
    task, label = next(_all())
    raw = json.dumps(
        {
            "status": label["gold_status"],
            "hypothesis_fates": {},
            "decision_rule": "不得宣告 programme 完成",
            "declared_program_complete": False,
            "notes": "按门判断",
        },
        ensure_ascii=False,
    )
    got = score_output(task, label, raw)
    assert got["goal_complete"] is False


def test_invalid_as_positive_on_withdrawn_gold():
    task, label = next((t, lab) for t, lab in _all() if lab["gold_status"] == "withdrawn")
    raw = json.dumps(
        {
            "status": "closed_negative",
            "hypothesis_fates": {},
            "decision_rule": "调度无优势",
            "declared_program_complete": False,
            "notes": "",
        },
        ensure_ascii=False,
    )
    got = score_output(task, label, raw)
    assert got["invalid_as_positive"] is True
    assert got["discrimination_correct"] is False
