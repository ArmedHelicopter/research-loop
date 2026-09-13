"""Train-only broker for a pinned, separately named prospective partition.

No legacy custody conversion, validation reader, lease, network, or model port.
The broker owner pins the seal; the caller can select only exact train tokens.
"""
from __future__ import annotations

import contextlib
import csv
import hashlib
import io
import json
import os
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence

from evaluation.modular.canonical_lineage import record_token
from evaluation.modular.extended_ingestion import (
    _PUBLIC_SAB, _inside, _receipt,
    prepare_extended_public_task, project_extended_public_record,
)
from evaluation.modular.fresh_airs_custodian import CustodyError, _check, _write_new
from evaluation.modular.fresh_airs_hf_custodian import safe_error
from evaluation.modular.process_source_qualification import process_audit, prospective_split
from research_loop.modular import source_ingestion
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.ontology import canonical, digest

ZERO = "0" * 64
SOURCES = ("scicode", "scienceagentbench")
COUNTS = {"scicode": 80, "scienceagentbench": 102}


def _concrete(path):
    path = Path(path).absolute()
    for ancestor in (path, *path.parents):
        try:
            info = ancestor.stat(follow_symlinks=False)
        except FileNotFoundError:
            continue
        except OSError:
            raise CustodyError() from None
        if stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise CustodyError()
    return path.resolve()


@dataclass(frozen=True)
class TrainExportItem:
    source: str
    token: str
    group_sha256: str
    source_receipt_digest: str

    def __post_init__(self):
        if self.source not in SOURCES:
            raise CustodyError()
        _check({key: value for key, value in self.data().items() if key != "source"},
               {"token": "sha", "group_sha256": "sha", "source_receipt_digest": "sha"})

    def data(self):
        return asdict(self)


@dataclass(frozen=True)
class TrainExport:
    tasks: tuple[PublicTask, ...]
    receipt: FrozenRecord


