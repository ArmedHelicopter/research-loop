"""Train-only production drivers for Q1.6 withdrawal and Q1.7 time-information panels."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask, required_text
from research_loop.modular.modules.context import ContextBuilder
from research_loop.modular.modules.admission import AuditItem, EvidenceAdmission, ScientificState
from research_loop.modular.panel_receipts import PanelCell, opaque_panel_cell_binding
from research_loop.modular.workflow import ModularWorkflow
from research_loop.ontology import ContractError, canonical

AdmissionPort = Callable[[PublicTask, FrozenRecord], Mapping[str, Any]]


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip(): raise ContractError(name + " must be nonempty")
    return value

def _binding(cell: PanelCell) -> dict[str, str]: return opaque_panel_cell_binding(cell)

def _admit(port: AdmissionPort | None, task: PublicTask, record: FrozenRecord) -> dict[str, Any]:
    if port is None: raise ContractError("withdrawal driver requires caller-supplied verified admission receipt")
    receipt=port(task,record)
    if (not isinstance(receipt,Mapping) or set(receipt)!={"record_digest","trusted_validator","validator_verified","admitted"}
        or receipt.get("record_digest")!=record.content_hash or not isinstance(receipt.get("trusted_validator"),str)
        or not receipt["trusted_validator"].strip() or receipt.get("validator_verified") is not True or receipt.get("admitted") is not True):
        raise ContractError("withdrawal admission receipt does not bind the selected record")
    return dict(receipt)

def _append(workflow: ModularWorkflow, record: FrozenRecord, receipt: Mapping[str,Any], root: str):
    return workflow.session.evidence.append({"kind":"measurement","root_material":{"record_digest":record.content_hash,"history_id":root},
        "representation":"raw","content":record.data()["evidence"],"subject_bindings":{"task":workflow.session.task.identity.task_id},
        "independent_group":workflow.session.task.identity.group_id}, {k:receipt[k] for k in ("trusted_validator","validator_verified","admitted")})

def _record(identity: Mapping[str,Any], kind: str, evidence: Mapping[str,Any]) -> FrozenRecord:
    return FrozenRecord.from_dict({"schema":"typed-withdrawal-public-record-v1","identity":dict(identity),"kind":kind,"evidence":dict(evidence)})

def _validate_bundle(task: PublicTask, body: Mapping[str,Any]) -> None:
    if set(body)!={"schema","identity","public_evidence","q16","q17"} or body["schema"]!="typed-withdrawal-panel-bundle-v1" or body["identity"]!=task.identity.data() or not isinstance(body["public_evidence"],Mapping) or not body["public_evidence"]:
        raise ContractError("withdrawal bundle identity or public evidence is invalid")
    q16=body["q16"]; common={"initial_answer","historical_summary","old_evidence","old_claim","invalidation_evidence","invalidation_action"}
    if not isinstance(q16,Mapping) or set(q16)!={"replacement","none","high_score"}: raise ContractError("q16 bundle lacks complete frozen variants")
    for variant,item in q16.items():
        required=common | ({"alternative_material"} if variant=="replacement" else {"historical_score"} if variant=="high_score" else set())
        if not isinstance(item,Mapping) or set(item)!=required: raise ContractError("Q1.6 variant material is malformed")
        for field in ("initial_answer","historical_summary","old_claim"): _text(item[field],field)
        for field in ("old_evidence","invalidation_evidence"):
            if not isinstance(item[field],Mapping) or not item[field]: raise ContractError(field+" must be concrete public material")
        action=item["invalidation_action"]
        if (not isinstance(action,Mapping) or set(action)!={"execution_success","outcome","state","audit","reason"} or type(action["execution_success"]) is not bool or action["outcome"] not in {"positive","negative"} or not isinstance(action["state"],Mapping) or set(action["state"])!={"validity","support","novelty","investment"} or not isinstance(action["audit"],list) or not action["audit"]): raise ContractError("Q1.6 invalidation action is not a closed caller fact")
        ScientificState(**action["state"]); [AuditItem(**entry) for entry in action["audit"]]; _text(action["reason"],"invalidation reason")
        if variant=="replacement" and (not isinstance(item["alternative_material"],Mapping) or not item["alternative_material"]): raise ContractError("replacement requires concrete caller alternative material")
        if variant=="high_score" and (not isinstance(item["historical_score"],Mapping) or set(item["historical_score"])!={"score","source","recorded_at"} or type(item["historical_score"]["score"]) not in {int,float} or not all(isinstance(item["historical_score"][k],str) and item["historical_score"][k].strip() for k in ("source","recorded_at"))): raise ContractError("high_score requires a concrete caller historical score")
    q17=body["q17"]
    if not isinstance(q17,Mapping) or set(q17)!={"irrelevant","causal","unknown"}: raise ContractError("q17 bundle lacks complete frozen variants")
    for variant,item in q17.items():
        if not isinstance(item,Mapping) or set(item)!={"initial_answer","historical_summary","before_evidence","current_evidence"}: raise ContractError("Q1.7 material fields are invalid")
        for field in ("initial_answer","historical_summary"): _text(item[field],field)
        for field in ("before_evidence","current_evidence"):
            value=item[field]
            if not isinstance(value,Mapping) or set(value)!={"observation","time_order","narrative","evidence_sufficient"} or not isinstance(value["observation"],str) or not isinstance(value["time_order"],str) or not isinstance(value["narrative"],str) or type(value["evidence_sufficient"]) is not bool: raise ContractError("Q1.7 evidence requires typed observation, time, narrative and sufficiency")
        before,current=item["before_evidence"],item["current_evidence"]
        if variant=="irrelevant" and (before["observation"]!=current["observation"] or before["time_order"]!=current["time_order"] or before["narrative"]==current["narrative"]): raise ContractError("irrelevant variant must preserve observation/time and change only narrative")
        if variant=="causal" and before["time_order"]==current["time_order"]: raise ContractError("causal variant requires a changed time or causal order")
        if variant=="unknown" and current["evidence_sufficient"] is not False: raise ContractError("unknown variant requires caller-declared insufficient evidence")

def freeze_withdrawal_bundle(task: PublicTask, *, public_evidence: Mapping[str,Any], q16: Mapping[str,Mapping[str,Any]], q17: Mapping[str,Mapping[str,Any]]) -> FrozenRecord:
    body={"schema":"typed-withdrawal-panel-bundle-v1","identity":task.identity.data(),"public_evidence":dict(public_evidence),"q16":{k:dict(v) for k,v in q16.items()},"q17":{k:dict(v) for k,v in q17.items()}}
    _validate_bundle(task,body); return FrozenRecord.from_dict(body)

def select_withdrawal_material(bundle: FrozenRecord, task: PublicTask, experiment_id: str, variant: str) -> FrozenRecord:
    body=bundle.data(); _validate_bundle(task,body)
    key={"Q1.6":"q16","Q1.7":"q17"}.get(experiment_id)
    if key is None or variant not in body[key]: raise ContractError("withdrawal bundle lacks selected material")
    return FrozenRecord.from_dict({"schema":"typed-withdrawal-panel-material-v1","experiment_id":experiment_id,"identity":body["identity"],"public_evidence":body["public_evidence"],**body[key][variant]})

def withdrawal_panel_injection(experiment_id: str, variant: str, *, task: FrozenRecord, evidence: FrozenRecord) -> Mapping[str,Any]:
    if evidence.data().get("schema")!="typed-withdrawal-panel-bundle-v1":
        from research_loop.modular.scenarios_history import history_injection
        return history_injection(experiment_id,variant)
    body=task.data(); public=PublicTask(DataIdentity.parse(body["identity"]),FrozenRecord.from_dict(body["payload"]))
    select_withdrawal_material(evidence,public,experiment_id,variant)
    return {"schema":"withdrawal-panel-controller-v1","material_bundle":evidence.data()}

def _resolve(task: PublicTask, scenario: FrozenRecord, experiment_id: str, variant: str) -> FrozenRecord:
    controller=scenario.data().get("controller_input",{})
    if not isinstance(controller,Mapping) or controller.get("schema")!="withdrawal-panel-controller-v1" or not isinstance(controller.get("material_bundle"),Mapping): raise ContractError("withdrawal driver requires compiler-bound frozen bundle")
    bundle=FrozenRecord.from_dict(controller["material_bundle"])
    if scenario.data().get("base",{}).get("evidence")!=bundle.content_hash: raise ContractError("withdrawal bundle does not match frozen scenario evidence")
    return select_withdrawal_material(bundle,task,experiment_id,variant)

def _candidate(value: FrozenRecord, objective: FrozenRecord) -> None:
    body=value.data()
    if body.get("objective_digest")!=objective.content_hash: raise ContractError("final candidate must copy required_objective_digest exactly")

@dataclass(frozen=True)
class Q16WithdrawalDriver:
    experiment_id: str="Q1.6"; slots: tuple[str,...] = ("initial","invalidation","final"); execution_limit:int=0; docker_execution:str="not_requested_by_driver"; admission_port: AdmissionPort|None=None
    def slots_for(self,cell:PanelCell)->tuple[str,...]: return self.slots
    def run(self,workflow:ModularWorkflow,*,cell:PanelCell,scenario:FrozenRecord,model,package):
        material=_resolve(workflow.session.task,scenario,"Q1.6",cell.variant); body=material.data(); bind=_binding(cell)
        initial=workflow.invoke_model("initial",model,instruction="Assess only the initial public answer and evidence; do not infer later information.",evidence_only=True,module_context=FrozenRecord.from_dict({"panel_cell":bind,"public_evidence":body["public_evidence"],"initial_answer":body["initial_answer"]}))
        old=_record(body["identity"],"old_source",body["old_evidence"]); invalid=_record(body["identity"],"invalidation",body["invalidation_evidence"])
        old_receipt=_admit(self.admission_port,workflow.session.task,old); invalid_receipt=_admit(self.admission_port,workflow.session.task,invalid)
        old_root=_append(workflow,old,old_receipt,"q16-old-source"); claim=workflow.session.claims.create(body["old_claim"],subject_bindings={"task":workflow.session.task.identity.task_id}); claim=workflow.session.claims.apply(claim.claim_id,{"supports":[old_root.root_id],"refutes":[],"subject_bindings":{"task":workflow.session.task.identity.task_id}},expected_revision=0).claim
        m1,m2="M1" in workflow.enabled,"M2" in workflow.enabled; action=body["invalidation_action"]
        review=workflow.invoke_model("invalidation",model,instruction="Describe the supplied caller-admitted invalidation evidence. It does not itself establish an alternative proposal.",module_context=FrozenRecord.from_dict({"panel_cell":bind,"historical_summary":body["historical_summary"],"old_record":old.data(),"old_claim":claim.data(),"invalidation_record":invalid.data(),"alternative_material":body.get("alternative_material"),"historical_score":body.get("historical_score"),"m1":"enabled" if m1 else "frozen_control","m2":"enabled" if m2 else "frozen_control"}))
        gate=None; revisions=[]; withdrawn=None
        if m1:
            state=ScientificState(**action["state"]); audit=[AuditItem(**entry) for entry in action["audit"]]
            gate=EvidenceAdmission.decide(identity=workflow.session.task.identity,state=state,outcome=action["outcome"],execution_success=action["execution_success"],trusted_validator=invalid_receipt["trusted_validator"],validator_verified=invalid_receipt["validator_verified"],evidence_ids=[invalid.content_hash],subject_bindings={"task":workflow.session.task.identity.task_id},required_audit=[entry.name for entry in audit],audit=audit)
            workflow._trace("operation_m1_evidence_gate","executed",invalidation_record=invalid.data(),disposition={"admitted":gate.admitted,"reason":gate.reason,"outcome":gate.outcome,"evidence_ids":list(gate.evidence_ids)},state=action["state"])
            if state.validity=="invalid":
                workflow.session.evidence.withdraw(old_root.root_id,action["reason"]); withdrawn=old_root.root_id
        else: workflow._trace("operation_m1_control","executed",old_record=old.data(),invalidation_record=invalid.data())
        if m2:
            revisions=[item.claim.data() for item in workflow.session.claims.refresh_after_withdrawal()] if withdrawn else []
            workflow._trace("operation_m2_withdrawal_propagation","executed",withdrawn_root=withdrawn,revisions=revisions)
        else:
            workflow._trace("operation_m2_control","executed",withdrawn_root=withdrawn,revisions=[])
        process={"invalidation_review":review.data(),"old_record":old.data(),"old_claim":claim.data(),"invalidation_record":invalid.data(),"invalidation_gate":None if gate is None else {"admitted":gate.admitted,"reason":gate.reason,"outcome":gate.outcome},"withdrawn_old_root":withdrawn,"revised_claims":revisions}
        stage=workflow._trace("stage_9" if m1 and m2 else "stage_1" if m1 else "operation_m1_control_final","executed",withdrawn_old_root=withdrawn)
        final=workflow.invoke_model("final",model,instruction="Return bounded train-only candidate. Copy required_objective_digest exactly; use actual gate and withdrawal processing, not a digest-only summary.",module_context=FrozenRecord.from_dict({"panel_cell":bind,"candidate_package":package.record.data(),"required_objective_digest":workflow.session.objective.content_hash,"withdrawal_processing":process,"alternative_material":body.get("alternative_material"),"historical_score":body.get("historical_score")}))
        _candidate(final,workflow.session.objective); return stage,final,(initial,review,final)

@dataclass(frozen=True)
class Q17TimeInformationDriver:
    experiment_id: str="Q1.7"; slots: tuple[str,...] = ("initial","reconstructed","final"); execution_limit:int=0; docker_execution:str="not_requested_by_driver"; admission_port: AdmissionPort|None=None
    def slots_for(self,cell:PanelCell)->tuple[str,...]: return self.slots
    def run(self,workflow:ModularWorkflow,*,cell:PanelCell,scenario:FrozenRecord,model,package):
        material=_resolve(workflow.session.task,scenario,"Q1.7",cell.variant); body=material.data(); bind=_binding(cell)
        initial=workflow.invoke_model("initial",model,instruction="Assess only the initial public answer and evidence; later evidence is unavailable at this stage.",evidence_only=True,module_context=FrozenRecord.from_dict({"panel_cell":bind,"public_evidence":body["public_evidence"],"initial_answer":body["initial_answer"]}))
        before=_record(body["identity"],"before",body["before_evidence"]); current=_record(body["identity"],"current",body["current_evidence"]); before_receipt=_admit(self.admission_port,workflow.session.task,before); current_receipt=_admit(self.admission_port,workflow.session.task,current)
        before_root=_append(workflow,before,before_receipt,"q17-before"); frozen=workflow.session.cache.get_or_build(ContextBuilder(workflow.session.task.identity,budget_bytes=workflow.session.context_budget),canonical(workflow.session.task.payload.data()),workflow.session.evidence,workflow.session.claims,mode="baseline",baseline_summary=body["historical_summary"])
        workflow.session.evidence.withdraw(before_root.root_id,"caller-declared current public update"); current_root=_append(workflow,current,current_receipt,"q17-current")
        m3="M3" in workflow.enabled
        context=workflow.session.cache.get_or_build(ContextBuilder(workflow.session.task.identity,budget_bytes=workflow.session.context_budget),canonical(workflow.session.task.payload.data()),workflow.session.evidence,workflow.session.claims,mode="candidate",baseline_summary=body["historical_summary"]) if m3 else frozen
        stage=workflow._trace("stage_9" if m3 else "operation_m3_control","executed",before_root=before_root.root_id,current_root=current_root.root_id,context=context.data(),control_context=frozen.data() if not m3 else None)
        rebuilt=workflow.invoke_model("reconstructed",model,instruction="Assess current caller-admitted public evidence after the declared context operation; unknown is allowed.",module_context=FrozenRecord.from_dict({"panel_cell":bind,"before_record":before.data(),"current_record":current.data(),"historical_summary":body["historical_summary"],"reconstructed_context":context.data(),"admission_receipts":{"before":before_receipt,"current":current_receipt},"m3":"enabled" if m3 else "frozen_control"}))
        final=workflow.invoke_model("final",model,instruction="Return bounded train-only candidate. Copy required_objective_digest exactly and use the actual reconstruction result.",module_context=FrozenRecord.from_dict({"panel_cell":bind,"candidate_package":package.record.data(),"required_objective_digest":workflow.session.objective.content_hash,"time_reconstruction":{"response":rebuilt.data(),"context":context.data(),"before_record":before.data(),"current_record":current.data()}}))
        _candidate(final,workflow.session.objective); return stage,final,(initial,rebuilt,final)

def install_drivers(target: dict[str,Any], *, admission_port: AdmissionPort|None=None):
    target.update({"Q1.6":Q16WithdrawalDriver(admission_port=admission_port),"Q1.7":Q17TimeInformationDriver(admission_port=admission_port)}); return target
