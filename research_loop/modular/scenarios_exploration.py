"""Fixture-only runnable scenarios for Q7.1--Q7.6.

The scenarios call the M1, M2, M5, and M7 interfaces on a caller-provided
``PublicTask``.  Controller-only synthetic facts are never sent to callbacks;
these are engineering mechanism checks, not benchmark measurements or claims
about scientific truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask, required_text
from research_loop.modular.modules.admission import AuditItem, EvidenceAdmission, ExplorationPolicy, ScientificState
from research_loop.modular.modules.evidence import ClaimLedger, EvidenceLedger
from research_loop.modular.modules.exploration import (
    Appeal, ExplorationBudget, ExplorationPlan, ExplorationRatioCandidate,
    FeasibilityObservation, InstrumentRepair, ResourceClosure, Veto,
    admit_exploration, review_appeal,
)
from research_loop.modular.modules.review import ReviewEngine
from research_loop.modular.runtime import AuditAuthority, AuditVerifier, RunSession
from research_loop.ontology import ContractError, digest


_VARIANTS = {
    "Q7.1": frozenset(("low_cost", "data_unknown", "measurement_repair", "valid_negative", "conflict")),
    "Q7.2": frozenset(("deterministic", "insufficient", "value")),
    "Q7.3": frozenset(("zero", "low", "medium", "high")),
    "Q7.4": frozenset(("invalid_measure", "repair", "old_evidence")),
    "Q7.5": frozenset(("valid_known", "novel_refuted", "infeasible", "easy_valid")),
    "Q7.6": frozenset(("contract_only", "real_counterexample")),
}


@dataclass(frozen=True)
class ExplorationScenarioResult:
    experiment_id: str
    variant: str
    next_payload: FrozenRecord
    mechanism_trace: FrozenRecord
    controller_record: FrozenRecord
    review_payloads: tuple[FrozenRecord, ...] = ()
    next_model_response: FrozenRecord | None = None


def exploration_injection(experiment_id: str, variant: str) -> Mapping[str, Any]:
    """Return only a closed fixture manipulation descriptor for the registry."""
    _validate(experiment_id, variant)
    return {"fixture_only": True, "fixture_notice": "synthetic fixture truth; not a benchmark effect",
            "auxiliary": {"experiment": experiment_id, "variant": variant,
                          "same_task_budget_across_arms": True}}


def select_train_ratio(*, identity: DataIdentity, rows: Sequence[Mapping[str, Any]]) -> FrozenRecord:
    """Select one finite predeclared ratio from train rows only.

    Provenance is checked before looking at a score row, so a validation caller
    cannot use this helper to inspect validation feedback.
    """
    identity.require_train()
    if not rows:
        raise ContractError("ratio selection needs finite train score rows")
    candidates: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {"ratio_id", "exploration_percent", "diagnostics", "waste", "task_units"}:
            raise ContractError("ratio score row has unexpected fields")
        candidate = ExplorationRatioCandidate(str(row["ratio_id"]), identity, row["exploration_percent"])
        if any(type(row[key]) is not int or row[key] < 0 for key in ("diagnostics", "waste", "task_units")):
            raise ContractError("ratio score values must be nonnegative integers")
        candidates.append({"ratio_id": candidate.ratio_id, "exploration_percent": candidate.exploration_percent,
                           "diagnostics": row["diagnostics"], "waste": row["waste"], "task_units": row["task_units"]})
    if len({row["ratio_id"] for row in candidates}) != len(candidates):
        raise ContractError("ratio candidates must have unique ids")
    # The ranking is deliberately finite and deterministic; it does not assert
    # a universal correct percentage.
    selected = min(candidates, key=lambda row: (-row["diagnostics"], row["waste"], -row["task_units"], row["ratio_id"]))
    return FrozenRecord.from_dict({"schema": "fixture-train-ratio-selection-v1", "fixture_only": True,
                                   "identity": identity.data(), "candidates": candidates, "selected": selected,
                                   "selection_scope": "train_only"})


def run_exploration_scenario(
    experiment_id: str,
    variant: str,
    *,
    task: PublicTask,
    frozen_controls: FrozenRecord,
    next_model: Callable[[FrozenRecord], Any] | None = None,
    review_model: Callable[[FrozenRecord], Mapping[str, Any]] | None = None,
    sidecar: Path | None = None,
    broker: DockerExecutionBroker | None = None,
) -> ExplorationScenarioResult:
    """Run one Q7 fixture through real module ports and prepare its next call."""
    _validate(experiment_id, variant)
    controls = _controls(task, frozen_controls)
    trace: list[dict[str, Any]] = [{"event": "fixture_start", "fixture_only": True,
                                    "task_digest": task.content_hash, "budget_digest": controls["budget_digest"]}]
    auxiliary, private, review_payloads = _apply(experiment_id, variant, task, trace, review_model, sidecar, broker)
    payload = FrozenRecord.from_dict({"schema": "exploration-scenario-next-model-v1", "fixture_only": True,
                                       "task": task.data(), "frozen_controls": controls,
                                       "experiment_id": experiment_id, "variant": variant,
                                       "scenario_auxiliary": auxiliary,
                                       "mechanism_trace_digest": digest(trace)})
    response_record = None
    if next_model is None:
        trace.append({"event": "next_model_payload_prepared", "payload_digest": payload.content_hash})
    else:
        response_record = _response_record(next_model(payload))
        trace.append({"event": "next_model_invoked", "payload_digest": payload.content_hash,
                      "response_digest": response_record.content_hash})
    return ExplorationScenarioResult(experiment_id, variant, payload,
                                     FrozenRecord.from_dict({"events": trace}),
                                     FrozenRecord.from_dict(private), tuple(review_payloads), response_record)


def _apply(experiment_id: str, variant: str, task: PublicTask, trace: list[dict[str, Any]],
           review_model: Callable[[FrozenRecord], Mapping[str, Any]] | None,
           sidecar: Path | None, broker: DockerExecutionBroker | None) -> tuple[dict[str, Any], dict[str, Any], list[FrozenRecord]]:
    identity, bindings = task.identity, _bindings(task)
    audits = [AuditItem("measurement", True, True)]
    auxiliary: dict[str, Any] = {"fixture_only": True}
    private: dict[str, Any] = {"fixture_only": True, "controller_ground_truth_private": True}
    review_payloads: list[FrozenRecord] = []
    if experiment_id == "Q7.1":
        state = {"low_cost": ScientificState("unknown", "undetermined", "unknown", "explore"),
                 "data_unknown": ScientificState("unknown", "undetermined", "unknown", "explore"),
                 "measurement_repair": ScientificState("invalid", "undetermined", "unknown", "repair"),
                 "valid_negative": ScientificState("valid", "refuted", "known", "explore"),
                 "conflict": ScientificState("unknown", "undetermined", "unknown", "explore")}[variant]
        policy = ExplorationPolicy.admit(identity=identity, state=state, safe=True, budget_available=True,
                                         subject_bindings=bindings, required_audit=["measurement"], audit=audits)
        admission = EvidenceAdmission.decide(identity=identity, state=state,
                                             outcome="negative" if variant == "valid_negative" else "positive",
                                             execution_success=True, trusted_validator="fixture-validator",
                                             validator_verified=True, evidence_ids=["fixture-evidence"],
                                             subject_bindings=bindings, required_audit=["measurement"], audit=audits)
        feasibility = _feasibility(_plan(task), data_status="unknown" if variant == "data_unknown" else "passed")
        permit = None
        if feasibility.stages["data"] == "passed":
            permit = admit_exploration(plan=_plan(task), feasibility=feasibility, budget=ExplorationBudget(4, 20))
        conflict_review = None
        if variant == "conflict":
            engine = ReviewEngine(identity)
            review = engine.open(task_binding=task.content_hash, evidence_snapshot="fixture-conflicting-observations",
                                 budget_units=2, roles=[{"role_id": "conflict", "question": "Reconcile the two bounded conflicting observations."}])
            review_payload = FrozenRecord.from_dict({"schema": "exploration-conflict-review-v1", "fixture_only": True,
                "task": task.data(), "observations": ["fixture-support", "fixture-refute"], "review": review.payload.data()})
            review_payloads.append(review_payload)
            response = review_model(review_payload) if review_model else {"assessment": "unknown", "evidence_refs": ["fixture-support", "fixture-refute"],
                "counterexamples": [], "uncertainty": "conflicting fixture observations require stronger review"}
            conflict_review = engine.submit(review.review_id, role_id="conflict", reviewer_id="fixture-reviewer", response=response, cost_units=2)
        auxiliary.update({"exploration_allowed": policy.allowed, "evidence_admitted": admission.admitted,
                          "evidence_admission": "admitted" if admission.admitted else "blocked",
                          "m7_diagnostic": permit.diagnostic_digest if permit else None,
                          "feasibility_next_stage": feasibility.next_stage,
                          "enhanced_conflict_review": conflict_review.before_hash if conflict_review else None})
        trace.append({"event": "exploration_and_evidence_separated", "policy_allowed": policy.allowed,
                      "evidence_admitted": admission.admitted, "m7_permit": permit is not None})
    elif experiment_id == "Q7.2":
        kind = {"deterministic": "deterministic_block", "insufficient": "evidence_insufficient", "value": "value_doubt"}[variant]
        veto = Veto(kind, "fixture veto", "fixture-veto-evidence")
        appeal = Appeal(veto, FrozenRecord.from_dict({"fixture": "smaller-diagnostic"}), 1, 5,
                        repair_digest="fixture-repair" if kind == "deterministic_block" else None)
        decision = review_appeal(plan=_plan(task), veto=veto, appeal=appeal, budget=ExplorationBudget(4, 20))
        auxiliary.update({"veto_kind": kind, "appeal_status": decision.status,
                          "permit": decision.permit.diagnostic_digest if decision.permit else None})
        trace.append({"event": "appeal_reviewed", "veto_kind": kind, "status": decision.status})
    elif experiment_id == "Q7.3":
        # Selection is an optimization operation.  It refuses validation before
        # allocating, executing, or inspecting any candidate receipt.
        identity.require_train()
        root = _require_execution_root(sidecar, broker, "Q7.3")
        rows, allocations = _run_ratio_candidates(task, root, broker)
        selected = select_train_ratio(identity=identity, rows=rows)
        requested = {"zero": 0, "low": 10, "medium": 30, "high": 60}[variant]
        arm = next(row for row in allocations if row["ratio_id"] == variant)
        auxiliary.update({"candidate_ratio": requested, "selection_digest": selected.content_hash,
                          "selection_scope": "train_only", "allocation": arm,
                          "same_budget": {"execution": 4, "tokens": "not_exercised"}})
        private["train_ratio_selection"] = selected.data()
        private["execution_allocations"] = allocations
        trace.append({"event": "finite_train_ratio_selected", "selection_digest": selected.content_hash,
                      "candidate_ratio": requested, "receipt_derived": True})
    elif experiment_id == "Q7.4":
        root = _require_execution_root(sidecar, broker, "Q7.4")
        repair, session, old_execution, old_admission, old_root = _run_invalid_instrument(task, root, broker, variant)
        new_execution, new_admission = (None, None)
        if variant == "repair":
            new_execution, new_admission = _run_repaired_instrument(session, broker)
        auxiliary.update({"repair_digest": repair.repair_digest, "old_execution": old_execution.content_hash,
                          "old_evidence_admitted": old_admission.data()["admitted"],
                          "old_root_active_after_withdrawal": session.evidence.is_active_admitted(old_root),
                          "old_requires_new_execution": repair.requires_new_execution(old_execution.content_hash),
                          "new_execution": new_execution.content_hash if new_execution else None,
                          "new_evidence_admitted": new_admission.data()["admitted"] if new_admission else None})
        trace.append({"event": "instrument_invalidated_old_evidence", "old_admitted": old_admission.data()["admitted"],
                      "new_execution_required": repair.requires_new_execution(old_execution.content_hash),
                      "new_execution": new_execution.content_hash if new_execution else None})
    elif experiment_id == "Q7.5":
        state = {"valid_known": ScientificState("valid", "supported", "known", "explore"),
                 "novel_refuted": ScientificState("valid", "refuted", "known", "stop"),
                 "infeasible": ScientificState("unknown", "undetermined", "unknown", "repair"),
                 "easy_valid": ScientificState("valid", "supported", "known", "explore")}[variant]
        evidence = EvidenceLedger(identity)
        root = evidence.append({"kind": "measurement", "root_material": {"fixture": variant}, "representation": "raw",
                                "content": {"fixture_only": True}, "subject_bindings": bindings,
                                "independent_group": identity.group_id},
                               {"trusted_validator": "fixture-validator", "validator_verified": True, "admitted": state.validity == "valid"})
        claims = ClaimLedger(evidence)
        claim = claims.create("fixture observation", subject_bindings=bindings)
        relation = claims.apply(claim.claim_id, {"supports": [root.root_id] if state.support == "supported" else [],
                                                 "refutes": [root.root_id] if state.support == "refuted" else [],
                                                 "subject_bindings": bindings}, expected_revision=claim.revision).claim
        novelty_transition = None
        if variant == "novel_refuted":
            novelty_transition = {"before": "novel", "after": "known", "reason": "fixture prior-art withdrawal",
                                  "observation_root_retained": evidence.is_active_admitted(root.root_id)}
            trace.append({"event": "novelty_withdrawn_observation_retained", **novelty_transition})
        auxiliary.update({"state": state.__dict__, "claim_status": relation.status,
                          "active_root_count": len(evidence.roots()), "novelty_transition": novelty_transition})
        trace.append({"event": "four_dimensions_preserved", "state": state.__dict__, "claim_status": relation.status})
    else:  # Q7.6
        # Authentic M1 contract success has no semantic-truth field.  M5 exposes
        # an actual reviewer response, which can retain unknown or name a counterexample.
        contract = EvidenceAdmission.decide(identity=identity, state=ScientificState("valid", "supported", "unknown", "explore"),
                                            outcome="positive", execution_success=True, trusted_validator="fixture-validator",
                                            validator_verified=True, evidence_ids=["contract-evidence"], subject_bindings=bindings,
                                            required_audit=["measurement"], audit=audits)
        engine = ReviewEngine(identity)
        review = engine.open(task_binding=task.content_hash, evidence_snapshot="fixture-contract-snapshot", budget_units=1,
                             roles=[{"role_id": "semantic", "question": "Does this counterexample bear on the proposed mechanism?"}])
        material = _semantic_material(variant)
        review_payload = FrozenRecord.from_dict({"schema": "exploration-semantic-review-v1", "fixture_only": True,
                                                  "task": task.data(), "contract_admitted": contract.admitted,
                                                  "theory": material["theory"], "construct": material["construct"],
                                                  "observation": material["observation"], "review": review.payload.data()})
        review_payloads.append(review_payload)
        response = review_model(review_payload) if review_model else {"assessment": "unknown", "evidence_refs": ["contract-evidence"],
                                                                        "counterexamples": [material["counterexample_id"]],
                                                                        "uncertainty": "fixture-only semantic review"}
        submitted = engine.submit(review.review_id, role_id="semantic", reviewer_id="fixture-reviewer", response=response, cost_units=1)
        sealed = engine.reveal(review.review_id)[0]
        auxiliary.update({"contract_admitted": contract.admitted, "review_submission": submitted.before_hash,
                          "review_response_digest": sealed.response.content_hash,
                          "review_response": sealed.response.data()})
        private["semantic_fixture_truth"] = material["controller_truth"]
        trace.append({"event": "contract_and_semantic_review_separated", "contract_admitted": contract.admitted,
                      "review_payload": review_payload.content_hash, "review_callback": review_model is not None})
    return auxiliary, private, review_payloads


def _controls(task: PublicTask, frozen_controls: FrozenRecord) -> dict[str, Any]:
    controls = frozen_controls.data()
    if set(controls) != {"task_digest", "budget_digest", "fixture_only"} or controls["task_digest"] != task.content_hash or controls["fixture_only"] is not True:
        raise ContractError("exploration scenario needs matching closed fixture controls")
    required_text(controls["budget_digest"], "budget digest")
    return controls


def _plan(task: PublicTask) -> ExplorationPlan:
    return ExplorationPlan("fixture-plan", task.identity, FrozenRecord.from_dict({"task": task.content_hash, "fixture_only": True}),
                           ResourceClosure("fixture-data", "fixture-artifact", "fixture-negative-control", 4, 20))


def _feasibility(plan: ExplorationPlan, *, data_status: str):
    observations = {"data": FeasibilityObservation("data", data_status, "fixture-data")}
    from research_loop.modular.modules.exploration import assess_feasibility
    return assess_feasibility(plan, observations)


_AUDIT_KEYS = {"fixture-audit-a": b"a" * 32, "fixture-audit-b": b"b" * 32}
_IMAGE = "fixture@sha256:" + "a" * 64


def _require_execution_root(sidecar: Path | None, broker: DockerExecutionBroker | None, experiment_id: str) -> Path:
    if not isinstance(sidecar, Path) or broker is None:
        raise ContractError(f"{experiment_id} requires a caller-owned fixture sidecar and restricted broker")
    if sidecar.exists() and any(sidecar.iterdir()):
        raise ContractError("exploration fixture sidecar must be unused")
    sidecar.mkdir(parents=True, exist_ok=True)
    return sidecar


def _session(task: PublicTask, sidecar: Path, *, executions: int) -> RunSession:
    return RunSession(task, package_digest="fixture-package",
                      arm=default_compatibility("base").arm(["M1", "M2", "M3", "M7"]),
                      objective=FrozenRecord.from_dict({"question": _question(task), "primary_endpoint": "fixture instrument or ratio diagnostic"}),
                      slots=("final",), execution_limit=executions, sidecar=sidecar,
                      verifier=AuditVerifier(_AUDIT_KEYS), required_audit=("measurement",))


def _execute(session: RunSession, broker: DockerExecutionBroker, *, label: str):
    source = session.sidecar / "public-fixture.csv"
    source.write_text("x\n1\n", encoding="utf-8")
    return session.execute(f"print('fixture {label}')", broker=broker, image=_IMAGE, inputs={"public": source})


def _audits(session: RunSession, execution_digest: str, state: ScientificState, outcome: str) -> list[FrozenRecord]:
    return [AuditAuthority(name, key).issue(identity=session.task.identity, objective_digest=session.objective.content_hash,
            execution_digest=execution_digest, state=state, outcome=outcome,
            audit=[AuditItem("measurement", True, True)]) for name, key in _AUDIT_KEYS.items()]


def _run_ratio_candidates(task: PublicTask, root: Path, broker: DockerExecutionBroker) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    total = 4
    candidates = (("zero", 0, 0), ("low", 10, 1), ("medium", 30, 2), ("high", 60, 3))
    rows, allocations = [], []
    for ratio_id, percent, exploration_units in candidates:
        budget = ExplorationBudget(total, 0)
        after_exploration = budget.reserve(exploration_units, 0)
        after_main = after_exploration.reserve(total - exploration_units, 0)
        session = _session(task, root / ratio_id, executions=total)
        diagnostic_receipts = [_execute(session, broker, label=f"ratio-{ratio_id}-diagnostic-{number}").content_hash
                               for number in range(exploration_units)]
        main_receipts = [_execute(session, broker, label=f"ratio-{ratio_id}-main-{number}").content_hash
                         for number in range(total - exploration_units)]
        # The only ranking input is typed status from the diagnostic receipts;
        # there is no controller expected-answer table.
        succeeded = sum(session.executions[value].status == "succeeded" for value in diagnostic_receipts)
        allocations.append({"ratio_id": ratio_id, "exploration_percent": percent,
                            "exploration_execution_units": exploration_units,
                            "main_task_execution_units": total - exploration_units,
                            "diagnostic_receipt_digests": diagnostic_receipts,
                            "main_receipt_digests": main_receipts,
                            "budget_after_exploration": after_exploration.__dict__,
                            "budget_after_main": after_main.__dict__,
                            "token_budget": "not_exercised"})
        rows.append({"ratio_id": ratio_id, "exploration_percent": percent, "diagnostics": succeeded,
                     "waste": exploration_units - succeeded, "task_units": total - exploration_units})
    return rows, allocations


def _run_invalid_instrument(task: PublicTask, root: Path, broker: DockerExecutionBroker, variant: str):
    session = _session(task, root, executions=2 if variant == "repair" else 1)
    old_execution = _execute(session, broker, label="invalid-instrument")
    # The old instrument first passes the typed admission gate.  The later
    # construct failure therefore has something real to withdraw, for either
    # polarity, instead of merely demonstrating an already-blocked root.
    old_state = ScientificState("valid", "refuted" if variant == "old_evidence" else "supported", "unknown", "explore")
    old_admission = session.admit(old_execution.content_hash, _audits(session, old_execution.content_hash, old_state,
                                                                          "negative" if variant == "old_evidence" else "positive"))
    repair = InstrumentRepair("fixture-instrument-v2", "fixture-instrument-v1", "fixture-repair", (old_execution.content_hash,))
    old_root = session.admission_roots[old_execution.content_hash]
    session.evidence.withdraw(old_root, "fixture construct/instrument invalidity; repair requires new execution")
    session.claims.refresh_after_withdrawal()
    return repair, session, old_execution, old_admission, old_root


def _run_repaired_instrument(session: RunSession, broker: DockerExecutionBroker):
    execution = _execute(session, broker, label="repaired-instrument")
    admission = session.admit(execution.content_hash, _audits(session, execution.content_hash,
                                                                ScientificState("valid", "supported", "unknown", "explore"), "positive"))
    return execution, admission


def _response_record(value: Any) -> FrozenRecord:
    if isinstance(value, FrozenRecord):
        return value
    if value is None or isinstance(value, Mapping):
        return FrozenRecord.from_dict({"schema": "exploration-next-response-v1", "response": value})
    raise ContractError("next model response must be a frozen record, mapping, or None")


def _question(task: PublicTask) -> str:
    payload = task.payload.data()
    return str(payload.get("research_question", payload.get("question", task.identity.task_id)))


def _semantic_material(variant: str) -> dict[str, str]:
    theory = "Catalyst C changes response R through pathway P under intervention I."
    construct = "Response R is operationalized as fluorescence measured four hours after I."
    if variant == "real_counterexample":
        observation = "With verified C exposure, I leaves R unchanged at four hours in the same assay."
        truth, identifier = "counterexample_hits_theory", "fixture-counterexample-hits"
    else:
        observation = "With verified C exposure, I changes a separate fluorescence channel outside the R assay."
        truth, identifier = "counterexample_misses_construct", "fixture-counterexample-misses"
    return {"theory": theory, "construct": construct, "observation": observation,
            "counterexample_id": identifier, "controller_truth": truth}


def _bindings(task: PublicTask) -> dict[str, str]:
    return {"task": task.identity.task_id, "subject": "fixture-subject"}


def _validate(experiment_id: str, variant: str) -> None:
    if experiment_id not in _VARIANTS or variant not in _VARIANTS[experiment_id]:
        raise ContractError("exploration scenario variant is not registered")
