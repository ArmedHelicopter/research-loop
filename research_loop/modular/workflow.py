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
from research_loop.modular.modules.improvement import AcceptanceReceipt, CandidatePackage, ExecutionRuntime

STAGES = ("stage_0.5", "stage_1", "stage_3", "stage_7", "stage_9", "frontier")
@dataclass(frozen=True)
class WorkflowResult:
    status: str
    detail: FrozenRecord

class ModularWorkflow:
    def __init__(self, session: RunSession, *, deployment: ExecutionRuntime | None = None) -> None:
        self.session=session; self.enabled=frozenset(session.arm.data()["enabled"])
        self.predictions=PredictionRegistry(session.task.identity, storage_path=session.sidecar/"predictions.jsonl")
        self.reviews=ReviewEngine(session.task.identity, storage_path=session.sidecar/"reviews.jsonl")
        self.revealed: FrozenRecord|None=None; self.deployment=deployment
        self.frontier_result: FrozenRecord | None = None
    def _trace(self, stage: str, status: str, **data: Any) -> WorkflowResult:
        item=FrozenRecord.from_dict({"stage":stage,"status":status,**data}); self.session._record("modular_workflow",item.data()); return WorkflowResult(status,item)
    def record_stages(self, records: Mapping[str, Mapping[str, str]]) -> tuple[WorkflowResult, ...]:
        if set(records) != set(STAGES): raise ContractError("every fixed stage requires a record")
        known = {event.content_hash: event.data() for event in self.session._events}; result=[]
        for stage in STAGES:
            item=records[stage]
            if set(item)=={"reason"}: result.append(self._trace("coverage_"+stage,"blocked",reason=item["reason"]))
            elif set(item)=={"trace_digest"} and item["trace_digest"] in known:
                event = known[item["trace_digest"]]
                if event["stage"] != "modular_workflow" or event["data"].get("stage") != stage or event["data"].get("status") != "executed":
                    raise ContractError("coverage trace does not bind this executed stage")
                result.append(self._trace("coverage_"+stage,"executed",trace_digest=item["trace_digest"]))
            else: raise ContractError("executed stage coverage requires an existing trace digest")
        return tuple(result)
    def _deployment_context(self) -> dict[str, Any]:
        if self.deployment is None:
            return {}
        package = self.deployment.active()
        if package.digest != self.session.lock.data()["package_digest"]:
            raise ContractError("deployed package does not match frozen run lock")
        # ``run_task`` verifies the durable port's actual state before every
        # request, including a request that needs no host-side task execution.
        self.deployment.run_task(self.session.task.identity, lambda _identity, active: active.digest)
        changes = package.record.data()["changes"]
        return {"deployment": {"package_digest": package.digest,
                                "prompt": changes.get("prompt", {}),
                                "memory": changes.get("memory", {}),
                                "config": changes.get("config", {})}}

    def invoke_model(self, slot: str, model: Callable[[FrozenRecord], FrozenRecord], *, instruction: str,
                     module_context: FrozenRecord | None = None, baseline_summary: str = "") -> FrozenRecord:
        context = module_context.data() if module_context else {}
        if "deployment" in context:
            raise ContractError("module context cannot override deployment payload")
        context.update(self._deployment_context())
        return self.session.invoke(slot, model, instruction=instruction, baseline_summary=baseline_summary,
                                   module_context=FrozenRecord.from_dict(context) if context else None)

    def propose(self,slot:str,model:Callable[[FrozenRecord],FrozenRecord],*,instruction:str)->WorkflowResult:
        if "M4" not in self.enabled:
            response=self.invoke_model(slot,model,instruction=instruction,module_context=FrozenRecord.from_dict({"control":"M4"}))
            return self._trace("operation_m4_control","executed",response_digest=response.content_hash)
        response=self.invoke_model(slot,model,instruction=instruction); body=response.data()
        if set(body)!={"question","branches","budget_units"}:raise ContractError("M4 proposal lacks operational prediction plan")
        plan=self.predictions.freeze(body["question"],body["branches"],budget_units=body["budget_units"])
        return self._trace("stage_1","executed",plan_digest=plan.payload.content_hash)
    def independent_review(self,roles:Sequence[tuple[str,str,str,str]],model:Callable[[FrozenRecord],FrozenRecord],*,evidence_snapshot:str)->WorkflowResult:
        if "M5" not in self.enabled:
            for slot, role, question, _reviewer in roles: self.invoke_model(slot,model,instruction="Answer the assigned review question.",module_context=FrozenRecord.from_dict({"control":"M5","role":role,"question":question}))
            return self._trace("operation_m5_control","executed",roles=[role for _,role,_,_ in roles])
        review=self.reviews.open(task_binding=self.session.task.identity.task_id,evidence_snapshot=required_text(evidence_snapshot,"evidence snapshot"),roles=[{"role_id":r,"question":q}for _,r,q,_ in roles],budget_units=len(roles))
        for slot,role,question,reviewer in roles:
            response=self.invoke_model(slot,model,instruction="Answer only the assigned review question.",module_context=FrozenRecord.from_dict({"review_id":review.review_id,"sealed":True,"role":role,"question":question}))
            self.reviews.submit(review.review_id,role_id=role,reviewer_id=reviewer,response=response.data(),cost_units=1)
        revealed=self.reviews.reveal(review.review_id); self.revealed=FrozenRecord.from_dict({"review_id":review.review_id,"submissions":[x.data()for x in revealed]})
        return self._trace("stage_7","executed",review_digest=self.revealed.content_hash)
    def retrieve_then_invoke(self,slot:str,model:Callable[[FrozenRecord],FrozenRecord],*,instruction:str,provider:RetrievalProvider,query:FrozenRecord,source_bundle:FrozenSourceBundle,policy:FrozenRetrievalPolicy,signals:RetrievalSignals)->FrozenRecord|WorkflowResult:
        if "M6" not in self.enabled:
            return self.invoke_model(slot,model,instruction=instruction,module_context=FrozenRecord.from_dict({"control":"M6"}))
        sources=retrieve(provider=provider,query=query,source_bundle=source_bundle,policy=policy,signals=signals)
        context={"retrieval":sources.data()}
        if self.revealed:context["independent_review"]=self.revealed.data()
        response=self.invoke_model(slot,model,instruction=instruction,module_context=FrozenRecord.from_dict(context))
        self._trace("stage_0.5","executed",active_triggers=list(sources.active_triggers),source_bundle_digest=source_bundle.content_hash); return response
    def explore(self,plan:ExplorationPlan,observations:Mapping[str,FeasibilityObservation],budget:ExplorationBudget,*,code:str,broker:Any,image:str,inputs:Mapping[str,Path])->WorkflowResult:
        if "M7" not in self.enabled:return self._trace("stage_3","blocked",module="M7",reason="module_not_enabled")
        report=assess_feasibility(plan,observations)
        try: permit=admit_exploration(plan=plan,feasibility=report,budget=budget)
        except ContractError as exc:return self._trace("stage_3","blocked",reason=str(exc),feasibility=report.stages)
        execution=self.session.execute(code,broker=broker,image=image,inputs=inputs)
        return self._trace("stage_3","executed",permit_digest=permit.diagnostic_digest,execution_digest=execution.content_hash)
    def run_panel(self,scheduler:FifoScheduler,*,experiment_id:str,jobs:Sequence[Mapping[str,Any]],worker_id:str,execute:Callable[[TaskLease],FrozenRecord])->WorkflowResult:
        if "M8" not in self.enabled:return self._trace("operation_m8_panel","blocked",module="M8",reason="module_not_enabled")
        snapshot={"evidence":self.session.evidence.version,"rules":self.session.objective.content_hash,"package":self.session.lock.data()["package_digest"]}
        for job in jobs:scheduler.enqueue(experiment_id=experiment_id,snapshot=snapshot,**job)
        receipts=[]
        while (lease:=scheduler.claim_next(worker_id,lease_seconds=60)) is not None:
            receipt=execute(lease)
            if not isinstance(receipt,FrozenRecord):raise ContractError("panel executor must return FrozenRecord")
            scheduler.complete(lease.run_id,receipt_id=receipt.content_hash,receipt=receipt.data(),cost_units=lease.cost_units);receipts.append(receipt.content_hash)
        merged=scheduler.merge(experiment_id)
        return self._trace("operation_m8_panel","executed",receipts=receipts,merged=[x.run_id for x in merged])

    def retrospective(self, blind_slot: str, reveal_slot: str, model: Callable[[FrozenRecord], FrozenRecord],
                      *, history_summary: FrozenRecord) -> WorkflowResult:
        """Two actual calls: seal the first review, then reveal historical prose.

        The independent review masks learned prompt/memory content in both arms;
        the deployed digest is still checked. This is a frozen audit role, not a
        candidate opportunity to rewrite the reviewer. Scientific correctness of
        the two responses remains an independent evaluator's responsibility.
        """
        if not isinstance(history_summary, FrozenRecord):
            raise ContractError("retrospective requires a frozen public history summary")
        snapshot = self.session.evidence.snapshot()
        deployment = self._deployment_context()
        context = {"review_stage": "retrospective", "evidence_snapshot": snapshot.content_hash,
                   "deployment_digest": deployment.get("deployment", {}).get("package_digest")}
        if "M5" not in self.enabled:
            context["history_summary"] = history_summary.data()
        review = self.reviews.open(task_binding=self.session.task.content_hash,
            evidence_snapshot=snapshot.content_hash,
            roles=[{"role_id": "retrospective", "question": "What do the original evidence and frozen rules justify?"}],
            budget_units=1)
        first = self.session.invoke(blind_slot, model, instruction="Review the provided evidence under the frozen objective; unknown and no valid counterexample are allowed.",
            module_context=FrozenRecord.from_dict(context), evidence_only=True)
        submitted = self.reviews.submit(review.review_id, role_id="retrospective", reviewer_id="retrospective-reviewer",
            response=first.data(), cost_units=1)
        self.reviews.reveal(review.review_id)
        context.update({"history_summary": history_summary.data(), "sealed_first_review": first.data(),
                        "first_review_digest": submitted.before_hash})
        revised = self.session.invoke(reveal_slot, model, instruction="Recheck the sealed judgment after seeing the historical summary. Cite evidence for any change; disagreement alone does not prove either judgment correct.",
            module_context=FrozenRecord.from_dict(context), evidence_only=True)
        revision = self.reviews.revise_after_reveal(review.review_id, role_id="retrospective", reviewer_id="retrospective-reviewer", response=revised.data())
        return self._trace("stage_9", "executed", review_id=review.review_id,
            method="evidence_first" if "M5" in self.enabled else "summary_first_control",
            evidence_snapshot=snapshot.content_hash, summary_digest=history_summary.content_hash,
            before_digest=submitted.before_hash, after_digest=revision.after_hash,
            slots=[blind_slot, reveal_slot], correctness="requires_independent_scoring")

    def frontier_audit(self, slot: str, model: Callable[[FrozenRecord], FrozenRecord],
                       *, plan_ids: Sequence[str] = ()) -> WorkflowResult:
        """Audit current gaps into proposals, with no benchmark or queue authority."""
        from research_loop.modular.frontier import validate_frontier
        catalog: dict[str, Any] = {"boundary:objective": {"kind": "boundary", "objective": self.session.objective.data()}}
        self.session.claims.refresh_after_withdrawal()
        for claim in self.session.claims.claims():
            catalog["claim:" + claim.claim_id] = {"kind": "remaining", "claim": claim.data()}
        for root in self.session.evidence.roots(admitted_only=False, active_only=False):
            catalog["evidence:" + root.root_id] = {"kind": "anomaly", "observation": root.data(), "anomaly_confirmed": False}
        for event in self.session._events:
            row = event.data()
            if row["stage"] in {"audit_rejected", "model_failure"} or (row["stage"] == "execution_result" and row["data"]["status"] != "succeeded"):
                catalog["check:" + event.content_hash] = {"kind": "failed_check", "trace": row}
        if isinstance(plan_ids, (str, bytes)) or len(set(plan_ids)) != len(plan_ids):
            raise ContractError("frontier prediction plans must be unique")
        for plan_id in plan_ids:
            plan = self.predictions.plan(plan_id)
            updates = self.predictions.updates(plan_id)
            catalog["plan:" + plan_id] = {"kind": "remaining" if updates else "untested", "plan": plan.data(),
                                          "updates": [update.data() for update in updates]}
        frozen_catalog = FrozenRecord.from_dict(catalog)
        response = self.invoke_model(slot, model, instruction="Audit the remaining research frontier. Proposals must cite supplied origins and describe a discriminating observation. An empty frontier does not complete the research programme. Never generate or admit this experiment's evaluation tasks.",
            module_context=FrozenRecord.from_dict({"frontier_catalog": catalog, "catalog_digest": frozen_catalog.content_hash,
                "authority": "proposals_only", "queue_admission": False, "benchmark_admission": False}))
        try:
            result = validate_frontier(response, frozen_catalog, self.session.task.identity)
        except ContractError as exc:
            self._trace("frontier", "rejected", response_digest=response.content_hash, reason=str(exc))
            raise
        self.frontier_result = result
        return self._trace("frontier", "executed", result=result.data(), response_digest=response.content_hash,
                           catalog_digest=frozen_catalog.content_hash, slot=slot)

    def training_followups(self) -> FrozenRecord:
        """Export proposals only on training; no method admits benchmark tasks."""
        self.session.task.identity.require_train()
        if self.frontier_result is None:
            raise ContractError("frontier has not been audited")
        return self.frontier_result
    def m9_policy(self, policy: FrozenRecord | None, *, receipt: AcceptanceReceipt | None = None,
                  candidate: CandidatePackage | None = None) -> WorkflowResult:
        if "M9" not in self.enabled:
            return self._trace("operation_m9_policy", "blocked", module="M9", reason="module_not_enabled",
                               policy_digest=policy.content_hash if policy else None)
        if self.deployment is None or receipt is None or candidate is None:
            return self._trace("operation_m9_policy", "blocked", module="M9", reason="deployment_activation_missing",
                               policy_digest=policy.content_hash if policy else None)
        if candidate.digest != self.session.lock.data()["package_digest"]:
            return self._trace("operation_m9_policy", "blocked", module="M9", reason="candidate_lock_mismatch",
                               candidate_digest=candidate.digest, policy_digest=policy.content_hash if policy else None)
        ack = self.deployment.activate(receipt, candidate)
        return self._trace("operation_m9_policy", "executed", package_digest=ack.active_digest,
                           memory_digest=ack.memory_digest, policy_digest=policy.content_hash if policy else None)




