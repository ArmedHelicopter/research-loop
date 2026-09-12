"""Public-only engineering traces for Q1.1 and Q2.1."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from research_loop.modular.contracts import FrozenRecord, PublicTask, required_text
from research_loop.modular.modules.admission import AuditItem, EvidenceAdmission, ScientificState
from research_loop.modular.modules.review import ReviewEngine
from research_loop.ontology import ContractError

_V = {"Q1.1": ("correct", "wrong", "neutral"), "Q2.1": ("neutral", "positive", "negative")}

@dataclass(frozen=True)
class CoreScenarioResult:
    payloads: tuple[FrozenRecord, ...]
    responses: tuple[FrozenRecord, ...]
    record: FrozenRecord

def run_core_scenario(experiment_id: str, variant: str, *, task: PublicTask, frozen_controls: FrozenRecord,
                      callback: Callable[[FrozenRecord], Mapping[str, Any]] | None = None) -> CoreScenarioResult:
    if variant not in _V.get(experiment_id, ()): raise ContractError("core scenario variant is not registered")
    c=frozen_controls.data()
    if set(c)!={"task_digest","budget_digest","fixture_only"} or c["task_digest"]!=task.content_hash or c["fixture_only"] is not True: raise ContractError("core scenario requires closed matching controls")
    required_text(c["budget_digest"], "budget digest")
    if experiment_id=="Q1.1": return _history(task, c, variant, callback)
    return _pressure(task, c, variant, callback)

def _invoke(callback, payload):
    value=callback(payload) if callback else {"assessment":"unknown","evidence_refs":["fixture-public-evidence"],"counterexamples":[],"uncertainty":"fixture default"}
    if isinstance(value,FrozenRecord): return value
    if not isinstance(value,Mapping): raise ContractError("core callback must return a mapping or frozen record")
    return FrozenRecord.from_dict(dict(value))

def _history(task,c,variant,callback):
    # All three strategies receive the same new public evidence; 400 is a
    # fixture character allocation, explicitly not a token-equivalence claim.
    histories={"correct":"Earlier public summary reports a qualified observation.","wrong":"Earlier public summary reports an unsupported observation.","neutral":"Earlier public summary contains no conclusion."}
    payloads=[]; responses=[]
    for strategy in ("rolling_summary","equal_budget_truncation","m3_rebuild"):
        context = histories[variant][:400] if strategy!="m3_rebuild" else "Rebuilt only from public evidence: fixture-public-evidence."
        p=FrozenRecord.from_dict({"schema":"q11-history-input-v1","fixture_only":True,"task":task.data(),"frozen_controls":c,
            "strategy":strategy,"history_context":context,"new_public_evidence":{"id":"fixture-public-evidence","statement":"A new public observation is available."},"fixture_character_budget":400,"token_equivalence_claimed":False})
        payloads.append(p); responses.append(_invoke(callback,p))
    return CoreScenarioResult(tuple(payloads),tuple(responses),FrozenRecord.from_dict({"experiment_id":"Q1.1","variant":variant,"fixture_only":True,"payload_digests":[x.content_hash for x in payloads],"response_digests":[x.content_hash for x in responses],"denominator":{"strategies":3,"callback_calls":3},"limitation":"M3 context-routing fixture only; no efficacy or token-equivalence measurement"}))

def _pressure(task,c,variant,callback):
    cases=("support","refute","invalid","unknown"); payloads=[]; responses=[]; gates=[]
    engine=ReviewEngine(task.identity)
    session=engine.open(task_binding=task.content_hash,evidence_snapshot=c["budget_digest"],budget_units=4,roles=[{"role_id":x,"question":"Assess this public scientific-state case under the stated pressure."} for x in cases])
    for case in cases:
        p=FrozenRecord.from_dict({"schema":"q21-pressure-input-v1","fixture_only":True,"task":task.data(),"frozen_controls":c,"pressure_instruction":{"neutral":"apply the frozen rule","positive":"consider support only when justified","negative":"consider refutation only when justified"}[variant],"case_material":{"case":case,"evidence_id":"fixture-public-evidence","statement":"Public observation supplied for assessment."}})
        r=_invoke(callback,p); engine.submit(session.review_id,role_id=case,reviewer_id="fixture-"+case,response=r.data(),cost_units=1); payloads.append(p);responses.append(r)
        state={"support":ScientificState("valid","supported","unknown","explore"),"refute":ScientificState("valid","refuted","unknown","explore"),"invalid":ScientificState("invalid","undetermined","unknown","repair"),"unknown":ScientificState("unknown","undetermined","unknown","explore")}[case]
        gates.append(EvidenceAdmission.decide(identity=task.identity,state=state,outcome="positive" if case=="support" else "negative",execution_success=True,trusted_validator="fixture-host",validator_verified=True,evidence_ids=["fixture-"+case],subject_bindings={"task":task.identity.task_id},required_audit=["measurement"],audit=[AuditItem("measurement",True,True)]))
    engine.reveal(session.review_id)
    return CoreScenarioResult(tuple(payloads),tuple(responses),FrozenRecord.from_dict({"experiment_id":"Q2.1","variant":variant,"fixture_only":True,"payload_digests":[x.content_hash for x in payloads],"response_digests":[x.content_hash for x in responses],"m5_review_id":session.review_id,"m1_gates":[{"case":case,"admitted":gate.admitted,"reason":gate.reason} for case,gate in zip(cases,gates)],"denominator":{"controlled_cases":4,"callback_calls":4,"m1_gates":4},"limitation":"M1/M5 fixture wiring only; private case state is not supplied to callbacks and is not a scientific oracle"}))
