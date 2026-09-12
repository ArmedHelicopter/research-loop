"""Activation-aware real module driver for a frozen RunSession."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from research_loop.modular.contracts import FrozenRecord, required_text
from research_loop.ontology import ContractError
from research_loop.modular.runtime import RunSession
from research_loop.modular.modules.predictions import PredictionRegistry
from research_loop.modular.modules.review import ReviewEngine
from research_loop.modular.modules.retrieval import FrozenRetrievalPolicy, FrozenSourceBundle, RetrievalProvider, RetrievalSignals, retrieve
from research_loop.modular.modules.exploration import ExplorationPlan, FeasibilityObservation, ExplorationBudget, assess_feasibility, admit_exploration
from research_loop.modular.modules.scheduling import FifoScheduler, TaskLease

STAGES = ("stage_0.5", "stage_1", "stage_3", "stage_7", "stage_9", "frontier")
@dataclass(frozen=True)
class WorkflowResult:
    status: str
    detail: FrozenRecord

class ModularWorkflow:
    def __init__(self, session: RunSession) -> None:
        self.session=session; self.enabled=frozenset(session.arm.data()["enabled"])
        self.predictions=PredictionRegistry(session.task.identity, storage_path=session.sidecar/"predictions.jsonl")
        self.reviews=ReviewEngine(session.task.identity, storage_path=session.sidecar/"reviews.jsonl")
        self.revealed: FrozenRecord|None=None
    def _trace(self, stage: str, status: str, **data: Any) -> WorkflowResult:
        item=FrozenRecord.from_dict({"stage":stage,"status":status,**data}); self.session._record("modular_workflow",item.data()); return WorkflowResult(status,item)
    def record_stages(self, records: Mapping[str, Mapping[str, str]]) -> tuple[WorkflowResult, ...]:
        if set(records) != set(STAGES): raise ContractError("every fixed stage requires a record")
        known = {event.content_hash for event in self.session._events}; result=[]
        for stage in STAGES:
            item=records[stage]
            if set(item)=={"reason"}: result.append(self._trace("coverage_"+stage,"blocked",reason=item["reason"]))
            elif set(item)=={"trace_digest"} and item["trace_digest"] in known: result.append(self._trace("coverage_"+stage,"executed",trace_digest=item["trace_digest"]))
            else: raise ContractError("executed stage coverage requires an existing trace digest")
        return tuple(result)
    def propose(self,slot:str,model:Callable[[FrozenRecord],FrozenRecord],*,instruction:str)->WorkflowResult:
        if "M4" not in self.enabled:
            response=self.session.invoke(slot,model,instruction=instruction,module_context=FrozenRecord.from_dict({"control":"M4"}))
            return self._trace("operation_m4_control","executed",response_digest=response.content_hash)
        response=self.session.invoke(slot,model,instruction=instruction); body=response.data()
        if set(body)!={"question","branches","budget_units"}:raise ContractError("M4 proposal lacks operational prediction plan")
        plan=self.predictions.freeze(body["question"],body["branches"],budget_units=body["budget_units"])
        return self._trace("stage_1","executed",plan_digest=plan.payload.content_hash)
    def independent_review(self,roles:Sequence[tuple[str,str,str,str]],model:Callable[[FrozenRecord],FrozenRecord],*,evidence_snapshot:str)->WorkflowResult:
        if "M5" not in self.enabled:
            for slot, role, question, _reviewer in roles: self.session.invoke(slot,model,instruction="Answer the assigned review question.",module_context=FrozenRecord.from_dict({"control":"M5","role":role,"question":question}))
            return self._trace("operation_m5_control","executed",roles=[role for _,role,_,_ in roles])
        review=self.reviews.open(task_binding=self.session.task.identity.task_id,evidence_snapshot=required_text(evidence_snapshot,"evidence snapshot"),roles=[{"role_id":r,"question":q}for _,r,q,_ in roles],budget_units=len(roles))
        for slot,role,question,reviewer in roles:
            response=self.session.invoke(slot,model,instruction="Answer only the assigned review question.",module_context=FrozenRecord.from_dict({"review_id":review.review_id,"sealed":True,"role":role,"question":question}))
            self.reviews.submit(review.review_id,role_id=role,reviewer_id=reviewer,response=response.data(),cost_units=1)
        revealed=self.reviews.reveal(review.review_id); self.revealed=FrozenRecord.from_dict({"review_id":review.review_id,"submissions":[x.data()for x in revealed]})
        return self._trace("stage_7","executed",review_digest=self.revealed.content_hash)
    def retrieve_then_invoke(self,slot:str,model:Callable[[FrozenRecord],FrozenRecord],*,instruction:str,provider:RetrievalProvider,query:FrozenRecord,source_bundle:FrozenSourceBundle,policy:FrozenRetrievalPolicy,signals:RetrievalSignals)->FrozenRecord|WorkflowResult:
        if "M6" not in self.enabled:
            return self.session.invoke(slot,model,instruction=instruction,module_context=FrozenRecord.from_dict({"control":"M6"}))
        sources=retrieve(provider=provider,query=query,source_bundle=source_bundle,policy=policy,signals=signals)
        context={"retrieval":sources.data()}
        if self.revealed:context["independent_review"]=self.revealed.data()
        response=self.session.invoke(slot,model,instruction=instruction,module_context=FrozenRecord.from_dict(context))
        self._trace("stage_0.5","executed",active_triggers=list(sources.active_triggers),source_bundle_digest=source_bundle.content_hash); return response
    def explore(self,plan:ExplorationPlan,observations:Mapping[str,FeasibilityObservation],budget:ExplorationBudget,*,code:str,broker:Any,image:str,inputs:Mapping[str,Path])->WorkflowResult:
        if "M7" not in self.enabled:return self._trace("stage_3","blocked",module="M7",reason="module_not_enabled")
        report=assess_feasibility(plan,observations)
        try: permit=admit_exploration(plan=plan,feasibility=report,budget=budget)
        except ContractError as exc:return self._trace("stage_3","blocked",reason=str(exc),feasibility=report.stages)
        execution=self.session.execute(code,broker=broker,image=image,inputs=inputs)
        return self._trace("stage_3","executed",permit_digest=permit.diagnostic_digest,execution_digest=execution.content_hash)
    def run_panel(self,scheduler:FifoScheduler,*,experiment_id:str,jobs:Sequence[Mapping[str,Any]],worker_id:str,execute:Callable[[TaskLease],FrozenRecord])->WorkflowResult:
        if "M8" not in self.enabled:return self._trace("stage_9","blocked",module="M8",reason="module_not_enabled")
        snapshot={"evidence":self.session.evidence.version,"rules":self.session.objective.content_hash,"package":self.session.lock.data()["package_digest"]}
        for job in jobs:scheduler.enqueue(experiment_id=experiment_id,snapshot=snapshot,**job)
        receipts=[]
        while (lease:=scheduler.claim_next(worker_id,lease_seconds=60)) is not None:
            receipt=execute(lease)
            if not isinstance(receipt,FrozenRecord):raise ContractError("panel executor must return FrozenRecord")
            scheduler.complete(lease.run_id,receipt_id=receipt.content_hash,receipt=receipt.data(),cost_units=lease.cost_units);receipts.append(receipt.content_hash)
        merged=scheduler.merge(experiment_id)
        return self._trace("operation_m8_panel","executed",receipts=receipts,merged=[x.run_id for x in merged])
    def m9_policy(self,policy:FrozenRecord|None)->WorkflowResult:
        return self._trace("operation_m9_policy","blocked",module="M9",reason="m9_execution_hook_missing",policy_digest=policy.content_hash if policy else None)




