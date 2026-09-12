"""Structural protocol replay, separate from scientific audit authentication.

A hash chain establishes ordering. This verifier additionally checks that a
successful decision has an actual call, execution and admission lineage. It
does not authenticate audit issuers or decide whether their science is right.
"""
from pathlib import Path
import re

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.benchmarks.execution import ExecutionReceipt
from research_loop.modular.modules.admission import AuditItem, EvidenceAdmission, ScientificState
from research_loop.modular.runtime import candidate_reasons, verify_trace
from research_loop.ontology import ContractError


def verify_protocol_trace(path: Path) -> FrozenRecord:
    chain = verify_trace(path)
    events = [FrozenRecord(line).data() for line in path.read_text(encoding="utf-8").splitlines()]
    lock = events[0]["data"]
    if FrozenRecord.from_dict(lock).content_hash != chain.data()["lock_digest"]:
        raise ContractError("protocol objective lock is not self-bound")
    if lock.get("schema") != "run-lock-v1" or not isinstance(lock.get("slots"), list):
        raise ContractError("protocol lock schema is invalid")
    calls, attempts, pending_call, pending_execution = [], 0, None, False
    program_sha = None
    executions, raw_audits, admissions = {}, {}, {}
    response, response_request, final, failed, execution_terminal = None, None, None, False, False
    for event in events[1:]:
        stage, data = event["stage"], event["data"]
        if stage == "objective_lock" or final is not None:
            raise ContractError("protocol changes its lock or continues after a final decision")
        if execution_terminal:
            raise ContractError("protocol continues after a terminal execution")
        if failed and stage not in {"final_decision", "execution_terminal"}:
            raise ContractError("protocol continues after a terminal external failure")
        if stage == "model_request":
            request = data.get("request", {})
            if pending_call is not None or pending_execution:
                raise ContractError("protocol has overlapping external calls")
            pending_call = FrozenRecord.from_dict(request).content_hash
            calls.append(request.get("slot"))
            if (data.get("request_digest") != pending_call
                    or request.get("lock_digest") != chain.data()["lock_digest"]
                    or request.get("objective") != lock["objective"]
                    or FrozenRecord.from_dict(request.get("task", {})).content_hash != lock["task_digest"]
                    or calls != lock["slots"][:len(calls)]):
                raise ContractError("protocol request has task, objective or schedule drift")
        elif stage in {"model_response", "model_failure"}:
            if pending_call is None or data.get("request_digest") != pending_call:
                raise ContractError("protocol response lacks its request")
            pending_call = None
            if stage == "model_response":
                response = FrozenRecord.from_dict(data["response"])
                response_request = data["request_digest"]
            else:
                failed = True
        elif stage == "driver_failure":
            if pending_call is not None or pending_execution or response is None or data.get("schema") != "driver-failure-v1":
                raise ContractError("driver failure lacks a completed model response")
            if (data.get("response_digest") != response.content_hash or data.get("request_digest") != response_request
                    or not isinstance(data.get("driver_id"), str)
                    or not data["driver_id"] or not isinstance(data.get("error_type"), str) or not data["error_type"]):
                raise ContractError("driver failure lacks response, driver, or error binding")
            failed = True
        elif stage == "controller_failure":
            if pending_call is not None or pending_execution or data.get("schema") != "controller-failure-v1":
                raise ContractError("controller failure has unresolved work")
            if not isinstance(data.get("driver_id"), str) or not data["driver_id"] or not isinstance(data.get("error_type"), str) or not data["error_type"]:
                raise ContractError("controller failure lacks typed driver details")
            failed = True
        elif stage == "execution_request":
            attempts += 1
            if pending_execution or pending_call is not None or data.get("attempt") != attempts or attempts > lock["execution_limit"]:
                raise ContractError("protocol execution violates its frozen allocation")
            pending_execution = True
            program_sha = data.get("program_sha256")
            if not isinstance(program_sha, str) or not re.fullmatch("[0-9a-f]{64}", program_sha):
                raise ContractError("protocol execution lacks a program digest")
        elif stage == "execution_result":
            execution_id = data.get("execution_digest")
            if not pending_execution or not isinstance(execution_id, str) or execution_id in executions:
                raise ContractError("protocol execution result lacks a unique request")
            if data.get("status") not in {"succeeded", "failed", "timed_out", "unavailable", "rejected"}:
                raise ContractError("protocol execution has an illegal state")
            if data.get("record", {}).get("status") != data["status"]:
                raise ContractError("protocol execution status disagrees with its receipt")
            execution = ExecutionReceipt.parse(data.get("receipt"))
            if (execution.content_hash != execution_id or execution.identity.data() != lock["identity"]
                    or execution.record.data() != data["record"] or execution.status != data["status"]
                    or (execution.artifact is not None and execution.artifact.sha256 != program_sha)):
                raise ContractError("protocol execution envelope has subject, program or digest drift")
            pending_execution = False
            executions[execution_id] = data
            if execution.status in {"unavailable", "rejected"}:
                failed = True
        elif stage == "execution_failure":
            if not pending_execution or set(data) != {"attempt", "program_sha256", "error_type"}:
                raise ContractError("protocol execution failure lacks its pending request")
            if (data["attempt"] != attempts or data["program_sha256"] != program_sha
                    or not isinstance(data["error_type"], str) or not data["error_type"]):
                raise ContractError("protocol execution failure has invalid binding")
            pending_execution = False
            failed = execution_terminal = True
        elif stage == "execution_terminal":
            if set(data) != {"execution_digest", "status"}:
                raise ContractError("protocol execution terminal has an invalid envelope")
            execution_id = data["execution_digest"]
            if (not failed or pending_execution or execution_id not in executions
                    or data["status"] not in {"unavailable", "rejected"}
                    or executions[execution_id]["status"] != data["status"]):
                raise ContractError("protocol execution terminal lacks its failed execution binding")
            execution_terminal = True
        elif stage == "scientific_audit_inputs":
            if data.get("execution_digest") not in executions:
                raise ContractError("protocol audit lacks an execution")
            raw_audits[data["execution_digest"]] = data.get("receipts")
        elif stage == "scientific_admission":
            execution_id = data.get("execution_digest")
            raw = raw_audits.get(execution_id)
            if execution_id not in executions or not isinstance(raw, list) or len(raw) != 2:
                raise ContractError("protocol admission lacks execution and both raw audits")
            if (data.get("identity") != lock["identity"]
                    or data.get("objective_digest") != FrozenRecord.from_dict(lock["objective"]).content_hash):
                raise ContractError("protocol admission has subject drift")
            _check_audit_structure(raw, data, lock, ExecutionReceipt.parse(executions[execution_id]["receipt"]))
            admissions[execution_id] = data
        elif stage == "audit_rejected":
            if data.get("execution_digest") not in raw_audits:
                raise ContractError("protocol audit rejection lacks the submitted audits")
        elif stage == "final_decision":
            final = data
            decision = final.get("decision")
            if (decision not in {"blocked", "proceed", "closed_negative", "unknown", "invalid", "withdrawn"}
                    or final.get("lock_digest") != chain.data()["lock_digest"]
                    or final.get("identity") != lock["identity"] or final.get("programme_complete") is not False
                    or final.get("model_calls") != len(calls) or final.get("execution_attempts") != attempts):
                raise ContractError("protocol final decision has illegal state or binding")
            if pending_call is not None or pending_execution:
                raise ContractError("protocol final decision leaves external work unresolved")
            # A blocked run may be closed without another model call after a
            # failure or an incomplete schedule. It cannot thereby succeed.
            if decision != "blocked":
                if failed or calls != lock["slots"] or response is None or final.get("candidate_digest") != response.content_hash:
                    raise ContractError("protocol final decision lacks a complete model response")
                candidate = response.data()
                if candidate_reasons(candidate, FrozenRecord.from_dict(lock["objective"]).content_hash):
                    raise ContractError("protocol successful decision has an invalid candidate")
                if any(execution_id not in executions for execution_id in candidate["evidence_ids"]):
                    raise ContractError("protocol candidate has unbound evidence")
                expected = {"positive": "proceed", "negative": "closed_negative"}.get(candidate.get("outcome"), candidate.get("outcome"))
                if (decision != expected or candidate.get("programme_complete") is not False
                        or candidate.get("objective_digest") != FrozenRecord.from_dict(lock["objective"]).content_hash
                        or final.get("reasons") != []):
                    raise ContractError("protocol final decision contradicts its candidate")
                if decision in {"proceed", "closed_negative"}:
                    ids = candidate.get("evidence_ids")
                    if not isinstance(ids, list) or not ids:
                        raise ContractError("protocol scientific decision lacks evidence")
                    outcome = candidate["outcome"]
                    for execution_id in ids:
                        admitted = admissions.get(execution_id, {})
                        if (executions.get(execution_id, {}).get("status") != "succeeded"
                                or admitted.get("admitted") is not True or admitted.get("outcome") != outcome
                                or admitted.get("state", {}).get("validity") != "valid"
                                or admitted.get("state", {}).get("support") != {"positive": "supported", "negative": "refuted"}[outcome]):
                            raise ContractError("protocol scientific decision lacks qualifying execution and admission")
                    if final.get("scientific_validated") is not True:
                        raise ContractError("protocol scientific decision contradicts its validation flag")
                elif final.get("scientific_validated") is not False:
                    raise ContractError("protocol non-scientific decision claims validation")
            elif not final.get("reasons") or final.get("scientific_validated") is not False:
                raise ContractError("protocol blocked decision lacks a reason or claims validation")
    return FrozenRecord.from_dict({"schema": "protocol-structure-verification-v1", "trace": chain.data(),
        "decision": final["decision"] if final else None,
        "structurally_verified": True, "scientific_audit_authenticated": False,
        "limitation": "scientific truth, audit signatures and host access isolation require independent verification"})


