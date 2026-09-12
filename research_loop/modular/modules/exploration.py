"""M7: train-only, budgeted exploration without changing FIFO or evidence rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from research_loop.modular.contracts import DataIdentity, FrozenRecord, required_text
from research_loop.ontology import ContractError, digest

STAGES = ("data", "minimal_run", "discriminating_measurement", "independent_result")
VETOES = ("deterministic_block", "evidence_insufficient", "value_doubt")


@dataclass(frozen=True)
class ResourceClosure:
    data_version: str
    minimum_artifact_digest: str
    negative_control_id: str
    execution_units: int
    token_units: int

    def __post_init__(self) -> None:
        for field in ("data_version", "minimum_artifact_digest", "negative_control_id"):
            required_text(getattr(self, field), field)
        if not isinstance(self.execution_units, int) or not isinstance(self.token_units, int) or self.execution_units < 0 or self.token_units < 0:
            raise ContractError("resource closure budgets must be nonnegative integers")


@dataclass(frozen=True)
class ExplorationPlan:
    plan_id: str
    identity: DataIdentity
    frozen_plan: FrozenRecord
    closure: ResourceClosure

    def __post_init__(self) -> None:
        required_text(self.plan_id, "plan id")
        if not isinstance(self.identity, DataIdentity) or not isinstance(self.frozen_plan, FrozenRecord):
            raise ContractError("exploration plan needs frozen identity and plan")
        # A frozen plan may execute a bounded diagnostic against its current
        # validation task.  Only candidate selection and strategy learning are
        # train-only; this object carries no cross-task feedback channel.

    @property
    def content_hash(self) -> str:
        return digest({"plan_id": self.plan_id, "identity": self.identity.data(),
                       "frozen_plan": self.frozen_plan.data(), "closure": self.closure.__dict__})


@dataclass(frozen=True)
class FeasibilityObservation:
    stage: str
    status: str  # passed, failed, unknown
    artifact_digest: str
    independent_source_group: str | None = None

    def __post_init__(self) -> None:
        if self.stage not in STAGES or self.status not in {"passed", "failed", "unknown"}:
            raise ContractError("invalid feasibility observation")
        required_text(self.artifact_digest, "artifact digest")
        if self.stage == "independent_result" and self.status == "passed" and not self.independent_source_group:
            raise ContractError("independent result needs independent source group")


@dataclass(frozen=True)
class FeasibilityReport:
    plan_digest: str
    stages: Mapping[str, str]
    next_stage: str | None

    @property
    def is_ready(self) -> bool:
        return all(self.stages.get(stage) == "passed" for stage in STAGES)


def assess_feasibility(plan: ExplorationPlan, observations: Mapping[str, FeasibilityObservation]) -> FeasibilityReport:
    """Advance one explicit stage at a time; a zero-exit run cannot skip measurement."""
    states: dict[str, str] = {}
    blocked = False
    next_stage: str | None = None
    for stage in STAGES:
        observation = observations.get(stage)
        if blocked:
            states[stage] = "blocked"
            continue
        if observation is None:
            states[stage] = "pending"
            if next_stage is None:
                next_stage = stage
            blocked = True
            continue
        if observation.stage != stage:
            raise ContractError("feasibility observation stage mismatch")
        states[stage] = observation.status
        if observation.status != "passed":
            if next_stage is None:
                next_stage = stage
            blocked = True
    return FeasibilityReport(plan.content_hash, states, next_stage)


def select_claimed_diagnostic(plan: ExplorationPlan, policy: FrozenRecord,
                              candidates: tuple[FrozenRecord, ...]) -> FrozenRecord:
    """Select a bounded diagnostic inside a previously claimed item.

    This is an execution-time choice, not strategy optimization, and may run on
    either domain.  Training-only tuning of a criterion remains a separate API.
    """
    policy_data = policy.data() if isinstance(policy, FrozenRecord) else {}
    if set(policy_data) != {"policy_version", "identity", "criterion", "frozen_before_validation"}:
        raise ContractError("diagnostic selection requires a frozen bound policy")
    if policy_data["identity"] != plan.identity.data() or policy_data["criterion"] not in {"subjective", "uncertainty_per_cost"}:
        raise ContractError("diagnostic policy does not bind the claimed plan")
    if plan.identity.domain == "validation" and policy_data["frozen_before_validation"] is not True:
        raise ContractError("validation diagnostic policy was not frozen before validation")
    if not candidates:
        raise ContractError("diagnostic selection needs candidates")
    rows = [item.data() for item in candidates]
    required = {"diagnostic_id", "subjective_score", "uncertainty_reduction", "cost"}
    if any(set(row) != required or type(row["cost"]) not in {int, float} or row["cost"] <= 0 for row in rows):
        raise ContractError("diagnostic candidates are invalid")
    if policy_data["criterion"] == "subjective":
        chosen = max(zip(rows, candidates), key=lambda pair: (pair[0]["subjective_score"], pair[0]["diagnostic_id"]))
    else:
        chosen = max(zip(rows, candidates), key=lambda pair: (pair[0]["uncertainty_reduction"] / pair[0]["cost"], pair[0]["diagnostic_id"]))
    return chosen[1]


@dataclass(frozen=True)
class Veto:
    kind: str
    reason: str
    evidence_digest: str

    def __post_init__(self) -> None:
        if self.kind not in VETOES:
            raise ContractError("invalid veto kind")
        required_text(self.reason, "veto reason")
        required_text(self.evidence_digest, "veto evidence digest")


@dataclass(frozen=True)
class Appeal:
    veto: Veto
    smaller_diagnostic: FrozenRecord
    proposed_execution_units: int
    proposed_token_units: int
    repair_digest: str | None = None

    def __post_init__(self) -> None:
        if self.proposed_execution_units < 0 or self.proposed_token_units < 0:
            raise ContractError("appeal budget must be nonnegative")
        if self.veto.kind == "deterministic_block" and not self.repair_digest:
            raise ContractError("deterministic veto appeal needs a repair digest")


@dataclass(frozen=True)
class ExplorationBudget:
    execution_limit: int
    token_limit: int
    execution_used: int = 0
    token_used: int = 0

    def __post_init__(self) -> None:
        values = (self.execution_limit, self.token_limit, self.execution_used, self.token_used)
        if any(not isinstance(value, int) or value < 0 for value in values) or self.execution_used > self.execution_limit or self.token_used > self.token_limit:
            raise ContractError("invalid exploration budget")

    def reserve(self, execution: int, tokens: int) -> "ExplorationBudget":
        if execution < 0 or tokens < 0 or self.execution_used + execution > self.execution_limit or self.token_used + tokens > self.token_limit:
            raise ContractError("exploration budget exhausted")
        return ExplorationBudget(self.execution_limit, self.token_limit, self.execution_used + execution, self.token_used + tokens)


@dataclass(frozen=True)
class ExplorationPermit:
    plan_digest: str
    diagnostic_digest: str
    veto_kind: str | None
    budget_after: ExplorationBudget
    evidence_admission: str = "not_evidence"


def admit_exploration(*, plan: ExplorationPlan, feasibility: FeasibilityReport,
                      budget: ExplorationBudget) -> ExplorationPermit:
    """Issue a bounded diagnostic permit after data closure, without queue control."""
    if feasibility.plan_digest != plan.content_hash:
        raise ContractError("feasibility report does not bind exploration plan")
    if feasibility.stages.get("data") != "passed" or feasibility.next_stage is None:
        raise ContractError("exploration requires a passed data stage and pending diagnostic")
    after = budget.reserve(plan.closure.execution_units, plan.closure.token_units)
    diagnostic = digest({"plan": plan.content_hash, "stage": feasibility.next_stage,
                         "negative_control": plan.closure.negative_control_id})
    return ExplorationPermit(plan.content_hash, diagnostic, None, after)


@dataclass(frozen=True)
class AppealDecision:
    status: str  # diagnostic_permitted or requires_reassessment
    veto_kind: str
    permit: ExplorationPermit | None


def review_appeal(*, plan: ExplorationPlan, veto: Veto, appeal: Appeal,
                  budget: ExplorationBudget) -> AppealDecision:
    """Review all three veto types without using appeal to bypass hard blocks."""
    if appeal.veto != veto:
        raise ContractError("appeal does not bind veto")
    if appeal.proposed_execution_units > plan.closure.execution_units or appeal.proposed_token_units > plan.closure.token_units:
        raise ContractError("appeal is not smaller than the frozen plan")
    if veto.kind == "deterministic_block":
        # A repair must be independently re-assessed; this permit cannot bypass
        # an authorization, resource, or contract block.
        return AppealDecision("requires_reassessment", veto.kind, None)
    after = budget.reserve(appeal.proposed_execution_units, appeal.proposed_token_units)
    permit = ExplorationPermit(plan.content_hash, appeal.smaller_diagnostic.content_hash, veto.kind, after)
    return AppealDecision("diagnostic_permitted", veto.kind, permit)


def appeal_veto(*, plan: ExplorationPlan, veto: Veto, appeal: Appeal,
                budget: ExplorationBudget) -> ExplorationPermit:
    """Return only a usable diagnostic permit for the two non-hard vetoes."""
    decision = review_appeal(plan=plan, veto=veto, appeal=appeal, budget=budget)
    if decision.permit is None:
        raise ContractError("deterministic block requires repaired plan reassessment")
    return decision.permit


@dataclass(frozen=True)
class ExplorationRatioCandidate:
    ratio_id: str
    train_identity: DataIdentity
    exploration_percent: int

    def __post_init__(self) -> None:
        required_text(self.ratio_id, "ratio id")
        self.train_identity.require_train()
        if not isinstance(self.exploration_percent, int) or not 0 <= self.exploration_percent <= 100:
            raise ContractError("exploration percentage must be 0..100")


@dataclass(frozen=True)
class InstrumentRepair:
    instrument_id: str
    prior_instrument_digest: str
    repair_digest: str
    invalidated_evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for field in ("instrument_id", "prior_instrument_digest", "repair_digest"):
            required_text(getattr(self, field), field)
        if not self.invalidated_evidence_ids or any(not value for value in self.invalidated_evidence_ids):
            raise ContractError("repair must name invalidated evidence")

    def requires_new_execution(self, evidence_id: str) -> bool:
        return evidence_id in self.invalidated_evidence_ids
