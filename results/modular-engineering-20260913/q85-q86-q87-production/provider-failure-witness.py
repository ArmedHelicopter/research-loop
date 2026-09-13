"""Replayable offline evidence, executed against the frozen production source."""
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path.cwd()))
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.modules.retrieval import SourceDocument, FrozenSourceBundle
from research_loop.modular.recorded_retrieval import RecordedRetrievalProvider
from research_loop.ontology import ContractError

destination = Path(__file__).resolve().parent
manifest = json.loads((destination / "m6-final-corrected-source-before.json").read_text(encoding="utf-8"))
assert all(hashlib.sha256(Path(row["path"]).read_bytes()).hexdigest() == row["disk_sha256"] for row in manifest["files"])


class Journal:
    def __init__(self): self.events = []
    def _record(self, stage, data): self.events.append({"stage": stage, "data": data})


document = SourceDocument("public", "caller-root", "support", FrozenRecord.from_dict({"text": "public fixture"}))
bundle = FrozenSourceBundle("fixture", (document,))
query = FrozenRecord.from_dict({"question": "public fixture"})
journal = Journal()


class PartialFailure(RuntimeError):
    cost = {"usd": 0.25, "status": "provider_reported_fixture_not_a_real_charge"}


class Partial:
    def search(self, **kwargs):
        assert journal.events[0]["stage"] == "q8_retrieval_request"
        assert journal.events[0]["data"]["remaining"] == {"provider_calls": 0, "source_slots": 0}
        yield document
        raise PartialFailure("fixture transport ended after one item")


port = RecordedRetrievalProvider(Partial(), journal, provider_calls=1, source_cap=2)
try: port.search(lane="support", query=query, source_bundle=bundle, source_limit=2)
except PartialFailure: pass
else: raise AssertionError("partial failure disappeared")
failure = journal.events[-1]["data"]
assert failure["returned_before_failure"] == 1 and failure["reported_cost"] == PartialFailure.cost
assert failure["verified_external_cost"] == {"units": None, "status": "unknown"}
partial_events = journal.events
journal = Journal(); yielded = []


class Infinite:
    def search(self, **kwargs):
        while True:
            yielded.append(1)
            yield document


port = RecordedRetrievalProvider(Infinite(), journal, provider_calls=1, source_cap=1)
try: port.search(lane="support", query=query, source_bundle=bundle, source_limit=1)
except ContractError: pass
else: raise AssertionError("unbounded provider was accepted")
assert len(yielded) == 2 and journal.events[-2]["data"]["within_reservation"] is False
before = len(yielded)
try: port.search(lane="support", query=query, source_bundle=bundle, source_limit=1)
except ContractError: pass
else: raise AssertionError("retry exceeded the call reservation")
assert len(yielded) == before
result = {"schema": "q8-provider-failure-witness-v1", "source_commit": manifest["source_commit"],
    "provider_source_sha256": hashlib.sha256(Path("research_loop/modular/recorded_retrieval.py").read_bytes()).hexdigest(),
    "partial_failure": partial_events, "bounded_overrun": journal.events, "yielded_items": len(yielded),
    "retry_performed_provider_io": False, "paid_calls": 0, "scientific_verified": False}
(destination / "provider-failure-witness.json").write_bytes(json.dumps(result, indent=2).encode("utf-8"))
