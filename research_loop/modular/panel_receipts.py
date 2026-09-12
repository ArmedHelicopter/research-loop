"""Fail-closed verification for a frozen, complete modular experiment panel.

This module verifies engineering provenance and coverage.  It deliberately does
not turn a successful runtime trace, a caller-provided score, or a local
decision string into scientific acceptance.  Scientific scoring and acceptance
need separately configured authorities.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from types import MappingProxyType

from research_loop.modular.contracts import DataIdentity, FrozenRecord, required_text
from research_loop.modular.combinations import validate_design
from research_loop.modular.p0_panel import validate_fixed_control_design
from research_loop.modular.experiments import registry
from research_loop.modular.runtime import verify_trace
from research_loop.modular.protocol_trace import verify_protocol_trace
from research_loop.modular.benchmarks.catalog import REQUIRED_BENCHMARKS, SUPPORTED_BENCHMARKS
from evaluation.modular.calibration import verify_calibration_receipt
from research_loop.ontology import ContractError, canonical

# Compatibility name for callers that mean the default required pair.
BENCHMARKS = frozenset(REQUIRED_BENCHMARKS)
MODULES = ("P0", "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9")
# P0 is a required control plane; the nine binary research modules are M1--M9.
RESEARCH_MODULES = MODULES[1:]
REQUIRED_TRIPLES = (("M2", "M3", "M5"), ("M4", "M5", "M6"),
                    ("M1", "M4", "M7"), ("M3", "M6", "M9"), ("M7", "M8", "M9"))


def _hex(value: str, field: str) -> str:
    required_text(value, field)
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ContractError(f"{field} must be a sha256 digest")
    return value


def _names(values: Iterable[str], field: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, Mapping)):
        raise ContractError(f"{field} must be a collection")
    result = tuple(values)
    if not result or len(set(result)) != len(result):
        raise ContractError(f"{field} must be nonempty and unique")
    for value in result:
        required_text(value, field)
    return result


@dataclass(frozen=True)
class PanelCell:
    """One predeclared task/variant/arm/replicate observation opportunity."""
    coverage_id: str
    identity: DataIdentity
    replicate: str
    variant: str
    arm_id: str
    runtime_arm: FrozenRecord
    task_digest: str
    scenario_digest: str
    package_digest: str
    scorer_digest: str

    def __post_init__(self) -> None:
        if self.identity.benchmark not in SUPPORTED_BENCHMARKS:
            raise ContractError("panel cell has an unsupported benchmark")
        required_text(self.coverage_id, "coverage id")
        required_text(self.replicate, "replicate")
        required_text(self.variant, "variant")
        required_text(self.arm_id, "arm id")
        if not isinstance(self.runtime_arm, FrozenRecord):
            raise ContractError("panel cell needs a frozen runtime arm")
        for value, field in ((self.task_digest, "task digest"), (self.scenario_digest, "scenario digest"),
                             (self.package_digest, "package digest"),
                             (self.scorer_digest, "scorer digest")):
            _hex(value, field)

    @property
    def key(self) -> tuple[str, str, str, str, str, str, str]:
        return (self.coverage_id, self.identity.benchmark, self.identity.task_id,
                self.identity.group_id, self.replicate, self.variant, self.arm_id)

    @property
    def task_panel_key(self) -> tuple[str, str, str, str, str]:
        return self.key[:5]

    def data(self) -> dict[str, Any]:
        return {"coverage_id": self.coverage_id, "identity": self.identity.data(),
                "replicate": self.replicate, "variant": self.variant, "arm_id": self.arm_id,
                "runtime_arm": self.runtime_arm.data(), "task_digest": self.task_digest, "scenario_digest": self.scenario_digest,
                "package_digest": self.package_digest, "scorer_digest": self.scorer_digest}


@dataclass(frozen=True)
class CombinationObligations:
    """Frozen routing coverage; status is not inferred from a score."""
    pairs: tuple[tuple[str, str], ...]
    triples: tuple[tuple[str, str, str], ...]
    full_arm: tuple[str, ...]
    leave_one_out: tuple[str, ...]

    def __post_init__(self) -> None:
        normalized_pairs = {tuple(sorted(pair)) for pair in self.pairs}
        if normalized_pairs != set(combinations(RESEARCH_MODULES, 2)) or len(self.pairs) != 36:
            raise ContractError("all 36 research-module pairs must be frozen")
        if set(self.triples) != set(REQUIRED_TRIPLES) or len(self.triples) != 5:
            raise ContractError("the five preregistered triples must be frozen")
        if tuple(sorted(self.full_arm)) != RESEARCH_MODULES:
            raise ContractError("full arm must contain exactly M1 through M9")
        if tuple(sorted(self.leave_one_out)) != RESEARCH_MODULES:
            raise ContractError("leave-one-out must cover every research module")

    def data(self) -> dict[str, Any]:
        return {"pairs": [list(x) for x in self.pairs], "triples": [list(x) for x in self.triples],
                "full_arm": list(self.full_arm), "leave_one_out": list(self.leave_one_out),
                "status": "routing_only"}


@dataclass(frozen=True)
class FrozenPanel:
    """Complete expected cells, frozen before validation output is observed."""
    stage: str
    domain: str
    split_digest: str
    candidate_digest: str
    scope_ids: tuple[str, ...]
    legal_arm_grids: Mapping[str, FrozenRecord]
    acceptance_criteria: FrozenRecord
    cells: tuple[PanelCell, ...]
    combinations: CombinationObligations
    required_benchmarks: tuple[str, ...] = REQUIRED_BENCHMARKS

    def __post_init__(self) -> None:
        object.__setattr__(self, "legal_arm_grids", MappingProxyType(dict(self.legal_arm_grids)))
        object.__setattr__(self, "scope_ids", tuple(self.scope_ids))
        object.__setattr__(self, "cells", tuple(self.cells))
        object.__setattr__(self, "required_benchmarks", _names(self.required_benchmarks, "required benchmark"))
        required_text(self.stage, "stage")
        if self.domain not in {"train", "validation"}:
            raise ContractError("panel domain must be train or validation")
        _hex(self.split_digest, "split digest")
        _hex(self.candidate_digest, "candidate digest")
        if (not set(self.required_benchmarks) <= set(SUPPORTED_BENCHMARKS)
                or not set(REQUIRED_BENCHMARKS) <= set(self.required_benchmarks)):
            raise ContractError("panel required benchmarks must be supported and include the core pair")
        if not isinstance(self.acceptance_criteria, FrozenRecord):
            raise ContractError("panel requires frozen legal-arm grid and acceptance criteria")
        if set(_names(self.scope_ids, "scope id")) - set(registry()) or set(self.legal_arm_grids) != set(self.scope_ids):
            raise ContractError("panel scope and legal-arm grids must be exact registered ids")
        legal_by_scope = {}
        for coverage, design_record in self.legal_arm_grids.items():
            if not isinstance(design_record, FrozenRecord): raise ContractError("legal-arm grid must be frozen")
            required = set(registry()[coverage].modules) - {"P0"}
            if not required:
                design = validate_fixed_control_design(design_record).data()
                if set(registry()[coverage].modules) != {"P0"}:
                    raise ContractError("P0 fixed grid only applies to P0-only coverage")
                legal_by_scope[coverage] = {"p0-fixed": FrozenRecord.from_dict(design["runtime_arm"])}
            else:
                validate_design(design_record); design = design_record.data()
                if set(design["factors"]) != required:
                    raise ContractError("legal-arm grid factors must equal the registered module set")
                legal_by_scope[coverage] = {row["id"]: FrozenRecord.from_dict(row["arm"]) for row in design["cells"] if row["status"] == "executable"}
        if not self.cells or any(not isinstance(cell, PanelCell) for cell in self.cells):
            raise ContractError("panel requires typed expected cells")
        if any(cell.identity.domain != self.domain for cell in self.cells):
            raise ContractError("cell domain differs from frozen panel")
        if any(cell.identity.split_id != self.split_digest for cell in self.cells):
            raise ContractError("cell split identity differs from frozen panel")
        if any(cell.coverage_id not in legal_by_scope or cell.arm_id not in legal_by_scope[cell.coverage_id] or cell.runtime_arm != legal_by_scope[cell.coverage_id][cell.arm_id] for cell in self.cells):
            raise ContractError("cell arm is not the frozen compatibility-derived legal arm")
        if len({cell.key for cell in self.cells}) != len(self.cells):
            raise ContractError("duplicate expected panel cell")
        if {cell.coverage_id for cell in self.cells} != set(self.scope_ids):
            raise ContractError("panel must exactly cover its registered scope")
        if {(cell.coverage_id, cell.identity.benchmark) for cell in self.cells} != {
                (coverage, benchmark) for coverage in self.scope_ids for benchmark in self.required_benchmarks}:
            raise ContractError("each obligation must independently cover every required benchmark")
        # Each task panel has the exact same variant x legal-arm grid.  Thus a
        # caller cannot omit a negative arm or compare different tasks by arm.
        grouped: dict[tuple[str, str, str, str, str], list[PanelCell]] = {}
        for cell in self.cells:
            grouped.setdefault(cell.task_panel_key, []).append(cell)
        for rows in grouped.values():
            variants, arms = {row.variant for row in rows}, {row.arm_id for row in rows}
            spec = registry()[rows[0].coverage_id]
            if variants != set(spec.variants) or arms != set(legal_by_scope[rows[0].coverage_id]):
                raise ContractError("task panel differs from registered variants or frozen legal-arm grid")
            if len(rows) != len(variants) * len(arms):
                raise ContractError("task panel lacks a complete variant by legal-arm grid")
            if {(row.variant, row.arm_id) for row in rows} != set(
                    (variant, arm) for variant in variants for arm in arms):
                raise ContractError("task panel has a missing or duplicate paired cell")
            if len({row.identity for row in rows}) != 1:
                raise ContractError("paired cells must use one exact task and split identity")
        for coverage, legal in legal_by_scope.items():
          for arm_id in legal:
            arm_rows = [cell for cell in self.cells if cell.coverage_id == coverage and cell.arm_id == arm_id]
            if len({cell.package_digest for cell in arm_rows}) != 1:
                raise ContractError("an arm must have one package across paired tasks")
        if len({cell.scorer_digest for cell in self.cells}) != 1:
            raise ContractError("panel must use one frozen scorer across paired tasks")
        # Distinctness is benchmark + source group, never a coincidental group name.
        if not { (cell.identity.benchmark, cell.identity.group_id) for cell in self.cells }:
            raise ContractError("panel needs source groups")

    @property
    def digest(self) -> str:
        return FrozenRecord.from_dict({"stage": self.stage, "domain": self.domain,
            "split_digest": self.split_digest, "candidate_digest": self.candidate_digest,
            "scope_ids": list(self.scope_ids), "legal_arm_grid_digests": {k: v.content_hash for k, v in sorted(self.legal_arm_grids.items())},
            "acceptance_criteria_digest": self.acceptance_criteria.content_hash,
            "required_benchmarks": list(self.required_benchmarks),
            "combinations": self.combinations.data(),
            "cells": [cell.data() for cell in sorted(self.cells, key=lambda cell: cell.key)]}).content_hash

    @property
    def arm_schedule(self) -> tuple[str, ...]:
        return tuple(sorted({f"{cell.coverage_id}:{cell.arm_id}" for cell in self.cells}))

    @property
    def validation_groups(self) -> tuple[str, ...]:
        # Custody owns canonical group identifiers.  They are already
        # benchmark-namespaced (or a deterministic merged-group representative);
        # prepending a cell benchmark would double-prefix real custody groups.
        return tuple(sorted({cell.identity.group_id for cell in self.cells}))


@dataclass(frozen=True)
class RuntimeReceipt:
    cell_key: tuple[str, str, str, str, str, str, str]
    status: str
    trace_path: Path
    trace_digest: str
    output_digest: str | None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"succeeded", "failed", "unscored", "blocked"}:
            raise ContractError("unknown runtime status")
        _hex(self.trace_digest, "trace digest")
        if self.output_digest is not None:
            _hex(self.output_digest, "output digest")
        if self.status == "succeeded" and self.failure_reason is not None:
            raise ContractError("successful receipt cannot carry a failure reason")
        if self.status != "succeeded" and not self.failure_reason:
            raise ContractError("failed or unscored cell needs an honest reason")


@dataclass(frozen=True)
class ScientificScorerReceipt:
    """Opaque independent scorer material; only a configured verifier may trust it."""
    cell_key: tuple[str, str, str, str, str, str, str]
    receipt: FrozenRecord


@dataclass(frozen=True)
class ValidationAcceptance:
    lease: FrozenRecord
    acceptance: FrozenRecord
    calibration_receipt: FrozenRecord | None = None
    protocol_digest: str | None = None


class SignedAuthority:
    """Small HMAC fixture authority; keys belong in independent services in production."""
    def __init__(self, authority_id: str, key: bytes):
        self.authority_id = required_text(authority_id, "authority id")
        if not isinstance(key, bytes) or len(key) < 32:
            raise ContractError("authority key must have at least 32 bytes")
        self._key = key

    def issue(self, body: Mapping[str, Any]) -> FrozenRecord:
        material = dict(body)
        material["authority"] = self.authority_id
        return FrozenRecord.from_dict({"body": material,
            "mac": hmac.new(self._key, canonical(material).encode(), hashlib.sha256).hexdigest()})


def verify_signed(record: FrozenRecord, keys: Mapping[str, bytes], *, schema: str) -> dict[str, Any]:
    envelope = record.data()
    if set(envelope) != {"body", "mac"} or not isinstance(envelope["body"], dict):
        raise ContractError("malformed authority receipt")
    body, authority = envelope["body"], envelope["body"].get("authority")
    if body.get("schema") != schema or authority not in keys or not isinstance(envelope["mac"], str):
        raise ContractError("untrusted authority receipt")
    expected = hmac.new(keys[authority], canonical(body).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(envelope["mac"], expected):
        raise ContractError("authority receipt signature mismatch")
    return body


@dataclass(frozen=True)
class PanelVerdict:
    panel_digest: str
    engineering_verified: bool
    scientific_verified: bool
    acceptance_verified: bool
    decision: str
    observed_cells: int
    failures: int
    unscored: int
    blocked: int
    adapted_score_verified: bool
    limitation: str | None


class PanelReceiptVerifier:
    """Verify every frozen cell; no default path grants scientific acceptance."""
    def __init__(self, *, scorer_verifier: Callable[[ScientificScorerReceipt, PanelCell, FrozenPanel], None] | None = None,
                 custody_keys: Mapping[str, bytes] | None = None,
                 acceptance_keys: Mapping[str, bytes] | None = None,
                 calibration_keys: Mapping[str, bytes] | None = None):
        self._scorer_verifier = scorer_verifier
        self._custody_keys = dict(custody_keys or {})
        self._acceptance_keys = dict(acceptance_keys or {})
        self._calibration_keys = dict(calibration_keys or {})

    def verify(self, panel: FrozenPanel, runtime: Iterable[RuntimeReceipt], *,
               scorer_receipts: Iterable[ScientificScorerReceipt] = (),
               validation: ValidationAcceptance | None = None) -> PanelVerdict:
        rows = tuple(runtime)
        if len({row.trace_path.resolve() for row in rows}) != len(rows):
            raise ContractError("one runtime trace cannot be relabeled as multiple cells")
        if len({row.trace_digest for row in rows}) != len(rows):
            raise ContractError("one runtime trace digest cannot be relabeled as multiple cells")
        expected = {cell.key: cell for cell in panel.cells}
        actual = {row.cell_key: row for row in rows}
        if len(actual) != len(rows):
            raise ContractError("duplicate runtime receipt; reruns cannot replace a cell")
        if set(actual) != set(expected):
            missing, unexpected = set(expected) - set(actual), set(actual) - set(expected)
            raise ContractError(f"runtime receipt coverage mismatch: missing={len(missing)} unexpected={len(unexpected)}")
        for key, row in actual.items():
            grid = panel.legal_arm_grids[expected[key].coverage_id].data()
            self._verify_runtime(row, expected[key], p0_control_digest=grid.get("p0_control_digest"))
        scored = tuple(scorer_receipts)
        if len({row.cell_key for row in scored}) != len(scored) or not set(row.cell_key for row in scored) <= set(expected):
            raise ContractError("duplicate or unexpected scorer receipt")
        scientific = False
        adapted_score = False
        if self._scorer_verifier is not None:
            # A scorer receipt is required for every successful execution; failed
            # cells remain in the denominator but cannot be silently scored as 0.
            successful = {key for key, row in actual.items() if row.status == "succeeded"}
            by_key = {row.cell_key: row for row in scored}
            if not successful:
                raise ContractError("all failed cells are insufficient scientific evidence")
            if set(by_key) != successful:
                raise ContractError("independent scorer receipts must exactly cover successful cells")
            for key, receipt in by_key.items():
                self._scorer_verifier(receipt, expected[key], panel)
                raw = receipt.receipt.data()
                # v2 is issued by the independent adapted-metric service.  Its
                # signed body remains opaque until the configured verifier has
                # authenticated it above; do not mistake an envelope for an
                # unsigned v1 caller score.
                body = raw.get("body") if set(raw) == {"body", "mac"} and isinstance(raw.get("body"), dict) else raw
                if (body.get("schema") not in {"independent-scored-cell-v1", "independent-scored-cell-v2"}
                        or body.get("runtime_trace_digest") != actual[key].trace_digest
                        or body.get("scorer_digest") != expected[key].scorer_digest):
                    raise ContractError("scorer receipt lacks typed runtime and scorer binding")
            # Adapted benchmark scores authenticate the configured calculation,
            # but their receipts explicitly say calibration and scientific
            # validity are unmeasured.  They must not promote a panel through
            # the scientific or validation-acceptance paths.
            adapted_score = any((row.receipt.data().get("body", row.receipt.data()).get("schema")
                                 == "independent-scored-cell-v2") for row in scored)
            scientific = not adapted_score
        elif scored:
            raise ContractError("caller supplied scorer receipts without an independent scorer verifier")
        acceptance_decision = None
        if panel.domain == "validation" and validation is not None:
            acceptance_decision = self.verify_validation_acceptance(panel, validation, scientific, rows, scored)
        elif validation is not None:
            raise ContractError("acceptance applies only to validation panels")
        failed = sum(row.status == "failed" for row in rows)
        unscored = sum(row.status == "unscored" for row in rows)
        blocked = sum(row.status == "blocked" for row in rows)
        accepted = acceptance_decision == "accepted"
        decision = acceptance_decision or ("evidence_verified" if scientific else "adapted_score_verified" if adapted_score else "engineering_verified")
        limitation = ("combination routing_only: no contrast matrix was measured" if not accepted else None)
        if not scientific:
            limitation = ("adapted score calculation is authenticated; calibration and scientific validity are not measured"
                          if adapted_score else "independent trusted scoring service is not configured")
        return PanelVerdict(panel.digest, True, scientific, accepted, decision, len(rows), failed, unscored, blocked,
                            adapted_score, limitation)

    def _verify_runtime(self, receipt: RuntimeReceipt, expected: PanelCell, *, p0_control_digest: str | None = None) -> None:
        verify_protocol_trace(receipt.trace_path)
        trace = verify_trace(receipt.trace_path).data()
        if trace["trace_digest"] != receipt.trace_digest:
            raise ContractError("runtime trace digest does not match the hash-chained journal")
        events = [FrozenRecord(line).data() for line in receipt.trace_path.read_text(encoding="utf-8").splitlines()]
        lock = events[0].get("data")
        if events[0].get("lock_digest") != FrozenRecord.from_dict(lock).content_hash:
            raise ContractError("objective lock event does not bind its own lock")
        if not isinstance(lock, dict) or lock.get("identity") != expected.identity.data():
            raise ContractError("runtime trace task binding mismatch")
        if lock.get("task_digest") != expected.task_digest or lock.get("package_digest") != expected.package_digest or lock.get("arm") != expected.runtime_arm.data():
            raise ContractError("runtime trace package or legal-arm binding mismatch")
        requests = [event["data"].get("request", {}) for event in events if event["stage"] == "model_request"]
        if p0_control_digest is not None and (not requests or any(
                request.get("module_context", {}).get("p0_control_digest") != p0_control_digest
                for request in requests)):
            raise ContractError("runtime request lacks the frozen P0 control binding")
        expected_binding = {"experiment_id": expected.coverage_id, "variant": expected.variant,
                            "replicate": expected.replicate, "arm_id": expected.arm_id,
                            "scenario_digest": expected.scenario_digest}
        bound_request = any(request.get("task", {}).get("identity") == expected.identity.data()
                            and request.get("module_context", {}).get("panel_cell") == expected_binding
                            for request in requests)
        bound_early_failure = (not requests and events[-1].get("stage") == "controller_failure"
                               and events[-1].get("data", {}).get("panel_cell") == expected_binding)
        if not bound_request and not bound_early_failure:
            raise ContractError("runtime trace lacks a bound task and scenario request")
        pending = None
        slots = []
        for event in events[1:]:
            data = event["data"]
            if event["stage"] == "model_request":
                request = data.get("request")
                if pending is not None or not isinstance(request, dict):
                    raise ContractError("runtime request sequence is incomplete")
                pending = FrozenRecord.from_dict(request).content_hash
                if data.get("request_digest") != pending or request.get("lock_digest") != trace["lock_digest"]:
                    raise ContractError("runtime request digest is not bound to its frozen lock")
                if (FrozenRecord.from_dict(request.get("task", {})).content_hash != expected.task_digest
                        or request.get("objective") != lock.get("objective")):
                    raise ContractError("runtime request task or objective drift")
                slots.append(request.get("slot"))
                if slots != lock.get("slots", [])[:len(slots)]:
                    raise ContractError("runtime request violates the frozen call schedule")
            elif event["stage"] in {"model_response", "model_failure"}:
                if pending is None or data.get("request_digest") != pending:
                    raise ContractError("runtime response is not bound to a pending request")
                pending = None
        terminal = events[-1]
        if terminal["stage"] in {"driver_failure", "controller_failure"} and terminal["data"].get("driver_id") != expected.coverage_id:
            raise ContractError("terminal driver failure does not bind this panel obligation")
        responses = [event["data"]["response"] for event in events if event["stage"] == "model_response"]
        observed = FrozenRecord.from_dict({"responses": responses, "terminal": terminal["data"]}).content_hash
        has_model_failure = any(event["stage"] == "model_failure" for event in events)
        if terminal["stage"] == "final_decision":
            closing_failure = terminal["data"].get("decision") == "blocked" and has_model_failure
            if (pending is not None or (not closing_failure and (slots != lock.get("slots") or not responses
                    or terminal["data"].get("candidate_digest") != FrozenRecord.from_dict(responses[-1]).content_hash))
                    or terminal["data"].get("lock_digest") != trace["lock_digest"]
                    or terminal["data"].get("identity") != expected.identity.data()):
                raise ContractError("final decision lacks a complete response-bound candidate")
        if receipt.status == "succeeded":
            if terminal["stage"] != "final_decision" or terminal["data"].get("decision") not in {"proceed", "closed_negative", "unknown", "invalid", "withdrawn"} or any(event["stage"] == "model_failure" for event in events) or not responses or receipt.output_digest != observed:
                raise ContractError("successful receipt lacks terminal runtime output evidence")
        elif receipt.status == "failed":
            if not (terminal["stage"] in {"model_failure", "driver_failure", "controller_failure"} and receipt.output_digest is None) and not (
                    terminal["stage"] == "final_decision" and terminal["data"].get("decision") == "blocked"
                    and has_model_failure and receipt.output_digest == observed):
                raise ContractError("failed receipt does not match terminal runtime evidence")
        elif terminal["stage"] != "final_decision" or receipt.output_digest != observed:
            raise ContractError("non-success receipt lacks a bound terminal decision")
        if receipt.status == "blocked" and terminal["data"].get("decision") != "blocked":
            raise ContractError("blocked receipt contradicts the actual terminal decision")


    def verify_validation_acceptance(self, panel: Any, validation: ValidationAcceptance, scientific: bool,
                           runtime: tuple[RuntimeReceipt, ...], scorer: tuple[ScientificScorerReceipt, ...]) -> str | None:
        if not scientific or not self._custody_keys or not self._acceptance_keys or not self._calibration_keys:
            return None
        if validation.calibration_receipt is None or validation.protocol_digest is None:
            raise ContractError("validation requires a trusted calibration receipt and protocol binding")
        scorer_digests = {cell.scorer_digest for cell in panel.cells}
        if len(scorer_digests) != 1:
            raise ContractError("validation panel must have exactly one scorer digest")
        calibration = verify_calibration_receipt(validation.calibration_receipt, self._calibration_keys,
                                                 panel_digest=panel.digest, scorer_digest=next(iter(scorer_digests)),
                                                 protocol_digest=validation.protocol_digest,
                                                 required_benchmarks=panel.required_benchmarks)
        lease = verify_signed(validation.lease, self._custody_keys, schema="custody-panel-lease-v2")
        if (lease.get("panel_digest") != panel.digest or lease.get("candidate_digest") != panel.candidate_digest
                or lease.get("split_digest") != panel.split_digest or tuple(lease.get("arm_schedule", ())) != panel.arm_schedule
                or tuple(sorted(lease.get("groups", ()))) != panel.validation_groups or lease.get("status") != "consumed"
                or lease.get("scorer_digest") != next(iter(scorer_digests)) or lease.get("protocol_digest") != validation.protocol_digest
                or lease.get("calibration_receipt_digest") != validation.calibration_receipt.content_hash
                or lease.get("criteria_digest") != calibration["criteria_digest"]
                or tuple(lease.get("required_benchmarks", ())) != panel.required_benchmarks
                or lease.get("stage") != panel.stage
                or lease.get("task_identities_digest") != hashlib.sha256(canonical(sorted(
                    [cell.identity.data() for cell in panel.cells], key=canonical)).encode()).hexdigest()):
            raise ContractError("custody lease is not bound to this exact frozen validation panel")
        acceptance = verify_signed(validation.acceptance, self._acceptance_keys, schema="panel-acceptance-v1")
        runtime_digest = FrozenRecord.from_dict({"runtime": [self._runtime_data(row) for row in sorted(runtime, key=lambda row: row.cell_key)]}).content_hash
        scorer_digest = FrozenRecord.from_dict({"scorer": [
            {"cell_key": list(row.cell_key), "receipt_digest": row.receipt.content_hash}
            for row in sorted(scorer, key=lambda row: row.cell_key)]}).content_hash
        if (acceptance.get("panel_digest") != panel.digest or acceptance.get("candidate_digest") != panel.candidate_digest
                or acceptance.get("lease_digest") != validation.lease.content_hash
                or acceptance.get("runtime_digest") != runtime_digest or acceptance.get("scorer_receipts_digest") != scorer_digest
                or acceptance.get("decision") not in {"accepted", "rejected", "inconclusive"}):
            raise ContractError("acceptance receipt is not bound to panel, candidate, and custody lease")
        return acceptance["decision"]

    @staticmethod
    def _runtime_data(row: RuntimeReceipt) -> dict[str, Any]:
        return {"cell_key": list(row.cell_key), "status": row.status, "trace_digest": row.trace_digest,
                "output_digest": row.output_digest, "failure_reason": row.failure_reason}
