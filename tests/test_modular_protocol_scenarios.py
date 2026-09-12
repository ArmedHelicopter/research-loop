import subprocess

import pytest

from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.experiments import ControllerInputs, registry, scenario
from research_loop.modular.protocol_trace import verify_protocol_trace
from research_loop.modular.runtime import verify_trace
from research_loop.modular.scenarios_protocol import run_protocol_scenario
from research_loop.ontology import ContractError


def task_for(benchmark):
    identity = DataIdentity(benchmark, "fixture", "fixture-group", "v1", "split", "train")
    if benchmark == "blade":
        return BladeAdapter().prepare(identity, {"task_id": "fixture", "dataset_id": "public",
            "research_question": "What changes?", "data_schema": [{"name": "x"}]})
    return DiscoveryBenchAdapter().prepare(identity, {"task_id": "fixture", "question": "What changes?",
        "source_kind": "synthetic", "difficulty": "fixture", "dataset": [{"name": "public", "columns": []}]})


def run(root, experiment, variant, benchmark="blade", model=None):
    root.mkdir()
    task = task_for(benchmark)
    controls = FrozenRecord.from_dict({"task_digest": task.content_hash, "budget_digest": "frozen", "fixture_only": True})
    broker = DockerExecutionBroker([root], runner=lambda *a, **k: subprocess.CompletedProcess(a[0], 0, b"fixture result", b""))
    return run_protocol_scenario(experiment, variant, task=task, frozen_controls=controls,
                                 sidecar=root, broker=broker, model=model)


@pytest.mark.parametrize("benchmark", ["blade", "discoverybench"])
@pytest.mark.parametrize(("experiment", "variant"), [(key, variant) for key in ("Q2.6", "Q2.7") for variant in registry()[key].variants])
def test_all_protocol_faults_block_actual_gate_or_receipt(tmp_path, benchmark, experiment, variant):
    result = run(tmp_path / variant, experiment, variant, benchmark)
    assert result.record.data()["receipt_admitted"] is False
    assert result.model_payload.data()["task"] == task_for(benchmark).data()
    assert result.gate.data()["candidate_digest"] == result.response.content_hash
    assert result.model_payload.data()["objective"]["primary_endpoint"] == "registered primary contrast"
    if variant == "missing_lock":
        # Runtime had a legitimate complete sequence; only the controlled
        # missing-lock replay fails, leaving the original journal intact.
        assert result.gate.data()["decision"] == "proceed"
        assert "objective lock" in result.record.data()["protocol_rejection"]
        assert verify_protocol_trace(tmp_path / variant / "trace.jsonl").data()["decision"] == "proceed"
    else:
        assert result.gate.data()["decision"] == "blocked"
    inputs = ControllerInputs(FrozenRecord.from_dict({"task": "fixture"}), FrozenRecord.from_dict({}), FrozenRecord.from_dict({"calls": 1}))
    assert scenario(registry()[experiment], variant, inputs=inputs).data()["controller_input"]["fault"] == variant


def test_q26_actual_model_can_preserve_unknown_without_accepting_the_proposed_pivot(tmp_path):
    def model(request):
        return FrozenRecord.from_dict({"objective_digest": FrozenRecord.from_dict(request.data()["objective"]).content_hash,
            "outcome": "unknown", "evidence_ids": [], "conclusion": "The primary result is not established.", "programme_complete": False})
    result = run(tmp_path / "unknown", "Q2.6", "late_pivot", model=model)
    assert result.gate.data()["decision"] == "unknown"
    assert result.record.data()["protocol_verification"]["scientific_audit_authenticated"] is False


def rechain(path, rows):
    previous, lines = None, []
    for index, row in enumerate(rows):
        row.update(sequence=index, previous=previous)
        item = FrozenRecord.from_dict(row)
        previous = item.content_hash
        lines.append(item.encoded)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.mark.parametrize("fault", ["execution", "audit", "request", "illegal_state", "candidate_swap", "late_event"])
def test_protocol_replay_rejects_rechained_missing_steps_and_false_terminal_decisions(tmp_path, fault):
    run(tmp_path / "source", "Q2.7", "missing_lock")
    original = tmp_path / "source" / "trace.jsonl"
    rows = [FrozenRecord(line).data() for line in original.read_text(encoding="utf-8").splitlines()]
    if fault == "execution":
        rows = [row for row in rows if row["stage"] not in {"execution_request", "execution_result"}]
    elif fault == "audit":
        rows = [row for row in rows if row["stage"] not in {"scientific_audit_inputs", "scientific_admission"}]
    elif fault == "request":
        rows = [row for row in rows if row["stage"] != "model_request"]
    elif fault == "illegal_state":
        rows[-1]["data"]["decision"] = "programme_complete"
    elif fault == "candidate_swap":
        rows[-1]["data"]["candidate_digest"] = "different-response"
    else:
        rows.append(dict(rows[1]))
    replay = tmp_path / "replay.jsonl"
    rechain(replay, rows)
    assert verify_trace(replay).data()["events"] == len(rows)
    with pytest.raises(ContractError):
        verify_protocol_trace(replay)


def test_replay_is_not_a_signature_or_scientific_truth_verifier(tmp_path):
    run(tmp_path / "source", "Q2.7", "missing_lock")
    proof = verify_protocol_trace(tmp_path / "source" / "trace.jsonl").data()
    assert proof["structurally_verified"] and not proof["scientific_audit_authenticated"]
    assert "scientific truth" in proof["limitation"]
