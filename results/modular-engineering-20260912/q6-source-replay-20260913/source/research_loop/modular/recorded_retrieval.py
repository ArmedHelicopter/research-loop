"""Bounded caller-provider I/O with pre-I/O reservations and partial receipts."""
from __future__ import annotations

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.modules.retrieval import SourceDocument
from research_loop.ontology import ContractError


class RecordedRetrievalProvider:
    def __init__(self, provider, session, *, provider_calls: int, source_cap: int):
        self.provider, self.session = provider, session
        self.calls_left, self.sources_left = provider_calls, source_cap
        self.calls_used = self.sources_returned = 0

    def search(self, *, lane, query, source_bundle, source_limit):
        if self.calls_left < 1 or source_limit < 1 or source_limit > self.sources_left:
            raise ContractError("retrieval reservation exceeds total budget")
        # Reserve the complete call and result allowance before provider code runs.
        self.calls_left -= 1
        self.sources_left -= source_limit
        self.calls_used += 1
        self.session._record("q8_retrieval_request", {
            "lane": lane, "query": query.data(), "query_digest": query.content_hash,
            "call_limit": 1, "source_limit": source_limit,
            "reservation": {"provider_calls": 1, "source_slots": source_limit},
            "remaining": {"provider_calls": self.calls_left, "source_slots": self.sources_left},
            "external_cost": {"units": None, "status": "unknown"}})
        known = {doc.source_id: doc for doc in source_bundle.documents}
        rows = []
        try:
            iterator = iter(self.provider.search(lane=lane, query=query, source_bundle=source_bundle,
                                                 call_limit=1, source_limit=source_limit))
            for ordinal in range(source_limit + 1):
                try:
                    document = next(iterator)
                except StopIteration:
                    break
                self.sources_returned += 1
                self.session._record("q8_retrieval_item", {
                    "lane": lane, "ordinal": ordinal,
                    "source_digest": FrozenRecord.from_dict(document.data()).content_hash if isinstance(document, SourceDocument) else None,
                    "within_reservation": ordinal < source_limit})
                if ordinal == source_limit:
                    raise ContractError("provider exceeded frozen source budget")
                if not isinstance(document, SourceDocument) or known.get(document.source_id) != document or document.lane != lane:
                    raise ContractError("provider returned a non-frozen or mislabelled source")
                rows.append(document)
        except Exception as exc:
            self.session._record("q8_retrieval_failure", {
                "lane": lane, "error_type": type(exc).__name__, "returned_before_failure": len(rows),
                "reported_cost": getattr(exc, "cost", None),
                "verified_external_cost": {"units": None, "status": "unknown"},
                "reserved_provider_calls": 1, "reserved_source_slots": source_limit})
            raise
        self.session._record("q8_retrieval_result", {
            "lane": lane, "returned": len(rows), "unused_reserved_sources": source_limit - len(rows),
            "provider_invocations": 1, "external_cost": {"units": None, "status": "unknown"}})
        return rows
