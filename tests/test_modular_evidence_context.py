"""Engineering regressions for M1--M3; these are not scientific benchmark results."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_loop.modular.contracts import DataIdentity
from research_loop.modular.modules.admission import AuditItem, EvidenceAdmission, ExplorationPolicy, ScientificState
from research_loop.modular.modules.context import ContextBuilder, ContextCache
from research_loop.modular.modules.evidence import ClaimLedger, EvidenceLedger
from research_loop.ontology import ContractError


def identity(*, domain: str = "train", task: str = "task-a", group: str = "group-a") -> DataIdentity:
    return DataIdentity("discovery", task, group, "v1", "split-a", domain)


def audit(*, passed: bool = True) -> list[AuditItem]:
    return [AuditItem("schema", True, passed), AuditItem("binding", True, passed)]


def state(*, validity: str = "valid", support: str = "supported", novelty: str = "unknown", investment: str = "explore") -> ScientificState:
    return ScientificState(validity, support, novelty, investment)  # type: ignore[arg-type]


def admit(ident: DataIdentity, *, outcome: str = "positive", current: ScientificState | None = None, passed: bool = True):
    return EvidenceAdmission.decide(
        identity=ident, state=current or state(), outcome=outcome, execution_success=True,
        trusted_validator="host-validator", validator_verified=True, evidence_ids=["e-1"],
        subject_bindings={"subject": "s-1"}, required_audit=["schema", "binding"], audit=audit(passed=passed),
    )


def observation(*, root: str = "raw-1", representation: str = "raw", bindings: dict[str, str] | None = None):
    return {
        "kind": "measurement", "root_material": {"raw_artifact": root},
        "representation": representation, "content": {"view": representation, "root": root},
        "subject_bindings": bindings or {"subject": "s-1"}, "independent_group": "group-a",
    }


def receipt(*, admitted: bool = True, verified: bool = True):
    return {"trusted_validator": "host-validator", "validator_verified": verified, "admitted": admitted}


def test_m1_strict_audit_host_validation_and_positive_negative_symmetry():
    ident = identity()
    positive = admit(ident, outcome="positive")
    negative = admit(ident, outcome="negative")
    assert positive.admitted and negative.admitted
    assert not admit(ident, current=state(validity="unknown")).admitted
    assert not admit(ident, passed=False).admitted
    with pytest.raises(ContractError, match="literal boolean"):
        AuditItem("schema", "true", True)  # type: ignore[arg-type]
    with pytest.raises(ContractError, match="cover"):
        EvidenceAdmission.decide(
            identity=ident, state=state(), outcome="positive", execution_success=True,
            trusted_validator="host", validator_verified=True, evidence_ids=["e"], subject_bindings={},
            required_audit=["schema", "binding"], audit=[AuditItem("schema", True, True)],
        )
    with pytest.raises(ContractError, match="verified trusted-validator"):
        EvidenceLedger(ident).append(observation(), receipt(admitted=True, verified=False))


def test_m1_exploration_is_not_evidence_admission():
    ident = identity()
    permit = ExplorationPolicy.admit(
        identity=ident, state=state(validity="unknown", investment="explore"), safe=True,
        budget_available=True, subject_bindings={"subject": "s-1"},
        required_audit=["schema", "binding"], audit=audit(),
    )
    assert permit.allowed
    assert not admit(ident, current=state(validity="unknown")).admitted
    assert not ExplorationPolicy.admit(
        identity=ident, state=state(investment="repair"), safe=True, budget_available=True,
        subject_bindings={}, required_audit=["schema", "binding"], audit=audit(),
    ).allowed


def test_m2_deduplicates_evidence_roots_and_summary_cannot_create_evidence():
    ledger = EvidenceLedger(identity())
    raw = ledger.append(observation(representation="raw"), receipt())
    report = ledger.append(observation(representation="report"), receipt())
    summary = ledger.append(observation(representation="summary"), receipt())
    assert raw.root_id == report.root_id == summary.root_id
    assert len(ledger.roots()) == 1
    with pytest.raises(ContractError, match="summary cannot create"):
        ledger.append(observation(root="new", representation="summary"), receipt())


def test_m2_relations_preserve_independent_support_and_reject_cross_subject():
    ledger = EvidenceLedger(identity())
    root_one = ledger.append(observation(root="one"), receipt()).root_id
    root_two = ledger.append(observation(root="two"), receipt()).root_id
    claims = ClaimLedger(ledger)
    claim = claims.create("binding relation", subject_bindings={"subject": "s-1"})
    revised = claims.apply(claim.claim_id, {"supports": [root_one, root_two], "refutes": [], "subject_bindings": {"subject": "s-1"}}, expected_revision=0)
    assert revised.claim.status == "supported"
    ledger.withdraw(root_one, "instrument defect")
    changes = claims.refresh_after_withdrawal()
    assert changes[0].claim.status == "supported"
    assert changes[0].claim.support_roots == (root_two,)
    other = EvidenceLedger(identity(task="task-b", group="group-b"))
    with pytest.raises(ContractError, match="matching data identity"):
        ContextBuilder(identity(), budget_bytes=2000).build("q", other, ClaimLedger(other))
    with pytest.raises(ContractError, match="revision conflict"):
        claims.apply(claim.claim_id, {"supports": [root_two], "refutes": [], "subject_bindings": {"subject": "s-1"}}, expected_revision=0)


def test_m2_persists_append_withdrawal_and_claim_revisions(tmp_path: Path):
    ident = identity()
    evidence_path, claim_path = tmp_path / "evidence.jsonl", tmp_path / "claims.jsonl"
    evidence = EvidenceLedger(ident, storage_path=evidence_path)
    root = evidence.append(observation(), receipt()).root_id
    claims = ClaimLedger(evidence, storage_path=claim_path)
    claim = claims.create("bound result", subject_bindings={"subject": "s-1"})
    claims.apply(claim.claim_id, {"supports": [root], "refutes": [], "subject_bindings": {"subject": "s-1"}}, expected_revision=0)
    evidence.withdraw(root, "withdrawn")
    claims.refresh_after_withdrawal()
    reloaded_evidence = EvidenceLedger(ident, storage_path=evidence_path)
    reloaded_claims = ClaimLedger(reloaded_evidence, storage_path=claim_path)
    assert not reloaded_evidence.is_active_admitted(root)
    assert reloaded_claims.claims()[0].status == "undetermined"
    assert reloaded_claims.claims()[0].revision == 2


def test_m3_rebuilds_current_context_does_not_promote_summary_and_invalidates_cache():
    ident = identity()
    evidence = EvidenceLedger(ident)
    root = evidence.append(observation(), receipt()).root_id
    claims = ClaimLedger(evidence)
    claim = claims.create("current claim", subject_bindings={"subject": "s-1"})
    claims.apply(claim.claim_id, {"supports": [root], "refutes": [], "subject_bindings": {"subject": "s-1"}}, expected_revision=0)
    builder, cache = ContextBuilder(ident, budget_bytes=10000), ContextCache()
    first = cache.get_or_build(builder, "question", evidence, claims)
    assert any(row["kind"] == "claim" for row in first.entries.data()["entries"])
    baseline = builder.build("question", evidence, claims, mode="baseline", baseline_summary="claim is certain")
    assert baseline.entries.data()["entries"][0]["evidence_roots"] == []
    evidence.withdraw(root, "invalid")
    second = cache.get_or_build(builder, "question", evidence, claims)
    assert second.content_hash != first.content_hash
    assert not any(row["kind"] == "claim" for row in second.entries.data()["entries"])


def test_m3_validation_context_is_ephemeral_and_memory_domain_isolated():
    train = identity(domain="train")
    validation = identity(domain="validation")
    train_evidence, validation_evidence = EvidenceLedger(train), EvidenceLedger(validation)
    train_claims, validation_claims = ClaimLedger(train_evidence), ClaimLedger(validation_evidence)
    cache = ContextCache()
    train_bundle = cache.get_or_build(ContextBuilder(train, budget_bytes=400), "q", train_evidence, train_claims)
    validation_bundle = cache.get_or_build(ContextBuilder(validation, budget_bytes=400), "q", validation_evidence, validation_claims)
    assert not train_bundle.ephemeral
    assert validation_bundle.ephemeral
    assert cache.size() == 1


def test_q1_remaining_m1_m3_paths_withdraw_without_replacement_and_preserve_unknown():
    """Q1.5 is M5-owned; this verifies M1--M3 do not promote its old narrative."""
    ident = identity()
    evidence = EvidenceLedger(ident)
    root = evidence.append(observation(), receipt()).root_id
    claims = ClaimLedger(evidence)
    claim = claims.create("old explanation", subject_bindings={"subject": "s-1"})
    claims.apply(claim.claim_id, {"supports": [root], "refutes": [], "subject_bindings": {"subject": "s-1"}}, expected_revision=0)
    builder = ContextBuilder(ident, budget_bytes=10_000)
    # Q1.5: candidate reconstruction does not ingest a historical summary as fact.
    before = builder.build("q", evidence, claims, baseline_summary="old explanation is final")
    assert all(row["kind"] != "untrusted_summary" for row in before.entries.data()["entries"])
    # Q1.6: invalid evidence is withdrawn even though no replacement exists.
    evidence.withdraw(root, "leaked source")
    after = builder.build("q", evidence, claims)
    assert not any(row["kind"] == "claim" for row in after.entries.data()["entries"])
    # Q1.7/Q7.5: unknown validity remains distinct from support, novelty and investment.
    unknown = state(validity="unknown", support="undetermined", novelty="novel", investment="explore")
    assert unknown.validity == "unknown" and unknown.novelty == "novel"
    assert ExplorationPolicy.admit(
        identity=ident, state=unknown, safe=True, budget_available=True, subject_bindings={},
        required_audit=["schema", "binding"], audit=audit(),
    ).allowed
    assert not admit(ident, current=unknown).admitted
