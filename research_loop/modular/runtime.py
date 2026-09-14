"""Controller seams for frozen calls, restricted execution and dual evidence audit.

The controller is trusted. A tested model receives only ModelRequest; it cannot
call the host audit authority or write controller journals. Deployment still has
to enforce that process boundary. HMAC verifies receipt origin, not scientific truth.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
from uuid import uuid4
from typing import Any, Callable, Mapping

from .contracts import ContractError, DataIdentity, FrozenRecord, PublicTask, required_text, strict_bool
from .benchmarks.execution import DockerExecutionBroker, ExecutionReceipt, ExecutionRequest
from .modules.admission import AuditItem, EvidenceAdmission, ScientificState
from .modules.context import ContextBuilder, ContextCache
from .modules.evidence import ClaimLedger, EvidenceLedger
from .artifact_catalogue import ArtifactCatalogue, source_snapshot
from .combinations import default_compatibility
from research_loop.ontology import canonical, digest


def candidate_reasons(body: dict, objective_digest: str) -> list[str]:
    """Shared closed candidate checks for live admission and journal replay."""
    reasons = []
    if set(body) != {"objective_digest", "outcome", "evidence_ids", "conclusion", "programme_complete"}:
        reasons.append("candidate_schema")
    if body.get("objective_digest") != objective_digest:
        reasons.append("objective_drift")
    if body.get("programme_complete") is not False:
        reasons.append("programme_completion_unauthorized")
    if body.get("outcome") not in {"positive", "negative", "unknown", "invalid", "withdrawn"}:
        reasons.append("invalid_outcome")
    ids = body.get("evidence_ids")
    if not isinstance(ids, list) or any(not isinstance(x, str) for x in ids) or len(set(ids)) != len(ids):
        reasons.append("invalid_evidence_ids")
    if not isinstance(body.get("conclusion"), str) or not body.get("conclusion", "").strip():
        reasons.append("missing_conclusion")
    return reasons


class AuditAuthority:
    """Private evaluator-side issuer. Never put this object/key in solver workers."""

    def __init__(self, authority_id: str, key: bytes):
        self.authority_id = required_text(authority_id, "authority id")
        if not isinstance(key, bytes) or len(key) < 32:
            raise ContractError("audit authentication requires at least 32 key bytes")
        self._key = key

    def issue(self, *, identity: DataIdentity, objective_digest: str,
              execution_digest: str, state: ScientificState, outcome: str,
              audit: list[AuditItem]) -> FrozenRecord:
        if outcome not in {"positive", "negative"}:
            raise ContractError("audit requires explicit outcome")
        body = {"schema": "host-scientific-audit-v1", "authority": self.authority_id,
                "identity": identity.data(), "objective_digest": objective_digest,
                "execution_digest": execution_digest, "state": state.__dict__, "outcome": outcome,
                "audit": [{"name": item.name, "executed": item.executed, "passed": item.passed} for item in audit]}
        return FrozenRecord.from_dict({"body": body, "mac": hmac.new(self._key, canonical(body).encode(), hashlib.sha256).hexdigest()})

    def issue_material(self, *, identity: DataIdentity, subject_digest: str,
                       execution_success: bool, state: ScientificState, outcome: str,
                       audit: list[AuditItem]) -> FrozenRecord:
        """Authenticate caller-provided public material without inventing an execution.

        The caller owns the observed material and obtains this receipt from an
        authority.  The controller only verifies its origin and exact subject
        binding; it does not treat the signature as a scientific result.
        """
        if outcome not in {"positive", "negative"}:
            raise ContractError("material audit requires explicit outcome")
        strict_bool(execution_success, "material execution success")
        required_text(subject_digest, "material audit subject digest")
        body = {"schema": "host-material-audit-v1", "authority": self.authority_id,
                "identity": identity.data(), "subject_digest": subject_digest,
                "execution_success": execution_success, "state": state.__dict__, "outcome": outcome,
                "audit": [{"name": item.name, "executed": item.executed, "passed": item.passed} for item in audit]}
        return FrozenRecord.from_dict({"body": body, "mac": hmac.new(self._key, canonical(body).encode(), hashlib.sha256).hexdigest()})


class AuditVerifier:
    """Trusted controller-side verification with a frozen pair of authorities."""

    def __init__(self, keys: Mapping[str, bytes]):
        if len(keys) != 2 or any(not isinstance(key, bytes) or len(key) < 32 for key in keys.values()):
            raise ContractError("two registered audit authorities required")
        for name in keys:
            required_text(name, "authority id")
        self._keys = dict(keys)

    def verify_evidence(self, receipts: list[FrozenRecord], *, identity: DataIdentity,
                        objective_digest: str, execution: ExecutionReceipt,
                        required_audit: tuple[str, ...]) -> FrozenRecord:
        """Verify fixed host receipt binding without applying an M1 disposition."""
        if len(receipts) != 2:
            raise ContractError("two complete audit receipts required")
        bodies = {}
        for receipt in receipts:
            if not isinstance(receipt, FrozenRecord):
                raise ContractError("malformed audit receipt")
            envelope = receipt.data()
            if set(envelope) != {"body", "mac"} or not isinstance(envelope["body"], dict):
                raise ContractError("malformed audit envelope")
            body = envelope["body"]
            if set(body) != {"schema", "authority", "identity", "objective_digest", "execution_digest", "state", "outcome", "audit"}:
                raise ContractError("unexpected scientific audit fields")
            authority = body["authority"]
            if authority not in self._keys or authority in bodies or not isinstance(envelope["mac"], str):
                raise ContractError("unknown or duplicate audit authority")
            expected = hmac.new(self._keys[authority], canonical(body).encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(envelope["mac"], expected):
                raise ContractError("audit signature mismatch")
            if (body["schema"] != "host-scientific-audit-v1" or body["identity"] != identity.data()
                    or body["objective_digest"] != objective_digest or body["execution_digest"] != execution.content_hash):
                raise ContractError("audit subject or frozen objective mismatch")
            try:
                state = ScientificState(**body["state"])
                checks = [AuditItem(**row) for row in body["audit"]]
            except (TypeError, KeyError) as exc:
                raise ContractError("malformed scientific state or audit") from exc
            bodies[authority] = {"state": body["state"], "outcome": body["outcome"],
                                  "audit": sorted(body["audit"], key=lambda row: row["name"])}
        normalized = list(bodies.values())
        if normalized[0] != normalized[1]:
            raise ContractError("dual audit disagreement")
        return FrozenRecord.from_dict({"schema": "verified-dual-audit-evidence-v1", "identity": identity.data(),
            "objective_digest": objective_digest, "execution_digest": execution.content_hash,
            "authorities": sorted(bodies), **normalized[0]})

    def verify_material(self, receipts: list[FrozenRecord], *, identity: DataIdentity,
                        subject_digest: str, required_audit: tuple[str, ...]) -> FrozenRecord:
        """Verify a pair of authority-issued public-material receipts.

        This deliberately has no execution receipt parameter: callers may
        supply a public observation that this RunSession did not execute.  The
        signed ``subject_digest`` binds the material, task, state, outcome and
        audit facts before a model is called.
        """
        required_text(subject_digest, "material audit subject digest")
        if len(receipts) != 2:
            raise ContractError("two complete material audit receipts required")
        bodies = {}
        expected_fields = {"schema", "authority", "identity", "subject_digest", "execution_success", "state", "outcome", "audit"}
        for receipt in receipts:
            if not isinstance(receipt, FrozenRecord):
                raise ContractError("malformed material audit receipt")
            envelope = receipt.data()
            if set(envelope) != {"body", "mac"} or not isinstance(envelope["body"], dict):
                raise ContractError("malformed material audit envelope")
            body = envelope["body"]
            if set(body) != expected_fields:
                raise ContractError("unexpected material audit fields")
            authority = body["authority"]
            if authority not in self._keys or authority in bodies or not isinstance(envelope["mac"], str):
                raise ContractError("unknown or duplicate material audit authority")
            expected = hmac.new(self._keys[authority], canonical(body).encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(envelope["mac"], expected):
                raise ContractError("material audit signature mismatch")
            if (body["schema"] != "host-material-audit-v1" or body["identity"] != identity.data()
                    or body["subject_digest"] != subject_digest):
                raise ContractError("material audit subject binding mismatch")
            try:
                ScientificState(**body["state"])
                checks = [AuditItem(**row) for row in body["audit"]]
                strict_bool(body["execution_success"], "material execution success")
                if body["outcome"] not in {"positive", "negative"}:
                    raise ContractError("material audit outcome is invalid")
                # This verifies only receipt shape and registered checklist.
                # Calling EvidenceAdmission here would make the M1-off arm
                # execute the intervention it is meant to control for.
                if (not required_audit or len(set(required_audit)) != len(required_audit)
                        or {item.name for item in checks} != set(required_audit)
                        or len({item.name for item in checks}) != len(checks)):
                    raise ContractError("material audit checklist is incomplete")
            except (TypeError, KeyError) as exc:
                raise ContractError("malformed material audit state or checks") from exc
            bodies[authority] = {"execution_success": body["execution_success"], "state": body["state"],
                                  "outcome": body["outcome"], "audit": sorted(body["audit"], key=lambda row: row["name"])}
        normalized = list(bodies.values())
        if normalized[0] != normalized[1]:
            raise ContractError("dual material audit disagreement")
        return FrozenRecord.from_dict({"schema": "verified-dual-material-audit-v1", "identity": identity.data(),
            "subject_digest": subject_digest, "authorities": sorted(bodies), **normalized[0]})

    def verify_pair(self, receipts: list[FrozenRecord], *, identity: DataIdentity,
                    objective_digest: str, execution: ExecutionReceipt,
                    required_audit: tuple[str, ...]) -> FrozenRecord:
        """Apply the existing M1 EvidenceAdmission disposition after host verification."""
        verified = self.verify_evidence(receipts, identity=identity, objective_digest=objective_digest,
                                        execution=execution, required_audit=required_audit).data()
        state = ScientificState(**verified["state"])
        checks = [AuditItem(**row) for row in verified["audit"]]
        disposition = EvidenceAdmission.decide(identity=identity, state=state, outcome=verified["outcome"],
            execution_success=execution.status == "succeeded", trusted_validator="+".join(verified["authorities"]),
            validator_verified=True, evidence_ids=[execution.content_hash],
            subject_bindings={"task": identity.task_id, "objective": objective_digest},
            required_audit=required_audit, audit=checks)
        return FrozenRecord.from_dict({"schema": "verified-dual-audit-v1", "identity": identity.data(),
            "objective_digest": objective_digest, "execution_digest": execution.content_hash,
            "authorities": verified["authorities"], "state": verified["state"],
            "outcome": verified["outcome"], "audit": verified["audit"], "admitted": disposition.admitted})


class RunSession:
    """One task, one immutable objective, one bounded sequence of model calls.

    This does not optimize, score, or claim programme completion. Modules alter
    public context through explicit calls; all external calls and final gates are
    recorded. A crashed/incomplete run is inspected, never silently re-executed.
    """

    def __init__(self, task: PublicTask, *, package_digest: str, arm: FrozenRecord,
                 objective: FrozenRecord, slots: tuple[str, ...], execution_limit: int,
                 sidecar: Path, verifier: AuditVerifier, required_audit: tuple[str, ...],
                 context_budget: int = 12000, experiment_id: str | None = None):
        if not slots or len(set(slots)) != len(slots) or any(not isinstance(x, str) or not x for x in slots):
            raise ContractError("unique frozen call slots required")
        if type(execution_limit) is not int or execution_limit < 0:
            raise ContractError("invalid execution allocation")
        if not required_audit or len(set(required_audit)) != len(required_audit):
            raise ContractError("unique required scientific audits required")
        for name in required_audit:
            required_text(name, "required audit")
        arm_body = arm.data()
        try:
            checked_arm = default_compatibility(arm_body["baseline_digest"]).arm(arm_body["enabled"])
        except (KeyError, TypeError) as exc:
            raise ContractError("invalid runtime activation") from exc
        if checked_arm != arm:
            raise ContractError("runtime activation must bind the registered compatibility contract")
        if sidecar.exists() and any(sidecar.iterdir()):
            raise ContractError("run directory already used; inspect its journal instead of rerunning")
        sidecar.mkdir(parents=True, exist_ok=True)
        self.task, self.sidecar, self.verifier = task, sidecar, verifier
        self.objective = objective
        self.required_audit, self.context_budget = required_audit, context_budget
        self.slots, self.execution_limit = slots, execution_limit
        self.arm = arm
        self.lock = FrozenRecord.from_dict({"schema": "run-lock-v1", "task_digest": task.content_hash,
            "identity": task.identity.data(), "package_digest": required_text(package_digest, "package digest"),
            "arm": arm.data(), "objective": objective.data(), "slots": list(slots),
            "execution_limit": execution_limit, "required_audit": list(required_audit), "context_budget": context_budget})
        self.evidence = EvidenceLedger(task.identity, storage_path=sidecar / "evidence.jsonl")
        self.claims = ClaimLedger(self.evidence, storage_path=sidecar / "claims.jsonl")
        self._artifact_source = source_snapshot(Path(__file__))
        self._artifact_config = {"kind":"run_lock", "digest":self.lock.content_hash, "canonical":self.lock.data()}
        self.artifacts = ArtifactCatalogue(sidecar / "artifacts.jsonl", identity=task.identity,
            run_id=uuid4().hex, experiment_id=experiment_id, lock_digest=self.lock.content_hash,
            producer_source=self._artifact_source)
        self.cache = ContextCache()
        self.executions: dict[str, ExecutionReceipt] = {}
        self.admissions: dict[str, FrozenRecord] = {}
        self.admission_roots: dict[str, str] = {}
        self._events: list[FrozenRecord] = []
        self._event_artifacts: list[str] = []
        self._next_call, self._attempts, self._terminal = 0, 0, False
        self._research_version = None
        self._record("objective_lock", self.lock.data())

    def bind_research_version(self, boundary) -> None:
        from research_loop.modular.research_versions import ResearchVersionBoundary
        if self._research_version is not None or not isinstance(boundary, ResearchVersionBoundary) or boundary.session is not self:
            raise ContractError("research version must bind this session exactly once")
        boundary.assert_immutable()
        self._research_version = boundary

    def check_research_access(self, *, operation: str, slot: str | None = None, reporting_only: bool = False) -> None:
        if type(reporting_only) is not bool or (reporting_only and (operation != "model" or slot != "final")):
            raise ContractError("report-only authority is restricted to the final model slot")
        boundary = self._research_version
        if boundary is None: return
        boundary.assert_immutable()
        if reporting_only: return
        try: boundary.require_research()
        except ContractError:
            self._record("research_version_io_refused", {"operation": operation, "slot": slot,
                "state": boundary.state, "parent_digest": boundary.parent.content_hash, "before_io": True})
            raise

    def _record(self, stage: str, data: dict) -> FrozenRecord:
        event = FrozenRecord.from_dict({"sequence": len(self._events), "previous": self._events[-1].content_hash if self._events else None,
                                       "lock_digest": self.lock.content_hash, "stage": stage, "data": data})
        with (self.sidecar / "trace.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(event.encoded + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        self._events.append(event)
        descriptor = self.artifacts.append(kind="trace_event", module='P0' if stage=='objective_lock' else None, payload=event,
            parents=(() if len(self._events) == 1 else (self._event_artifacts[-1],)),
            producer_source=self._artifact_source, config_refs=(self._artifact_config,),
            coverage='covered' if stage=='objective_lock' else 'uncovered')
        self._event_artifacts.append(descriptor.content_hash)
        return event

    def record_artifact(self, *, kind: str, module: str, payload: FrozenRecord | Mapping[str, Any] | None,
                        parents: tuple[str, ...] = (), status: str = "produced", cost: Mapping[str, Any] | None = None,
                        checks: tuple[Mapping[str, Any], ...] = (), optimizer_visible: bool = False,
                        producer_source: Mapping[str, Any] | None = None) -> FrozenRecord:
        """Attach a typed module output to the latest immutable trace event."""
        trace_parent = self._event_artifacts[-1] if self._event_artifacts else None
        return self.artifacts.append(kind=kind, module=module, payload=payload,
            parents=(*parents, *((trace_parent,) if trace_parent else ())), status=status,
            producer_source=producer_source or self._artifact_source, config_refs=(self._artifact_config,),
            cost=cost, checks=checks, optimizer_visible=optimizer_visible)

    def invoke(self, slot: str, model: Callable[[FrozenRecord], FrozenRecord], *, instruction: str,
               baseline_summary: str = "", module_context: FrozenRecord | None = None,
               evidence_only: bool = False, reporting_only: bool = False,
               context_projection: Callable[[FrozenRecord], FrozenRecord] | None = None) -> FrozenRecord:
        self.check_research_access(operation="model", slot=slot, reporting_only=reporting_only)
        if self._terminal or self._next_call >= len(self.slots) or slot != self.slots[self._next_call]:
            raise ContractError("call does not match frozen schedule")
        if type(evidence_only) is not bool:
            raise ContractError("evidence-only review flag must be boolean")
        mode = "candidate" if "M3" in self.arm.data()["enabled"] else "baseline"
        if "M2" in self.arm.data()["enabled"]:
            self.claims.refresh_after_withdrawal()
        if evidence_only:
            # An independent retrospective first pass must not inherit a claim
            # summary, including one hidden in the normal reconstructed context.
            context = FrozenRecord.from_dict({"identity": self.task.identity.data(),
                "records": [root.data() for root in self.evidence.roots(admitted_only=False, active_only=False)],
                "withdrawn": self.evidence.snapshot().data()["withdrawn"]})
            if len(context.encoded.encode()) > self.context_budget:
                raise ContractError("raw evidence review exceeds frozen context budget")
        else:
            bundle = self.cache.get_or_build(ContextBuilder(self.task.identity, budget_bytes=self.context_budget),
                canonical(self.task.payload.data()), self.evidence, self.claims, mode=mode, baseline_summary=baseline_summary)
            context = FrozenRecord.from_dict(bundle.public_data())
        if context_projection is not None:
            original_context = context
            context = context_projection(context)
            if not isinstance(context, FrozenRecord): raise ContractError('public evidence projection must be frozen')
            self._record('q8_public_evidence_context', {'slot': slot, 'controller_context': original_context.data(),
                'public_context': context.data(), 'public_digest': context.content_hash})
        request = FrozenRecord.from_dict({"schema": "public-model-request-v1", "task": self.task.data(),
            "lock_digest": self.lock.content_hash, "objective": self.objective.data(), "slot": slot,
            "instruction": required_text(instruction, "instruction"), "context": context.data(),
            "module_context": module_context.data() if module_context else {},
            "execution_feedback": [{"id": k, "status": e.status, "stdout": e.record.data().get("stdout", ""),
                                    "stderr": e.record.data().get("stderr", "")} for k, e in self.executions.items()]})
        self._next_call += 1  # Reserve before I/O; a failed call consumes its slot.
        self._record("model_request", {"request_digest": request.content_hash, "request": request.data()})
        try:
            response = model(request)
            if not isinstance(response, FrozenRecord):
                raise ContractError("model port returned a non-record")
        except Exception as exc:
            self._terminal = True
            self._record("model_failure", {"request_digest": request.content_hash, "error_type": type(exc).__name__})
            raise
        self._record("model_response", {"request_digest": request.content_hash, "response": response.data()})
        return response

    def execute(self, code: str, *, broker: DockerExecutionBroker, image: str,
                inputs: Mapping[str, Path], timeout_seconds: int = 20) -> ExecutionReceipt:
        self.check_research_access(operation="execution")
        if self._terminal or self._attempts >= self.execution_limit:
            raise ContractError("execution allocation exhausted or run terminal")
        self._attempts += 1
        program = self.sidecar / f"analysis-{self._attempts}.py"
        program.write_text(required_text(code, "program"), encoding="utf-8")
        self._record("execution_request", {"attempt": self._attempts, "program_sha256": hashlib.sha256(program.read_bytes()).hexdigest()})
        try:
            result = broker.execute(ExecutionRequest(self.task.identity, image, program, inputs, timeout_seconds))
        except Exception as exc:
            self._terminal = True
            self._record("execution_failure", {"attempt": self._attempts,
                         "program_sha256": hashlib.sha256(program.read_bytes()).hexdigest(),
                         "error_type": type(exc).__name__})
            raise
        self.executions[result.content_hash] = result
        self._record("execution_result", {"execution_digest": result.content_hash, "status": result.status,
                                         "record": result.record.data(), "receipt": result.data()})
        if result.status in {"unavailable", "rejected"}:
            self._record("execution_terminal", {"execution_digest": result.content_hash, "status": result.status})
            self._terminal = True
        return result

    def driver_failure(self, *, driver_id: str, response: FrozenRecord, error_type: str) -> FrozenRecord:
        """Close after a driver rejects its last real model response.

        This is distinct from a model-port failure: the response reached the
        controller, but the closed scenario driver could not use it.
        """
        if self._terminal or not isinstance(response, FrozenRecord):
            raise ContractError("driver failure requires an active response")
        if not isinstance(driver_id, str) or not driver_id or not isinstance(error_type, str) or not error_type:
            raise ContractError("driver failure needs typed driver and error")
        last = self._events[-1].data()
        if last["stage"] != "model_response" or FrozenRecord.from_dict(last["data"]["response"]).content_hash != response.content_hash:
            raise ContractError("driver failure must bind the last model response")
        self._terminal = True
        return self._record("driver_failure", {"schema": "driver-failure-v1", "driver_id": driver_id,
            "response_digest": response.content_hash, "request_digest": last["data"]["request_digest"],
            "error_type": error_type})

    def controller_failure(self, *, driver_id: str, error_type: str, panel_cell: Mapping[str, Any] | None = None) -> FrozenRecord:
        """Close a driver before it obtained a response to bind as a rejection."""
        if self._terminal or not isinstance(driver_id, str) or not driver_id or not isinstance(error_type, str) or not error_type:
            raise ContractError("controller failure needs an active typed driver")
        self._terminal = True
        body = {"schema": "controller-failure-v1", "driver_id": driver_id, "error_type": error_type}
        if panel_cell is not None:
            if not isinstance(panel_cell, Mapping):
                raise ContractError("controller failure panel binding must be a mapping")
            body["panel_cell"] = dict(panel_cell)
        return self._record("controller_failure", body)

    def admit(self, execution_digest: str, audits: list[FrozenRecord]) -> FrozenRecord:
        self.check_research_access(operation="scientific_admission")
        if self._terminal:
            raise ContractError("terminal runs cannot admit evidence")
        if execution_digest not in self.executions:
            raise ContractError("audit references unknown execution")
        execution = self.executions[execution_digest]
        self._record("scientific_audit_inputs", {"execution_digest": execution_digest,
            "receipts": [receipt.data() if isinstance(receipt, FrozenRecord) else {"malformed_type": type(receipt).__name__}
                         for receipt in audits]})
        try:
            admission = self.verifier.verify_pair(audits, identity=self.task.identity, objective_digest=self.objective.content_hash,
                                                  execution=execution, required_audit=self.required_audit)
        except ContractError as exc:
            self._record("audit_rejected", {"execution_digest": execution_digest, "reason": str(exc)})
            raise
        self._record("scientific_admission", admission.data())
        self.admissions[execution_digest] = admission
        # A trusted observation retains raw execution provenance. The issuer's
        # actual scientific checks are in the signed audit, not inferred from exit 0.
        observed = self.evidence.append({"kind": "measurement", "root_material": {"execution_digest": execution_digest},
            "representation": "raw", "content": {"stdout": execution.record.data().get("stdout", "")},
            "subject_bindings": {"task": self.task.identity.task_id, "objective": self.objective.content_hash},
            "independent_group": self.task.identity.group_id},
            {"trusted_validator": "+".join(admission.data()["authorities"]), "validator_verified": True,
             "admitted": admission.data()["admitted"]})
        self.admission_roots[execution_digest] = observed.root_id
        return admission

    def finish(self, candidate: FrozenRecord) -> FrozenRecord:
        if self._events[-1].data()["stage"] == "final_decision":
            raise ContractError("a run has only one final decision")
        body = candidate.data()
        reasons = candidate_reasons(body, self.objective.content_hash)
        if self._terminal or self._next_call != len(self.slots):
            reasons.append("incomplete_execution_schedule")
        outcome = body.get("outcome")
        ids = body.get("evidence_ids")
        if "invalid_evidence_ids" in reasons:
            ids = []
        if outcome in {"positive", "negative"}:
            if not ids or any(x not in self.admissions or not self.admissions[x].data()["admitted"]
                              or self.admissions[x].data()["outcome"] != outcome
                              or self.admissions[x].data()["state"]["support"] != {"positive": "supported", "negative": "refuted"}[outcome]
                              or not self.evidence.is_active_admitted(self.admission_roots[x])
                              for x in ids):
                reasons.append("missing_validated_evidence")
        if any(x not in self.executions for x in ids):
            reasons.append("unbound_evidence")
        result = FrozenRecord.from_dict({"schema": "run-decision-v1", "identity": self.task.identity.data(),
            "lock_digest": self.lock.content_hash, "candidate_digest": candidate.content_hash,
            "decision": "blocked" if reasons else "proceed" if outcome == "positive" else "closed_negative" if outcome == "negative" else outcome,
            "reasons": reasons, "scientific_validated": not reasons and outcome in {"positive", "negative"},
            "programme_complete": False, "model_calls": self._next_call, "execution_attempts": self._attempts})
        self._record("final_decision", result.data())
        self._terminal = True
        return result


def verify_trace(path: Path) -> FrozenRecord:
    """Read-only crash inspection verifies hash chaining, never resumes a call."""
    previous, lock, stages = None, None, []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        event = FrozenRecord(line)
        row = event.data()
        if row.get("sequence") != number or row.get("previous") != previous:
            raise ContractError("trace ordering or hash mismatch")
        lock = lock or row["lock_digest"]
        if row["lock_digest"] != lock:
            raise ContractError("trace lock drift")
        previous = event.content_hash
        stages.append(row["stage"])
    if not stages or stages[0] != "objective_lock":
        raise ContractError("trace lacks objective lock")
    return FrozenRecord.from_dict({"lock_digest": lock, "events": len(stages), "trace_digest": previous,
                                  "terminal": stages[-1] in {"final_decision", "model_failure", "driver_failure", "controller_failure", "execution_terminal", "execution_failure"}, "stages": stages})
