"""Adversarial checks for the offline prediction fixture custody seam."""
from __future__ import annotations

import json
import os

import pytest

from research_loop.modular.prediction_scenario_artifacts import verify_prediction_scenario_artifacts
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.scenarios_predictions import run_prediction_scenario
from research_loop.ontology import ContractError
from tests.test_modular_prediction_scenarios import controls, public_task


def _run(tmp_path, callback=None):
    task = public_task("blade"); root = tmp_path / "attempt"
    result = run_prediction_scenario("Q3.2", "separate", task=task, frozen_controls=controls(task),
                                     artifact_root=root, plan_callback=callback)
    return task, root, result


def test_reader_returns_only_after_original_callback_records_and_never_replays(tmp_path):
    seen = []
    task, root, result = _run(tmp_path, lambda payload: seen.append(payload.content_hash) or {"ordinary": "raw"})
    original = {name: (root / name).read_bytes() for name in ("prediction-scenario-artifacts.jsonl", "prediction-scenario-terminal.json", "prediction-scenario-closure.json")}
    check = verify_prediction_scenario_artifacts(root, task=task, controls=controls(task), experiment_id="Q3.2", variant="separate")
    assert check.data()["callback_count"] == 3 and len(seen) == 3
    assert all((root / name).read_bytes() == raw for name, raw in original.items())
    assert result.callback_responses[0].data()["response"] == {"ordinary": "raw"}


def test_callback_failure_is_durable_and_reader_does_not_accept_completion(tmp_path):
    task = public_task("discovery"); root = tmp_path / "failed"
    with pytest.raises(RuntimeError):
        run_prediction_scenario("Q3.1", "mechanism", task=task, frozen_controls=controls(task), artifact_root=root,
                                plan_callback=lambda _payload: (_ for _ in ()).throw(RuntimeError("fixture callback failed")))
    assert verify_prediction_scenario_artifacts(root, task=task, controls=controls(task), experiment_id="Q3.1",
                                                variant="mechanism", complete=False).data()["status"] == "failed"
    with pytest.raises(ContractError):
        verify_prediction_scenario_artifacts(root, task=task, controls=controls(task), experiment_id="Q3.1", variant="mechanism")


@pytest.mark.parametrize("attack", ["extra", "partial", "wrong_subject", "link"])
def test_inventory_partial_subject_and_link_attacks_are_rejected(tmp_path, attack):
    task, root, _ = _run(tmp_path)
    journal = root / "prediction-scenario-artifacts.jsonl"
    if attack == "extra":
        (root / "unregistered.txt").write_text("x", encoding="utf-8")
    elif attack == "partial":
        with journal.open("ab") as stream: stream.write(b'{"partial":')
    elif attack == "wrong_subject":
        # Coherently replace the visible task field in a parsed row; the original
        # terminal/closure bindings still reject it rather than trusting hashes.
        rows = journal.read_text(encoding="utf-8").splitlines(); row = json.loads(rows[1]); row["data"]["task"]["identity"]["task_id"] = "other-task"
        rows[1] = FrozenRecord.from_dict(row).encoded
        journal.write_text("\n".join(rows) + "\n", encoding="utf-8")
    else:
        target = tmp_path / "outside"; target.write_text("x", encoding="utf-8")
        try: os.symlink(target, root / "linked")
        except OSError: pytest.skip("link creation unavailable")
    with pytest.raises(ContractError):
        verify_prediction_scenario_artifacts(root, task=task, controls=controls(task), experiment_id="Q3.2", variant="separate")