class ProspectiveTrainExporter:
    sources = SOURCES
    item_type = TrainExportItem
    max_items = 164

    def __init__(self, config: Mapping, sealed_root: Path, *, expected_split_digest: str,
                 expected_audit_digest: str, output_root: Path, audit_root: Path):
        _check({"split": expected_split_digest, "audit": expected_audit_digest}, {"split": "sha", "audit": "sha"})
        self.config = json.loads(json.dumps(config))
        self.sealed_root, self.output_root, self.audit_root = map(_concrete, (sealed_root, output_root, audit_root))
        private = _concrete(self._private_root())
        for left, right in ((self.output_root, private), (self.audit_root, private),
                            (self.output_root, self.sealed_root), (self.audit_root, self.sealed_root),
                            (self.output_root, self.audit_root)):
            if left.is_relative_to(right) or right.is_relative_to(left):
                raise CustodyError()
        self.expected_split_digest, self.expected_audit_digest = expected_split_digest, expected_audit_digest
        self._previous, self._sequence = ZERO, 0

    def _private_root(self):
        return self.config["extended_private_root"]

    def _open_journal(self):
        path = self.audit_root / "exports.jsonl"
        self._previous, self._sequence = ZERO, 0
        if path.exists():
            _concrete(path)
            for line in path.read_bytes().splitlines():
                row = json.loads(line)
                entry_sha = row.pop("entry_sha256", None)
                if (row.get("schema") != "prospective-train-export-event-v1"
                        or entry_sha != digest(row)
                        or row.get("sequence") != self._sequence + 1
                        or row.get("previous_sha256") != self._previous
                        or row.get("split_sha256") != self.expected_split_digest
                        or row.get("event") not in {"export_reserved", "sources_verified", "exposure_reserved", "export_completed", "export_failed"}):
                    raise CustodyError()
                self._previous, self._sequence = entry_sha, self._sequence + 1

    def _event(self, event, *, request_sha, attempt, phase, possible=(), error=None, source_digests=None, receipt_sha=ZERO):
        row = {"schema": "prospective-train-export-event-v1", "sequence": self._sequence + 1,
               "previous_sha256": self._previous, "split_sha256": self.expected_split_digest,
               "audit_sha256": self.expected_audit_digest, "event": event, "attempt": attempt,
               "request_sha256": request_sha, "phase": phase, "possibly_exposed_tokens": sorted(possible),
               "source_receipt_digests": source_digests or {source: ZERO for source in self.sources},
               "error": error, "receipt_sha256": receipt_sha, "model_calls": 0, "network_calls": 0,
               "known_cost_units": 0, "cost_status": "local_export_no_model_or_network_io"}
        entry_sha = digest(row)
        raw = (canonical({**row, "entry_sha256": entry_sha}) + "\n").encode()
        with (self.audit_root / "exports.jsonl").open("ab") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        self._previous, self._sequence = entry_sha, self._sequence + 1

    def _allocation(self, items):
        split_path, audit_path = self.sealed_root / "prospective-split.json", self.sealed_root / "process-audit.json"
        split = json.loads(_concrete(split_path).read_bytes())
        audit = json.loads(_concrete(audit_path).read_bytes())
        if digest(split) != self.expected_split_digest or digest(audit) != self.expected_audit_digest:
            raise CustodyError()
        groups = split.get("groups")
        if not isinstance(groups, list):
            raise CustodyError()
        base = [{key: value for key, value in group.items() if key != "split"} for group in groups]
        expected = prospective_split(audit, base, seed=split.get("seed"), validation_percent=split.get("validation_percent"))
        expected["source_receipt_digests"] = split.get("source_receipt_digests")
        if expected != split or set(split["source_receipt_digests"]) != set(SOURCES):
            raise CustodyError()
        by_token = {}
        for source in SOURCES:
            spec = source_ingestion.SOURCE_SNAPSHOTS[source]
            for index in range(COUNTS[source]):
                by_token[record_token(source, spec.revision, index)] = (source, index)
        allocation = {}
        for group in groups:
            for token in group["member_tokens"]:
                if token in allocation or token not in by_token:
                    raise CustodyError()
                source, index = by_token[token]
                if group["source"] not in {source, "mixed_extended"}:
                    raise CustodyError()
                allocation[token] = (source, index, group["group_sha256"], group["split"])
        if set(allocation) != set(by_token):
            raise CustodyError()
        for item in items:
            found = allocation.get(item.token)
            if (found is None or found[0] != item.source or found[2] != item.group_sha256 or found[3] != "train"
                    or item.source_receipt_digest != split["source_receipt_digests"][item.source]):
                raise CustodyError()
        return split, audit, {item.token: allocation[item.token][1] for item in items}

    def _verify_audit_inputs(self, audit):
        checked = process_audit(self.config)
        # The original audit end boundary is immutable; recomputation verifies
        # every actual input and observation without pretending time stood still.
        checked["end_boundary_utc"] = audit["end_boundary_utc"]
        if checked != audit:
            raise CustodyError()

    def _verify_source_receipts(self, split, audit):
        receipts = {}
        for source in SOURCES:
            spec = source_ingestion.SOURCE_SNAPSHOTS[source]
            snapshot = _concrete(Path(self.config["extended_private_root"]) / "snapshots" / source / spec.revision)
            receipt = _receipt(snapshot, source)
            original = _concrete(self.config["acquisition_receipts"][source]).read_bytes()
            if (hashlib.sha256(original).hexdigest() != audit["start_boundary_acquisition_receipts"][source]
                    or digest(json.loads(original)) != digest(receipt)
                    or digest(receipt) != split["source_receipt_digests"][source]):
                raise CustodyError()
            receipts[source] = receipt
        return receipts

    def _read_selected(self, items, indexes, receipts):
        selected = {source: {indexes[item.token]: item for item in items if item.source == source} for source in SOURCES}
        result = {}
        for source, desired in selected.items():
            if not desired:
                continue
            spec = source_ingestion.SOURCE_SNAPSHOTS[source]
            snapshot = Path(self.config["extended_private_root"]) / "snapshots" / source / spec.revision
            declarations = {row["source_path"]: row for row in receipts[source]["artifacts"]}

            def bound_bytes(name):
                raw = _inside(snapshot, name).read_bytes()
                declaration = declarations[name]
                if len(raw) != declaration["size_bytes"] or hashlib.sha256(raw).hexdigest() != declaration["local_sha256"]:
                    raise CustodyError()
                return raw

            index = 0
            if source == "scicode":
                for name in ("problems_dev.jsonl", "problems_test.jsonl"):
                    for raw in bound_bytes(name).splitlines():
                        if not raw.strip():
                            continue
                        if index in desired:
                            # No JSON object or field is inspected for any
                            # non-selected record, including validation rows.
                            result[desired[index].token] = project_extended_public_record(source, json.loads(raw))
                        index += 1
            else:
                csv.field_size_limit(256 * 1024 * 1024)
                reader = csv.reader(io.StringIO(bound_bytes("ScienceAgentBench.csv").decode("utf-8"), newline=""))
                header = next(reader)
                if len(header) != len(set(header)) or not _PUBLIC_SAB <= set(header):
                    raise CustodyError()
                positions = {key: header.index(key) for key in _PUBLIC_SAB}
                for values in reader:
                    if index in desired:
                        if len(values) != len(header):
                            raise CustodyError()
                        # Consume CSV framing for other rows, but never build
                        # their field mappings or inspect their public values.
                        public = {key: values[position] for key, position in positions.items()}
                        result[desired[index].token] = project_extended_public_record(source, public)
                    index += 1
            if index != COUNTS[source]:
                raise CustodyError()
        if set(result) != {item.token for item in items}:
            raise CustodyError()
        return result

    def _prepare_task(self, item, material):
        task_id, public = material
        identity = DataIdentity(item.source, task_id, item.group_sha256,
            source_ingestion.SOURCE_SNAPSHOTS[item.source].revision, self.expected_split_digest, "train")
        return prepare_extended_public_task(identity, public)

    def _write_public_packet(self, target, item, task, material):
        _write_new(target / "public.json", task.data())
        return {"source": item.source, "token": item.token, "group_sha256": item.group_sha256,
                "task_sha256": task.content_hash, "identity_sha256": digest(task.identity.data()),
                "public_file_sha256": hashlib.sha256((target / "public.json").read_bytes()).hexdigest()}

    def _before_exposure(self):
        pass

    def _before_publish(self):
        pass

    def export(self, item_allowlist: Sequence[TrainExportItem]) -> TrainExport:
        self.audit_root.mkdir(parents=True, exist_ok=True)
        _concrete(self.audit_root)
        lock_path = self.audit_root / "export.lock"
        try:
            lock = lock_path.open("xb")
        except Exception:
            raise CustodyError() from None
        reserved, possible, phase, source_digests = False, [], "allocation", None
        request_sha, attempt = ZERO, 0
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self._open_journal()
                attempt = self._sequence + 1
                items = tuple(item_allowlist)
                valid = bool(items) and len(items) <= self.max_items and all(type(item) is self.item_type for item in items)
                if valid:
                    request_sha = digest([item.data() for item in items])
                self._event("export_reserved", request_sha=request_sha, attempt=attempt, phase=phase)
                reserved = True
                if not valid or len({item.token for item in items}) != len(items) or self.output_root.exists():
                    raise CustodyError()
                split, audit, indexes = self._allocation(items)
                phase = "source_verification"
                self._verify_audit_inputs(audit)
                receipts = self._verify_source_receipts(split, audit)
                source_digests = {source: digest(value) for source, value in receipts.items()}
                self._event("sources_verified", request_sha=request_sha, attempt=attempt, phase=phase, source_digests=source_digests)
                phase = "train_projection"
                material = self._read_selected(items, indexes, receipts)
                tasks = []
                for item in items:
                    tasks.append(self._prepare_task(item, material[item.token]))
                self._verify_audit_inputs(audit)
                if self._verify_source_receipts(split, audit) != receipts:
                    raise CustodyError()
                phase = "materialization"
                staging = self.audit_root / f"attempt-{attempt:06d}" / "staging"
                staging.mkdir(parents=True, exist_ok=False)
                packets = []
                for item, task in zip(items, tasks):
                    self._before_exposure()
                    possible.append(item.token)
                    # Reserve exposure *before* the first task byte is written.
                    self._event("exposure_reserved", request_sha=request_sha, attempt=attempt, phase=phase,
                                possible=possible, source_digests=source_digests)
                    target = staging / item.token
                    packet = self._write_public_packet(target, item, task, material[item.token])
                    _write_new(target / "receipt.json", packet)
                    packets.append(packet)
                receipt = FrozenRecord.from_dict({"schema": "prospective-train-export-receipt-v1",
                    "split_sha256": self.expected_split_digest, "audit_sha256": self.expected_audit_digest,
                    "request_sha256": request_sha, "source_receipt_digests": source_digests,
                    "packets": packets, "public_projection_written": True, "typed_public_tasks_available_on_success": True,
                    "raw_private_payload_returned": False, "validation_projection_count": 0,
                    "scientific_execution_qualified": False, "legacy_custody_mutated": False,
                    "model_calls": 0, "network_calls": 0, "known_cost_units": 0,
                    "output_root_locator_sha256": digest(str(self.output_root))})
                _write_new(staging / "export-receipt.json", receipt.data())
                self._before_publish()
                self.output_root.parent.mkdir(parents=True, exist_ok=True)
                _concrete(self.output_root)
                if self.output_root.exists():
                    raise CustodyError()
                os.replace(staging, self.output_root)
                phase = "published"
                self._event("export_completed", request_sha=request_sha, attempt=attempt, phase=phase,
                            possible=possible, source_digests=source_digests, receipt_sha=receipt.content_hash)
                return TrainExport(tuple(tasks), receipt)
        except Exception as error:
            if reserved:
                try:
                    self._event("export_failed", request_sha=request_sha, attempt=attempt, phase=phase,
                                possible=possible, source_digests=source_digests, error=safe_error(error))
                except Exception:
                    # The earlier durable reservation remains incomplete. Do
                    # not emit a raw filesystem exception or continue output.
                    raise CustodyError("export_failed_journal_incomplete") from None
            raise CustodyError() from None
        finally:
            lock.close()
            lock_path.unlink()
