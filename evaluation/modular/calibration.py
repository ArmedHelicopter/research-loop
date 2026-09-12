"""Signed scorer-calibration gate for validation custody.

The receipt is deliberately narrow: it establishes that a configured external
authority bound a scorer and its calibration protocol to one frozen panel.  It
does not establish scientific truth or replace a later acceptance authority.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any, Mapping

from research_loop.modular.contracts import FrozenRecord, required_text
from research_loop.ontology import ContractError, canonical


BENCHMARKS = frozenset(("blade", "discoverybench"))


def _digest(value: Any, field: str) -> str:
    required_text(value, field)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ContractError(f"{field} must be a sha256 digest")
    return value


def _nonnegative_counts(value: Any) -> None:
    if not isinstance(value, Mapping) or not value:
        raise ContractError("calibration confusion matrix must be nonempty")
    for row in value.values():
        if not isinstance(row, Mapping) or not row or any(type(count) is not int or count < 0 for count in row.values()):
            raise ContractError("calibration confusion matrix counts must be nonnegative integers")


def _uncertainty(value: Any) -> None:
    if not isinstance(value, Mapping) or not value or any(type(number) not in {int, float} or number < 0 for number in value.values()):
        raise ContractError("calibration uncertainty must be nonnegative numeric fields")


@dataclass(frozen=True)
class CalibrationAuthority:
    """Testable signing adapter; production keys belong to an external service."""
    authority_id: str
    key: bytes

    def __post_init__(self) -> None:
        required_text(self.authority_id, "calibration authority id")
        if not isinstance(self.key, bytes) or len(self.key) < 32:
            raise ContractError("calibration authority key must have at least 32 bytes")

    def issue(self, body: Mapping[str, Any]) -> FrozenRecord:
        material = dict(body)
        material["authority"] = self.authority_id
        validate_calibration_body(material)
        return FrozenRecord.from_dict({"body": material,
            "mac": hmac.new(self.key, canonical(material).encode(), hashlib.sha256).hexdigest()})


def validate_calibration_body(body: Mapping[str, Any]) -> None:
    required = {"schema", "authority", "panel_digest", "scorer_digest", "protocol_digest", "scorer_code_digest",
                "judge_identity", "judge_parameters", "rubric_digest", "calibration_manifest_digest",
                "blind_review_protocol_digest", "arbitration_protocol_digest", "applicable_benchmarks",
                "confusion_matrix", "uncertainty"}
    if not isinstance(body, Mapping) or set(body) != required or body["schema"] != "scorer-calibration-v1":
        raise ContractError("invalid scorer calibration receipt schema")
    for field in ("authority", "judge_identity"):
        required_text(body[field], field)
    for field in ("panel_digest", "scorer_digest", "protocol_digest", "scorer_code_digest", "rubric_digest",
                  "calibration_manifest_digest", "blind_review_protocol_digest", "arbitration_protocol_digest"):
        _digest(body[field], field)
    if not isinstance(body["judge_parameters"], Mapping):
        raise ContractError("judge parameters must be a mapping")
    if not isinstance(body["applicable_benchmarks"], list) or set(body["applicable_benchmarks"]) != BENCHMARKS or len(body["applicable_benchmarks"]) != len(BENCHMARKS):
        raise ContractError("calibration must exactly cover both required benchmarks")
    _nonnegative_counts(body["confusion_matrix"])
    _uncertainty(body["uncertainty"])


def verify_calibration_receipt(receipt: FrozenRecord, keys: Mapping[str, bytes], *, panel_digest: str,
                               scorer_digest: str, protocol_digest: str) -> Mapping[str, Any]:
    if not isinstance(receipt, FrozenRecord):
        raise ContractError("calibration receipt must be frozen")
    envelope = receipt.data()
    if set(envelope) != {"body", "mac"} or not isinstance(envelope["body"], Mapping) or not isinstance(envelope["mac"], str):
        raise ContractError("malformed scorer calibration receipt")
    body = envelope["body"]
    validate_calibration_body(body)
    authority = body["authority"]
    if authority not in keys or not isinstance(keys[authority], bytes):
        raise ContractError("untrusted scorer calibration authority")
    expected = hmac.new(keys[authority], canonical(dict(body)).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(envelope["mac"], expected):
        raise ContractError("scorer calibration signature mismatch")
    if body["panel_digest"] != _digest(panel_digest, "panel digest") or body["scorer_digest"] != _digest(scorer_digest, "scorer digest") or body["protocol_digest"] != _digest(protocol_digest, "protocol digest"):
        raise ContractError("scorer calibration does not bind exact panel, scorer, and protocol")
    return body
