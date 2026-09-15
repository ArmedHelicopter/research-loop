"""Retain and independently re-read admission controller checkpoints.

This sidecar is engineering custody evidence only.  It binds exact attempt-file
bytes to a configured producer and an append-only local sequence; it supplies
no score, module, or scientific authority.  Rehashing a local sequence is only
detectable when a caller supplies an independently retained external tail.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Mapping

from research_loop.modular.artifact_catalogue import source_snapshot
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError

_ZERO = "0" * 64
_ROW_SCHEMA = "admission-controller-attempt-transition-v2"
_RECEIPT_SCHEMA = "admission-controller-attempt-transitions-v2"
_ROW_KEYS = frozenset({"schema", "sequence", "previous_transition_digest", "checkpoint", "producer_source", "retention_source", "config_digest"})
_RECEIPT_KEYS = frozenset({"schema", "count", "external_tail", "current_checkpoint", "config_digest", "producer_source", "retention_source"})
_CHECKPOINT_KEYS = frozenset({"path", "sha256", "bytes"})


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: Any) -> bool:
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _checkpoint(value: Any, *, path: str) -> bool:
    return (isinstance(value, dict) and set(value) == _CHECKPOINT_KEYS and value.get("path") == path
            and _digest(value.get("sha256")) and type(value.get("bytes")) is int and value["bytes"] >= 0)


class AttemptTransitions:
    """Write-once copies of exact bytes written to controller-attempt.json."""

    def __init__(self, root: Path, *, producer_source: Path, config_digest: str):
        if not _digest(config_digest):
            raise ContractError("attempt transition configuration digest differs")
        self.root = Path(root)
        self.producer_source = Path(producer_source)
        self.config_digest = config_digest
        self.path = self.root / "controller-attempt-transitions.jsonl"
        self.checkpoints = self.root / "controller-attempt-checkpoints"
        self.sequence = 0
        self.previous = _ZERO
        if self.path.exists():
            raise ContractError("attempt transition sidecar must begin at an unused controller root")

    def append_checkpoint(self, current_checkpoint: Path) -> FrozenRecord:
        """Copy bytes only after the controller's atomic write has completed."""
        raw = Path(current_checkpoint).read_bytes()
        self.sequence += 1
        relative = f"controller-attempt-checkpoints/{self.sequence:06d}.json"
        copy_path = self.root / relative
        self.checkpoints.mkdir(exist_ok=True)
        try:
            with copy_path.open("xb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise ContractError("attempt checkpoint copy already exists") from exc
        row = FrozenRecord.from_dict({
            "schema": _ROW_SCHEMA,
            "sequence": self.sequence,
            "previous_transition_digest": self.previous,
            "checkpoint": {"path": relative, "sha256": _sha256(raw), "bytes": len(raw)},
            "producer_source": source_snapshot(self.producer_source),
            "retention_source": source_snapshot(Path(__file__)),
            "config_digest": self.config_digest,
        })
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(row.encoded + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.previous = row.content_hash
        return row

    def receipt(self, current_checkpoint: Path) -> FrozenRecord:
        if self.sequence < 1:
            raise ContractError("attempt transition receipt requires a persisted checkpoint")
        raw = Path(current_checkpoint).read_bytes()
        return FrozenRecord.from_dict({
            "schema": _RECEIPT_SCHEMA,
            "count": self.sequence,
            "external_tail": self.previous,
            "current_checkpoint": {"path": "controller-attempt.json", "sha256": _sha256(raw), "bytes": len(raw)},
            "config_digest": self.config_digest,
            "producer_source": source_snapshot(self.producer_source),
            "retention_source": source_snapshot(Path(__file__)),
        })


def _receipt_data(receipt: FrozenRecord | Mapping[str, Any]) -> dict[str, Any]:
    return receipt.data() if isinstance(receipt, FrozenRecord) else dict(receipt)


def verify_attempt_transitions(root: Path, receipt: FrozenRecord | Mapping[str, Any], *,
                               producer_source: Path, config_digest: str,
                               current_checkpoint: Path, external_tail: str) -> FrozenRecord:
    """Read, validate, and re-read chain/copies/sources/current bytes before return."""
    root = Path(root)
    received = _receipt_data(receipt)
    producer = source_snapshot(Path(producer_source))
    retention = source_snapshot(Path(__file__))
    if (set(received) != _RECEIPT_KEYS or received.get("schema") != _RECEIPT_SCHEMA
            or type(received.get("count")) is not int or received["count"] < 1
            or not _digest(received.get("external_tail")) or received.get("config_digest") != config_digest
            or received.get("producer_source") != producer or received.get("retention_source") != retention
            or not _checkpoint(received.get("current_checkpoint"), path="controller-attempt.json")):
        raise ContractError("attempt transition receipt differs")
    if received["external_tail"] != external_tail:
        raise ContractError("attempt transition external tail differs")
    chain_path = root / "controller-attempt-transitions.jsonl"
    try:
        chain_before = chain_path.read_bytes()
        current_before = Path(current_checkpoint).read_bytes()
    except OSError as exc:
        raise ContractError("attempt transition inputs are unavailable") from exc
    lines = chain_before.decode("utf-8").splitlines()
    previous = _ZERO
    retained: list[tuple[Path, bytes]] = []
    for sequence, line in enumerate(lines, start=1):
        record = FrozenRecord(line)
        row = record.data()
        relative = f"controller-attempt-checkpoints/{sequence:06d}.json"
        checkpoint = row.get("checkpoint")
        if (set(row) != _ROW_KEYS or row.get("schema") != _ROW_SCHEMA
                or type(row.get("sequence")) is not int or row["sequence"] != sequence
                or row.get("previous_transition_digest") != previous or not _digest(previous)
                or row.get("config_digest") != config_digest or row.get("producer_source") != producer
                or row.get("retention_source") != retention or not _checkpoint(checkpoint, path=relative)):
            raise ContractError("attempt transition row differs")
        try:
            raw = (root / relative).read_bytes()
        except OSError as exc:
            raise ContractError("attempt transition checkpoint is unavailable") from exc
        if checkpoint["sha256"] != _sha256(raw) or checkpoint["bytes"] != len(raw):
            raise ContractError("attempt transition checkpoint bytes differ")
        retained.append((root / relative, raw))
        previous = record.content_hash
    if len(retained) != received["count"] or previous != external_tail:
        raise ContractError("attempt transition chain differs")
    expected_current = {"path": "controller-attempt.json", "sha256": _sha256(current_before), "bytes": len(current_before)}
    if received["current_checkpoint"] != expected_current or retained[-1][1] != current_before:
        raise ContractError("final retained checkpoint differs")
    # Detect a replacement during validation; this does not assert OS-level
    # immutability after the caller regains control.
    if (chain_path.read_bytes() != chain_before or Path(current_checkpoint).read_bytes() != current_before
            or any(path.read_bytes() != raw for path, raw in retained)
            or source_snapshot(Path(producer_source)) != producer or source_snapshot(Path(__file__)) != retention):
        raise ContractError("attempt transition changed during verification")
    return FrozenRecord.from_dict({"schema": "admission-controller-attempt-transition-verification-v1",
                                   "count": len(retained), "external_tail": external_tail,
                                   "current_checkpoint": expected_current,
                                   "status": "verified"})