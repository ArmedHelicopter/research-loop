"""Rewrite an isolated Q8.6 specimen, rebuilding its storage dependencies."""
import hashlib
from pathlib import Path

from research_loop.modular.artifact_catalogue import ArtifactCatalogue, source_snapshot
from research_loop.modular.contracts import FrozenRecord


def rewrite(sidecar, *, fault, identity):
    journal = sidecar / "artifacts.jsonl"
    entries = [FrozenRecord(line).data() for line in journal.read_text(encoding="utf-8").splitlines()]
    originals = {p.name: FrozenRecord(p.read_text(encoding="utf-8").strip()).data()
                 for p in sidecar.glob("research-version-*.json")}
    old_run_id = entries[0]["descriptor"]["binding"]["run_id"]
    remap = {old_run_id: "f" * 32} if fault == "run_id" else {}
    def mapped(value):
        seen = set()
        while value in remap and value not in seen:
            seen.add(value); value = remap[value]
        return value
    def remember(before, after):
        old, new = FrozenRecord.from_dict(before).content_hash, FrozenRecord.from_dict(after).content_hash
        if old != new:
            remap[old] = new
    def transform(value):
        if isinstance(value, str):
            return mapped(value)
        if isinstance(value, list):
            return [transform(item) for item in value]
        if not isinstance(value, dict):
            return value
        before = value
        row = {key: transform(item) for key, item in value.items()}
        if row.get("kind") == "source_request" and "request" in row:
            if fault == "source_bundle": row["source_bundle_digest"] = "0" * 64
            if fault == "visible_sources": row["visible_source_ids"] = []
        if row.get("schema") == "q8-origin-qualification-v1" and fault == "receipt_scientific":
            row["scientific_verified"] = True
        if {"freeze_receipt", "new_objective", "authorization", "state"} <= row.keys():
            if fault == "child_schema": row["schema"] = "forged-v9"
            if fault == "child_state": row["state"] = "forged-v9"
        if row.get("to") == "needs_review" and "parent_digest" in row:
            if fault == "transition_from": row["from"] = "forged"
            if fault == "transition_reason": row["reason"] = "forged"
        if set(row) == {"path", "sha256", "bytes", "record_digest"} and row["path"] in originals:
            record = FrozenRecord.from_dict(transform(originals[row["path"]]))
            raw = (record.encoded + "\n").encode("utf-8")
            (sidecar / row["path"]).write_bytes(raw)
            remap[before["sha256"]] = hashlib.sha256(raw).hexdigest()
            row = {"path": row["path"], "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "record_digest": record.content_hash}
        remember(before, row)
        return row
    def settled(value):
        # Canonical key order can put a receipt before the subject it cites.
        # Iterate this local object until all newly discovered digest edges agree.
        for _ in range(20):
            new = transform(value)
            if new == value: return new
            value = new
        raise AssertionError("coherent copy did not settle")

    rebuilt, events, previous_entry, previous_trace = [], [], None, None
    for index, original_entry in enumerate(entries):
        original_descriptor = original_entry["descriptor"]
        descriptor = settled(original_descriptor)
        if descriptor["kind"] == "trace_event":
            old_event = original_descriptor["payload"]["canonical"]
            event = settled(old_event)
            event.update(sequence=len(events), previous=previous_trace)
            remember(old_event, event)
            previous_trace = FrozenRecord.from_dict(event).content_hash
            events.append(event)
            descriptor["payload"]["canonical"] = event
        if fault == "producer_source" and descriptor["kind"] in {"research_version_inputs", "research_version_parent", "research_version_child"}:
            descriptor["producer_source"] = source_snapshot(Path(__file__).parents[1] / "research_loop/modular/contracts.py")
        if descriptor["payload"]["canonical"] is not None:
            payload = FrozenRecord.from_dict(descriptor["payload"]["canonical"])
            descriptor["payload"] = {"digest": payload.content_hash, "bytes": len(payload.encoded.encode("utf-8")),
                "encoding": "canonical_json", "canonical": payload.data()}
        descriptor["parents"] = [mapped(parent) for parent in descriptor["parents"]]
        remember(original_descriptor, descriptor)
        frozen_descriptor = FrozenRecord.from_dict(descriptor)
        remap[original_entry["descriptor_digest"]] = frozen_descriptor.content_hash
        entry = FrozenRecord.from_dict({**original_entry, "sequence": index, "previous": previous_entry,
            "descriptor": descriptor, "descriptor_digest": frozen_descriptor.content_hash})
        remap[FrozenRecord.from_dict(original_entry).content_hash] = entry.content_hash
        previous_entry = entry.content_hash
        rebuilt.append(entry)
    journal.write_bytes("".join(row.encoded + "\n" for row in rebuilt).encode("utf-8"))
    (sidecar / "trace.jsonl").write_bytes("".join(FrozenRecord.from_dict(row).encoded + "\n" for row in events).encode("utf-8"))
    binding = rebuilt[0].data()["descriptor"]["binding"]
    seal = FrozenRecord.from_dict({"schema": "artifact-catalogue-seal-v1", "count": len(rebuilt), "head": previous_entry, "binding": binding})
    (sidecar / "artifacts.jsonl.seal.json").write_bytes((seal.encoded + "\n").encode("utf-8"))
    ArtifactCatalogue(journal, identity=identity, **binding).verify()
    # Every file snapshot must match, not merely one occurrence of its digest.
    def check(value):
        if isinstance(value, list):
            for item in value: check(item)
        elif isinstance(value, dict):
            if set(value) == {"path", "sha256", "bytes", "record_digest"} and value["path"] in originals:
                raw = (sidecar / value["path"]).read_bytes()
                assert value["sha256"] == hashlib.sha256(raw).hexdigest() and value["bytes"] == len(raw)
                assert value["record_digest"] == FrozenRecord(raw.decode().strip()).content_hash
            for item in value.values(): check(item)
    check(events)
    check([row.data() for row in rebuilt])
