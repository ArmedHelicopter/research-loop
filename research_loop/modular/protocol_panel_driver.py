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
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping, Sequence

from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask, required_text, strict_bool
from research_loop.modular.experiments import registry
from research_loop.modular.modules.improvement import TrainingManifest
from research_loop.modular.p0_panel import validate_fixed_control_design
from research_loop.modular.panel_receipts import opaque_panel_cell_binding
from research_loop.modular.protocol_trace import verify_protocol_trace
from research_loop.ontology import ContractError, canonical


_VARIANTS = ("missing_lock", "missing_execution", "missing_audit", "illegal_state")
_HEX = frozenset("0123456789abcdef")
ProtocolAuditPort = Callable[[FrozenRecord], Sequence[FrozenRecord]]


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
    if set(body) != required and set(body) != required | {"program_sha256"}:
        raise ContractError("caller public execution fields are incomplete")
    program = required_text(body["program"], "caller program")
    program_sha = hashlib.sha256(program.encode("utf-8")).hexdigest()
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
    return {"program": program, "program_sha256": program_sha,
            "csv_bytes_hex": csv_hex, "csv_sha256": csv_sha, "image": _image(body["image"]),
            "timeout_seconds": timeout}


def _p0_grid(value: Any) -> FrozenRecord:
    record = value if isinstance(value, FrozenRecord) else FrozenRecord.from_dict(dict(_mapping(value, "P0 fixed-control grid")))
    return validate_fixed_control_design(record)


def freeze_protocol_bundle(task: PublicTask, *, execution: Mapping[str, Any],
                           p0_fixed_control: FrozenRecord) -> FrozenRecord:
    """Freeze source-bound public execution material before any runtime call."""
    if not isinstance(task, PublicTask):
        raise ContractError("protocol bundle requires a public task")
    return FrozenRecord.from_dict({
        "schema": "q27-protocol-panel-bundle-v1", "identity": task.identity.data(),
        "payload_digest": task.payload.content_hash, "p0_fixed_control": _p0_grid(p0_fixed_control).data(),
        "execution": _execution(execution),
    })


def protocol_panel_injection(variant: str, *, task: FrozenRecord, evidence: FrozenRecord,
                             p0_fixed_control: FrozenRecord) -> Mapping[str, Any]:
    """Project one canonical caller bundle into the standard scenario body."""
    if variant not in _VARIANTS:
        raise ContractError("protocol panel variant is not registered")
    public = PublicTask(DataIdentity.parse(task.data()["identity"]), FrozenRecord.from_dict(task.data()["payload"]))
    body = evidence.data()
    if body.get("schema") != "q27-protocol-panel-bundle-v1":
        raise ContractError("protocol panel requires typed caller execution material")
    bundle = FrozenRecord.from_dict(body)
    remade = freeze_protocol_bundle(public, execution=body.get("execution", {}),
                                    p0_fixed_control=FrozenRecord.from_dict(_mapping(body.get("p0_fixed_control"), "P0 grid")))
    if remade.content_hash != bundle.content_hash:
        raise ContractError("protocol caller bundle is not a canonical closed reconstruction")
    actual = _p0_grid(p0_fixed_control)
    if actual.content_hash != _p0_grid(body["p0_fixed_control"]).content_hash:
        raise ContractError("protocol caller bundle P0 control differs from the actual fixed-control grid")
    return {"schema": "q27-protocol-controller-v1", "bundle": bundle.data(),
            "p0_fixed_control": actual.data()}


