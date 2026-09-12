"""M1: explicit scientific state, evidence admission, and exploration permission.

This module deliberately accepts typed host facts.  It does not inspect prose to
decide whether an outcome is scientifically valid or whether a result is positive.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping, Sequence

from research_loop.modular.contracts import DataIdentity, required_text, strict_bool
from research_loop.ontology import ContractError

Validity = Literal["valid", "invalid", "unknown"]
Support = Literal["supported", "refuted", "undetermined"]
Novelty = Literal["known", "novel", "unknown"]
Investment = Literal["explore", "repair", "stop"]
Outcome = Literal["positive", "negative"]


@dataclass(frozen=True)
class ScientificState:
    validity: Validity
    support: Support
    novelty: Novelty
    investment: Investment

    def __post_init__(self) -> None:
        if self.validity not in {"valid", "invalid", "unknown"}:
            raise ContractError("invalid evidence validity")
        if self.support not in {"supported", "refuted", "undetermined"}:
            raise ContractError("invalid claim support")
        if self.novelty not in {"known", "novel", "unknown"}:
            raise ContractError("invalid novelty")
        if self.investment not in {"explore", "repair", "stop"}:
            raise ContractError("invalid investment state")


@dataclass(frozen=True)
class AuditItem:
    """One required check: ``executed`` and ``passed`` cannot be conflated."""

    name: str
    executed: bool
    passed: bool

    def __post_init__(self) -> None:
        required_text(self.name, "audit item name")
        strict_bool(self.executed, "audit executed")
        strict_bool(self.passed, "audit passed")
        if not self.executed and self.passed:
            raise ContractError("an unexecuted audit item cannot pass")


def _complete_audit(required: Sequence[str], actual: Sequence[AuditItem]) -> bool:
    required_names = tuple(required)
    if not required_names or len(set(required_names)) != len(required_names):
        raise ContractError("required audit must be a nonempty unique checklist")
    if any(not isinstance(name, str) or not name.strip() for name in required_names):
        raise ContractError("required audit names must be nonempty text")
    if len({item.name for item in actual}) != len(actual):
        raise ContractError("duplicate audit item")
    by_name = {item.name: item for item in actual}
    if set(by_name) != set(required_names):
        raise ContractError("audit does not cover the registered checklist")
    return all(item.executed and item.passed for item in by_name.values())


def _bindings(value: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ContractError("subject bindings require a mapping")
    result: dict[str, str] = {}
    for key, item in value.items():
        result[required_text(key, "binding key")] = required_text(item, "binding value")
    return result


@dataclass(frozen=True)
class EvidenceDisposition:
    admitted: bool
    reason: str
    outcome: Outcome
    evidence_ids: tuple[str, ...]
    identity: DataIdentity


@dataclass(frozen=True)
class ExplorationPermit:
    allowed: bool
    reason: str
    identity: DataIdentity
    subject_bindings: tuple[tuple[str, str], ...]


class EvidenceAdmission:
    """Require a trusted host validation receipt before evidence can be admitted."""

    @staticmethod
    def decide(
        *,
        identity: DataIdentity,
        state: ScientificState,
        outcome: Outcome,
        execution_success: bool,
        trusted_validator: str,
        validator_verified: bool,
        evidence_ids: Sequence[str],
        subject_bindings: Mapping[str, str],
        required_audit: Sequence[str],
        audit: Sequence[AuditItem],
    ) -> EvidenceDisposition:
        strict_bool(execution_success, "execution success")
        strict_bool(validator_verified, "validator verified")
        if outcome not in {"positive", "negative"}:
            raise ContractError("outcome must be explicitly positive or negative")
        required_text(trusted_validator, "trusted validator")
        _bindings(subject_bindings)
        ids = tuple(required_text(value, "evidence id") for value in evidence_ids)
        if not ids or len(set(ids)) != len(ids):
            raise ContractError("evidence admission needs unique evidence ids")
        audited = _complete_audit(required_audit, audit)
        admitted = (
            execution_success
            and validator_verified
            and audited
            and state.validity == "valid"
        )
        reason = "admitted" if admitted else "host validation, audit, execution, or validity gate failed"
        # Positive and valid-negative observations take the identical gate.  Their
        # effect on a claim belongs in M2 relation edges, not this admission decision.
        return EvidenceDisposition(admitted, reason, outcome, ids, identity)


class ExplorationPolicy:
    """Exploration is independent from scientific evidence admission."""

    @staticmethod
    def admit(
        *,
        identity: DataIdentity,
        state: ScientificState,
        safe: bool,
        budget_available: bool,
        subject_bindings: Mapping[str, str],
        required_audit: Sequence[str],
        audit: Sequence[AuditItem],
    ) -> ExplorationPermit:
        strict_bool(safe, "exploration safe")
        strict_bool(budget_available, "exploration budget available")
        bindings = _bindings(subject_bindings)
        audited = _complete_audit(required_audit, audit)
        allowed = safe and budget_available and audited and state.investment == "explore"
        reason = "exploration permitted" if allowed else "safety, budget, audit, or investment gate failed"
        return ExplorationPermit(allowed, reason, identity, tuple(sorted(bindings.items())))
