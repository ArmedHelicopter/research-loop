import subprocess

import pytest

from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.experiments import ControllerInputs, registry, scenario
from research_loop.modular.protocol_trace import verify_protocol_trace
from research_loop.modular.modules.admission import AuditItem, ScientificState
from research_loop.modular.polarity_goal_panel_drivers import admission_subject, freeze_polarity_goal_bundle
from research_loop.modular.runtime import AuditAuthority, verify_trace
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


def typed_q26_bundle(task):
    """Create the caller-owned material required by the production Q2.6 path.

    This deliberately does not reuse the protocol fixture.  The fixture's
    controller input is an engineering fault record and must remain rejected
    by the typed production driver.
    """
    keys = {"typed-a": b"a" * 32, "typed-b": b"b" * 32}

    def signed_item(experiment, variant):
        public = {"source_id": task.identity.group_id,
                  "observation": f"Public source material for {experiment} {variant}."}
        locked = {"objective": "registered primary contrast"}
        proposal = {"source_id": task.identity.group_id,
                    "statement": "The public report describes the registered endpoint."}
        subject = admission_subject(task, experiment_id=experiment, public_material=public,
                                    **({"locked_objective": locked, "proposal": proposal}
                                       if experiment == "Q2.6" else {}))
        receipts = [AuditAuthority(name, key).issue_material(
            identity=task.identity, subject_digest=subject.content_hash,
            execution_success=True,
            state=ScientificState("valid", "supported", "unknown", "explore"),
            outcome="positive", audit=[AuditItem("measurement", True, True)]).data()
            for name, key in keys.items()]
        item = {"public_material": public, "admission_receipts": receipts}
        if experiment == "Q2.6":
            item.update({"locked_objective": locked, "proposal": proposal})
        return item

    return freeze_polarity_goal_bundle(
        task,
        q25={name: signed_item("Q2.5", name)
             for name in ("invalid_positive", "invalid_negative", "valid_negative")},
        q26={name: signed_item("Q2.6", name)
             for name in ("secondary_win", "maintenance", "late_pivot")},
    )


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
        if experiment == "Q2.6":
            specific = "programme_completion_unauthorized" if variant == "maintenance" else "objective_drift"
            assert specific in result.gate.data()["reasons"]
    old_inputs = ControllerInputs(FrozenRecord.from_dict({"task": "fixture"}), FrozenRecord.from_dict({}), FrozenRecord.from_dict({"calls": 1}))
    if experiment == "Q2.6":
        # The protocol fault fixture remains useful for replay engineering, but
        # is not caller material accepted by the production goal-lock driver.
        with pytest.raises(ContractError, match="typed polarity/goal caller material is required"):
            scenario(registry()[experiment], variant, inputs=old_inputs)
        task = task_for(benchmark)
        typed = typed_q26_bundle(task)
        typed_inputs = ControllerInputs(FrozenRecord.from_dict(task.data()), typed,
                                        FrozenRecord.from_dict({"calls": 2}))
        compiled = scenario(registry()[experiment], variant, inputs=typed_inputs)
        controller = compiled.data()["controller_input"]
        assert controller["schema"] == "polarity-goal-controller-v2"
        assert controller["bundle"]["q26"][variant]["public_material"]["source_id"] == task.identity.group_id
        assert "fixture_only" not in FrozenRecord.from_dict(controller).encoded
    else:
        # Legacy replay fixtures remain independent of the typed production path.
        with pytest.raises(ContractError, match="P0|typed"):
            scenario(registry()[experiment], variant, inputs=old_inputs)


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


@pytest.mark.parametrize("fault", ["execution", "audit", "request", "illegal_state", "candidate_swap", "late_event", "fake_envelope", "fake_audits", "incomplete_unknown"])
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
    elif fault == "fake_envelope":
        result = next(row for row in rows if row["stage"] == "execution_result")
        result["data"]["receipt"] = {"status": "succeeded"}
    elif fault == "fake_audits":
        audit = next(row for row in rows if row["stage"] == "scientific_audit_inputs")
        audit["data"]["receipts"] = [{}, {}]
    elif fault == "incomplete_unknown":
        response = next(row for row in rows if row["stage"] == "model_response")
        candidate = response["data"]["response"]
        candidate["outcome"] = "unknown"
        del candidate["conclusion"]
        del candidate["evidence_ids"]
        rows[-1]["data"].update(decision="unknown", scientific_validated=False,
                              candidate_digest=FrozenRecord.from_dict(candidate).content_hash)
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


def test_terminal_unavailable_execution_cannot_be_followed_by_model_calls(tmp_path):
    from research_loop.modular.benchmarks.execution import ExecutionReceipt
    run(tmp_path / "source", "Q2.7", "missing_lock")
    source = tmp_path / "source" / "trace.jsonl"
    rows = [FrozenRecord(line).data() for line in source.read_text(encoding="utf-8").splitlines()]
    rows = [row for row in rows if row["stage"] not in {"scientific_audit_inputs", "scientific_admission"}]
    result = next(row["data"] for row in rows if row["stage"] == "execution_result")
    envelope = result["receipt"]
    envelope["status"] = "unavailable"
    envelope["record"] = {"status": "unavailable", "reason": "fixture daemon unavailable"}
    receipt = ExecutionReceipt.parse(envelope)
    result.update(execution_digest=receipt.content_hash, status=receipt.status, record=receipt.record.data())
    response = next(row["data"]["response"] for row in rows if row["stage"] == "model_response")
    response.update(outcome="unknown", evidence_ids=[])
    rows[-1]["data"].update(decision="unknown", scientific_validated=False,
                          candidate_digest=FrozenRecord.from_dict(response).content_hash)
    replay = tmp_path / "unavailable.jsonl"
    rechain(replay, rows)
    with pytest.raises(ContractError, match="terminal external failure"):
        verify_protocol_trace(replay)
