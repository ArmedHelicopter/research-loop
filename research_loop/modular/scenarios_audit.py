"""Fixture-only Q2.4/Q2.5 runs through the signed dual-audit gate.

The runner receives an already prepared public task, frozen controls, and an
engineering-only broker.  It never loads benchmark data, labels, gold answers,
or a model.  Its synthetic ground truth is retained by the controller only.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import FrozenRecord, PublicTask, required_text
from research_loop.modular.modules.admission import AuditItem, ScientificState
from research_loop.modular.runtime import AuditAuthority, AuditVerifier, RunSession, verify_trace
from research_loop.ontology import ContractError


_VARIANTS = {
    "Q2.4": frozenset(("one_fail", "both_fail", "disagree", "same_wrong")),
    "Q2.5": frozenset(("invalid_positive", "invalid_negative", "valid_negative")),
}
_KEYS = {"fixture-audit-a": b"a" * 32, "fixture-audit-b": b"b" * 32}


@dataclass(frozen=True)
class AuditScenarioResult:
    experiment_id: str
    variant: str
    gate: FrozenRecord
    trace: FrozenRecord
    audit_receipts: tuple[FrozenRecord, ...]
    model_payload: FrozenRecord
    record: FrozenRecord


def audit_injection(experiment_id: str, variant: str) -> Mapping[str, Any]:
    _validate(experiment_id, variant)
    return {"fixture_only": True, "fixture_notice": "engineering fixture; not a benchmark measurement",
            "auxiliary": {"audit_pair_variant": variant, "controller_ground_truth_private": experiment_id == "Q2.4" and variant == "same_wrong"}}


def run_audit_scenario(experiment_id: str, variant: str, *, task: PublicTask,
                       frozen_controls: FrozenRecord, sidecar: Path,
                       broker: DockerExecutionBroker,
                       model: Callable[[FrozenRecord], FrozenRecord] | None = None) -> AuditScenarioResult:
    """Run one bounded, signed audit fixture and preserve its real trace.

    ``same_wrong`` intentionally demonstrates a residual limitation: two valid
    signatures can agree on a fixture judgment that the controller marks wrong.
    That controller-only fact never enters the solver request.
    """
    _validate(experiment_id, variant)
    controls = frozen_controls.data()
    if set(controls) != {"task_digest", "budget_digest", "fixture_only"} or controls["task_digest"] != task.content_hash or controls["fixture_only"] is not True:
        raise ContractError("audit scenario requires matching frozen fixture controls")
    required_text(controls["budget_digest"], "budget digest")
    if sidecar.exists() and any(sidecar.iterdir()):
        raise ContractError("audit fixture sidecar must be unused")
    objective = FrozenRecord.from_dict({"question": _question(task), "primary_endpoint": "fixture audit gate",
                                         "frozen_controls_digest": frozen_controls.content_hash})
    session = RunSession(task, package_digest="fixture-package", arm=default_compatibility("base").arm(["M1", "M2", "M3"]),
                         objective=objective, slots=("final",), execution_limit=1, sidecar=sidecar,
                         verifier=AuditVerifier(_KEYS), required_audit=("measurement",))
    public_input = sidecar / "public-fixture.csv"
    public_input.write_text("x\n1\n", encoding="utf-8")
    execution = session.execute("print('fixture execution')", broker=broker,
                                image="fixture@sha256:" + "a" * 64, inputs={"public": public_input})
    receipts, outcome, private_truth = _receipts(experiment_id, variant, session, execution.content_hash)
    admission_error = None
    try:
        admission = session.admit(execution.content_hash, list(receipts))
    except ContractError as exc:
        admission, admission_error = None, str(exc)
    seen: list[FrozenRecord] = []
    def engineering_callback(request: FrozenRecord) -> FrozenRecord:
        seen.append(request)
        if model is not None:
            return model(request)
        return _candidate(session, execution.content_hash, outcome)
    session.invoke("final", engineering_callback, instruction="Report only the fixture evidence.",
                   module_context=FrozenRecord.from_dict({"fixture_only": True, "controls_digest": frozen_controls.content_hash,
                                                           "callback": "engineering_default" if model is None else "injected"}))
    gate = session.finish(_candidate(session, execution.content_hash, outcome))
    trace = verify_trace(sidecar / "trace.jsonl")
    record = FrozenRecord.from_dict({"fixture_only": True, "controls": controls,
        "execution_digest": execution.content_hash, "audit_receipt_digests": [item.content_hash for item in receipts],
        "admission_error": admission_error, "admission": admission.data() if admission else None,
        "gate": gate.data(), "denominator": {"scheduled": 1, "execution_attempts": 1, "model_calls": 1, "finalized": 1},
        "residual_limitation": {"fixture_controller_ground_truth": "scientifically_wrong" if private_truth else "not_injected",
                                "false_admission_observed": variant == "same_wrong" and gate.data()["decision"] == "proceed",
                                "meaning": "signature agreement authenticates issuers, not scientific truth"} if variant == "same_wrong" else None})
    return AuditScenarioResult(experiment_id, variant, gate, trace, receipts, seen[0], record)


def _receipts(experiment_id: str, variant: str, session: RunSession, execution_digest: str) -> tuple[tuple[FrozenRecord, ...], str, bool]:
    if experiment_id == "Q2.4":
        outcome, state = "positive", ScientificState("valid", "supported", "unknown", "explore")
        if variant == "one_fail":
            audits = ([AuditItem("measurement", True, True)], [AuditItem("measurement", True, False)])
        elif variant == "both_fail":
            audits = ([AuditItem("measurement", True, False)],) * 2
        elif variant == "disagree":
            first = AuditAuthority("fixture-audit-a", _KEYS["fixture-audit-a"]).issue(identity=session.task.identity, objective_digest=session.objective.content_hash, execution_digest=execution_digest, state=state, outcome="positive", audit=[AuditItem("measurement", True, True)])
            second = AuditAuthority("fixture-audit-b", _KEYS["fixture-audit-b"]).issue(identity=session.task.identity, objective_digest=session.objective.content_hash, execution_digest=execution_digest, state=ScientificState("valid", "refuted", "unknown", "explore"), outcome="negative", audit=[AuditItem("measurement", True, True)])
            return (first, second), outcome, False
        else:
            audits = ([AuditItem("measurement", True, True)],) * 2
        wrong = variant == "same_wrong"
    else:
        outcome = "negative" if variant.endswith("negative") else "positive"
        validity = "valid" if variant == "valid_negative" else "invalid"
        state = ScientificState(validity, "refuted" if outcome == "negative" else "supported", "unknown", "explore")
        audits, wrong = ([AuditItem("measurement", True, True)],) * 2, False
    receipts = tuple(AuditAuthority(name, _KEYS[name]).issue(identity=session.task.identity, objective_digest=session.objective.content_hash,
        execution_digest=execution_digest, state=state, outcome=outcome, audit=list(audits[index])) for index, name in enumerate(_KEYS))
    return receipts, outcome, wrong


def _candidate(session: RunSession, execution_digest: str, outcome: str) -> FrozenRecord:
    return FrozenRecord.from_dict({"objective_digest": session.objective.content_hash, "outcome": outcome,
        "evidence_ids": [execution_digest], "conclusion": "engineering fixture only", "programme_complete": False})


def _question(task: PublicTask) -> str:
    payload = task.payload.data()
    return str(payload.get("research_question", payload.get("question", task.identity.task_id)))


def _validate(experiment_id: str, variant: str) -> None:
    if experiment_id not in _VARIANTS or variant not in _VARIANTS[experiment_id]:
        raise ContractError("audit scenario variant is not registered")
