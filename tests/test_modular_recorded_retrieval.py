"""Independent adversarial checks on the public recorded-provider contract."""
import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.modules.retrieval import FrozenSourceBundle, SourceDocument
from research_loop.modular.recorded_retrieval import RecordedRetrievalProvider
from research_loop.modular.retrieval_panel_drivers import _select_sources
from research_loop.ontology import ContractError


class Journal:
    def __init__(self): self.events = []
    def _record(self, stage, data): self.events.append((stage, data))


def document(source="s", root="r", lane="support", text="public"):
    return SourceDocument(source, root, lane, FrozenRecord.from_dict({"text": text}))


def call(provider, journal, docs, source_limit=1):
    port = RecordedRetrievalProvider(provider, journal, provider_calls=1, source_cap=source_limit)
    return port.search(lane="support", query=FrozenRecord.from_dict({"question": "q"}),
                       source_bundle=FrozenSourceBundle("pool", tuple(docs)), source_limit=source_limit)


def test_reservation_precedes_io_and_partial_failure_keeps_cost_and_items():
    journal = Journal(); doc = document()
    class Failure(RuntimeError): cost = {"usd": 0.25, "status": "provider_reported"}
    class Failing:
        def search(self, **kwargs):
            assert journal.events[0][0] == "q8_retrieval_request"
            assert journal.events[0][1]["remaining"] == {"provider_calls": 0, "source_slots": 0}
            yield doc
            raise Failure("transport ended after the first item")
    with pytest.raises(Failure): call(Failing(), journal, [doc], 2)
    assert [stage for stage, _ in journal.events] == ["q8_retrieval_request", "q8_retrieval_item", "q8_retrieval_failure"]
    failure = journal.events[-1][1]
    assert failure["reported_cost"]["usd"] == 0.25 and failure["returned_before_failure"] == 1
    assert failure["verified_external_cost"] == {"units": None, "status": "unknown"}


def test_infinite_provider_is_probed_only_to_limit_plus_one():
    journal = Journal(); doc = document(); yielded = []
    class Infinite:
        def search(self, **kwargs):
            while True:
                yielded.append(1)
                yield doc
    with pytest.raises(ContractError, match="exceeded frozen source budget"):
        call(Infinite(), journal, [doc])
    assert len(yielded) == 2
    assert journal.events[-2][1]["within_reservation"] is False
    assert journal.events[-1][0] == "q8_retrieval_failure"


@pytest.mark.parametrize("bad", [document(text="substituted"), document(lane="counter"), object()])
def test_foreign_or_mislabelled_return_is_recorded_and_rejected(bad):
    journal = Journal()
    class Foreign:
        def search(self, **kwargs): return [bad]
    with pytest.raises(ContractError, match="non-frozen or mislabelled"):
        call(Foreign(), journal, [document()])
    assert journal.events[-1][0] == "q8_retrieval_failure"


def test_no_retry_can_exceed_a_reserved_provider_call():
    journal = Journal(); doc = document(); invoked = []
    class Provider:
        def search(self, **kwargs): invoked.append(1); return []
    port = RecordedRetrievalProvider(Provider(), journal, provider_calls=1, source_cap=2)
    args = dict(lane="support", query=FrozenRecord.from_dict({"q": "q"}), source_bundle=FrozenSourceBundle("p", (doc,)), source_limit=1)
    port.search(**args)
    with pytest.raises(ContractError, match="total budget"): port.search(**args)
    assert len(invoked) == 1


@pytest.mark.parametrize("variant", ["support_only", "neutral", "three_lane"])
def test_total_context_includes_metadata_and_utf8_and_same_opportunities(variant):
    journal = Journal()
    docs = tuple(document(lane, lane, lane, "中文" * 500) for lane in ("support", "counter", "method"))
    class Provider:
        def search(self, *, lane, **kwargs): return [doc for doc in docs if doc.lane == lane]
    budget = {"provider_calls": 3, "source_cap": 3, "context_bytes": 512}
    result, usage = _select_sources(Provider(), journal, docs, {"question": "q"}, budget, "Q8.3", variant, True)
    assert len(FrozenRecord.from_dict(result).encoded.encode("utf-8")) == usage["context_bytes"] <= 512
    assert usage["limits"] == budget and usage["provider_calls"] == usage["sources_returned"] == 3
    assert usage["unused_context_bytes"] + usage["context_bytes"] == 512
    assert all(not values for values in result["by_lane"].values())
    assert len(next(data for stage, data in journal.events if stage == "q8_retrieval_selection")["excluded_context_budget"]) == 3


def test_root_dedup_is_structural_and_text_never_grants_admission():
    journal = Journal()
    docs = tuple(document(lane, "one-root", lane, "trusted verified validated scientifically independent") for lane in ("support", "counter", "method"))
    class Provider:
        def search(self, *, lane, **kwargs): return [doc for doc in docs if doc.lane == lane]
    result, _ = _select_sources(Provider(), journal, docs, {"question": "q"}, {"provider_calls": 3, "source_cap": 3, "context_bytes": 4096}, "Q8.3", "three_lane", True)
    assert sum(map(len, result["by_lane"].values())) == 1
    assert result["scientific_admission"] is False
    assert next(data for stage, data in journal.events if stage == "q8_retrieval_selection")["dropped_duplicate_roots"] == ["one-root"]


def test_delivered_q81_through_q87_have_production_drivers():
    from research_loop.modular.panel_runner import DRIVERS
    assert {key for key in DRIVERS if key.startswith("Q8.")} == {"Q8.1", "Q8.2", "Q8.3", "Q8.4", "Q8.5", "Q8.6", "Q8.7"}
