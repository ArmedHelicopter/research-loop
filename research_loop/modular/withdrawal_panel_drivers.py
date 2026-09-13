"""Train-only production drivers for Q1.6 withdrawal and Q1.7 time-information panels."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask, required_text
from research_loop.modular.modules.context import ContextBuilder
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
    for name, variants, required in (("q16",("replacement","none","high_score"),("initial_answer","historical_summary","invalidation_evidence","alternative_material")), ("q17",("irrelevant","causal","unknown"),("initial_answer","historical_summary","current_evidence"))):
        entries=body[name]
        if not isinstance(entries,Mapping) or set(entries)!=set(variants): raise ContractError(name+" bundle lacks complete frozen variants")
        for item in entries.values():
            if not isinstance(item,Mapping) or set(item)!=set(required): raise ContractError(name+" material fields are invalid")
            for field in ("initial_answer","historical_summary"):_text(item[field],field)
            for field in set(required)-{"initial_answer","historical_summary"}:
                if not isinstance(item[field],Mapping): raise ContractError(field+" must be concrete public material")

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
        initial=workflow.invoke_model("initial",model,instruction="Assess only the supplied initial public answer and evidence; do not infer later information.",evidence_only=True,module_context=FrozenRecord.from_dict({"panel_cell":bind,"public_evidence":body["public_evidence"],"initial_answer":body["initial_answer"]}))
        invalid=_record(body["identity"],"invalidation",body["invalidation_evidence"]); receipt=_admit(self.admission_port,workflow.session.task,invalid)
        m1,m2="M1" in workflow.enabled,"M2" in workflow.enabled
        review=workflow.invoke_model("invalidation",model,instruction="Assess the caller-admitted invalidation evidence and state what it permits; a alternative proposal is not automatically supported.",module_context=FrozenRecord.from_dict({"panel_cell":bind,"public_evidence":body["public_evidence"],"historical_summary":body["historical_summary"],"invalidation_record":invalid.data(),"alternative_material":body["alternative_material"],"admission_receipt":receipt,"m1":"enabled" if m1 else "frozen_control","m2":"enabled" if m2 else "frozen_control"}))
        process={"invalidation_review":review.data(),"invalidation_record":invalid.data(),"admission_receipt":receipt,"withdrawn_root":None,"revised_claims":[]}
        if m1:
            root=_append(workflow,invalid,receipt,"q16-invalidation"); claim=workflow.session.claims.create(body["initial_answer"],subject_bindings={"task":workflow.session.task.identity.task_id}); claim=workflow.session.claims.apply(claim.claim_id,{"supports":[root.root_id],"refutes":[],"subject_bindings":{"task":workflow.session.task.identity.task_id}},expected_revision=0).claim
            workflow.session.evidence.withdraw(root.root_id,"caller-admitted invalidation")
            revised=workflow.session.claims.refresh_after_withdrawal() if m2 else ()
            process.update({"withdrawn_root":root.root_id,"revised_claims":[x.claim.data() for x in revised]})
            stage=workflow._trace("stage_1" if not m2 else "stage_9","executed",withdrawn_root=root.root_id,revised_claims=process["revised_claims"])
        else: stage=workflow._trace("operation_m1_control","executed",invalidation_record=invalid.data())
        final=workflow.invoke_model("final",model,instruction="Return bounded train-only candidate. Copy required_objective_digest exactly; use actual withdrawal processing, not a digest-only summary.",module_context=FrozenRecord.from_dict({"panel_cell":bind,"candidate_package":package.record.data(),"required_objective_digest":workflow.session.objective.content_hash,"withdrawal_processing":process,"alternative_material":body["alternative_material"]}))
        _candidate(final,workflow.session.objective); return stage,final,(initial,review,final)

@dataclass(frozen=True)
class Q17TimeInformationDriver:
    experiment_id: str="Q1.7"; slots: tuple[str,...] = ("initial","reconstructed","final"); execution_limit:int=0; docker_execution:str="not_requested_by_driver"; admission_port: AdmissionPort|None=None
    def slots_for(self,cell:PanelCell)->tuple[str,...]: return self.slots
    def run(self,workflow:ModularWorkflow,*,cell:PanelCell,scenario:FrozenRecord,model,package):
        material=_resolve(workflow.session.task,scenario,"Q1.7",cell.variant); body=material.data(); bind=_binding(cell)
        initial=workflow.invoke_model("initial",model,instruction="Assess only the initial public answer and evidence; later evidence is unavailable at this stage.",evidence_only=True,module_context=FrozenRecord.from_dict({"panel_cell":bind,"public_evidence":body["public_evidence"],"initial_answer":body["initial_answer"]}))
        current=_record(body["identity"],"current",body["current_evidence"]); receipt=_admit(self.admission_port,workflow.session.task,current)
        m3="M3" in workflow.enabled
        root=_append(workflow,current,receipt,"q17-current") if m3 else None
        context=workflow.session.cache.get_or_build(ContextBuilder(workflow.session.task.identity,budget_bytes=workflow.session.context_budget),canonical(workflow.session.task.payload.data()),workflow.session.evidence,workflow.session.claims,mode="candidate" if m3 else "baseline",baseline_summary=body["historical_summary"])
        stage=workflow._trace("stage_9" if m3 else "operation_m3_control","executed",current_root=root.root_id if root else None,context=context.data())
        rebuilt=workflow.invoke_model("reconstructed",model,instruction="Assess current caller-admitted public evidence after the declared context operation; unknown is allowed.",module_context=FrozenRecord.from_dict({"panel_cell":bind,"current_record":current.data(),"historical_summary":body["historical_summary"],"reconstructed_context":context.data(),"admission_receipt":receipt,"m3":"enabled" if m3 else "frozen_control"}))
        final=workflow.invoke_model("final",model,instruction="Return bounded train-only candidate. Copy required_objective_digest exactly and use the actual reconstruction result.",module_context=FrozenRecord.from_dict({"panel_cell":bind,"candidate_package":package.record.data(),"required_objective_digest":workflow.session.objective.content_hash,"time_reconstruction":{"response":rebuilt.data(),"context":context.data(),"current_record":current.data()}}))
        _candidate(final,workflow.session.objective); return stage,final,(initial,rebuilt,final)

def install_drivers(target: dict[str,Any], *, admission_port: AdmissionPort|None=None):
    target.update({"Q1.6":Q16WithdrawalDriver(admission_port=admission_port),"Q1.7":Q17TimeInformationDriver(admission_port=admission_port)}); return target
