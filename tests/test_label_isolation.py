from pathlib import Path

from experiments.sep_of_powers.render_prompt import load_task, render_prompt

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "data" / "tasks" / "pilot"
LABELS = ROOT / "data" / "labels" / "pilot"


def test_every_task_has_a_label():
    task_ids = {p.stem for p in TASKS.glob("T*.json")}
    label_ids = {p.stem for p in LABELS.glob("T*.json")}
    assert task_ids == label_ids
    assert task_ids


def test_prompts_do_not_contain_label_payloads():
    for task_path in TASKS.glob("T*.json"):
        task = load_task(task_path)
        label = (LABELS / task_path.name).read_text(encoding="utf-8")
        for arm in ("A", "B"):
            prompt = render_prompt(task, arm=arm)
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
