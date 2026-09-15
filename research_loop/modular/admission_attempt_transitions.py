"""Retain and independently re-read admission controller checkpoints.

This sidecar is engineering custody evidence only.  It binds exact attempt-file
bytes to a configured producer and an append-only local sequence; it supplies
no score, module, or scientific authority.  Rehashing a local sequence is only
detectable when a caller supplies an independently retained external tail.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

from research_loop.modular.artifact_catalogue import source_snapshot
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError

_ZERO = "0" * 64
_ROW_SCHEMA = "admission-controller-attempt-transition-v2"
_RECEIPT_SCHEMA = "admission-controller-attempt-transitions-v2"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class AttemptTransitions:
    """Write-once copies of the exact bytes written to controller-attempt.json."""

    def __init__(self, root: Path, *, producer_source: Path, config_digest: str):
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
        except FileExistsError as exc:
            raise ContractError("attempt checkpoint copy already exists") from exc
        row = FrozenRecord.from_dict({
            "schema": _ROW_SCHEMA,
            "sequence": self.sequence,
            "previous_transition_digest": self.previous,
            "checkpoint": {"path": relative, "sha256": _sha256(raw), "bytes": len(raw)},
            "producer_source": source_snapshot(self.producer_source),
            "config_digest": self.config_digest,
        })
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(row.encoded + "\n")
            handle.flush()
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
        })


def _receipt_data(receipt: FrozenRecord | Mapping[str, Any]) -> dict[str, Any]:
    return receipt.data() if isinstance(receipt, FrozenRecord) else dict(receipt)


def verify_attempt_transitions(root: Path, receipt: FrozenRecord | Mapping[str, Any], *,
                               producer_source: Path, config_digest: str,
                               current_checkpoint: Path, external_tail: str) -> FrozenRecord:
    """Read chain, retained bytes, current bytes, and an external tail anew."""
    root = Path(root)
    received = _receipt_data(receipt)
    if received.get("schema") != _RECEIPT_SCHEMA or received.get("config_digest") != config_digest:
        raise ContractError("attempt transition receipt configuration differs")
    if received.get("producer_source") != source_snapshot(Path(producer_source)):
        raise ContractError("attempt transition receipt producer differs")
    if received.get("external_tail") != external_tail:
        raise ContractError("attempt transition external tail differs")
    try:
        lines = (root / "controller-attempt-transitions.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ContractError("attempt transition sidecar is unavailable") from exc
    previous = _ZERO
    rows: list[dict[str, Any]] = []
    for sequence, line in enumerate(lines, start=1):
        record = FrozenRecord(line)
        row = record.data()
        checkpoint = row.get("checkpoint")
        if (row.get("schema") != _ROW_SCHEMA or row.get("sequence") != sequence
                or row.get("previous_transition_digest") != previous
                or row.get("config_digest") != config_digest
                or row.get("producer_source") != source_snapshot(Path(producer_source))
                or not isinstance(checkpoint, dict)
                or checkpoint.get("path") != f"controller-attempt-checkpoints/{sequence:06d}.json"):
            raise ContractError("attempt transition row differs")
        try:
            raw = (root / checkpoint["path"]).read_bytes()
        except (KeyError, OSError) as exc:
            raise ContractError("attempt transition checkpoint is unavailable") from exc
        if checkpoint.get("sha256") != _sha256(raw) or checkpoint.get("bytes") != len(raw):
            raise ContractError("attempt transition checkpoint bytes differ")
        previous = record.content_hash
        rows.append(row)
    if not rows or received.get("count") != len(rows) or previous != external_tail:
        raise ContractError("attempt transition chain differs")
    current = Path(current_checkpoint).read_bytes()
    expected_current = {"path": "controller-attempt.json", "sha256": _sha256(current), "bytes": len(current)}
    if received.get("current_checkpoint") != expected_current:
        raise ContractError("current controller checkpoint differs")
    if rows[-1]["checkpoint"] != {"path": f"controller-attempt-checkpoints/{len(rows):06d}.json",
                                     "sha256": _sha256(current), "bytes": len(current)}:
        raise ContractError("final retained checkpoint differs")
    return FrozenRecord.from_dict({"schema": "admission-controller-attempt-transition-verification-v1",
                                   "count": len(rows), "external_tail": external_tail,
                                   "current_checkpoint": expected_current,
                                   "status": "verified"})
