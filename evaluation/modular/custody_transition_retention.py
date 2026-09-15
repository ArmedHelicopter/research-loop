"""Private, opt-in custody transition retention for independent P0 audit readback."""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Any, Mapping

from evaluation.modular.custody_audit_projection import custody_state_anchor, verify_custody_snapshot
from research_loop.modular.artifact_catalogue import source_snapshot
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError


R = FrozenRecord.from_dict
_STATUS = "custody-transition-capture-status-v1"
_CAPTURE = "custody-transition-capture-v1"
_REPORT = "custody-transition-retention-readback-v1"
_ANCHOR = "custody-transition-manifest-anchor-v1"
_MANIFEST = "transitions.jsonl"
_STATUS_LOG = "capture-status.jsonl"
_ALLOWED = frozenset({"inventory", "attest", "split", "lease_validation", "lease_panel", "consume_validation", "issued_validation_receipt"})
_HEX = frozenset("0123456789abcdef")


def _hex(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX


def _reparse(path: Path) -> bool:
    info = path.stat(follow_symlinks=False)
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _plain(path: Path) -> Path:
    path = Path(path)
    for part in (path, *path.parents):
        if part.exists() and _reparse(part):
            raise ContractError("custody transition retention reparse path refused")
    return path.resolve(strict=True)


def _record(raw: bytes, message: str) -> FrozenRecord:
    try:
        result = FrozenRecord(raw.decode("utf-8").removesuffix("\n"))
    except (UnicodeDecodeError, ContractError) as exc:
        raise ContractError(message) from exc
    if raw != (result.encoded + "\n").encode("utf-8"):
        raise ContractError(message)
    return result


def _new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())


def _append(path: Path, raw: bytes) -> None:
    with path.open("ab") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())


def custody_transition_manifest_anchor(raw: bytes) -> FrozenRecord:
    if not isinstance(raw, bytes):
        raise ContractError("custody transition manifest anchor needs bytes")
    return R({"schema": _ANCHOR, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})


