"""Q2.6/Q2.7 controlled protocol faults using actual RunSession journals."""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import FrozenRecord, PublicTask, required_text
from research_loop.modular.modules.admission import AuditItem, ScientificState
from research_loop.modular.protocol_trace import verify_protocol_trace
from research_loop.modular.runtime import AuditAuthority, AuditVerifier, RunSession
from research_loop.ontology import ContractError

_VARIANTS = {"Q2.6": ("secondary_win", "maintenance", "late_pivot"),
             "Q2.7": ("missing_lock", "missing_execution", "missing_audit", "illegal_state")}
_KEYS = {"fixture-a": b"a" * 32, "fixture-b": b"b" * 32}


def protocol_injection(experiment_id: str, variant: str) -> dict:
    if variant not in _VARIANTS.get(experiment_id, ()):
        raise ContractError("protocol scenario variant is not registered")
    return {"fixture_only": True, "fault": variant,
            "fixture_notice": "controlled engineering fault, not a benchmark efficacy observation"}


@dataclass(frozen=True)
class ProtocolScenarioResult:
    model_payload: FrozenRecord
    response: FrozenRecord
    gate: FrozenRecord
    record: FrozenRecord


def run_protocol_scenario(experiment_id: str, variant: str, *, task: PublicTask,
                          frozen_controls: FrozenRecord, sidecar: Path,
                          broker: DockerExecutionBroker,
                          model: Callable[[FrozenRecord], FrozenRecord] | None = None) -> ProtocolScenarioResult:
    injection = protocol_injection(experiment_id, variant)
    controls = frozen_controls.data()
    if (set(controls) != {"task_digest", "budget_digest", "fixture_only"}
            or controls["task_digest"] != task.content_hash or controls["fixture_only"] is not True):
        raise ContractError("protocol scenario requires matching frozen fixture controls")
    required_text(controls["budget_digest"], "budget digest")
    objective = FrozenRecord.from_dict({"question": task.payload.data().get("research_question", task.payload.data().get("question", task.identity.task_id)),
        "primary_endpoint": "registered primary contrast", "success_rule": "primary evidence must qualify",
        "frozen_controls_digest": frozen_controls.content_hash})
    session = RunSession(task, package_digest="fixture-package", arm=default_compatibility("base").arm(["M1", "M2", "M3"]),
        objective=objective, slots=("final",), execution_limit=1, sidecar=sidecar,
        verifier=AuditVerifier(_KEYS), required_audit=("measurement",))
    execution_id = "unexecuted-fixture-evidence"
    if variant != "missing_execution":
        source = sidecar / "public-fixture.csv"
        source.write_text("x\n1\n", encoding="utf-8")
        execution = session.execute("print('fixture observation')", broker=broker,
            image="fixture@sha256:" + "a" * 64, inputs={"fixture": source})
        execution_id = execution.content_hash
        if variant not in {"missing_audit", "secondary_win", "maintenance", "late_pivot"}:
            receipts = [AuditAuthority(name, key).issue(identity=task.identity,
                objective_digest=objective.content_hash, execution_digest=execution_id,
                state=ScientificState("valid", "supported", "unknown", "explore"), outcome="positive",
                audit=[AuditItem("measurement", True, True)]) for name, key in _KEYS.items()]
            session.admit(execution_id, receipts)
    # The proposal is visibly separate from the current lock. Secondary success
    # and maintenance completion are never fabricated as primary evidence.
    proposed = objective.data()
    if variant == "secondary_win":
        proposed["primary_endpoint"] = "selected secondary contrast"
    elif variant == "late_pivot":
        proposed.update({"question": "post hoc easier question", "success_rule": "weakened after observation"})
    proposed_objective = FrozenRecord.from_dict(proposed)
    seen = []
    def callback(request: FrozenRecord) -> FrozenRecord:
        seen.append(request)
        if model is not None:
            return model(request)
        return FrozenRecord.from_dict({"objective_digest": proposed_objective.content_hash,
            "outcome": "proceed" if variant == "illegal_state" else "positive",
            "evidence_ids": [execution_id], "conclusion": "controlled fixture proposal",
            "programme_complete": variant == "maintenance"})
    response = session.invoke("final", callback, instruction="Evaluate this fixture under the unchanged primary objective. Secondary findings and maintenance progress do not complete it.",
        module_context=FrozenRecord.from_dict({"fixture": injection, "proposed_objective": proposed_objective.data(),
            "primary_result": "not_established" if experiment_id == "Q2.6" else "fixture_only",
            "proposed_revision_authorized": False, "callback": "engineering_default" if model is None else "injected"}))
    gate = session.finish(response)
    source_trace = sidecar / "trace.jsonl"
    source_before = source_trace.read_bytes()
    checked_trace = source_trace
    if variant == "missing_lock":
        # Offline replay removes the lock and rechains all remaining events so
        # rejection cannot be attributed merely to a stale chain checksum.
        checked_trace = sidecar / "missing-lock-replay.jsonl"
        events = [FrozenRecord(line).data() for line in source_trace.read_text(encoding="utf-8").splitlines()][1:]
        previous, rows = None, []
        for index, event in enumerate(events):
            event.update(sequence=index, previous=previous)
            record = FrozenRecord.from_dict(event)
            previous = record.content_hash
            rows.append(record.encoded)
        checked_trace.write_text("\n".join(rows) + "\n", encoding="utf-8")
    verification, rejection = None, None
    try:
        verification = verify_protocol_trace(checked_trace)
    except ContractError as exc:
        rejection = str(exc)
    if source_trace.read_bytes() != source_before:
        raise ContractError("protocol replay modified its original journal")
    return ProtocolScenarioResult(seen[0], response, gate, FrozenRecord.from_dict({
        "experiment_id": experiment_id, "variant": variant, "fixture_only": True,
        "frozen_controls_digest": frozen_controls.content_hash, "objective_digest": objective.content_hash,
        "original_trace": str(source_trace), "checked_trace": str(checked_trace),
        "protocol_verification": verification.data() if verification else None,
        "protocol_rejection": rejection, "receipt_admitted": verification is not None and gate.data()["decision"] != "blocked",
        "denominator": {"scheduled": 1, "model_calls": 1, "execution_attempts": session._attempts},
        "limitation": "fixture protocol enforcement only; scientific endpoint relevance and authorized version changes need independent review"}))
