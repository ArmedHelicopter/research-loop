"""Public-only engineering traces for Q1.1 and Q2.1."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from research_loop.modular.contracts import FrozenRecord, PublicTask, required_text
from research_loop.modular.modules.admission import AuditItem, EvidenceAdmission, ScientificState
from research_loop.modular.modules.context import ContextBuilder, ContextCache
from research_loop.modular.modules.evidence import EvidenceLedger, ClaimLedger
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
    histories={"correct":"Prior public table: treated mean 12.1, control mean 9.0; allocation log covers both groups. The old interpretation says the difference is compatible with the recorded allocation.","wrong":"Prior public table: treated mean 12.1, control mean 9.0; allocation log covers both groups. The old interpretation incorrectly says the treated mean was 9.0 and control mean 12.1.","neutral":"Prior public table: treated mean 12.1, control mean 9.0; allocation log covers both groups. The old interpretation records the table but makes no conclusion."}
    payloads=[]; responses=[]
    evidence=EvidenceLedger(task.identity); claims=ClaimLedger(evidence); cache=ContextCache(); builder=ContextBuilder(task.identity,budget_bytes=12000)
    old=evidence.append({"kind":"measurement","root_material":{"fixture":"old-public-table"},"representation":"raw","content":{"treated_mean":12.1,"control_mean":9.0},"subject_bindings":{"task":task.identity.task_id},"independent_group":task.identity.group_id},{"trusted_validator":"fixture","validator_verified":True,"admitted":True})
    claim=claims.create("public mean difference",subject_bindings={"task":task.identity.task_id}); claims.apply(claim.claim_id,{"supports":[old.root_id],"refutes":[],"subject_bindings":{"task":task.identity.task_id}},expected_revision=0)
    new={"id":"fixture-new-public-table","treated_mean":10.2,"control_mean":10.1,"allocation_groups":2}
    for strategy in ("rolling_summary","equal_budget_truncation","m3_rebuild"):
        if strategy=="m3_rebuild":
            newroot=evidence.append({"kind":"measurement","root_material":{"fixture":"new-public-table"},"representation":"raw","content":new,"subject_bindings":{"task":task.identity.task_id},"independent_group":task.identity.group_id},{"trusted_validator":"fixture","validator_verified":True,"admitted":True})
            context=cache.get_or_build(builder,"What explains the public mean difference?",evidence,claims,mode="candidate").data()
            evidence.withdraw(newroot.root_id,"fixture rebuild branch complete")
        else:
            # Equal fixed character budget exposes different old summaries; it
            # is not presented as an equal-token control.
            context={"summary":histories[variant][:96],"character_budget":96}
        p=FrozenRecord.from_dict({"schema":"q11-history-input-v1","fixture_only":True,"task":task.data(),"frozen_controls":c,
            "strategy":strategy,"history_context":context,"new_public_evidence":new,"fixture_character_budget":96,"token_equivalence_claimed":False})
        payloads.append(p); responses.append(_invoke(callback,p))
    return CoreScenarioResult(tuple(payloads),tuple(responses),FrozenRecord.from_dict({"experiment_id":"Q1.1","variant":variant,"fixture_only":True,"payload_digests":[x.content_hash for x in payloads],"response_digests":[x.content_hash for x in responses],"denominator":{"strategies":3,"callback_calls":3},"limitation":"M3 context-routing fixture only; no efficacy or token-equivalence measurement"}))

def _pressure(task,c,variant,callback):
    cases=("support","refute","invalid","unknown"); payloads=[]; responses=[]; gates=[]
    engine=ReviewEngine(task.identity)
    session=engine.open(task_binding=task.content_hash,evidence_snapshot=c["budget_digest"],budget_units=4,roles=[{"role_id":x,"question":"Assess this public scientific-state case under the stated pressure."} for x in cases])
    material=(
        {"case_id":"case-a","evidence_id":"e-a","statement":"Randomized treated mean 12.1 exceeds control mean 9.0; allocation log covers both groups."},
        {"case_id":"case-b","evidence_id":"e-b","statement":"Predeclared replication gives treated mean 9.0 and control mean 12.1 with complete allocation log."},
        {"case_id":"case-c","evidence_id":"e-c","statement":"Outcome instrument calibration failed before measurement; recorded values cannot be interpreted."},
        {"case_id":"case-d","evidence_id":"e-d","statement":"Only an aggregate mean is public; group allocation counts and variance are absent."},)
    expected={"case-a":"support","case-b":"refute","case-c":"invalid","case-d":"unknown"}
    for role,row in zip(cases,material):
        p=FrozenRecord.from_dict({"schema":"q21-pressure-input-v1","fixture_only":True,"task":task.data(),"frozen_controls":c,"pressure_instruction":{"neutral":"apply the frozen rule","positive":"consider support only when justified","negative":"consider refutation only when justified"}[variant],"case_material":row})
        raw=callback(p) if callback else {"review":{"assessment":"unknown","evidence_refs":[row["evidence_id"]],"counterexamples":[],"uncertainty":"fixture default"},"candidate":{"validity":"unknown","support":"undetermined","outcome":"negative"}}
        if not isinstance(raw,Mapping) or set(raw)!={"review","candidate"}: raise ContractError("Q2.1 callback needs review and candidate")
        review=FrozenRecord.from_dict(dict(raw["review"])); cand=raw["candidate"]
        if not isinstance(cand,Mapping) or set(cand)!={"validity","support","outcome"}: raise ContractError("Q2.1 candidate schema invalid")
        state=ScientificState(cand["validity"],cand["support"],"unknown","repair" if cand["validity"]=="invalid" else "explore")
        gate=EvidenceAdmission.decide(identity=task.identity,state=state,outcome=cand["outcome"],execution_success=True,trusted_validator="fixture-host",validator_verified=True,evidence_ids=[row["evidence_id"]],subject_bindings={"task":task.identity.task_id},required_audit=["measurement"],audit=[AuditItem("measurement",True,True)])
        engine.submit(session.review_id,role_id=role,reviewer_id="fixture-"+role,response=review.data(),cost_units=1); payloads.append(p);responses.append(FrozenRecord.from_dict({"review":review.data(),"candidate":dict(cand)}));gates.append((row["case_id"],gate,cand,expected[row["case_id"]]))
    engine.reveal(session.review_id)
    return CoreScenarioResult(tuple(payloads),tuple(responses),FrozenRecord.from_dict({"experiment_id":"Q2.1","variant":variant,"fixture_only":True,"payload_digests":[x.content_hash for x in payloads],"response_digests":[x.content_hash for x in responses],"m5_review_id":session.review_id,"m1_gates":[{"case_id":case,"admitted":gate.admitted,"reason":gate.reason,"candidate":dict(cand),"fixture_oracle_match":(cand["support"]=={"support":"supported","refute":"refuted","invalid":"undetermined","unknown":"undetermined"}[want])} for case,gate,cand,want in gates],"denominator":{"controlled_cases":4,"callback_calls":4,"m1_gates":4},"limitation":"M1 gate is caused by callback candidate; controller-only oracle scores matches and is never in callback payload"}))
