"""Signed scorer-calibration gate for validation custody.

The receipt is deliberately narrow: it establishes that a configured external
authority bound a scorer and its calibration protocol to one frozen panel.  It
does not establish scientific truth or replace a later acceptance authority.
"""
from __future__ import annotations

import hashlib
import hmac
import math
from dataclasses import dataclass
from typing import Any, Mapping

from research_loop.modular.contracts import FrozenRecord, required_text
from research_loop.modular.benchmarks.catalog import REQUIRED_BENCHMARKS, SUPPORTED_BENCHMARKS
from research_loop.ontology import ContractError, canonical, digest

BENCHMARKS = frozenset(REQUIRED_BENCHMARKS)
COVERAGE_KINDS = ("valid_positive", "valid_negative", "invalid_measurement", "uncertain",
                  "negation_or_quoted_completion", "correct_rejection", "over_rejection",
                  "reasonable_alternative", "empty_output")


def _digest(value: Any, field: str) -> str:
    required_text(value, field)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ContractError(f"{field} must be a sha256 digest")
    return value


def _count_map(value: Any, expected: tuple[str, ...], field: str) -> None:
    if not isinstance(value, Mapping) or set(value) != set(expected) or any(type(number) is not int or number < 0 for number in value.values()):
        raise ContractError(f"{field} must have exact nonnegative integer counts")


def _uncertainty(value: Any, benchmarks: tuple[str, ...]) -> None:
    if not isinstance(value, Mapping) or set(value) != set(benchmarks) or any(type(number) not in {int, float} or not math.isfinite(number) or number < 0 for number in value.values()):
        raise ContractError("calibration uncertainty must be finite nonnegative values for every declared benchmark")


def _criteria(value: Any) -> Mapping[str, Any]:
    required = {"minimum_cases_per_benchmark", "minimum_coverage", "minimum_precision", "minimum_recall",
                "maximum_abstention_rate", "maximum_uncertainty"}
    if not isinstance(value, Mapping) or set(value) != required:
        raise ContractError("invalid frozen calibration criteria")
    if type(value["minimum_cases_per_benchmark"]) is not int or value["minimum_cases_per_benchmark"] <= 0:
        raise ContractError("frozen calibration criteria need positive case minimum")
    _count_map(value["minimum_coverage"], COVERAGE_KINDS, "frozen calibration coverage criteria")
    for field in ("minimum_precision", "minimum_recall", "maximum_abstention_rate", "maximum_uncertainty"):
        number = value[field]
        if type(number) not in {int, float} or not math.isfinite(number) or number < 0 or (field != "maximum_uncertainty" and number > 1):
            raise ContractError("frozen calibration thresholds must be finite and in range")
    return value


def _requested_benchmarks(value: Any) -> tuple[str, ...]:
    benchmarks = _names(value, "required benchmark")
    if not set(benchmarks) <= set(SUPPORTED_BENCHMARKS) or not set(REQUIRED_BENCHMARKS) <= set(benchmarks):
        raise ContractError("required benchmarks must be supported and include the core pair")
    return benchmarks


def _names(value: Any, field: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, Mapping)):
        raise ContractError(f"{field} must be a collection")
    result = tuple(value)
    if not result or len(set(result)) != len(result) or any(not isinstance(name, str) or not name for name in result):
        raise ContractError(f"{field} must be nonempty and unique")
    return result


def calibration_eligible(body: Mapping[str, Any], *, required_benchmarks: tuple[str, ...] = REQUIRED_BENCHMARKS) -> bool:
    """Evaluate the externally signed criteria; this function has no defaults."""
    criteria = _criteria(body["criteria"])
    requested = _requested_benchmarks(required_benchmarks)
    if not set(requested) <= set(body["applicable_benchmarks"]):
        return False
    for benchmark in requested:
        coverage, matrix = body["coverage"][benchmark], body["confusion_matrix"][benchmark]
        total = sum(coverage.values())
        if total < criteria["minimum_cases_per_benchmark"] or any(coverage[name] < criteria["minimum_coverage"][name] for name in COVERAGE_KINDS):
            return False
        outcomes = matrix["tp"] + matrix["tn"] + matrix["fp"] + matrix["fn"] + matrix["abstained"]
        if outcomes != total:
            return False
        precision_denominator, recall_denominator = matrix["tp"] + matrix["fp"], matrix["tp"] + matrix["fn"]
        if not precision_denominator or not recall_denominator:
            return False
        if matrix["tp"] / precision_denominator < criteria["minimum_precision"]:
            return False
        if matrix["tp"] / recall_denominator < criteria["minimum_recall"]:
            return False
        if matrix["abstained"] / total > criteria["maximum_abstention_rate"]:
            return False
        if body["uncertainty"][benchmark] > criteria["maximum_uncertainty"]:
            return False
    return True


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
                "criteria", "criteria_digest", "coverage", "confusion_matrix", "uncertainty"}
    if not isinstance(body, Mapping) or set(body) != required or body["schema"] != "scorer-calibration-v1":
        raise ContractError("invalid scorer calibration receipt schema")
    for field in ("authority", "judge_identity"):
        required_text(body[field], field)
    for field in ("panel_digest", "scorer_digest", "protocol_digest", "scorer_code_digest", "rubric_digest",
                  "calibration_manifest_digest", "blind_review_protocol_digest", "arbitration_protocol_digest"):
        _digest(body[field], field)
    if not isinstance(body["judge_parameters"], Mapping):
        raise ContractError("judge parameters must be a mapping")
    if not isinstance(body["applicable_benchmarks"], list):
        raise ContractError("calibration applicable benchmarks must be a list")
    applicable = _requested_benchmarks(body["applicable_benchmarks"])
    criteria = _criteria(body["criteria"])
    if body["criteria_digest"] != _digest(body["criteria_digest"], "criteria digest") or body["criteria_digest"] != digest(dict(criteria)):
        raise ContractError("calibration criteria digest mismatch")
    if not isinstance(body["coverage"], Mapping) or set(body["coverage"]) != set(applicable) or not isinstance(body["confusion_matrix"], Mapping) or set(body["confusion_matrix"]) != set(applicable):
        raise ContractError("calibration must carry every declared benchmark coverage and confusion counts")
    for benchmark in applicable:
        _count_map(body["coverage"][benchmark], COVERAGE_KINDS, f"{benchmark} calibration coverage")
        _count_map(body["confusion_matrix"][benchmark], ("tp", "tn", "fp", "fn", "abstained"), f"{benchmark} calibration confusion matrix")
    _uncertainty(body["uncertainty"], applicable)


def verify_calibration_receipt(receipt: FrozenRecord, keys: Mapping[str, bytes], *, panel_digest: str,
                               scorer_digest: str, protocol_digest: str,
                               required_benchmarks: tuple[str, ...] = REQUIRED_BENCHMARKS) -> Mapping[str, Any]:
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
    if not calibration_eligible(body, required_benchmarks=_requested_benchmarks(required_benchmarks)):
        raise ContractError("metadata-authenticated scorer calibration does not meet frozen criteria")
    return body
