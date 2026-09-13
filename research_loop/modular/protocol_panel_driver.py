"""Typed production seam for Q2.7 P0 protocol-structure fault replays.

The source run executes one caller-frozen public program and receives two
caller-owned audit receipts.  A separate, read-only post-finish hook writes a
controlled rechained copy and verifies that removing a required protocol event
is refused.  It does not modify the source journal or change its terminal
decision.  The hook is deliberately separate because ``RunSession.finish`` is
the sole source terminal writer.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import os
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping, Sequence

from research_loop.modular.benchmarks.execution import DockerExecutionBroker, ExecutionReceipt, ExecutionRequest
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask, required_text, strict_bool
from research_loop.modular.experiments import registry
from research_loop.modular.modules.improvement import TrainingManifest
from research_loop.modular.p0_panel import validate_fixed_control_design
from research_loop.modular.panel_receipts import opaque_panel_cell_binding
from research_loop.modular.protocol_trace import verify_protocol_trace
from research_loop.ontology import ContractError, canonical


_VARIANTS = ("missing_lock", "missing_execution", "missing_audit", "illegal_state")
_HEX = frozenset("0123456789abcdef")
ProtocolAuditPort = Callable[[FrozenRecord], FrozenRecord]
_ALLOCATION = {'docker_attempts': 1, 'audit_calls': 1, 'audit_authorities': 2,
               'material_receipts': 2, 'runtime_receipts': 2, 'model_calls': 1,
               'audit_cost_accounting': 'reported_or_unknown'}


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{name} must be a mapping")
    return value


def _digest(value: Any, name: str) -> str:
    text = required_text(value, name)
    if len(text) != 64 or any(char not in _HEX for char in text):
        raise ContractError(f"{name} must be a sha256 digest")
    return text


def _image(value: Any) -> str:
    text = required_text(value, "execution image")
    name, marker, digest = text.partition("@sha256:")
    if not name or marker != "@sha256:" or len(digest) != 64 or any(char not in _HEX for char in digest):
        raise ContractError("execution image must have a fixed sha256 digest")
    return text


def _execution(value: Any) -> dict[str, Any]:
    body = dict(_mapping(value, "caller public execution"))
    required = {"program", "csv_bytes_hex", "csv_sha256", "image", "timeout_seconds"}
    if not required <= set(body) or set(body) - required - {"program_sha256", "program_byte_count", "csv_byte_count"}:
        raise ContractError("caller public execution fields are incomplete")
    program = required_text(body["program"], "caller program")
    if "\r" in program:
        raise ContractError("program source must use LF; execution bytes follow host text translation")
    program_bytes = program.replace("\n", os.linesep).encode("utf-8")
    program_sha = hashlib.sha256(program_bytes).hexdigest()
    if "program_sha256" in body and _digest(body["program_sha256"], "caller program digest") != program_sha:
        raise ContractError("caller program digest does not match its literal text")
    csv_hex = required_text(body["csv_bytes_hex"], "caller CSV bytes")
    if len(csv_hex) % 2 or any(char not in _HEX for char in csv_hex):
        raise ContractError("caller CSV must be lowercase hexadecimal bytes")
    csv = bytes.fromhex(csv_hex)
    if not csv:
        raise ContractError("caller CSV cannot be empty")
    csv_sha = _digest(body["csv_sha256"], "caller CSV digest")
    if hashlib.sha256(csv).hexdigest() != csv_sha:
        raise ContractError("caller CSV digest does not match its literal bytes")
    timeout = body["timeout_seconds"]
    if type(timeout) is not int or not 1 <= timeout <= 60:
        raise ContractError("execution timeout must be an integer from 1 to 60")
    for key, actual in (("program_byte_count", len(program_bytes)), ("csv_byte_count", len(csv))):
        if key in body and (type(body[key]) is not int or body[key] != actual):
            raise ContractError("literal artifact byte count drift")
    return {"program": program, "program_sha256": program_sha, "program_byte_count": len(program_bytes), "csv_byte_count": len(csv),
            "csv_bytes_hex": csv_hex, "csv_sha256": csv_sha, "image": _image(body["image"]),
            "timeout_seconds": timeout}


def _p0_grid(value: Any) -> FrozenRecord:
    record = value if isinstance(value, FrozenRecord) else FrozenRecord.from_dict(dict(_mapping(value, "P0 fixed-control grid")))
    return validate_fixed_control_design(record)


def freeze_protocol_bundle(task: PublicTask, *, execution: Mapping[str, Any],
                           p0_fixed_control: FrozenRecord, measurement_contract: Mapping[str, Any]) -> FrozenRecord:
    """Freeze source-bound public execution material before any runtime call."""
    if not isinstance(task, PublicTask):
        raise ContractError("protocol bundle requires a public task")
    task.identity.require_train()
    measurement = dict(_mapping(measurement_contract, "measurement contract"))
    if set(measurement) != {"source_id", "contract_id", "method", "output_key"} or measurement["source_id"] != task.identity.group_id:
        raise ContractError("measurement contract must bind the public source")
    for key, value in measurement.items(): required_text(value, key)
    checked_execution = _execution(execution)
    ExecutionRequest(task.identity, checked_execution["image"], Path("planned.py"), {"public_csv": Path("planned.csv")}, checked_execution["timeout_seconds"])
    return FrozenRecord.from_dict({
        "schema": "q27-protocol-panel-bundle-v2", "measurement_contract": measurement, "allocation": _ALLOCATION, "identity": task.identity.data(),
        "payload_digest": task.payload.content_hash, "p0_fixed_control": _p0_grid(p0_fixed_control).data(),
        "execution": checked_execution,
    })


def protocol_panel_injection(variant: str, *, task: FrozenRecord, evidence: FrozenRecord,
                             p0_fixed_control: FrozenRecord) -> Mapping[str, Any]:
    """Project one canonical caller bundle into the standard scenario body."""
    if variant not in _VARIANTS:
        raise ContractError("protocol panel variant is not registered")
    public = PublicTask(DataIdentity.parse(task.data()["identity"]), FrozenRecord.from_dict(task.data()["payload"]))
    body = evidence.data()
    if body.get("schema") != "q27-protocol-panel-bundle-v2":
        raise ContractError("protocol panel requires typed caller execution material")
    bundle = FrozenRecord.from_dict(body)
    remade = freeze_protocol_bundle(public, execution=body.get("execution", {}),
                                    p0_fixed_control=FrozenRecord.from_dict(_mapping(body.get("p0_fixed_control"), "P0 grid")), measurement_contract=body.get("measurement_contract", {}))
    if remade.content_hash != bundle.content_hash:
        raise ContractError("protocol caller bundle is not a canonical closed reconstruction")
    actual = _p0_grid(p0_fixed_control)
    if actual.content_hash != _p0_grid(body["p0_fixed_control"]).content_hash:
        raise ContractError("protocol caller bundle P0 control differs from the actual fixed-control grid")
    return {"schema": "q27-protocol-controller-v2", "bundle": bundle.data(),
            "p0_fixed_control": actual.data()}


def protocol_audit_subject(*, task: PublicTask, objective: FrozenRecord,
                           execution: ExecutionReceipt, bundle: FrozenRecord) -> FrozenRecord:
    """Actual public material for independent checks, with signed subject binding."""
    spec = bundle.data()["execution"]
    _check_execution(execution, task, spec)
    return FrozenRecord.from_dict({"schema": "q27-runtime-audit-subject-v2", "identity": task.identity.data(),
        "task_digest": task.content_hash, "public_task": task.data(), "objective": objective.data(),
        "objective_digest": objective.content_hash, "bundle_digest": bundle.content_hash,
        "execution_digest": execution.content_hash, "execution_status": execution.status,
        "execution_receipt": execution.data(), "measurement_contract": bundle.data()["measurement_contract"],
        "public_artifacts": {"program_bytes_hex": spec["program"].replace("\n", os.linesep).encode().hex(),
                             "csv_bytes_hex": spec["csv_bytes_hex"]}, "required_audit": ["measurement"]})


def _check_execution(execution, task, spec):
    expected = {"public_csv": {"artifact_id": "public_csv", "sha256": spec["csv_sha256"], "byte_count": spec["csv_byte_count"]}}
    if (not isinstance(execution, ExecutionReceipt) or execution.identity != task.identity
            or execution.artifact is None or execution.artifact.identity != task.identity
            or execution.artifact.sha256 != spec["program_sha256"]
            or execution.artifact.byte_count != spec["program_byte_count"]
            or execution.record.data().get("input_artifacts") != expected):
        raise ContractError("actual execution artifacts differ from the frozen literal material")


def _checked_audits(session, subject, raw, execution):
    if not isinstance(raw, FrozenRecord):
        raise ContractError("audit batch must be frozen")
    row = raw.data()
    if (set(row) != {"schema", "subject_digest", "material_receipts", "runtime_receipts", "cost"}
            or row["schema"] != "q27-audit-batch-v2" or row["subject_digest"] != subject.content_hash):
        raise ContractError("audit batch subject or schema mismatch")
    cost = row["cost"]
    if (not isinstance(cost, Mapping) or set(cost) != {"unit", "units"} or cost["unit"] != "audit_units"
            or (cost["units"] is not None and (type(cost["units"]) is not int or cost["units"] < 0))):
        raise ContractError("audit batch cost must be measured or explicitly unknown")
    for field in ("material_receipts", "runtime_receipts"):
        if not isinstance(row[field], list) or len(row[field]) != 2 or any(not isinstance(x, dict) for x in row[field]):
            raise ContractError("two complete linked receipts per authority required")
    material = [FrozenRecord.from_dict(x) for x in row["material_receipts"]]
    runtime = [FrozenRecord.from_dict(x) for x in row["runtime_receipts"]]
    checked_material = session.verifier.verify_material(material, identity=session.task.identity,
        subject_digest=subject.content_hash, required_audit=("measurement",)).data()
    checked_runtime = session.verifier.verify_evidence(runtime, identity=session.task.identity,
        objective_digest=session.objective.content_hash, execution=execution, required_audit=("measurement",)).data()
    if (checked_material["execution_success"] != (execution.status == "succeeded") or any(
            checked_material[field] != checked_runtime[field] for field in ("authorities", "state", "outcome", "audit"))):
        raise ContractError("material and runtime audits disagree or misstate actual execution")
    return runtime


@dataclass(frozen=True)
class ProtocolReplayAuthority:
    """Caller-configured HMAC receipt issuer for post-finish replay findings.

    The HMAC establishes the configured issuer and exact finding binding.  It
    does not establish OS isolation, audit independence, or scientific truth.
    """
    name: str
    key: bytes

    def __post_init__(self) -> None:
        required_text(self.name, "replay authority")
        if not isinstance(self.key, bytes) or len(self.key) < 16:
            raise ContractError("replay authority key is invalid")

    def issue(self, finding: FrozenRecord) -> FrozenRecord:
        if not isinstance(finding, FrozenRecord):
            raise ContractError("replay finding must be frozen")
        body = {"schema": "q27-signed-replay-receipt-v1", "authority": self.name, "finding": finding.data()}
        mac = hmac.new(self.key, canonical(body).encode("utf-8"), hashlib.sha256).hexdigest()
        return FrozenRecord.from_dict({**body, "mac": mac})

    def verify(self, receipt: FrozenRecord) -> FrozenRecord:
        if not isinstance(receipt, FrozenRecord):
            raise ContractError("replay receipt must be frozen")
        body = receipt.data()
        if set(body) != {"schema", "authority", "finding", "mac"} or body["schema"] != "q27-signed-replay-receipt-v1":
            raise ContractError("replay receipt schema is invalid")
        if body["authority"] != self.name or not isinstance(body["finding"], dict) or not isinstance(body["mac"], str):
            raise ContractError("replay receipt authority is invalid")
        expected = hmac.new(self.key, canonical({"schema": body["schema"], "authority": body["authority"],
            "finding": body["finding"]}).encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, body["mac"]):
            raise ContractError("replay receipt signature does not verify")
        return FrozenRecord.from_dict(body["finding"])


def _material(task: PublicTask, scenario: FrozenRecord, *, variant: str) -> tuple[FrozenRecord, dict[str, Any], FrozenRecord]:
    body = scenario.data()
    if set(body) != {"experiment_id", "variant", "controller_input", "base", "controls"}:
        raise ContractError("protocol scenario has unexpected top-level fields")
    if body["experiment_id"] != "Q2.7" or body["variant"] != variant:
        raise ContractError("protocol scenario experiment or variant drift")
    controller = _mapping(body["controller_input"], "protocol controller")
    if set(controller) != {"schema", "bundle", "p0_fixed_control"} or controller.get("schema") != "q27-protocol-controller-v2":
        raise ContractError("typed protocol panel material is required")
    bundle = FrozenRecord.from_dict(dict(_mapping(controller["bundle"], "protocol bundle")))
    source = bundle.data()
    remade = freeze_protocol_bundle(task, execution=source.get("execution", {}),
                                    p0_fixed_control=FrozenRecord.from_dict(_mapping(source.get("p0_fixed_control"), "P0 grid")), measurement_contract=source.get("measurement_contract", {}))
    base = _mapping(body["base"], "protocol scenario base")
    if (set(base) != {"task", "evidence", "budget"} or base["task"] != task.content_hash
            or base["evidence"] != bundle.content_hash or remade.content_hash != bundle.content_hash):
        raise ContractError("protocol scenario does not bind its caller material")
    _digest(base["budget"], "protocol budget digest")
    controls = _mapping(body["controls"], "protocol controls")
    if set(controls) != {"same_task", "same_evidence", "same_budget"} or not all(
            strict_bool(controls[name], name) for name in controls):
        raise ContractError("protocol scenario controls are not fixed")
    grid = _p0_grid(controller["p0_fixed_control"])
    if grid.content_hash != _p0_grid(source["p0_fixed_control"]).content_hash:
        raise ContractError("protocol scenario P0 control differs from its caller bundle")
    return bundle, _execution(source["execution"]), grid


def _candidate(value: FrozenRecord, objective_digest: str) -> FrozenRecord:
    body = value.data()
    if (set(body) != {"objective_digest", "outcome", "evidence_ids", "conclusion", "programme_complete"}
            or body.get("objective_digest") != objective_digest or body.get("outcome") not in {"positive", "negative", "unknown", "invalid", "withdrawn"}
            or not isinstance(body.get("evidence_ids"), list) or any(not isinstance(row, str) or not row for row in body["evidence_ids"])
            or len(set(body["evidence_ids"])) != len(body["evidence_ids"]) or not isinstance(body.get("conclusion"), str)
            or not body["conclusion"].strip() or body.get("programme_complete") is not False):
        raise ContractError("protocol final candidate has an invalid bounded schema")
    return value


def _verify_binding(workflow, *, cell, scenario: FrozenRecord, package, p0_grid: FrozenRecord,
                    expected_p0_control_digest: str | None) -> str:
    session = workflow.session
    if (cell.coverage_id != "Q2.7" or cell.variant not in _VARIANTS or cell.arm_id != "p0-fixed"
            or set(registry()["Q2.7"].modules) != {"P0"} or cell.scenario_digest != scenario.content_hash
            or session.task.identity != cell.identity or session.task.content_hash != cell.task_digest
            or session.arm != cell.runtime_arm or package.digest != cell.package_digest
            or session.lock.data().get("package_digest") != cell.package_digest
            or session.lock.data().get("arm") != cell.runtime_arm.data() or tuple(session.slots) != ("final",)):
        raise ContractError("protocol cell, session, or package binding drift")
    try:
        manifest = TrainingManifest(FrozenRecord.from_dict(package.record.data()["training_manifest"]))
    except (AttributeError, KeyError, TypeError) as exc:
        raise ContractError("protocol package lacks a valid training manifest") from exc
    if session.task.identity not in manifest.identities():
        raise ContractError("protocol package training manifest omits this task")
    if expected_p0_control_digest is None:
        raise ContractError("protocol driver requires a trusted expected P0 control digest")
    expected = _digest(expected_p0_control_digest, "trusted expected P0 control digest")
    grid = validate_fixed_control_design(p0_grid).data()
    if grid["runtime_arm"] != cell.runtime_arm.data() or grid["p0_control_digest"] != expected:
        raise ContractError("protocol P0 fixed control does not bind this runtime cell")
    return expected


@dataclass(frozen=True)
class Q27ProtocolDriver:
    """One-execution source driver; controlled faults exist only in replay."""
    broker: DockerExecutionBroker | None = None
    audit_port: ProtocolAuditPort | None = None
    expected_p0_control_digest: str | None = None
    experiment_id: str = "Q2.7"
    slots: tuple[str, ...] = ("final",)
    execution_limit: int = 1
    docker_execution: str = "one caller-frozen public Docker execution per P0 cell"

    def slots_for(self, cell) -> tuple[str, ...]:
        return self.slots

    def run(self, workflow, *, cell, scenario: FrozenRecord, model, package):
        if not isinstance(self.broker, DockerExecutionBroker) or not callable(self.audit_port):
            raise ContractError("protocol driver requires caller-owned execution and audit ports")
        bundle, execution_spec, p0_grid = _material(workflow.session.task, scenario, variant=cell.variant)
        p0_digest = _verify_binding(workflow, cell=cell, scenario=scenario, package=package, p0_grid=p0_grid,
                                    expected_p0_control_digest=self.expected_p0_control_digest)
        workflow.session._record("q27_allocation", {"allocation": bundle.data()["allocation"]})
        csv_path = workflow.session.sidecar / "q27-public.csv"
        csv_bytes = bytes.fromhex(execution_spec["csv_bytes_hex"])
        csv_path.write_bytes(csv_bytes)
        if hashlib.sha256(csv_path.read_bytes()).hexdigest() != execution_spec["csv_sha256"]:
            raise ContractError("written public CSV does not retain its caller digest")
        execution = workflow.session.execute(execution_spec["program"], broker=self.broker, image=execution_spec["image"],
            inputs={"public_csv": csv_path}, timeout_seconds=execution_spec["timeout_seconds"])
        _check_execution(execution, workflow.session.task, execution_spec)
        subject = protocol_audit_subject(task=workflow.session.task, objective=workflow.session.objective,
            execution=execution, bundle=bundle)
        workflow.session._record("q27_audit_request", {"call_number": 1, "allocation": _ALLOCATION,
            "subject": subject.data(), "subject_digest": subject.content_hash, "cost": {"unit": "audit_units", "units": None}})
        raw = None
        try:
            raw = self.audit_port(subject)
            if isinstance(raw, FrozenRecord):
                workflow.session._record("q27_audit_response", {"subject_digest": subject.content_hash, "batch": raw.data()})
            receipts = _checked_audits(workflow.session, subject, raw, execution)
            workflow.session._record("q27_audit_result", {"call_number": 1, "subject_digest": subject.content_hash,
                "runtime_receipts": len(receipts), "material_receipts": 2, "cost": raw.data()["cost"]})
        except Exception as exc:
            workflow.session._record("q27_audit_failure", {"call_number": 1, "subject_digest": subject.content_hash,
                "error_type": type(exc).__name__, "cost": {"unit": "audit_units", "units": None},
                "reported_cost": raw.data().get("cost") if isinstance(raw, FrozenRecord) else None})
            raise
        admission = workflow.session.admit(execution.content_hash, receipts)
        trace = workflow._trace("protocol_source_execution", "executed", p0_control_digest=p0_digest,
            execution_digest=execution.content_hash, execution_status=execution.status,
            audit_subject_digest=subject.content_hash, audit_receipt_digests=[row.content_hash for row in receipts],
            admission_digest=admission.content_hash, budget=_ALLOCATION,
            science="execution and signature bindings only; scientific correctness requires independent review")
        final = workflow.invoke_model("final", model,
            instruction="Return the bounded train-only candidate record. Use only the frozen objective and the actual execution evidence identifier; zero exit alone is not scientific validation.",
            evidence_only=True, module_context=FrozenRecord.from_dict({"panel_cell": opaque_panel_cell_binding(cell),
                "p0_control_digest": p0_digest, "required_objective_digest": workflow.session.objective.content_hash,
                "public_execution": {"program_sha256": execution_spec["program_sha256"],
                    "csv_sha256": execution_spec["csv_sha256"], "image": execution_spec["image"],
                    "execution_digest": execution.content_hash, "execution_status": execution.status}}))
        return trace, _candidate(final, workflow.session.objective.content_hash), (final,)


def _rechain(path: Path, events: list[dict[str, Any]]) -> None:
    prior, lines = None, []
    for number, event in enumerate(events):
        row = dict(event)
        row["sequence"], row["previous"] = number, prior
        frozen = FrozenRecord.from_dict(row)
        prior = frozen.content_hash
        lines.append(frozen.encoded)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _faulted_events(events: list[dict[str, Any]], variant: str) -> list[dict[str, Any]]:
    if variant == "missing_lock":
        return events[1:]
    if variant == "missing_execution":
        return [event for event in events if event["stage"] not in {"execution_request", "execution_result"}]
    if variant == "missing_audit":
        return [event for event in events if event["stage"] not in {"scientific_audit_inputs", "scientific_admission"}]
    if variant == "illegal_state":
        copied = [dict(event) for event in events]
        final = next(event for event in copied if event["stage"] == "final_decision")
        data = dict(final["data"])
        data["decision"] = "illegal_state"
        final["data"] = data
        return copied
    raise ContractError("protocol replay variant is not registered")


def verify_after_finish(*, cell, scenario: FrozenRecord, session, candidate: FrozenRecord,
                        terminal: FrozenRecord, replay_authority: ProtocolReplayAuthority,
                        expected_p0_control_digest: str) -> FrozenRecord:
    """Issue one immutable result from the authentic source, or retain ineligibility."""
    from research_loop.modular.runtime import RunSession
    if (not isinstance(session, RunSession) or not session._terminal
            or not isinstance(replay_authority, ProtocolReplayAuthority)
            or not isinstance(candidate, FrozenRecord) or not isinstance(terminal, FrozenRecord)):
        raise ContractError("replay requires a completed real session and typed inputs")
    bundle, execution_spec, p0_grid = _material(session.task, scenario, variant=cell.variant)
    grid = validate_fixed_control_design(p0_grid).data()
    if (cell.coverage_id != "Q2.7" or cell.variant not in _VARIANTS or cell.arm_id != "p0-fixed"
            or cell.scenario_digest != scenario.content_hash
            or session.task.identity != cell.identity or session.task.content_hash != cell.task_digest
            or session.arm != cell.runtime_arm or grid["runtime_arm"] != cell.runtime_arm.data()
            or grid["p0_control_digest"] != _digest(expected_p0_control_digest, "trusted P0 control")
            or session.lock.data().get("package_digest") != cell.package_digest
            or session.lock.data().get("arm") != cell.runtime_arm.data() or tuple(session.slots) != ("final",)):
        raise ContractError("protocol replay source does not bind its frozen P0 cell")
    source_path = session.sidecar / "trace.jsonl"
    _no_links(source_path)
    before = source_path.read_bytes()
    events = [FrozenRecord(line).data() for line in before.decode("utf-8").splitlines()]
    if events != [x.data() for x in session._events] or not events or events[-1]["stage"] != "final_decision":
        raise ContractError("source journal differs from the completed session")
    responses = [e["data"]["response"] for e in events if e["stage"] == "model_response"]
    if (terminal.data() != events[-1]["data"] or not responses or candidate.data() != responses[-1]
            or terminal.data().get("candidate_digest") != candidate.content_hash
            or terminal.data().get("lock_digest") != session.lock.content_hash):
        raise ContractError("terminal and candidate must exactly match the real source journal")
    requests = [e["data"]["request"] for e in events if e["stage"] == "model_request"]
    if not requests or any(r["module_context"].get("panel_cell") != opaque_panel_cell_binding(cell)
            or r["module_context"].get("p0_control_digest") != expected_p0_control_digest for r in requests):
        raise ContractError("source requests lack exact cell and trusted P0 binding")
    source = verify_protocol_trace(source_path)
    # Reauthenticate the real source pair, including the full material subject.
    audit_requests = [e["data"] for e in events if e["stage"] == "q27_audit_request"]
    audit_responses = [e["data"] for e in events if e["stage"] == "q27_audit_response"]
    source_executions = [e["data"]["receipt"] for e in events if e["stage"] == "execution_result"]
    if len(source_executions) != 1 or len(audit_requests) != 1 or len(audit_responses) != 1:
        raise ContractError("source lacks its actual execution and audit attempt")
    execution = ExecutionReceipt.parse(source_executions[0]); _check_execution(execution, session.task, execution_spec)
    subject = protocol_audit_subject(task=session.task, objective=session.objective, execution=execution, bundle=bundle)
    if audit_requests[0]["subject"] != subject.data() or audit_requests[0]["subject_digest"] != subject.content_hash:
        raise ContractError("source audit request is not the frozen actual subject")
    _checked_audits(session, subject, FrozenRecord.from_dict(audit_responses[0]["batch"]), execution)
    eligible = (source.data()["decision"] in {"proceed", "closed_negative"} and execution.status == "succeeded"
                and any(e["stage"] == "scientific_admission" and e["data"].get("admitted") is True for e in events))
    if source_path.read_bytes() != before:
        raise ContractError("source changed during eligibility verification")
    # An exclusive directory reserves this cell's sole replay attempt. Never overwrite evidence.
    replay_root = session.sidecar / "q27-replay"
    _no_links(session.sidecar)
    try: replay_root.mkdir()
    except FileExistsError as exc: raise ContractError("replay attempt already exists; preserve and inspect it") from exc
    replay_path = replay_root / "trace.jsonl"
    attempt = {"schema": "q27-replay-attempt-v2", "cell_key": list(cell.key), "scenario_digest": scenario.content_hash,
        "source_sha256": hashlib.sha256(before).hexdigest(), "source_trace_digest": source.data()["trace"]["trace_digest"],
        "source_decision": terminal.data()["decision"], "candidate_digest": candidate.content_hash,
        "allocation": _ALLOCATION, "eligible": eligible}
    _exclusive_record(replay_root / "attempt.json", FrozenRecord.from_dict(attempt))
    rejection = None; replay = None
    if eligible:
        _rechain(replay_path, _faulted_events(events, cell.variant))
        try: verify_protocol_trace(replay_path)
        except ContractError as exc: rejection = str(exc)
        replay_bytes = replay_path.read_bytes()
        replay = {"path": str(replay_path.relative_to(session.sidecar)), "sha256": hashlib.sha256(replay_bytes).hexdigest(),
                  "digest": FrozenRecord(replay_bytes.decode().splitlines()[-1]).content_hash}
    if source_path.read_bytes() != before:
        _exclusive_record(replay_root / "failure.json", FrozenRecord.from_dict({"reason": "source_changed", **attempt}))
        raise ContractError("controlled replay source changed")
    status = "refused" if rejection else "unexpected_acceptance" if eligible else "ineligible"
    finding = FrozenRecord.from_dict({**attempt, "schema": "q27-protocol-replay-finding-v2",
        "status": status, "inconclusive": not eligible, "source_structure_digest": source.content_hash,
        "fault": cell.variant, "replay": replay, "replay_refusal": rejection,
        "eligibility_reason": None if eligible else "source_has_no_qualifying_terminal_admission",
        "actual": {"docker_attempts": session._attempts, "audit_calls": len(audit_requests), "model_calls": session._next_call,
                   "audit_cost": audit_responses[0]["batch"]["cost"]},
        "limitation": "host-authenticated structural experiment; signatures and synthetic source checks do not establish scientific validity"})
    receipt = replay_authority.issue(finding)
    if replay_authority.verify(receipt) != finding:
        raise ContractError("replay authority did not preserve the finding")
    _exclusive_record(replay_root / "receipt.json", receipt)
    if status == "unexpected_acceptance":
        raise ContractError("eligible controlled replay unexpectedly accepted; signed failure retained")
    return receipt


def _exclusive_record(path: Path, value: FrozenRecord):
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(value.encoded + "\n")
        handle.flush(); os.fsync(handle.fileno())


def install_drivers(target: MutableMapping[str, Any], *, broker: DockerExecutionBroker,
                    audit_port: ProtocolAuditPort, expected_p0_control_digest: str):
    """Install only when the caller supplies all real runtime dependencies."""
    target["Q2.7"] = Q27ProtocolDriver(broker=broker, audit_port=audit_port,
        expected_p0_control_digest=expected_p0_control_digest)
    return target



def _no_links(path: Path):
    if not isinstance(path, Path): raise ContractError("artifact path must be a Path")
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ContractError("artifact ancestry must not contain links or junctions")


def verify_protocol_replay_receipt(receipt: FrozenRecord, *, cell, scenario: FrozenRecord,
                                  source_trace_path: Path, replay_authority: ProtocolReplayAuthority,
                                  expected_p0_control_digest: str) -> FrozenRecord:
    """Read-only replay validation. Only status=refused qualifies a successful cell.

    Ineligible and unexpected-acceptance findings are authenticated failures or
    incomplete experiments, never successful P0 fault checks.
    """
    if not isinstance(replay_authority, ProtocolReplayAuthority):
        raise ContractError("trusted replay authority is required")
    finding = replay_authority.verify(receipt); row = finding.data()
    required = {'schema', 'cell_key', 'scenario_digest', 'source_sha256', 'source_trace_digest',
        'source_decision', 'candidate_digest', 'allocation', 'eligible', 'status', 'inconclusive',
        'source_structure_digest', 'fault', 'replay', 'replay_refusal', 'eligibility_reason', 'actual', 'limitation'}
    if set(row) != required or row['schema'] != 'q27-protocol-replay-finding-v2':
        raise ContractError('closed replay finding schema required')
    _no_links(source_trace_path)
    if not source_trace_path.is_file(): raise ContractError('source trace is missing')
    before = source_trace_path.read_bytes()
    events = [FrozenRecord(line).data() for line in before.decode().splitlines()]
    source = verify_protocol_trace(source_trace_path)
    requests = [e['data']['request'] for e in events if e['stage']=='model_request']
    responses = [e['data']['response'] for e in events if e['stage']=='model_response']
    if not requests or not responses or events[-1]['stage'] != 'final_decision':
        raise ContractError('replay source is not a completed model-bound run')
    raw_task = requests[0]['task']
    task = PublicTask(DataIdentity.parse(raw_task['identity']), FrozenRecord.from_dict(raw_task['payload']))
    bundle, spec, grid_record = _material(task, scenario, variant=cell.variant)
    grid = grid_record.data(); lock = events[0]['data']; terminal = events[-1]['data']
    if (cell.coverage_id != 'Q2.7' or cell.arm_id != 'p0-fixed' or cell.scenario_digest != scenario.content_hash
            or task.identity != cell.identity or task.content_hash != cell.task_digest
            or grid['p0_control_digest'] != _digest(expected_p0_control_digest, 'trusted P0 control')
            or grid['runtime_arm'] != cell.runtime_arm.data() or lock['arm'] != cell.runtime_arm.data()
            or lock['package_digest'] != cell.package_digest
            or any(r['module_context'].get('panel_cell') != opaque_panel_cell_binding(cell)
                   or r['module_context'].get('p0_control_digest') != expected_p0_control_digest for r in requests)):
        raise ContractError('replay source, scenario or P0 control binding mismatch')
    expected_bindings = {'cell_key': list(cell.key), 'scenario_digest': scenario.content_hash,
        'source_sha256': hashlib.sha256(before).hexdigest(), 'source_trace_digest': source.data()['trace']['trace_digest'],
        'source_structure_digest': source.content_hash, 'source_decision': terminal['decision'],
        'candidate_digest': FrozenRecord.from_dict(responses[-1]).content_hash, 'fault': cell.variant, 'allocation': _ALLOCATION}
    if any(row[k] != v for k,v in expected_bindings.items()):
        raise ContractError('signed finding does not describe this actual source')
    executions = [e['data']['receipt'] for e in events if e['stage']=='execution_result']
    audits = [e['data'] for e in events if e['stage']=='q27_audit_request']
    audit_results = [e['data'] for e in events if e['stage']=='q27_audit_response']
    if len(executions)!=1 or len(audits)!=1 or len(audit_results)!=1:
        raise ContractError('source execution/audit allocation is incomplete')
    execution = ExecutionReceipt.parse(executions[0]); _check_execution(execution,task,spec)
    subject = protocol_audit_subject(task=task, objective=FrozenRecord.from_dict(lock['objective']), execution=execution,bundle=bundle)
    if audits[0]['subject'] != subject.data() or audit_results[0]['subject_digest'] != subject.content_hash:
        raise ContractError('source audit subject is not the actual frozen execution')
    actual = {'docker_attempts': terminal['execution_attempts'], 'model_calls': terminal['model_calls'],
              'audit_calls': len(audits), 'audit_cost': audit_results[0]['batch']['cost']}
    if row['actual'] != actual: raise ContractError('signed actual usage differs from source journal')
    eligible = (terminal['decision'] in {'proceed','closed_negative'} and execution.status=='succeeded'
                and any(e['stage']=='scientific_admission' and e['data'].get('admitted') is True for e in events))
    if type(row['eligible']) is not bool or row['eligible'] != eligible or row['inconclusive'] is not (not eligible):
        raise ContractError('replay eligibility does not match source admission')
    replay_root = source_trace_path.parent / 'q27-replay'; _no_links(replay_root)
    stored = replay_root / 'receipt.json'; attempt_path = replay_root / 'attempt.json'
    _no_links(stored); _no_links(attempt_path)
    if FrozenRecord(stored.read_text().strip()) != receipt:
        raise ContractError('stored immutable receipt differs from supplied receipt')
    attempt = FrozenRecord(attempt_path.read_text().strip()).data()
    expected_attempt = {k: row[k] for k in ('cell_key','scenario_digest','source_sha256','source_trace_digest','source_decision','candidate_digest','allocation','eligible')}
    expected_attempt['schema']='q27-replay-attempt-v2'
    if attempt != expected_attempt: raise ContractError('replay attempt manifest drift')
    path = replay_root / 'trace.jsonl'; _no_links(path)
    if not eligible:
        if (row['status']!='ineligible' or row['replay'] is not None or row['replay_refusal'] is not None
                or row['eligibility_reason']!='source_has_no_qualifying_terminal_admission' or path.exists()):
            raise ContractError('ineligible source must not claim a fault experiment')
    else:
        replay = row['replay']
        if (not isinstance(replay,dict) or set(replay)!={'path','sha256','digest'}
                or Path(replay['path']) != Path('q27-replay')/'trace.jsonl' or row['eligibility_reason'] is not None
                or not path.is_file() or path.samefile(source_trace_path)):
            raise ContractError('replay path is missing, foreign or aliases its source')
        replay_bytes = path.read_bytes()
        actual_events = [FrozenRecord(line).data() for line in replay_bytes.decode().splitlines()]
        expected_events = []; prior = None
        for i,event in enumerate(_faulted_events(events,cell.variant)):
            next_row={**event,'sequence':i,'previous':prior}; prior=FrozenRecord.from_dict(next_row).content_hash
            expected_events.append(next_row)
        if (actual_events != expected_events or replay['sha256'] != hashlib.sha256(replay_bytes).hexdigest()
                or replay['digest'] != prior):
            raise ContractError('replay is not the exact registered fault of this source')
        rejection = None
        try: verify_protocol_trace(path)
        except ContractError as exc: rejection=str(exc)
        expected_status='refused' if rejection else 'unexpected_acceptance'
        if row['status']!=expected_status or row['replay_refusal']!=rejection:
            raise ContractError('registered replay refusal is not reproducible')
    if source_trace_path.read_bytes()!=before:
        raise ContractError('source changed during read-only replay verification')
    return finding
