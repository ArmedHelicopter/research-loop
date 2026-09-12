"""Fixture-only runnable scenarios for Q1.2--Q1.7.

These scenarios exercise the real M2, M3 and M5 ports using a caller supplied
``PublicTask`` and frozen public-source digests.  They neither load a dataset
nor use labels, gold answers, optimizer state, or validation feedback.  Their
synthetic assertions are deliberately marked fixture-only and are mechanism
checks, never evidence of a benchmark effect.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from research_loop.modular.contracts import FrozenRecord, PublicTask, required_text
from research_loop.modular.modules.context import ContextBuilder
from research_loop.modular.modules.evidence import ClaimLedger, EvidenceLedger
from research_loop.modular.modules.review import ReviewEngine
from research_loop.ontology import ContractError, digest


_VARIANTS = {
    "Q1.2": frozenset(("summary_only", "registered", "withdraw")),
    "Q1.3": frozenset(("log", "report", "summary", "memory")),
    "Q1.4": frozenset(("one_withdrawn", "all_withdrawn", "copies")),
    "Q1.5": frozenset(("blind_first", "summary_first")),
    "Q1.6": frozenset(("replacement", "none", "high_score")),
    "Q1.7": frozenset(("irrelevant", "causal", "unknown")),
}


@dataclass(frozen=True)
class HistoryScenarioResult:
    experiment_id: str
    variant: str
    next_payload: FrozenRecord
    mechanism_trace: FrozenRecord


def history_injection(experiment_id: str, variant: str) -> Mapping[str, Any]:
    """Return a closed, auxiliary-only controller manipulation description."""
    _validate_variant(experiment_id, variant)
    return {
        "fixture_only": True,
        "fixture_notice": "synthetic fixture truth; not a benchmark effect",
        "auxiliary": {
            "Q1.2": {"dependency_representation": variant, "withdraw_upstream": True},
            "Q1.3": {"representation": variant, "duplicate_root": True},
            "Q1.4": {"support_topology": variant, "qualified_fixture_provenance": True},
            "Q1.5": {"review_order": variant, "sealed_public_inputs": True},
            "Q1.6": {"replacement_availability": variant, "invalidity_requires_retraction": True},
            "Q1.7": {"information_kind": variant, "unknown_is_allowed": True},
        }[experiment_id],
    }


def run_history_scenario(
    experiment_id: str,
    variant: str,
    *,
    task: PublicTask,
    frozen_controls: FrozenRecord,
    next_model: Callable[[FrozenRecord], Any] | None = None,
) -> HistoryScenarioResult:
    """Manipulate the current task's fixture ledgers and invoke the next port.

    ``frozen_controls`` has exactly task/evidence/budget public digests and a
    fixture-only marker.  This function intentionally has no path, data, gold,
    label, scorer, or optimizer argument.
    """
    _validate_variant(experiment_id, variant)
    controls = frozen_controls.data()
    if set(controls) != {"task_digest", "evidence_digest", "budget_digest", "fixture_only"}:
        raise ContractError("history scenario needs closed frozen public controls")
    if controls["task_digest"] != task.content_hash or controls["fixture_only"] is not True:
        raise ContractError("history scenario task or fixture control mismatch")
    for key in ("evidence_digest", "budget_digest"):
        required_text(controls[key], key)

    evidence, claims = EvidenceLedger(task.identity), None
    trace: list[dict[str, Any]] = [{"event": "fixture_start", "fixture_only": True,
                                    "task_digest": task.content_hash,
                                    "evidence_digest": controls["evidence_digest"],
                                    "budget_digest": controls["budget_digest"]}]
    claims = ClaimLedger(evidence)
    _apply(experiment_id, variant, task, evidence, claims, trace)
    context = ContextBuilder(task.identity, budget_bytes=12_000).build(
        _question(task), evidence, claims, mode="candidate")
    payload = FrozenRecord.from_dict({
        "schema": "history-scenario-next-model-v1",
        "task": task.data(),
        "frozen_controls": controls,
        "experiment_id": experiment_id,
        "variant": variant,
        "fixture_only": True,
        "context": context.data(),
        "mechanism_trace_digest": digest(trace),
    })
    if next_model is not None:
        next_model(payload)  # The captured payload is the actual post-mutation invocation.
    trace.append({"event": "next_model_invoked", "payload_digest": payload.content_hash})
    return HistoryScenarioResult(experiment_id, variant, payload, FrozenRecord.from_dict({"events": trace}))


def _apply(experiment_id: str, variant: str, task: PublicTask, evidence: EvidenceLedger,
           claims: ClaimLedger, trace: list[dict[str, Any]]) -> None:
    if experiment_id == "Q1.2":
        root = _append(evidence, task, "upstream")
        upstream = _claim(claims, "upstream conclusion", root.root_id)
        downstream = claims.create("downstream interpretation", subject_bindings=_bindings(task))
        if variant == "summary_only":
            notice = claims.mark_unattributed_summary(downstream.claim_id, "upstream supports downstream", expected_revision=0)
            trace.append({"event": "summary_source_insufficient", "claim": notice.claim.claim_id})
        else:
            linked = claims.link_dependencies(downstream.claim_id, [upstream.claim_id], expected_revision=0).claim
            trace.append({"event": "registered_dependency", "claim": linked.claim_id, "depends_on": list(linked.depends_on)})
        evidence.withdraw(root.root_id, "fixture upstream invalid")
        revisions = claims.refresh_after_withdrawal()
        trace.append({"event": "withdrawal_refresh", "revised_claims": [item.claim.claim_id for item in revisions]})
    elif experiment_id == "Q1.3":
        raw = _append(evidence, task, "shared-observation", representation="raw")
        representation = {"log": "raw", "report": "report", "summary": "summary", "memory": "summary"}[variant]
        duplicate = _append(evidence, task, "shared-observation", representation=representation)
        trace.append({"event": "representation_dedup", "representation": variant,
                      "root_ids": [raw.root_id, duplicate.root_id], "independent_root_count": len(evidence.roots())})
    elif experiment_id == "Q1.4":
        first = _append(evidence, task, "chain-a")
        second = _append(evidence, task, "chain-b")
        claim = _claim(claims, "two qualified fixture chains", first.root_id, second.root_id)
        # Distinct IDs are insufficient by themselves.  Both records retain the
        # same statistical source group, while this fixture declares qualification.
        trace.append({"event": "fixture_provenance", "qualified_chains": [first.root_id, second.root_id],
                      "statistical_source_group": task.identity.group_id,
                      "distinct_ids_do_not_prove_independence": True})
        if variant == "copies":
            copy = _append(evidence, task, "chain-a", representation="report")
            trace.append({"event": "copied_root", "root_id": copy.root_id, "active_roots": len(evidence.roots())})
        else:
            evidence.withdraw(first.root_id, "fixture chain a invalid")
            if variant == "all_withdrawn": evidence.withdraw(second.root_id, "fixture chain b invalid")
            revisions = claims.refresh_after_withdrawal()
            trace.append({"event": "support_rechecked", "claim": claim.claim_id,
                          "support_roots": list(claims.claims()[0].support_roots),
                          "revisions": [item.claim.revision for item in revisions]})
    elif experiment_id == "Q1.5":
        root = _append(evidence, task, "review-evidence")
        engine = ReviewEngine(task.identity)
        snapshot = evidence.snapshot().content_hash
        review = engine.open(task_binding=task.content_hash, evidence_snapshot=snapshot, budget_units=1,
                             roles=[{"role_id": "evidence", "question": "Assess only sealed public evidence."}])
        order = ["evidence", "summary"] if variant == "blind_first" else ["summary", "evidence"]
        engine.submit(review.review_id, role_id="evidence", reviewer_id="fixture-reviewer",
                      response={"assessment": "unknown", "evidence_refs": [root.root_id], "counterexamples": [], "uncertainty": "fixture-only"}, cost_units=1)
        engine.reveal(review.review_id)
        trace.append({"event": "sealed_review", "review_order": order, "sealed_snapshot": snapshot,
                      "public_task_binding": task.content_hash})
    elif experiment_id == "Q1.6":
        invalid = _append(evidence, task, "invalid-evidence")
        claim = _claim(claims, "old high-score explanation", invalid.root_id)
        evidence.withdraw(invalid.root_id, "fixture leakage/computation/construct invalidity")
        claims.refresh_after_withdrawal()
        trace.append({"event": "retracted_without_substitution", "availability": variant,
                      "claim": claim.claim_id, "active_support": list(claims.claims()[0].support_roots)})
    else:  # Q1.7
        if variant == "causal":
            root = _append(evidence, task, "ordered-observation")
            _claim(claims, "meaningful causal ordering", root.root_id)
            trace.append({"event": "meaningful_time_order", "root": root.root_id})
        elif variant == "irrelevant":
            trace.append({"event": "irrelevant_narration_excluded", "narration": "fixture-only prose"})
        else:
            trace.append({"event": "unknown_preserved", "claim_status": "unknown"})


def _append(evidence: EvidenceLedger, task: PublicTask, root: str, *, representation: str = "raw"):
    return evidence.append({"kind": "measurement", "root_material": {"fixture_root": root},
        "representation": representation, "content": {"fixture_only": True, "root": root},
        "subject_bindings": _bindings(task), "independent_group": task.identity.group_id},
        {"trusted_validator": "fixture-validator", "validator_verified": True, "admitted": True})


def _claim(claims: ClaimLedger, statement: str, *roots: str):
    claim = claims.create(statement, subject_bindings=_bindings_from_identity(claims.identity))
    return claims.apply(claim.claim_id, {"supports": list(roots), "refutes": [],
        "subject_bindings": _bindings_from_identity(claims.identity)}, expected_revision=claim.revision).claim


def _bindings(task: PublicTask) -> dict[str, str]:
    return _bindings_from_identity(task.identity)


def _bindings_from_identity(identity) -> dict[str, str]:
    return {"task": identity.task_id, "subject": "fixture-subject"}


def _question(task: PublicTask) -> str:
    payload = task.payload.data()
    return str(payload.get("research_question", payload.get("task_id", task.identity.task_id)))


def _validate_variant(experiment_id: str, variant: str) -> None:
    if experiment_id not in _VARIANTS or variant not in _VARIANTS[experiment_id]:
        raise ContractError("history scenario variant is not registered")
