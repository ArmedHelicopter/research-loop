"""Typed registry for the 48 modular research obligations.

This registry makes an obligation executable as a controlled public fixture and
auditable as a state transition.  It does not manufacture a benchmark run.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from research_loop.modular.contracts import DataIdentity, FrozenRecord, required_text
from research_loop.ontology import ContractError, digest

STATES = ("designed", "implemented", "integration_verified", "train_measured", "candidate_frozen", "validation_measured", "accepted", "rejected", "inconclusive", "blocked")
TERMINAL = {"accepted", "rejected", "inconclusive", "blocked"}
BENCHMARKS = {"discoverybench", "blade"}

# Explicit rows retain all coverage IDs rather than deriving a completion count
# from module-level status.  endpoint names are interfaces, not claims that the
# corresponding runtime mechanism already exists.
_ROWS = (
 ("Q1.1",("M3",),"history",("correct","wrong","neutral"),"context_rebuild",False),("Q1.2",("M2","M3"),"dependency",("summary_only","registered","withdraw"),"claim_revision_context",False),("Q1.3",("M2",),"evidence_duplicate",("log","report","summary","memory"),"evidence_root_dedup",False),("Q1.4",("M2",),"support_chain",("one_withdrawn","all_withdrawn","copies"),"support_recheck",False),("Q1.5",("M5",),"review_order",("blind_first","summary_first"),"sealed_review",False),("Q1.6",("M1","M2"),"withdrawal",("replacement","none","high_score"),"claim_withdraw",False),("Q1.7",("M3",),"time_information",("irrelevant","causal","unknown"),"context_rebuild",False),
 ("Q2.1",("M1","M5"),"pressure",("neutral","positive","negative"),"admission_review",False),("Q2.2",("P0",),"completion_semantics",("affirm","negate","quote","counterfactual","local"),"completion_scorer",False),("Q2.3",("M1",),"audit_fault",("false","string_false","empty","duplicate","unknown","missing","parse_error"),"runner_admission",False),("Q2.4",("M1",),"audit_pair",("one_fail","both_fail","disagree","same_wrong"),"dual_audit",False),("Q2.5",("M1",),"evidence_polarity",("invalid_positive","invalid_negative","valid_negative"),"evidence_admission",False),("Q2.6",("M1",),"goal_lock",("secondary_win","maintenance","late_pivot"),"goal_lock",False),("Q2.7",("P0",),"protocol_trace",("missing_lock","missing_execution","missing_audit","illegal_state"),"trace_validator",False),
 ("Q3.1",("M4",),"hypothesis_tension",("mechanism","computation","measurement"),"prediction_matrix",False),("Q3.2",("M4",),"arm_structure",("joint","separate"),"multiarm_plan",True),("Q3.3",("M8",),"fifo_workers",("one_worker","k_workers"),"fifo_scheduler",False),("Q3.4",("M8",),"completion_order",("favorable_first","unfavorable_first"),"merge_barrier",False),("Q3.5",("M8",),"recovery_fault",("write_conflict","withdrawal","crash","expiry","duplicate"),"lease_recovery",False),
 ("Q4.1",("M4","M5"),"independence",("single","independent_samples","roles"),"sealed_review",False),("Q4.2",("M5",),"review_role",("mechanism","alternative","measurement","experiment","generic"),"sealed_review",False),("Q4.3",("M5",),"submission_order",("sealed_then_exchange","sequential"),"sealed_review",False),("Q4.4",("M5",),"counterexample",("none_valid","defective"),"sealed_review",False),("Q4.5",("M5",),"self_correction",("right_to_wrong","wrong_to_right","heterogeneous"),"sealed_review",False),
 ("Q5.1",("M7",),"feasibility",("subjective","data","minimal_run","measurement","independent"),"feasibility_stages",False),("Q5.2",("M4","M7"),"distinguishability",("zero_exit_same_prediction","negative_control"),"feasibility_stages",False),("Q5.3",("M4",),"dedup",("same_mechanism","opposite_prediction","title"),"prediction_matrix",False),("Q5.4",("M4","M7"),"diagnostic_choice",("subjective","preregistered_cost"),"exploration_admission",False),("Q5.5",("M6","M7"),"resource_closure",("missing_data","missing_method","missing_budget","missing_control"),"resource_closure",False),
 ("Q6.1",("P0","M9"),"authority",("change_rule","read_validation","forge_receipt","self_activate"),"custody_boundary",False),("Q6.2",("M9",),"transfer",("fixed","manual_train","automatic_train"),"candidate_builder",False),("Q6.3",("M9",),"meta_builder",("fixed","train_proposed"),"meta_candidate_builder",False),("Q6.4",("P0",),"scorer_repair",("negation","quotation","alternative"),"scorer_versioning",False),("Q6.5",("M9",),"feedback_loop",("unprotected","sealed_calibrated"),"promotion_guard",False),("Q6.6",("M9",),"deployment",("promote","rollback","drift","offline","duplicate"),"deployment_ack",False),
 ("Q7.1",("M1","M7"),"exploration_case",("low_cost","data_unknown","measurement_repair","valid_negative","conflict"),"exploration_admission",False),("Q7.2",("M7",),"veto",("deterministic","insufficient","value"),"veto_appeal",False),("Q7.3",("M7",),"ratio",("zero","low","medium","high"),"train_ratio_selection",False),("Q7.4",("M1","M7"),"instrument_repair",("invalid_measure","repair","old_evidence"),"instrument_repair",False),("Q7.5",("M1","M2"),"four_dimensions",("valid_known","novel_refuted","infeasible","easy_valid"),"state_separation",False),("Q7.6",("M1","M5"),"contract_science",("contract_only","real_counterexample"),"scientific_review",False),
 ("Q8.1",("P0","M6","M5"),"protocol_stage",("research","competition","distinguish","adversarial","retrospective","frontier"),"stage_trace",False),("Q8.2",("M6",),"retrieval_contribution",("correct","method","reframe"),"three_lane_retrieval",False),("Q8.3",("M6",),"retrieval_mode",("support_only","neutral","three_lane"),"three_lane_retrieval",False),("Q8.4",("M6","M2"),"source_independence",("shared_root","independent_roots"),"source_root_dedup",False),("Q8.5",("M6",),"retrieval_trigger",("always","never","new_mechanism","conflict","innovation","dependency_unknown","stagnation"),"retrieval_trigger_policy",False),("Q8.6",("M1","M6"),"retrieval_authority",("conflict","malicious_override","pause_new_version"),"goal_lock",False),("Q8.7",("M4","M5"),"frontier",("remaining","failed_check","untested","anomaly","empty"),"frontier_audit",False),
)

@dataclass(frozen=True)
class ExperimentSpec:
    experiment_id: str; modules: tuple[str,...]; scenario_kind: str; variants: tuple[str,...]; endpoint: str; combination: bool
    def __post_init__(self) -> None:
        required_text(self.experiment_id,"experiment id")
        if not self.modules or not self.variants: raise ContractError("experiment needs modules and variants")
    @property
    def record(self) -> FrozenRecord:
        return FrozenRecord.from_dict({"experiment_id":self.experiment_id,"modules":list(self.modules),"module_switches":{module:["off","on"] for module in self.modules},"scenario_kind":self.scenario_kind,"variants":list(self.variants),"endpoint":self.endpoint,"comparison_mode":"combination" if self.combination else "standalone_or_conditional","required_benchmarks":["discoverybench","blade"]})

def registry() -> Mapping[str, ExperimentSpec]:
    result={row[0]:ExperimentSpec(*row) for row in _ROWS}
    if len(result)!=48: raise ContractError("registry must contain exactly 48 unique experiments")
    return result

@dataclass(frozen=True)
class ControllerInputs:
    task: FrozenRecord; evidence: FrozenRecord; budget: FrozenRecord

def scenario(spec: ExperimentSpec, variant: str, *, inputs: ControllerInputs) -> FrozenRecord:
    if variant not in spec.variants: raise ContractError("variant is not registered")
    base={"task":inputs.task.content_hash,"evidence":inputs.evidence.content_hash,"budget":inputs.budget.content_hash}
    if spec.experiment_id=="Q1.1": injection={"history":{"correct":"fixture-supported","wrong":"fixture-withdrawn","neutral":"fixture-none"}[variant]}
    elif spec.experiment_id=="Q2.1": injection={"pressure":{"neutral":"apply_frozen_rule","positive":"seek_support_only_if_justified","negative":"seek_refutation_only_if_justified"}[variant]}
    elif spec.experiment_id=="Q2.3": injection={"audit":{"false":False,"string_false":"false","empty":[],"duplicate":["x","x"],"unknown":{"status":"unknown"},"missing":{"status":"proceed"},"parse_error":"{invalid"}[variant]}
    else: raise ContractError(f"blocked_endpoint_not_implemented:{spec.endpoint}")
    return FrozenRecord.from_dict({"experiment_id":spec.experiment_id,"variant":variant,"controller_input":injection,"base":base,"controls":{"same_task":True,"same_evidence":True,"same_budget":True}})

@dataclass(frozen=True)
class RunReceipt:
    benchmark: str; identity: DataIdentity; scenario_hash: str; arms: tuple[str,...]; module_switches: tuple[str,...]; package_digest: str; scorer_digest: str; trace_digest: str; run_digest: str
    def __post_init__(self) -> None:
        if self.benchmark not in BENCHMARKS or self.identity.domain not in {"train","validation"} or self.identity.benchmark!=self.benchmark: raise ContractError("invalid benchmark receipt")
        for value in (self.scenario_hash,self.package_digest,self.scorer_digest,self.trace_digest,self.run_digest): required_text(value,"receipt digest")
        if not self.arms or len(set(self.arms))!=len(self.arms) or len(set(self.module_switches))!=len(self.module_switches): raise ContractError("receipt needs unique arms and switches")

@dataclass(frozen=True)
class ExperimentLedger:
    entries: FrozenRecord
    @classmethod
    def create(cls) -> "ExperimentLedger":
        return cls(FrozenRecord.from_dict({key:{"status":"designed","spec_hash":value.record.content_hash,"history":[]} for key,value in registry().items()}))
    def data(self)->dict[str,object]: return self.entries.data()
    def transition(self, experiment_id:str, target:str, *, implementation_ref:str|None=None, scenario_record:FrozenRecord|None=None, receipts:tuple[RunReceipt,...]=(), blocked_reason:str|None=None) -> "ExperimentLedger":
        if target not in STATES: raise ContractError("unknown experiment state")
        specs=registry(); spec=specs.get(experiment_id)
        if spec is None: raise ContractError("unknown experiment id")
        data=self.entries.data(); current=data[experiment_id]["status"]
        if current in TERMINAL and current!="blocked": raise ContractError("terminal experiment cannot transition")
        order={state:i for i,state in enumerate(STATES[:7])}
        if target in order and current in order and order[target] != order[current]+1: raise ContractError("invalid experiment state transition")
        if target=="implemented" and not implementation_ref: raise ContractError("implemented requires implementation reference")
        if target=="integration_verified" and not implementation_ref: raise ContractError("integration verification requires trace reference")
        if target == "blocked" and not blocked_reason: raise ContractError("blocked requires an explicit reason")
        if target in {"train_measured","validation_measured"}:
            if scenario_record is None: raise ContractError("measurement requires frozen scenario")
            self._validate_receipts(spec, scenario_record, receipts, "train" if target=="train_measured" else "validation")
        if target in {"accepted","rejected","inconclusive"}: raise ContractError("scientific decision requires independent verifier")
        data[experiment_id]={"status":target,"spec_hash":spec.record.content_hash,"history":data[experiment_id]["history"]+[{"from":current,"to":target,"implementation_ref":implementation_ref,"scenario_hash":scenario_record.content_hash if scenario_record else None,"receipt_hashes":[receipt.run_digest for receipt in receipts],"blocked_reason":blocked_reason}]}
        return ExperimentLedger(FrozenRecord.from_dict(data))
    @staticmethod
    def _validate_receipts(spec:ExperimentSpec, scenario_record:FrozenRecord, receipts:tuple[RunReceipt,...], domain:str)->None:
        if {receipt.benchmark for receipt in receipts} != BENCHMARKS: raise ContractError("measurement needs both benchmark receipts")
        scenario_variant = scenario_record.data().get("variant")
        if scenario_record.data().get("experiment_id") != spec.experiment_id or scenario_variant not in spec.variants:
            raise ContractError("scenario does not bind registered experiment")
        groups=set()
        for receipt in receipts:
            if receipt.identity.domain != domain or receipt.scenario_hash != scenario_record.content_hash: raise ContractError("receipt domain or scenario binding mismatch")
            if scenario_variant not in receipt.arms: raise ContractError("receipt arms do not bind registered scenario")
            if set(receipt.module_switches) != {f"{module}:on" for module in spec.modules}: raise ContractError("receipt module switches do not bind registered experiment")
            groups.add(receipt.identity.group_id)
        if len(groups)!=2: raise ContractError("benchmark receipts need distinct task groups")
