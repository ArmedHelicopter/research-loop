"""Drives shipped error-catching renderer and scorer. Does not reimplement scoring."""

import json
from pathlib import Path

from experiments.error_catching.render_prompt import (
    load_task,
    render_auditor_prompt,
    render_executor_prompt,
    render_prompt,
)
from experiments.error_catching.score import load_label, score_pair

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "data" / "tasks" / "error_catching"
LABELS = ROOT / "data" / "labels" / "error_catching"


def _pairs():
    paths = sorted(TASKS.glob("EC*.json"))
    assert len(paths) >= 4
    for path in paths:
        yield load_task(path), load_label(LABELS / path.name)


def _executor_json(task, *, status: str, **extra) -> str:
    payload = {
        "status": status,
        "hypothesis_fates": {},
        "decision_rule": task["locked_rule"],
        "declared_program_complete": False,
        "notes": extra.pop("notes", ""),
    }
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


def test_at_least_four_known_bad_withdrawn_or_invalid():
    golds = []
    for task, label in _pairs():
        assert task["id"] == label["id"]
        assert "gold_status" not in task
        assert "gold_reason" not in task
        assert "violation_if" not in task
        assert label["gold_status"] in {"withdrawn", "invalid"}
        golds.append(label["gold_status"])
    assert "withdrawn" in golds
    assert "invalid" in golds


def test_prompt_omits_hidden_fields_and_matching_label_file():
    for task_path in sorted(TASKS.glob("EC*.json")):
        task = load_task(task_path)
        label_text = (LABELS / task_path.name).read_text(encoding="utf-8")
        prompts = [
            render_prompt(task, arm="executor"),
            render_prompt(task, arm="auditor"),
            render_executor_prompt(task),
            render_auditor_prompt(task),
            render_auditor_prompt(task, executor_output=_executor_json(task, status="proceed")),
        ]
        for prompt in prompts:
            assert "gold_status" not in prompt
            assert "gold_reason" not in prompt
            assert "violation_if" not in prompt
            assert '"gold_status"' not in prompt
            assert '"gold_reason"' not in prompt
            assert '"violation_if"' not in prompt
            assert label_text.strip() not in prompt


def test_prompts_include_written_record_and_not_labels_dir():
    task = load_task(TASKS / "EC001.json")
    exec_p = render_executor_prompt(task)
    aud_p = render_auditor_prompt(task)
    assert task["decision_record"]["status"] in exec_p
    assert task["decision_record"]["status"] in aud_p
    assert task["locked_rule"] in exec_p
    assert task["artifacts_summary"] in aud_p
    assert "data/labels" not in exec_p
    assert "data/labels" not in aud_p


def test_known_bad_proceed_is_not_clean():
    for task, label in _pairs():
        raw = _executor_json(task, status="proceed", notes="treat as success")
        result = score_pair(task, label, raw)
        assert result["clean"] is False
        assert result["treated_as_clean_success"] is True
        assert result["defect_caught"] is False
        assert "invalid_as_positive" in result["violations"]


def test_known_bad_complete_is_not_clean():
    for task, label in _pairs():
        raw = _executor_json(task, status="complete", notes="done")
        result = score_pair(task, label, raw)
        assert result["clean"] is False
        assert result["treated_as_clean_success"] is True
        assert "invalid_as_positive" in result["violations"]


def test_copying_planted_record_is_not_clean():
    for task, label in _pairs():
        raw = json.dumps(task["decision_record"], ensure_ascii=False)
        result = score_pair(task, label, raw)
        assert task["decision_record"]["status"] in {"proceed", "complete"}
        assert result["clean"] is False
        assert result["treated_as_clean_success"] is True


def test_auditor_invalid_catches_but_proceed_still_not_clean():
    task, label = next(_pairs())
    raw = _executor_json(task, status="proceed")
    auditor = json.dumps(
        {"verdict": "invalid", "failed_checks": ["status"], "notes": "block"},
        ensure_ascii=False,
    )
    result = score_pair(task, label, raw, auditor)
    assert result["defect_caught"] is True
    assert result["treated_as_clean_success"] is False
    assert result["clean"] is False


def test_executor_withdraw_is_a_catch():
    task = load_task(TASKS / "EC001.json")
    label = load_label(LABELS / "EC001.json")
    raw = _executor_json(task, status="withdrawn", notes="overlap")
    result = score_pair(task, label, raw)
    assert result["defect_caught"] is True
    assert result["treated_as_clean_success"] is False
    assert result["clean"] is True


def test_executor_invalid_is_a_catch():
    task = load_task(TASKS / "EC002.json")
    label = load_label(LABELS / "EC002.json")
    raw = _executor_json(task, status="invalid", notes="no new evidence")
    result = score_pair(task, label, raw)
    assert result["defect_caught"] is True
    assert result["clean"] is True
    assert result["treated_as_clean_success"] is False


def test_score_pair_has_no_overall_effectiveness():
    task, label = next(_pairs())
    result = score_pair(task, label, _executor_json(task, status="withdrawn"))
    assert "effectiveness" not in result
    assert "overall" not in result
    assert "overall_effectiveness" not in result


def test_unparseable_executor_is_not_clean_or_caught():
    task, label = next(_pairs())
    result = score_pair(task, label, "not-json")
    assert result["parse_ok"] is False
    assert result["clean"] is False
    assert result["defect_caught"] is False
