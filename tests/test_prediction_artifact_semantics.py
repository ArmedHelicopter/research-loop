"""Coherently resealed attacks use caller-owned inputs and intact full copies."""
import hashlib
import json
import shutil

import pytest

from research_loop.modular import scenarios_predictions as scenario
from research_loop.modular import prediction_scenario_artifacts as artifacts
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError
from tests.test_modular_prediction_scenarios import public_task, controls

JOURNAL = "prediction-scenario-artifacts.jsonl"
TERMINAL = "prediction-scenario-terminal.json"
CLOSURE = "prediction-scenario-closure.json"


def write(path, body):
    path.write_bytes((FrozenRecord.from_dict(body).encoded + "\n").encode())


def snapshot(root):
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.iterdir()}


def verify(root, task, *, complete=True, experiment="Q3.2", variant="separate"):
    before = snapshot(root)
    try:
        return artifacts.verify_prediction_scenario_artifacts(root, task=task, controls=controls(task),
            experiment_id=experiment, variant=variant, complete=complete)
    finally:
        assert snapshot(root) == before


def reseal(root, rows, terminal, closure):
    """Rehash all journal links, parent links, file inventory and outer closure."""
    old_to_new = {}
    previous = None
    for index, (old_hash, row) in enumerate(rows):
        row["sequence"], row["previous"] = index, previous
        row["parents"] = [old_to_new.get(p, p) for p in row["parents"]]
        previous = FrozenRecord.from_dict(row).content_hash
        old_to_new[old_hash] = previous
    (root / JOURNAL).write_bytes(b"".join((FrozenRecord.from_dict(r).encoded + "\n").encode() for _, r in rows))
    terminal["entry_count"] = len(rows)
    write(root / TERMINAL, terminal)
    closure["terminal"] = terminal
    closure["files"] = {name: {"sha256": hashlib.sha256((root / name).read_bytes()).hexdigest(),
        "bytes": len((root / name).read_bytes())} for name in (JOURNAL, TERMINAL)}
    write(root / CLOSURE, closure)


@pytest.mark.parametrize("attack", ["request_subject", "source", "attempt", "erase_operations", "raw",
    "trace", "outcome", "result_digest", "missing_parent", "registry_classification", "row_module"])
def test_rehashed_forgery_is_rejected_from_independent_input(tmp_path, attack):
    task = public_task("blade")
    # Preserve independent inputs before the producer creates any artifact.
    write(tmp_path / "independent-inputs.json", {"task": task.data(), "controls": controls(task).data(),
        "experiment_id": "Q3.2", "variant": "separate"})
    original, target = tmp_path / "original", tmp_path / "attack"
    scenario.run_prediction_scenario("Q3.2", "separate", task=task, frozen_controls=controls(task),
        artifact_root=original, plan_callback=lambda p: {"ordinary": "response"})
    shutil.copytree(original, target)
    assert verify(target, task).data()["semantic_completion_verified"]
    records = [FrozenRecord(line) for line in (target / JOURNAL).read_text().splitlines()]
    rows = [(r.content_hash, r.data()) for r in records]
    terminal = json.loads((target / TERMINAL).read_bytes())
    closure = json.loads((target / CLOSURE).read_bytes())
    def row(kind):
        return next(body for _, body in rows if body["kind"] == kind)
    if attack == "request_subject":
        row("callback_request")["data"]["task"]["identity"]["task_id"] = "unrelated"
    elif attack == "source":
        unrelated = tmp_path / "unrelated.py"
        unrelated.write_bytes(b"# unrelated producer\n")
        fake = {"path": str(unrelated.resolve()), "sha256": hashlib.sha256(unrelated.read_bytes()).hexdigest(), "bytes": unrelated.stat().st_size}
        row("inputs")["data"]["sources"] = [fake] * len(row("inputs")["data"]["sources"])
        closure["inputs"] = row("inputs")["data"]
        terminal["input_digest"] = row("attempt")["data"]["input_digest"] = FrozenRecord.from_dict(closure["inputs"]).content_hash
    elif attack == "attempt":
        row("attempt")["data"].update(task_digest="wrong", variant="joint", run_id="0" * 32)
    elif attack == "erase_operations":
        rows = rows[:2]
    elif attack == "raw":
        row("callback_raw")["data"]["value"] = {"ordinary": "changed"}
    elif attack == "trace":
        row("mechanism_trace")["data"]["events"].append({"event": "scientific_validated", "value": True})
    elif attack == "outcome":
        row("outcome")["data"].update(task_digest="wrong", variant="joint", fixture_only=False)
        terminal["result"] = row("outcome")["data"]
        terminal["result_digest"] = FrozenRecord.from_dict(terminal["result"]).content_hash
    elif attack == "result_digest":
        terminal["result_digest"] = "0" * 64
    elif attack == "missing_parent":
        row("callback_request")["parents"] = []
    elif attack == "registry_classification":
        event = next(b for _, b in rows if b["kind"] == "registry_event" and b["data"]["event"] == "outcome")
        event["data"]["classifications"] = {k: "consistent" for k in event["data"]["classifications"]}
    else:
        row("callback_request")["module"] = "M9"
    reseal(target, rows, terminal, closure)
    with pytest.raises(ContractError):
        verify(target, task)