def _anchor(value: FrozenRecord | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if type(value) is not FrozenRecord:
        raise ContractError("custody transition manifest anchor must be frozen")
    body = value.data()
    if set(body) != {"schema", "sha256", "bytes"} or body["schema"] != _ANCHOR or not _hex(body["sha256"]) or type(body["bytes"]) is not int or body["bytes"] < 1:
        raise ContractError("custody transition manifest anchor differs")
    return body


class CustodyTransitionRetainer:
    """Auditor-owned private sink; only use a fresh, non-reparse root."""
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        if self.root.exists() or _reparse(self.root.parent):
            raise ContractError("custody transition retention root must be new and plain")
        self.root.mkdir(parents=True)
        self._manifest, self._status = self.root / _MANIFEST, self.root / _STATUS_LOG
        self._previous, self._sequence = "0" * 64, 0

    def _status_event(self, operation: str, sequence: int, status: str, capture_digest: str | None = None) -> None:
        row = R({"schema": _STATUS, "operation": operation, "sequence": sequence,
                 "status": status, "capture_digest": capture_digest})
        raw = (row.encoded + "\n").encode("utf-8")
        _new(self._status, raw) if not self._status.exists() else _append(self._status, raw)

    def capture(self, operation: str, state_bytes: bytes, receipt: FrozenRecord | None = None) -> FrozenRecord:
        if operation not in _ALLOWED or not isinstance(state_bytes, bytes) or not state_bytes or receipt is not None and type(receipt) is not FrozenRecord:
            raise ContractError("invalid custody transition capture")
        sequence = self._sequence + 1
        self._status_event(operation, sequence, "attempted")
        try:
            state_name = f"state-{sequence:06d}.json"; _new(self.root / state_name, state_bytes)
            receipt_data: dict[str, Any] = {"status": "absent"}
            if receipt is not None:
                receipt_name = f"receipt-{sequence:06d}.json"; receipt_raw = (receipt.encoded + "\n").encode("utf-8")
                _new(self.root / receipt_name, receipt_raw)
                receipt_data = {"status": "retained", "file": receipt_name, "sha256": hashlib.sha256(receipt_raw).hexdigest(),
                                "bytes": len(receipt_raw), "digest": receipt.content_hash}
            row = R({"schema": _CAPTURE, "sequence": sequence, "previous_sha256": self._previous,
                     "operation": operation, "state_file": state_name, "state_anchor": custody_state_anchor(state_bytes).data(),
                     "receipt": receipt_data, "producer_sources": {"retainer": source_snapshot(Path(__file__))},
                     "optimizer_visible": False, "scientific_validated": False})
            raw = (row.encoded + "\n").encode("utf-8")
            _new(self._manifest, raw) if sequence == 1 else _append(self._manifest, raw)
            self._status_event(operation, sequence, "captured", row.content_hash)
        except Exception:
            try: self._status_event(operation, sequence, "failed")
            except Exception: pass
            raise
        self._previous, self._sequence = row.content_hash, sequence
        return R({"schema": _STATUS, "operation": operation, "status": "captured", "capture_digest": row.content_hash, "sequence": sequence})


def capture_custody_transition(retainer: Any, operation: str, state_bytes: bytes, receipt: FrozenRecord | None = None) -> FrozenRecord:
    """Keep retention failures observable without changing a durable custody outcome."""
    try:
        result = retainer.capture(operation, state_bytes, receipt)
        if type(result) is not FrozenRecord or result.data().get("status") != "captured":
            raise ContractError("custody retainer did not return a capture status")
        return result
    except Exception:
        return R({"schema": _STATUS, "operation": operation, "status": "failed", "error": "retention_capture_failed"})


def _safe_member(root: Path, name: Any, expected: str) -> Path:
    if not isinstance(name, str) or name != expected or "/" in name or "\\" in name:
        raise ContractError("custody transition retention member differs")
    return _plain(root / name)


def verify_custody_transition_retention(root: Path, *, receipt_keys: Mapping[str, bytes] | None = None,
                                        expected_manifest_anchor: FrozenRecord | None = None,
                                        expected_tail_capture_digest: str | None = None,
                                        expected_receipt_digest: str | None = None) -> FrozenRecord:
    """Verify retained captures; supplied anchors close the caller's expected tail."""
    root = _plain(root); manifest, status_path = _safe_member(root, _MANIFEST, _MANIFEST), _safe_member(root, _STATUS_LOG, _STATUS_LOG)
    manifest_before, status_before = manifest.read_bytes(), status_path.read_bytes()
    anchor = _anchor(expected_manifest_anchor)
    if anchor is not None and custody_transition_manifest_anchor(manifest_before).data() != anchor:
        raise ContractError("custody transition manifest anchor differs")
    statuses: dict[int, list[dict[str, Any]]] = {}
    for raw in status_before.splitlines(keepends=True):
        body = _record(raw, "custody transition status is not canonical").data()
        if (set(body) != {"schema", "operation", "sequence", "status", "capture_digest"} or body["schema"] != _STATUS
                or body["operation"] not in _ALLOWED or type(body["sequence"]) is not int or type(body["sequence"]) is bool or body["sequence"] < 1
                or body["status"] not in {"attempted", "captured", "failed"}
                or body["status"] == "captured" and not _hex(body["capture_digest"])
                or body["status"] != "captured" and body["capture_digest"] is not None):
            raise ContractError("custody transition status differs")
        statuses.setdefault(body["sequence"], []).append(body)
    previous, sequence, rows, observed = "0" * 64, 1, [], {manifest: manifest_before, status_path: status_before}
    for raw in manifest_before.splitlines(keepends=True):
        record = _record(raw, "custody transition manifest is not canonical"); body = record.data()
        required = {"schema", "sequence", "previous_sha256", "operation", "state_file", "state_anchor", "receipt", "producer_sources", "optimizer_visible", "scientific_validated"}
        if (set(body) != required or body["schema"] != _CAPTURE or body["sequence"] != sequence or body["previous_sha256"] != previous
                or body["operation"] not in _ALLOWED or body["optimizer_visible"] is not False or body["scientific_validated"] is not False
                or body["producer_sources"] != {"retainer": source_snapshot(Path(__file__))}):
            raise ContractError("custody transition manifest binding or source differs")
        if statuses.get(sequence) != [{"schema": _STATUS, "operation": body["operation"], "sequence": sequence, "status": "attempted", "capture_digest": None},
                                      {"schema": _STATUS, "operation": body["operation"], "sequence": sequence, "status": "captured", "capture_digest": record.content_hash}]:
            raise ContractError("custody transition status sequence differs")
        state_path = _safe_member(root, body["state_file"], f"state-{sequence:06d}.json"); state_raw = state_path.read_bytes(); observed[state_path] = state_raw
        if custody_state_anchor(state_raw).data() != body["state_anchor"]:
            raise ContractError("custody transition state bytes differ")
        receipt, receipt_status = None, "absent"; receipt_body = body["receipt"]
        if receipt_body != {"status": "absent"}:
            if (not isinstance(receipt_body, dict) or set(receipt_body) != {"status", "file", "sha256", "bytes", "digest"} or receipt_body["status"] != "retained"
                    or not _hex(receipt_body["sha256"]) or type(receipt_body["bytes"]) is not int or receipt_body["bytes"] < 1 or not _hex(receipt_body["digest"]) or receipt_keys is None):
                raise ContractError("custody transition receipt binding differs")
            receipt_path = _safe_member(root, receipt_body["file"], f"receipt-{sequence:06d}.json"); receipt_raw = receipt_path.read_bytes(); observed[receipt_path] = receipt_raw
            if len(receipt_raw) != receipt_body["bytes"] or hashlib.sha256(receipt_raw).hexdigest() != receipt_body["sha256"]:
                raise ContractError("custody transition receipt bytes differ")
            receipt = _record(receipt_raw, "custody transition receipt is not canonical")
            if receipt.content_hash != receipt_body["digest"]:
                raise ContractError("custody transition receipt digest differs")
            receipt_status = "retained"
        report = verify_custody_snapshot(state_path, anchor=R(body["state_anchor"]), receipt=receipt, receipt_keys=receipt_keys if receipt else None)
        rows.append({"sequence": sequence, "operation": body["operation"], "state_anchor": body["state_anchor"], "receipt_status": receipt_status, "snapshot_report_digest": report.content_hash})
        previous, sequence = record.content_hash, sequence + 1
    failed = [{"sequence": seq, "operation": group[0]["operation"]} for seq, group in sorted(statuses.items()) if seq >= sequence and group == [{"schema": _STATUS, "operation": group[0]["operation"], "sequence": seq, "status": "attempted", "capture_digest": None}, {"schema": _STATUS, "operation": group[0]["operation"], "sequence": seq, "status": "failed", "capture_digest": None}]]
    if set(statuses) != set(range(1, sequence)) | {row["sequence"] for row in failed}:
        raise ContractError("custody transition status inventory differs")
    if expected_tail_capture_digest is not None and previous != expected_tail_capture_digest:
        raise ContractError("custody transition expected tail differs")
    if expected_receipt_digest is not None and (not rows or rows[-1]["receipt_status"] != "retained" or expected_receipt_digest != body["receipt"]["digest"]):
        raise ContractError("custody transition expected receipt differs")
    expected_files = {_MANIFEST, _STATUS_LOG, *(f"state-{row['sequence']:06d}.json" for row in rows),
                      *(f"receipt-{row['sequence']:06d}.json" for row in rows if row["receipt_status"] == "retained")}
    if {path.name for path in root.iterdir() if path.is_file()} != expected_files:
        raise ContractError("custody transition retention contains unregistered files")
    for path, raw in observed.items():
        if path.read_bytes() != raw:
            raise ContractError("custody transition changed during readback")
    return R({"schema": _REPORT, "captures": rows, "capture_count": len(rows), "manifest_digest": previous,
              "failed_capture_statuses": failed, "complete_transition_history": False, "missing_or_failed_capture_possible": True,
              "optimizer_visible": False, "scientific_validated": False,
              "reader_sources": {"retention_reader": source_snapshot(Path(__file__))}})