def protocol_audit_subject(*, task: PublicTask, objective: FrozenRecord,
                           execution_digest: str, execution_status: str) -> FrozenRecord:
    """The exact runtime subject supplied to the caller-owned audit port."""
    if execution_status not in {"succeeded", "failed", "timed_out", "unavailable", "rejected"}:
        raise ContractError("protocol audit subject has an invalid execution status")
    return FrozenRecord.from_dict({"schema": "q27-runtime-audit-subject-v1", "identity": task.identity.data(),
        "task_digest": task.content_hash, "objective_digest": objective.content_hash,
        "execution_digest": _digest(execution_digest, "execution digest"), "execution_status": execution_status,
        "required_audit": ["measurement"]})


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
    if set(controller) != {"schema", "bundle", "p0_fixed_control"} or controller.get("schema") != "q27-protocol-controller-v1":
        raise ContractError("typed protocol panel material is required")
    bundle = FrozenRecord.from_dict(dict(_mapping(controller["bundle"], "protocol bundle")))
    source = bundle.data()
    remade = freeze_protocol_bundle(task, execution=source.get("execution", {}),
                                    p0_fixed_control=FrozenRecord.from_dict(_mapping(source.get("p0_fixed_control"), "P0 grid")))
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
        _bundle, execution_spec, p0_grid = _material(workflow.session.task, scenario, variant=cell.variant)
        p0_digest = _verify_binding(workflow, cell=cell, scenario=scenario, package=package, p0_grid=p0_grid,
                                    expected_p0_control_digest=self.expected_p0_control_digest)
        csv_path = workflow.session.sidecar / "q27-public.csv"
        csv_bytes = bytes.fromhex(execution_spec["csv_bytes_hex"])
        csv_path.write_bytes(csv_bytes)
        if hashlib.sha256(csv_path.read_bytes()).hexdigest() != execution_spec["csv_sha256"]:
            raise ContractError("written public CSV does not retain its caller digest")
        execution = workflow.session.execute(execution_spec["program"], broker=self.broker, image=execution_spec["image"],
            inputs={"public_csv": csv_path}, timeout_seconds=execution_spec["timeout_seconds"])
        subject = protocol_audit_subject(task=workflow.session.task, objective=workflow.session.objective,
            execution_digest=execution.content_hash, execution_status=execution.status)
        receipts = list(self.audit_port(subject))
        if len(receipts) != 2 or any(not isinstance(receipt, FrozenRecord) for receipt in receipts):
            raise ContractError("protocol audit port must return two frozen authority receipts")
        admission = workflow.session.admit(execution.content_hash, receipts)
        trace = workflow._trace("protocol_source_execution", "executed", p0_control_digest=p0_digest,
            execution_digest=execution.content_hash, execution_status=execution.status,
            audit_subject_digest=subject.content_hash, audit_receipt_digests=[row.content_hash for row in receipts],
            admission_digest=admission.content_hash, budget={"docker": 1, "audit_receipts": 2, "model": 1},
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
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
                        terminal: FrozenRecord, replay_authority: ProtocolReplayAuthority) -> FrozenRecord:
    """Verify an offline controlled omission after the real source terminal.

    An unexpected replay acceptance is a hard failure.  The returned signed
    receipt is intended for a runner hook to bind into its call plan and to
    fail the cell closed if absent, malformed, or not refused.
    """
    if not isinstance(replay_authority, ProtocolReplayAuthority) or not isinstance(candidate, FrozenRecord) or not isinstance(terminal, FrozenRecord):
        raise ContractError("protocol replay needs a caller-owned authority and frozen terminal inputs")
    _bundle, _execution_spec, p0_grid = _material(session.task, scenario, variant=cell.variant)
    grid = validate_fixed_control_design(p0_grid).data()
    if (cell.coverage_id != "Q2.7" or cell.variant not in _VARIANTS or cell.arm_id != "p0-fixed"
            or session.task.identity != cell.identity or session.task.content_hash != cell.task_digest
            or session.arm != cell.runtime_arm or grid["runtime_arm"] != cell.runtime_arm.data()
            or session.lock.data().get("package_digest") != cell.package_digest
            or session.lock.data().get("arm") != cell.runtime_arm.data()
            or tuple(session.slots) != ("final",)):
        raise ContractError("protocol replay source session does not bind its P0 cell")
    source_path = session.sidecar / "trace.jsonl"
    before = source_path.read_bytes()
    source = verify_protocol_trace(source_path)
    if terminal.data().get("candidate_digest") != candidate.content_hash or terminal.data().get("lock_digest") != session.lock.content_hash:
        raise ContractError("protocol replay terminal does not bind the source candidate and lock")
    events = [FrozenRecord(line).data() for line in before.decode("utf-8").splitlines()]
    replay_path = session.sidecar / f"q27-{cell.variant}-replay.jsonl"
    _rechain(replay_path, _faulted_events(events, cell.variant))
    try:
        verify_protocol_trace(replay_path)
    except ContractError as exc:
        rejection = str(exc)
    else:
        raise ContractError("controlled protocol replay was unexpectedly accepted")
    if source_path.read_bytes() != before:
        raise ContractError("controlled protocol replay modified the source journal")
    replay_trace = FrozenRecord.from_dict({"path": replay_path.name,
        "digest": FrozenRecord(replay_path.read_text(encoding="utf-8").splitlines()[-1]).content_hash})
    finding = FrozenRecord.from_dict({"schema": "q27-protocol-replay-finding-v1", "cell_key": list(cell.key),
        "scenario_digest": scenario.content_hash, "source_trace_digest": source.data()["trace"]["trace_digest"],
        "source_decision": terminal.data()["decision"], "source_structure_digest": source.content_hash,
        "candidate_digest": candidate.content_hash, "fault": cell.variant, "replay": replay_trace.data(),
        "replay_refusal": rejection, "budget": {"docker": 1, "audit_receipts": 2, "model": 1},
        "limitation": "structural replay and configured receipt origin are engineering evidence, not scientific validation"})
    receipt = replay_authority.issue(finding)
    if replay_authority.verify(receipt) != finding:
        raise ContractError("replay authority did not preserve the verified finding")
    return receipt


def install_drivers(target: MutableMapping[str, Any], *, broker: DockerExecutionBroker,
                    audit_port: ProtocolAuditPort, expected_p0_control_digest: str):
    """Install only when the caller supplies all real runtime dependencies."""
    target["Q2.7"] = Q27ProtocolDriver(broker=broker, audit_port=audit_port,
        expected_p0_control_digest=expected_p0_control_digest)
    return target
