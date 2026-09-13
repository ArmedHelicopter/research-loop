"""Custodian-only prospective primary train bridge to the standard scorer store."""
from __future__ import annotations

import contextlib
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path

from evaluation.modular.fresh_airs_custodian import CustodyError, _check, _write_new
from evaluation.modular.primary_prospective_exporter import PrimaryProspectiveTrainExporter, PrimaryTrainExportItem
from evaluation.modular.prospective_train_exporter import _concrete
from evaluation.modular.reference_store import _discovery, _blade, publish_train_reference_records
from evaluation.modular.train_io import PublicTrainPacket
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import canonical, digest

ZERO = "0" * 64


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class PrimaryReferenceItem:
    item: PrimaryTrainExportItem
    task_sha256: str
    public_sha256: str
    csv_sha256: str
    receipt_sha256: str

    def __post_init__(self):
        if type(self.item) is not PrimaryTrainExportItem:
            raise CustodyError()
        for value in (self.task_sha256, self.public_sha256, self.csv_sha256, self.receipt_sha256):
            _check(value, "sha")

    def data(self):
        return {"item": self.item.data(), "task_sha256": self.task_sha256,
                "public_sha256": self.public_sha256, "csv_sha256": self.csv_sha256,
                "receipt_sha256": self.receipt_sha256}


