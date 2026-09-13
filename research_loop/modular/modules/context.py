"""M3: context reconstructed from current M2 ledgers, never promoted summaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from research_loop.modular.contracts import DataIdentity, FrozenRecord, required_text
from research_loop.ontology import ContractError, canonical, digest

from .evidence import ClaimLedger, EvidenceLedger


@dataclass(frozen=True)
class ContextBundle:
    identity: DataIdentity
    question: str
    mode: str
    evidence_version: str
    claim_version: str
    entries: FrozenRecord
    used_bytes: int
    budget_bytes: int
    ephemeral: bool

    def data(self) -> dict[str, Any]:
        return {
            "identity": self.identity.data(), "question": self.question, "mode": self.mode,
            "evidence_version": self.evidence_version, "claim_version": self.claim_version,
            "entries": self.entries.data(), "used_bytes": self.used_bytes,
            "budget_bytes": self.budget_bytes, "ephemeral": self.ephemeral,
        }

    def public_data(self) -> dict[str, Any]:
        """Expose the constructed material without the controller's arm mode."""
        return {key: value for key, value in self.data().items() if key not in {"mode", "ephemeral"}}

    @property
    def content_hash(self) -> str:
        return digest(self.data())


class ContextBuilder:
    def __init__(self, identity: DataIdentity, *, budget_bytes: int) -> None:
        if type(budget_bytes) is not int or budget_bytes <= 0:
            raise ContractError("context budget must be a positive integer")
        self.identity = identity
        self.budget_bytes = budget_bytes

    def build(
        self,
        question: str,
        evidence: EvidenceLedger,
        claims: ClaimLedger,
        *,
        mode: str = "candidate",
        baseline_summary: str | None = None,
    ) -> ContextBundle:
        question = required_text(question, "context question")
        if evidence.identity != self.identity or claims.identity != self.identity:
            raise ContractError("context may only use matching data identity ledgers")
        if mode not in {"baseline", "candidate"}:
            raise ContractError("context mode must be baseline or candidate")
        evidence_version = evidence.version
        claim_version = claims.snapshot().content_hash
        if mode == "baseline":
            # The baseline hook is intentionally visible but semantically inert: it
            # receives no evidence root IDs and cannot become support by serialization.
            text = baseline_summary if baseline_summary is not None else ""
            if not isinstance(text, str):
                raise ContractError("baseline summary must be text")
            candidates = [{"kind": "untrusted_summary", "text": text, "evidence_roots": []}]
        else:
            candidates = []
            active_roots = {record.root_id for record in evidence.roots(admitted_only=True, active_only=True)}
            for claim in claims.claims():
                supports = [root for root in claim.support_roots if root in active_roots]
                refutes = [root for root in claim.refute_roots if root in active_roots]
                if not supports and not refutes and not claim.needs_review:
                    continue
                status = "undetermined" if supports and refutes else "supported" if supports else "refuted"
                candidates.append({
                    "kind": "claim", "claim_id": claim.claim_id, "statement": claim.statement,
                    "status": status, "support_roots": supports, "refute_roots": refutes,
                    "depends_on": list(claim.depends_on), "needs_review": claim.needs_review,
                    "revision": claim.revision,
                })
            for record in evidence.roots(admitted_only=True, active_only=True):
                candidates.append({
                    "kind": "evidence", "root_id": record.root_id, "payload": record.payload.data(),
                    "subject_bindings": dict(record.subject_bindings),
                })
        selected: list[dict[str, Any]] = []
        used = 0
        for item in candidates:
            cost = len(canonical(item).encode("utf-8"))
            if cost > self.budget_bytes - used:
                continue
            selected.append(item)
            used += cost
        return ContextBundle(
            self.identity, question, mode, evidence_version, claim_version,
            FrozenRecord.from_dict({"entries": selected}), used, self.budget_bytes,
            self.identity.domain == "validation",
        )


class ContextCache:
    """Domain-keyed derived cache. Validation entries are never retained."""

    def __init__(self) -> None:
        self._items: dict[str, ContextBundle] = {}

    def get_or_build(
        self,
        builder: ContextBuilder,
        question: str,
        evidence: EvidenceLedger,
        claims: ClaimLedger,
        *,
        mode: str = "candidate",
        baseline_summary: str | None = None,
    ) -> ContextBundle:
        candidate = builder.build(question, evidence, claims, mode=mode, baseline_summary=baseline_summary)
        # A history manipulation or context-budget change is part of the input,
        # even when the ledger has not changed. Cache by the complete bundle.
        key = candidate.content_hash
        if candidate.ephemeral:
            return candidate
        existing = self._items.get(key)
        if existing is not None:
            return existing
        self._items[key] = candidate
        return candidate

    def size(self) -> int:
        return len(self._items)
