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
from typing import Callable, Mapping

from .contracts import ContractError, DataIdentity, FrozenRecord, PublicTask, required_text
from .benchmarks.execution import DockerExecutionBroker, ExecutionReceipt, ExecutionRequest
from .modules.admission import AuditItem, EvidenceAdmission, ScientificState
from .modules.context import ContextBuilder, ContextCache
from .modules.evidence import ClaimLedger, EvidenceLedger
from .combinations import default_compatibility
from research_loop.ontology import canonical, digest


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


class AuditVerifier:
    """Trusted controller-side verification with a frozen pair of authorities."""

    def __init__(self, keys: Mapping[str, bytes]):
        if len(keys) != 2 or any(not isinstance(key, bytes) or len(key) < 32 for key in keys.values()):
            raise ContractError("two registered audit authorities required")
        for name in keys:
            required_text(name, "authority id")
        self._keys = dict(keys)

    def verify_pair(self, receipts: list[FrozenRecord], *, identity: DataIdentity,
                    objective_digest: str, execution: ExecutionReceipt,
                    required_audit: tuple[str, ...]) -> FrozenRecord:
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
            disposition = EvidenceAdmission.decide(identity=identity, state=state, outcome=body["outcome"],
                execution_success=execution.status == "succeeded", trusted_validator=authority,
                validator_verified=True, evidence_ids=[execution.content_hash],
                subject_bindings={"task": identity.task_id, "objective": objective_digest},
                required_audit=required_audit, audit=checks)
            bodies[authority] = {"state": body["state"], "outcome": body["outcome"],
                                 "audit": sorted(body["audit"], key=lambda row: row["name"]), "admitted": disposition.admitted}
        normalized = list(bodies.values())
        if normalized[0] != normalized[1]:
            raise ContractError("dual audit disagreement")
        return FrozenRecord.from_dict({"schema": "verified-dual-audit-v1", "identity": identity.data(),
            "objective_digest": objective_digest, "execution_digest": execution.content_hash,
            "authorities": sorted(bodies), **normalized[0]})


class RunSession:
    """One task, one immutable objective, one bounded sequence of model calls.

    This does not optimize, score, or claim programme completion. Modules alter
    public context through explicit calls; all external calls and final gates are
    recorded. A crashed/incomplete run is inspected, never silently re-executed.
    """

    def __init__(self, task: PublicTask, *, package_digest: str, arm: FrozenRecord,
                 objective: FrozenRecord, slots: tuple[str, ...], execution_limit: int,
                 sidecar: Path, verifier: AuditVerifier, required_audit: tuple[str, ...],
                 context_budget: int = 12000):
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
        self.cache = ContextCache()
        self.executions: dict[str, ExecutionReceipt] = {}
        self.admissions: dict[str, FrozenRecord] = {}
        self.admission_roots: dict[str, str] = {}
        self._events: list[FrozenRecord] = []
        self._next_call, self._attempts, self._terminal = 0, 0, False
        self._record("objective_lock", self.lock.data())

    def _record(self, stage: str, data: dict) -> FrozenRecord:
        event = FrozenRecord.from_dict({"sequence": len(self._events), "previous": self._events[-1].content_hash if self._events else None,
                                       "lock_digest": self.lock.content_hash, "stage": stage, "data": data})
        with (self.sidecar / "trace.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(event.encoded + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        self._events.append(event)
        return event

    def invoke(self, slot: str, model: Callable[[FrozenRecord], FrozenRecord], *, instruction: str,
               baseline_summary: str = "", module_context: FrozenRecord | None = None) -> FrozenRecord:
        if self._terminal or self._next_call >= len(self.slots) or slot != self.slots[self._next_call]:
            raise ContractError("call does not match frozen schedule")
        mode = "candidate" if "M3" in self.arm.data()["enabled"] else "baseline"
        self.claims.refresh_after_withdrawal()
        context = self.cache.get_or_build(ContextBuilder(self.task.identity, budget_bytes=self.context_budget),
            canonical(self.task.payload.data()), self.evidence, self.claims, mode=mode, baseline_summary=baseline_summary)
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
        if self._terminal or self._attempts >= self.execution_limit:
            raise ContractError("execution allocation exhausted or run terminal")
        self._attempts += 1
        program = self.sidecar / f"analysis-{self._attempts}.py"
        program.write_text(required_text(code, "program"), encoding="utf-8")
        self._record("execution_request", {"attempt": self._attempts, "program_sha256": hashlib.sha256(program.read_bytes()).hexdigest()})
        result = broker.execute(ExecutionRequest(self.task.identity, image, program, inputs, timeout_seconds))
        self.executions[result.content_hash] = result
        self._record("execution_result", {"execution_digest": result.content_hash, "status": result.status, "record": result.record.data()})
        if result.status in {"unavailable", "rejected"}:
            self._terminal = True
        return result

    def admit(self, execution_digest: str, audits: list[FrozenRecord]) -> FrozenRecord:
        if self._terminal:
            raise ContractError("terminal runs cannot admit evidence")
        if execution_digest not in self.executions:
            raise ContractError("audit references unknown execution")
        execution = self.executions[execution_digest]
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
        fields = {"objective_digest", "outcome", "evidence_ids", "conclusion", "programme_complete"}
        reasons = []
        if set(body) != fields:
            reasons.append("candidate_schema")
        if body.get("objective_digest") != self.objective.content_hash:
            reasons.append("objective_drift")
        if self._terminal or self._next_call != len(self.slots):
            reasons.append("incomplete_execution_schedule")
        if body.get("programme_complete") is not False:
            reasons.append("programme_completion_unauthorized")
        outcome = body.get("outcome")
        if outcome not in {"positive", "negative", "unknown", "invalid", "withdrawn"}:
            reasons.append("invalid_outcome")
        ids = body.get("evidence_ids")
        if not isinstance(ids, list) or any(not isinstance(x, str) for x in ids) or len(set(ids)) != len(ids):
            reasons.append("invalid_evidence_ids")
            ids = []
        if not isinstance(body.get("conclusion"), str) or not body.get("conclusion", "").strip():
            reasons.append("missing_conclusion")
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
                                  "terminal": stages[-1] in {"final_decision", "model_failure"}, "stages": stages})
