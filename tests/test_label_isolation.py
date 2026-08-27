import json
from pathlib import Path

from experiments.error_catching.render_prompt import (
    load_task as load_error_catching_task,
    render_auditor_prompt,
    render_executor_prompt,
)
from experiments.audit_contrast.render import (
    load_task as load_audit_task,
    render_arm_a,
    render_arm_b,
)
from experiments.true_lock.render import (
    load_task as load_true_lock_task,
    render_arm_a as render_true_lock_a,
    render_lock_prompt as render_true_lock_lock,
    render_observe_prompt as render_true_lock_obs,
)
from experiments.iteration_admission.render import (
    load_task as load_iteration_task,
    render_successor_prompt,
)
from experiments.sep_of_powers.render_prompt import load_task, render_prompt

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "data" / "tasks" / "pilot"
LABELS = ROOT / "data" / "labels" / "pilot"
EC_TASKS = ROOT / "data" / "tasks" / "error_catching"
EC_LABELS = ROOT / "data" / "labels" / "error_catching"
IT_TASKS = ROOT / "data" / "tasks" / "iteration"
IT_LABELS = ROOT / "data" / "labels" / "iteration"
AC_TASKS = ROOT / "data" / "tasks" / "audit_contrast"
AC_LABELS = ROOT / "data" / "labels" / "audit_contrast"
TL_TASKS = ROOT / "data" / "tasks" / "true_lock"
TL_LABELS = ROOT / "data" / "labels" / "true_lock"


def test_every_task_has_a_label():
    task_ids = {p.stem for p in TASKS.glob("T*.json")}
    label_ids = {p.stem for p in LABELS.glob("T*.json")}
    assert task_ids == label_ids
    assert task_ids


def test_prompts_do_not_contain_label_payloads():
    for task_path in TASKS.glob("T*.json"):
        task = load_task(task_path)
        label = (LABELS / task_path.name).read_text(encoding="utf-8")
        from experiments.sep_of_powers.render_prompt import render_lock_prompt, render_observe_prompt

        prompts = [
            render_prompt(task, arm="A"),
            render_prompt(task, arm="B"),
            render_lock_prompt(task),
            render_observe_prompt(task, committed_rule=task["locked_rule"]),
        ]
        for prompt in prompts:
            assert "gold_status" not in prompt
            assert "gold_reason" not in prompt
            assert "violation_if" not in prompt
            for fragment in (
                '"gold_status"',
                '"gold_reason"',
                '"violation_if"',
            ):
                assert fragment not in prompt
            # Full label file must not be embeddable from the prompt path.
            assert label.strip() not in prompt


def test_error_catching_every_task_has_a_label():
    task_ids = {p.stem for p in EC_TASKS.glob("EC*.json")}
    label_ids = {p.stem for p in EC_LABELS.glob("EC*.json")}
    assert task_ids == label_ids
    assert len(task_ids) >= 4


def test_error_catching_prompts_do_not_contain_label_payloads():
    for task_path in EC_TASKS.glob("EC*.json"):
        task = load_error_catching_task(task_path)
        label = (EC_LABELS / task_path.name).read_text(encoding="utf-8")
        prompts = [
            render_executor_prompt(task),
            render_auditor_prompt(task),
        ]
        for prompt in prompts:
            assert "gold_status" not in prompt
            assert "gold_reason" not in prompt
            assert "violation_if" not in prompt
            for fragment in (
                '"gold_status"',
                '"gold_reason"',
                '"violation_if"',
            ):
                assert fragment not in prompt
            assert label.strip() not in prompt


def test_iteration_every_task_has_a_label():
    task_ids = {p.stem for p in IT_TASKS.glob("I*.json")}
    label_ids = {p.stem for p in IT_LABELS.glob("I*.json")}
    assert task_ids == label_ids
    assert len(task_ids) >= 4


def test_iteration_prompts_do_not_contain_label_payloads():
    for task_path in IT_TASKS.glob("I*.json"):
        task = load_iteration_task(task_path)
        label = (IT_LABELS / task_path.name).read_text(encoding="utf-8")
        prompt = render_successor_prompt(task)
        assert "gold_" not in prompt
        assert "gold_status" not in prompt
        assert "gold_reason" not in prompt
        assert "gold_events" not in prompt
        assert "violation_if" not in prompt
        for fragment in (
            '"gold_status"',
            '"gold_reason"',
            '"gold_events"',
            '"violation_if"',
        ):
            assert fragment not in prompt
        assert label.strip() not in prompt


def test_audit_contrast_every_task_has_a_label():
    task_ids = {p.stem for p in AC_TASKS.glob("A*.json")}
    label_ids = {p.stem for p in AC_LABELS.glob("A*.json")}
    assert task_ids == label_ids
    assert len(task_ids) == 16


def test_audit_contrast_prompts_do_not_contain_label_payloads():
    for task_path in AC_TASKS.glob("A*.json"):
        task = load_audit_task(task_path)
        label = (AC_LABELS / task_path.name).read_text(encoding="utf-8")
        for prompt in (render_arm_a(task), render_arm_b(task)):
            assert "gold_status" not in prompt
            assert "gold_reason" not in prompt
            assert "violation_if" not in prompt
            assert label.strip() not in prompt


def test_true_lock_every_task_has_a_label():
    task_ids = {p.stem for p in TL_TASKS.glob("LCK*.json")}
    label_ids = {p.stem for p in TL_LABELS.glob("LCK*.json")}
    assert task_ids == label_ids
    assert len(task_ids) == 16


def test_true_lock_prompts_omit_gold_rule():
    for task_path in TL_TASKS.glob("LCK*.json"):
        task = load_true_lock_task(task_path)
        label_text = (TL_LABELS / task_path.name).read_text(encoding="utf-8")
        label = json.loads(label_text)
        prompts = [
            render_true_lock_a(task),
            render_true_lock_lock(task),
            render_true_lock_obs(task, committed_rule="x"),
        ]
        for prompt in prompts:
            assert "gold_status" not in prompt
            assert "gold_rule" not in prompt
            assert label["gold_rule"] not in prompt
            assert label_text.strip() not in prompt
            assert "locked_rule" not in prompt