def _check_audit_structure(raw: list, admission: dict, lock: dict, execution: ExecutionReceipt) -> None:
    """Check conditional disposition and bindings without claiming MAC trust."""
    bodies, authorities = [], []
    for receipt in raw:
        if not isinstance(receipt, dict) or set(receipt) != {"body", "mac"} or not isinstance(receipt["body"], dict):
            raise ContractError("protocol raw audit envelope is incomplete")
        if not isinstance(receipt["mac"], str) or not re.fullmatch("[0-9a-f]{64}", receipt["mac"]):
            raise ContractError("protocol raw audit MAC is malformed")
        body = receipt["body"]
        if set(body) != {"schema", "authority", "identity", "objective_digest", "execution_digest", "state", "outcome", "audit"}:
            raise ContractError("protocol raw audit body is incomplete")
        if (body["schema"] != "host-scientific-audit-v1" or body["identity"] != lock["identity"]
                or body["objective_digest"] != FrozenRecord.from_dict(lock["objective"]).content_hash
                or body["execution_digest"] != execution.content_hash):
            raise ContractError("protocol raw audit has subject drift")
        try:
            state = ScientificState(**body["state"])
            checks = [AuditItem(**row) for row in body["audit"]]
        except (TypeError, KeyError) as exc:
            raise ContractError("protocol raw audit state or checks are malformed") from exc
        disposition = EvidenceAdmission.decide(identity=execution.identity, state=state, outcome=body["outcome"],
            execution_success=execution.status == "succeeded", trusted_validator=body["authority"], validator_verified=True,
            evidence_ids=[execution.content_hash], subject_bindings={"task": execution.identity.task_id, "objective": body["objective_digest"]},
            required_audit=lock["required_audit"], audit=checks)
        authorities.append(body["authority"])
        bodies.append({"state": body["state"], "outcome": body["outcome"],
                       "audit": sorted(body["audit"], key=lambda row: row["name"]), "admitted": disposition.admitted})
    expected = {"schema": "verified-dual-audit-v1", "identity": lock["identity"],
        "objective_digest": FrozenRecord.from_dict(lock["objective"]).content_hash,
        "execution_digest": execution.content_hash, "authorities": sorted(authorities), **bodies[0]}
    if len(set(authorities)) != 2 or bodies[0] != bodies[1] or expected != admission:
        raise ContractError("protocol raw audits disagree with each other or the admission")
