"""M6: bounded, provenance-aware three-lane retrieval.

The module does not fetch a network itself.  A caller supplies a frozen source
bundle and a provider port; policy decisions are computed before any returned
text is considered.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Protocol

from research_loop.modular.contracts import FrozenRecord, required_text
from research_loop.ontology import ContractError, digest

LANES = ("support", "counter", "method")
TRIGGERS = ("new_mechanism", "key_conflict", "innovation_claim", "dependency_unknown", "stagnation")


@dataclass(frozen=True)
class RetrievalBudget:
    calls_per_lane: int
    sources_per_lane: int

    def __post_init__(self) -> None:
        if not isinstance(self.calls_per_lane, int) or not isinstance(self.sources_per_lane, int) or self.calls_per_lane < 0 or self.sources_per_lane < 0:
            raise ContractError("retrieval budget must be nonnegative integers")

    def data(self) -> dict[str, int]:
        return {"calls_per_lane": self.calls_per_lane, "sources_per_lane": self.sources_per_lane}


@dataclass(frozen=True)
class FrozenRetrievalPolicy:
    policy_id: str
    enabled_triggers: tuple[str, ...]
    budget: RetrievalBudget

    def __post_init__(self) -> None:
        required_text(self.policy_id, "policy id")
        if len(set(self.enabled_triggers)) != len(self.enabled_triggers) or not set(self.enabled_triggers) <= set(TRIGGERS):
            raise ContractError("unknown or duplicate retrieval trigger")

    @property
    def content_hash(self) -> str:
        return digest({"policy_id": self.policy_id, "enabled_triggers": list(self.enabled_triggers), "budget": self.budget.data()})


@dataclass(frozen=True)
class RetrievalSignals:
    new_mechanism: bool = False
    key_conflict: bool = False
    innovation_claim: bool = False
    dependency_unknown: bool = False
    stagnation: bool = False
    cheap_distinguishing_diagnostic_locked: bool = False

    def active(self, policy: FrozenRetrievalPolicy) -> tuple[str, ...]:
        values = {name: getattr(self, name) for name in TRIGGERS}
        result = [name for name in TRIGGERS if values[name] and name in policy.enabled_triggers]
        # Stagnation requests research only after a cheaper locked diagnostic is
        # unavailable; this condition is policy input, not retrieved prose.
        if self.cheap_distinguishing_diagnostic_locked and "stagnation" in result:
            result.remove("stagnation")
        return tuple(result)


@dataclass(frozen=True)
class SourceDocument:
    source_id: str
    root_source_id: str
    lane: str
    text: FrozenRecord

    def __post_init__(self) -> None:
        required_text(self.source_id, "source id")
        required_text(self.root_source_id, "root source id")
        if self.lane not in LANES:
            raise ContractError("invalid retrieval lane")
        if not isinstance(self.text, FrozenRecord):
            raise ContractError("source text must be frozen")

    def data(self) -> dict[str, object]:
        return {"source_id": self.source_id, "root_source_id": self.root_source_id,
                "lane": self.lane, "text": self.text.data()}


@dataclass(frozen=True)
class FrozenSourceBundle:
    bundle_id: str
    documents: tuple[SourceDocument, ...]

    def __post_init__(self) -> None:
        required_text(self.bundle_id, "source bundle id")
        if len({document.source_id for document in self.documents}) != len(self.documents):
            raise ContractError("duplicate source id in frozen bundle")

    @property
    def content_hash(self) -> str:
        return digest({"bundle_id": self.bundle_id, "documents": [document.data() for document in self.documents]})


class RetrievalProvider(Protocol):
    """Port for a local index or separately authorized retrieval service."""
    def search(self, *, lane: str, query: FrozenRecord, source_bundle: FrozenSourceBundle,
               call_limit: int, source_limit: int) -> Iterable[SourceDocument]: ...


@dataclass(frozen=True)
class SourceBundle:
    policy_digest: str
    source_bundle_digest: str
    active_triggers: tuple[str, ...]
    by_lane: Mapping[str, tuple[SourceDocument, ...]]
    dropped_duplicate_roots: tuple[str, ...]

    def data(self) -> dict[str, object]:
        return {"policy_digest": self.policy_digest, "source_bundle_digest": self.source_bundle_digest,
                "active_triggers": list(self.active_triggers),
                "by_lane": {lane: [document.data() for document in self.by_lane[lane]] for lane in LANES},
                "dropped_duplicate_roots": list(self.dropped_duplicate_roots)}


def retrieve(*, provider: RetrievalProvider, query: FrozenRecord, source_bundle: FrozenSourceBundle,
             policy: FrozenRetrievalPolicy, signals: RetrievalSignals) -> SourceBundle:
    """Call every lane within its independent budget, permitting empty lanes.

    Returned documents must belong to the frozen bundle and retain their lane.
    One root source can contribute once across the complete result, so a report
    and its paraphrase cannot receive duplicated weight in different lanes.
    """
    if not isinstance(query, FrozenRecord):
        raise ContractError("retrieval query must be frozen")
    active = signals.active(policy)
    allowed = {document.source_id: document for document in source_bundle.documents}
    seen_roots: set[str] = set()
    dropped: list[str] = []
    by_lane: dict[str, tuple[SourceDocument, ...]] = {}
    for lane in LANES:
        if not active or policy.budget.calls_per_lane == 0 or policy.budget.sources_per_lane == 0:
            by_lane[lane] = ()
            continue
        returned = list(provider.search(lane=lane, query=query, source_bundle=source_bundle,
                                        call_limit=policy.budget.calls_per_lane,
                                        source_limit=policy.budget.sources_per_lane))
        if len(returned) > policy.budget.sources_per_lane:
            raise ContractError("provider exceeded frozen source budget")
        selected: list[SourceDocument] = []
        for document in returned:
            known = allowed.get(document.source_id)
            if known != document or document.lane != lane:
                raise ContractError("provider returned a non-frozen or mislabelled source")
            if document.root_source_id in seen_roots:
                dropped.append(document.root_source_id)
                continue
            seen_roots.add(document.root_source_id)
            selected.append(document)
        by_lane[lane] = tuple(selected)
    return SourceBundle(policy.content_hash, source_bundle.content_hash, active, by_lane, tuple(sorted(set(dropped))))
