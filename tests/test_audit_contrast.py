"""Drive shipped audit-contrast renderer and scorer."""

import json
from pathlib import Path

from experiments.audit_contrast.render import load_task, render_arm_a, render_arm_b
from experiments.audit_contrast.run import summarize
from experiments.audit_contrast.score import load_label, score_output

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "data" / "tasks" / "audit_contrast"
LABELS = ROOT / "data" / "labels" / "audit_contrast"


def _all():
    paths = sorted(TASKS.glob("A*.json"))
    assert len(paths) == 16
    for path in paths:
        yield load_task(path), load_label(LABELS / path.name)


def test_mixed_eight_hold_eight_keep():
    hold = keep = 0
    for task, label in _all():
        assert task["id"] == label["id"]
        assert "gold_status" not in json.dumps(task)
        if label["gold_status"] in {"withdrawn", "invalid"}:
            hold += 1
        else:
            assert label["gold_status"] in {"proceed", "closed_negative"}
            keep += 1
    assert hold == 8 and keep == 8


def test_prompts_omit_labels_and_arm_a_has_no_checklist():
    for task_path in sorted(TASKS.glob("A*.json")):
        task = load_task(task_path)
        label_text = (LABELS / task_path.name).read_text(encoding="utf-8")
        a = render_arm_a(task)
        b = render_arm_b(task)
        for prompt in (a, b):
            assert "gold_status" not in prompt
            assert "gold_reason" not in prompt
            assert "violation_if" not in prompt
            assert label_text.strip() not in prompt
            assert task["written_record"]["status"] in prompt or json.dumps(
                task["written_record"]["status"]
            ) in prompt
        assert "独立 Auditor" not in a
        assert "独立 Auditor" in b
        for item in task["checklist"]:
            assert item not in a
            assert item in b


def test_hold_out_proceed_is_incorrect_keep_invalid_is_over_reject():
    task, label = next(
        (t, lab) for t, lab in _all() if lab["gold_status"] in {"withdrawn", "invalid"}
    )
    bad = json.dumps(
        {"audit_verdict": "valid", "recommended_status": "proceed", "notes": ""},
        ensure_ascii=False,
    )
    got = score_output(task, label, bad)
    assert got["item_correct"] is False
    assert got["miss"] is True

    keep_task, keep_label = next(
        (t, lab) for t, lab in _all() if lab["gold_status"] == "proceed"
    )
    over = json.dumps(
        {"audit_verdict": "invalid", "recommended_status": "withdrawn", "notes": ""},
        ensure_ascii=False,
    )
    got_keep = score_output(keep_task, keep_label, over)
    assert got_keep["item_correct"] is False
    assert got_keep["over_reject"] is True


def test_alias_status_withdrawn_counts_on_hold_item():
    task, label = next((t, lab) for t, lab in _all() if lab["gold_status"] == "withdrawn")
    raw = json.dumps({"status": "withdrawn", "notes": "单位错位"}, ensure_ascii=False)
    got = score_output(task, label, raw)
    assert got["item_correct"] is True
    assert got["audit_verdict"] == "invalid"


def test_summarize_does_not_emit_n40_fields():
    rows = []
    for i, (task, label) in enumerate(_all()):
        hold = label["gold_status"] in {"withdrawn", "invalid"}
        rec = "withdrawn" if hold else label["gold_status"]
        verdict = "invalid" if hold else "valid"
        for arm, correct in (("A", i % 2 == 0), ("B", True)):
            rows.append(
                {
                    "id": task["id"],
                    "arm": arm,
                    "item_correct": correct if arm == "A" else True,
                    "over_reject": False,
                    "miss": (not correct) if arm == "A" and hold else False,
                    "hold_out_item": hold,
                }
            )
    summary = summarize(rows)
    assert "violation_rate_A" not in summary
    assert "discrimination_A" not in summary
    assert "overall_effectiveness" not in summary
    assert summary["n_tasks"] == 16