@pytest.mark.parametrize("invalid", ["invalid JSON-compatible scalar", [1, 2], 17])
def test_invalid_callback_value_survives_before_adaptation_failure(tmp_path, invalid):
    task, root = public_task("discovery"), tmp_path / "invalid"
    with pytest.raises(ContractError):
        scenario.run_prediction_scenario("Q3.1", "mechanism", task=task, frozen_controls=controls(task),
            artifact_root=root, plan_callback=lambda p: invalid)
    rows = [json.loads(line) for line in (root / JOURNAL).read_text().splitlines()]
    assert next(r for r in rows if r["kind"] == "callback_raw")["data"]["value"] == invalid
    assert verify(root, task, complete=False, experiment="Q3.1", variant="mechanism").data()["status"] == "failed"


def test_post_callback_mechanism_failure_closes_exact_prefix(tmp_path, monkeypatch):
    task, root = public_task("blade"), tmp_path / "late-failure"
    original = scenario._record_unknown_outcomes
    def fail(*args):
        raise RuntimeError("injected mechanism failure")
    monkeypatch.setattr(scenario, "_record_unknown_outcomes", fail)
    with pytest.raises(RuntimeError):
        scenario.run_prediction_scenario("Q3.2", "separate", task=task, frozen_controls=controls(task), artifact_root=root)
    monkeypatch.setattr(scenario, "_record_unknown_outcomes", original)
    assert verify(root, task, complete=False).data()["callback_count"] == 3


def test_partial_write_is_retained_and_cannot_reach_next_callback(tmp_path, monkeypatch):
    task, root, seen = public_task("blade"), tmp_path / "partial", []
    original = artifacts.PredictionScenarioArtifactWriter._persist
    def fail(writer, record):
        if record.data()["kind"] == "callback_raw":
            with (root / JOURNAL).open("ab") as stream:
                stream.write(b'{"partial":')
            raise OSError("injected partial write")
        return original(writer, record)
    monkeypatch.setattr(artifacts.PredictionScenarioArtifactWriter, "_persist", fail)
    with pytest.raises(OSError):
        scenario.run_prediction_scenario("Q3.2", "separate", task=task, frozen_controls=controls(task),
            artifact_root=root, plan_callback=lambda p: seen.append(p) or None)
    assert len(seen) == 1 and b'{"partial":' in (root / JOURNAL).read_bytes()
    with pytest.raises(ContractError):
        verify(root, task, complete=False)


def test_real_registry_freezes_and_outcomes_are_registered_once_per_plan(tmp_path):
    task = public_task("blade")
    for variant, plan_count in (("joint", 1), ("separate", 3)):
        root = tmp_path / variant
        scenario.run_prediction_scenario("Q3.2", variant, task=task, frozen_controls=controls(task), artifact_root=root)
        events = [json.loads(line)["data"] for line in (root / JOURNAL).read_text().splitlines()
                  if json.loads(line)["kind"] == "registry_event"]
        assert sum(e["event"] == "freeze" for e in events) == plan_count
        assert sum(e["event"] == "outcome" for e in events) == plan_count
        assert all(set(e["classifications"].values()) == {"unknown"} for e in events if e["event"] == "outcome")


@pytest.mark.parametrize("experiment,variant,port,module", [
    ("Q5.2", "negative_control", "assess_feasibility", "M7"),
    ("Q5.3", "same_mechanism", "deduplicate_mechanism_predictions", "M4"),
    ("Q5.3", "title", "deduplicate_titles", "M4"),
    ("Q5.4", "preregistered_cost", "select_claimed_diagnostic", "M7"),
])
def test_actual_mechanism_output_full_copy_and_coherent_forgery(tmp_path, experiment, variant, port, module):
    task, original, target = public_task("discovery"), tmp_path / "original", tmp_path / "attack"
    write(tmp_path / "independent-inputs.json", {"task": task.data(), "controls": controls(task).data(),
        "experiment_id": experiment, "variant": variant})
    scenario.run_prediction_scenario(experiment, variant, task=task, frozen_controls=controls(task), artifact_root=original)
    shutil.copytree(original, target)
    assert verify(target, task, experiment=experiment, variant=variant).data()["semantic_completion_verified"]
    records = [FrozenRecord(line) for line in (target / JOURNAL).read_text().splitlines()]
    rows = [(r.content_hash, r.data()) for r in records]
    output = next(body for _, body in rows if body["kind"] == "mechanism_output" and body["data"]["port"] == port)
    assert output["module"] == module and output["data"]["inputs"]
    output["data"]["result"] = {"forged": "result"}
    reseal(target, rows, json.loads((target / TERMINAL).read_bytes()), json.loads((target / CLOSURE).read_bytes()))
    with pytest.raises(ContractError):
        verify(target, task, experiment=experiment, variant=variant)
