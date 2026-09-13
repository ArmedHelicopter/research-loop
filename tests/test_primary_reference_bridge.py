"""Synthetic references only. No real task answer, model or network access."""
import csv
import hashlib
import json
from pathlib import Path

from evaluation.modular import primary_process_qualification as qualification
from evaluation.modular.primary_prospective_exporter import PrimaryProspectiveTrainExporter, PrimaryTrainExportItem
from evaluation.modular.primary_reference_bridge import PrimaryReferenceItem, PrimaryProspectiveReferenceBridge
from evaluation.modular.reference_store import FrozenTrainReferenceResolver
from research_loop.ontology import digest
from test_primary_process_qualification import source_fixture, pin, write, SECRET

def material(tmp_path):
    config = source_fixture(tmp_path, public_projection=True, reference_projection=True)
    sealed = tmp_path / "sealed"
    receipt = qualification.seal_primary_process(sealed, config)
    split = json.loads((sealed / "prospective-split.json").read_bytes())
    audit = json.loads((sealed / "process-audit.json").read_bytes())
    eligibility = tmp_path / "eligibility.json"
    write(eligibility, {"schema": "primary-train-export-eligibility-v1", "split_sha256": receipt["split_sha256"],
        "audit_sha256": receipt["audit_sha256"], "train_export_enabled": True, "held_group_sha256": [],
        "held_member_tokens": [], "review_evidence_sha256": [digest("fixture-review")], "validation_access_enabled": False})
    exporter = PrimaryProspectiveTrainExporter(config, sealed, expected_split_digest=receipt["split_sha256"],
        expected_audit_digest=receipt["audit_sha256"], expected_split_sha256=pin(sealed / "prospective-split.json")["sha256"],
        expected_audit_sha256=pin(sealed / "process-audit.json")["sha256"], eligibility_path=eligibility,
        eligibility_sha256=pin(eligibility)["sha256"], output_root=tmp_path / "public", audit_root=tmp_path / "exports")
    sources = {row["token"]: row["source"] for row in audit["rows"]}
    items = {domain: [PrimaryTrainExportItem(sources[token], token, group["group_sha256"], digest(audit["input_bindings"]))
        for group in split["groups"] if group["split"] == domain for token in group["member_tokens"]] for domain in ("train", "validation")}
    selected = [next(item for item in items["train"] if item.source == source) for source in qualification.SOURCES]
    packets = exporter.export_packets(selected)
    key = tmp_path / "answer-key.csv"
    with key.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["dataset", "metadataid", "query_id", "gold_hypo"])
        writer.writeheader()
        for index in range(4):
            writer.writerow({"dataset": f"case{index}", "metadataid": index, "query_id": 0,
                "gold_hypo": "SYNTHETIC-DISCOVERY-BRIDGE-REFERENCE"})
        writer.writerow({"dataset": "UNALLOCATED", "metadataid": 99, "query_id": 0, "gold_hypo": "UNALLOCATED-REFERENCE-SENTINEL"})
    keys = {"synth": {**pin(key), "encoding": "utf-8-sig"}}
    requests = [PrimaryReferenceItem(item, packet.task.content_hash, pin(packet.packet_path)["sha256"],
        pin(packet.csv_path)["sha256"], pin(packet.packet_path.parent / "receipt.json")["sha256"])
        for item, packet in zip(selected, packets, strict=True)]
    bridge = PrimaryProspectiveReferenceBridge(exporter=exporter,
        export_receipt_sha256=pin(exporter.output_root / "export-receipt.json")["sha256"],
        store_root=tmp_path / "private-references", audit_root=tmp_path / "reference-audit", discovery_answer_keys=keys)
    return bridge, requests, packets, items

def test_primary_new_identity_reaches_standard_frozen_reference_resolver(tmp_path):
    bridge, requests, packets, _ = material(tmp_path)
    publication = bridge.prepare(requests, packets).data()
    resolver = FrozenTrainReferenceResolver(bridge.store_root, manifest_sha256=publication["manifest_sha256"],
        inventory_digest=publication["inventory_digest"], split_digest=publication["split_digest"])
    assert publication["reference_count"] == 2
    for packet in packets:
        handle = publication["task_handles"][digest(packet.task.identity.data())]
        reference = resolver(handle, packet.task.identity.benchmark)
        assert reference.data()["task_context"] == packet.task.payload.data()
        assert reference.data()["identity_digest"] == digest(packet.task.identity.data())
        assert "UNALLOCATED-REFERENCE-SENTINEL" not in reference.encoded
        assert "SYNTHETIC-" in reference.encoded
    assert "REFERENCE" not in json.dumps(publication)