class PrimaryProspectiveReferenceBridge:
    """Keep store and audit outside solver mounts; this is not OS isolation."""
    def __init__(self, *, exporter, export_receipt_sha256, store_root, audit_root, discovery_answer_keys):
        if type(exporter) is not PrimaryProspectiveTrainExporter:
            raise CustodyError()
        _check(export_receipt_sha256, "sha")
        self.exporter = exporter
        self.export_receipt_sha256 = export_receipt_sha256
        self.store_root, self.audit_root = map(_concrete, (store_root, audit_root))
        self.discovery_answer_keys = FrozenRecord.from_dict(discovery_answer_keys)
        for root in (self.store_root, self.audit_root):
            for other in (Path(exporter.config["snapshot_root"]), exporter.output_root,
                          exporter.audit_root, exporter.sealed_root):
                other = _concrete(other)
                if root.is_relative_to(other) or other.is_relative_to(root):
                    raise CustodyError()
        if self.store_root.is_relative_to(self.audit_root) or self.audit_root.is_relative_to(self.store_root):
            raise CustodyError()
        self._previous, self._sequence = ZERO, 0

    def _journal(self):
        self._previous, self._sequence = ZERO, 0
        path = _concrete(self.audit_root / "references.jsonl")
        if path.exists():
            for line in path.read_bytes().splitlines():
                row = json.loads(line)
                recorded = row.pop("entry_sha256")
                if (row.get("schema") != "primary-train-reference-event-v1" or recorded != digest(row)
                        or row.get("previous_sha256") != self._previous or row.get("sequence") != self._sequence + 1
                        or row.get("split_sha256") != self.exporter.expected_split_digest
                        or row.get("audit_sha256") != self.exporter.expected_audit_digest):
                    raise CustodyError()
                self._previous, self._sequence = recorded, self._sequence + 1

    def _event(self, event, phase, request_sha, attempt, possible=(), publication_sha=ZERO):
        row = {"schema": "primary-train-reference-event-v1", "event": event, "phase": phase,
            "sequence": self._sequence + 1, "previous_sha256": self._previous, "attempt": attempt,
            "request_sha256": request_sha, "split_sha256": self.exporter.expected_split_digest,
            "audit_sha256": self.exporter.expected_audit_digest, "eligibility_sha256": self.exporter.eligibility_sha256,
            "export_receipt_sha256": self.export_receipt_sha256,
            "answer_key_descriptors_sha256": self.discovery_answer_keys.content_hash,
            "possibly_read_train_tokens": sorted(possible), "publication_sha256": publication_sha,
            "error": "contract_or_io_failure" if event == "failed" else None,
            "model_calls": 0, "network_calls": 0, "known_cost_units": 0,
            "cost_status": "local_reference_preparation_no_external_calls", "validation_reference_count": 0}
        entry_sha = digest(row)
        with _concrete(self.audit_root / "references.jsonl").open("ab") as stream:
            stream.write((canonical({**row, "entry_sha256": entry_sha}) + "\n").encode())
            stream.flush(); os.fsync(stream.fileno())
        self._previous, self._sequence = entry_sha, self._sequence + 1

    def _bytes(self, path, expected):
        before = _concrete(path)
        raw = before.read_bytes()
        if _concrete(path) != before or _sha(raw) != expected:
            raise CustodyError()
        self._observed[before] = expected
        return raw

    def _packet_gate(self, requests, packets, audit):
        """Entire allocation and declared public packet gate precedes source reads."""
        if len(requests) != len(packets) or any(type(packet) is not PublicTrainPacket for packet in packets):
            raise CustodyError()
        for request, packet in zip(requests, packets, strict=True):
            identity = packet.task.identity
            identity.require_train()
            if (identity.benchmark != request.item.source or identity.group_id != request.item.group_sha256
                    or identity.dataset_version != audit["inventory_digest"]
                    or identity.split_id != self.exporter.expected_split_digest
                    or packet.task.content_hash != request.task_sha256):
                raise CustodyError()
        raw = self._bytes(self.exporter.output_root / "export-receipt.json", self.export_receipt_sha256)
        receipt = json.loads(raw)
        if (receipt.get("schema") != "prospective-train-export-receipt-v1"
                or receipt.get("split_sha256") != self.exporter.expected_split_digest
                or receipt.get("audit_sha256") != self.exporter.expected_audit_digest
                or receipt.get("validation_projection_count") != 0 or receipt.get("public_projection_written") is not True):
            raise CustodyError()
        records = receipt["packets"]
        by_token = {row["export_token"]: row for row in records}
        if len(by_token) != len(records):
            raise CustodyError()
        for request, packet in zip(requests, packets, strict=True):
            item = request.item
            root = self.exporter.output_root / item.token
            if (Path(packet.packet_path).absolute() != root / "public.json"
                    or Path(packet.csv_path).absolute() != root / "data.csv"):
                raise CustodyError()
            metadata = packet.receipt.data()
            if (metadata != by_token.get(item.token) or metadata.get("identity") != packet.task.identity.data()
                    or metadata.get("packet_hash") != request.task_sha256 or metadata.get("csv_sha256") != request.csv_sha256
                    or metadata.get("input_bindings_digest") != item.input_bindings_digest
                    or metadata.get("eligibility_sha256") != self.exporter.eligibility_sha256):
                raise CustodyError()
            if json.loads(self._bytes(packet.packet_path, request.public_sha256)) != {"task": packet.task.data(), "receipt": metadata}:
                raise CustodyError()
            if json.loads(self._bytes(root / "receipt.json", request.receipt_sha256)) != metadata:
                raise CustodyError()
            data = self._bytes(packet.csv_path, request.csv_sha256)
            if len(data) != metadata["csv_byte_count"]:
                raise CustodyError()
        return receipt

    def _reference_reader(self, path, allowed_hashes):
        """Parse only this once-read buffer, with exact locator and content pins."""
        path = _concrete(path)
        source = self.exporter._source_hashes.get(digest(str(path)))
        key = self._key_pins.get(path)
        expected = source if source is not None else key
        if expected is None or expected not in allowed_hashes or (source is not None and key is not None and source != key):
            raise CustodyError()
        return self._bytes(path, expected), expected

    def _finish_checks(self, items, audit):
        self.exporter._allocation(items)
        self.exporter._verify_audit_inputs(audit)
        for path, expected in tuple(self._observed.items()):
            self._bytes(path, expected)

    def prepare(self, requests, packets):
        self.audit_root.mkdir(parents=True, exist_ok=True)
        _concrete(self.audit_root)
        lock_path = self.audit_root / "reference.lock"
        try:
            lock = lock_path.open("xb")
        except BaseException:
            raise CustodyError() from None
        started, phase, possible, attempt, request_sha = False, "allocation", [], 0, ZERO
        self._observed = {}
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self._journal()
                attempt = self._sequence + 1
                requests, packets = tuple(requests), tuple(packets)
                valid = bool(requests) and len(requests) <= 308 and all(type(row) is PrimaryReferenceItem for row in requests)
                if valid:
                    request_sha = digest([row.data() for row in requests])
                self._event("attempt_reserved", phase, request_sha, attempt)
                started = True
                if not valid or len({row.item.token for row in requests}) != len(requests) or self.store_root.exists():
                    raise CustodyError()
                items = tuple(row.item for row in requests)
                split, audit, indexes = self.exporter._allocation(items)
                receipt = self._packet_gate(requests, packets, audit)
                phase = "source_verification"
                self.exporter._verify_audit_inputs(audit)
                sources = self.exporter._verify_source_receipts(split, audit)
                if receipt["source_receipt_digests"] != {source: digest(value) for source, value in sources.items()}:
                    raise CustodyError()
                material = self.exporter._read_selected(items, indexes, sources)
                for request, packet in zip(requests, packets, strict=True):
                    bound = material[request.item.token]
                    if (bound["task"] != packet.task or _sha(bound["csv_bytes"]) != request.csv_sha256
                            or bound["selector"] != packet.receipt.data().get("source_selector")):
                        raise CustodyError()
                keys = self.discovery_answer_keys.data()
                needed = {self.exporter._index[item.token].official_split.split("/", 1)[0] for item in items if item.source == "discoverybench"}
                if set(keys) != needed:
                    raise CustodyError()
                self._key_pins = {}
                for descriptor in keys.values():
                    if (set(descriptor) != {"path", "sha256", "encoding"} or descriptor["encoding"] not in {"utf-8-sig", "cp1252"}
                            or not isinstance(descriptor["path"], str) or not Path(descriptor["path"]).is_absolute()):
                        raise CustodyError()
                    _check(descriptor["sha256"], "sha")
                    path = _concrete(descriptor["path"])
                    if path in self._key_pins and self._key_pins[path] != descriptor["sha256"]:
                        raise CustodyError()
                    self._key_pins[path] = descriptor["sha256"]
                self._event("sources_verified", phase, request_sha, attempt)
                prepared = []
                phase = "reference_read"
                for request, packet in zip(requests, packets, strict=True):
                    self.exporter._eligibility(items)
                    possible.append(request.item.token)
                    self._event("reference_read_reserved", phase, request_sha, attempt, possible)
                    row = self.exporter._index[request.item.token].data()
                    snapshot = Path(self.exporter.config["snapshot_root"])
                    if request.item.source == "discoverybench":
                        references, bindings = _discovery(snapshot, row, packet, keys, read_bound=self._reference_reader)
                    else:
                        references, bindings = _blade(snapshot, row, packet, read_bound=self._reference_reader)
                    prepared.append((packet, references, bindings))
                phase = "publication"
                self._finish_checks(items, audit)
                self._event("publication_reserved", phase, request_sha, attempt, possible)
                staging = _concrete(self.audit_root / f"attempt-{attempt:06d}" / "staging")
                publication = publish_train_reference_records(staging, prepared, inventory_digest=audit["inventory_digest"],
                    split_digest=self.exporter.expected_split_digest)
                self._finish_checks(items, audit)
                self.store_root.parent.mkdir(parents=True, exist_ok=True)
                _concrete(self.store_root)
                if self.store_root.exists():
                    raise CustodyError()
                os.replace(staging, self.store_root)
                _write_new(self.audit_root / f"attempt-{attempt:06d}" / "publication.json", publication.data())
                self._event("completed", phase, request_sha, attempt, possible, publication.content_hash)
                return publication
        except BaseException:
            if started:
                try:
                    self._event("failed", phase, request_sha, attempt, possible)
                except BaseException:
                    pass  # The durable earlier reservation remains unresolved.
            raise CustodyError() from None
        finally:
            lock.close()
            lock_path.unlink()
