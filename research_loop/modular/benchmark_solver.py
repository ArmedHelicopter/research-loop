"""Train-only public-task solve path with a restricted execution boundary.

This module is deliberately narrower than scoring: it turns a prepared public
task, public data artifacts, and a frozen model schedule into an analysis
program plus a benchmark answer.  A Docker exit status is retained as execution
evidence only.  No score, audit admission, or scientific outcome is inferred
here.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Callable, Mapping

from research_loop.modular.benchmarks.execution import ArtifactReceipt, DockerExecutionBroker, ExecutionReceipt
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask, required_text
from research_loop.modular.runtime import AuditVerifier, RunSession
from research_loop.modular.protocol_trace import verify_protocol_trace as verify_common_protocol_trace
from research_loop.modular.workflow import ModularWorkflow
from research_loop.ontology import ContractError


ModelPort = Callable[[FrozenRecord], FrozenRecord]
_ANALYSIS_SLOT = "analysis_program"
_FINAL_SLOT = "final_answer"
_MAX_PROGRAM_BYTES = 48_000
_MAX_TEXT_BYTES = 16_000


@dataclass(frozen=True)
class CompletedSolverSession:
    """Read-only journal view; construction cannot resume or write a run."""

    task: PublicTask
    lock: FrozenRecord
    objective: FrozenRecord
    sidecar: Path


@dataclass(frozen=True)
class BenchmarkSolveResult:
    """Trace-bound result of one scheduled solve attempt, never a score."""

    session: RunSession | CompletedSolverSession
    artifacts: tuple[ArtifactReceipt, ...]
    analysis: FrozenRecord | None
    execution: ExecutionReceipt | None
    answer: FrozenRecord | None
    decision: FrozenRecord | None
    status: str

    @property
    def record(self) -> FrozenRecord:
        return FrozenRecord.from_dict({
            "schema": "benchmark-solve-result-v1",
            "identity": self.session.task.identity.data(),
            "objective_digest": self.session.objective.content_hash,
            "lock_digest": self.session.lock.content_hash,
            "status": self.status,
            "artifact_digests": [artifact.content_hash for artifact in self.artifacts],
            "analysis_digest": self.analysis.content_hash if self.analysis else None,
            "execution_digest": self.execution.content_hash if self.execution else None,
            "execution_status": self.execution.status if self.execution else None,
            "answer_digest": self.answer.content_hash if self.answer else None,
            "decision": self.decision.data() if self.decision else None,
            "scientific_effect": "not_measured",
        })


def run_benchmark_solve(*, task: PublicTask, public_inputs: Mapping[str, Path], image: str,
                        package_digest: str, arm: FrozenRecord, objective: FrozenRecord,
                        sidecar: Path, broker: DockerExecutionBroker, model: ModelPort,
                        audit_verifier: AuditVerifier, timeout_seconds: int = 20,
                        predecessor_context: FrozenRecord | None = None,
                        panel_cell_binding: FrozenRecord | None = None,
                        mechanism_provenance: FrozenRecord | None = None) -> BenchmarkSolveResult:
    """Run analysis-program -> Docker -> final benchmark-answer on one train task.

    ``predecessor_context`` is an immutable Q-specific mechanism receipt or
    output.  It is visible to both calls, which lets a Q3.1/Q4.3 driver affect
    the shared answer path without granting it scoring or host authority.
    """
    if not isinstance(task, PublicTask) or task.identity.domain != "train":
        raise ContractError("benchmark solve accepts prepared train PublicTask only")
    if not isinstance(broker, DockerExecutionBroker) or not callable(model):
        raise ContractError("benchmark solve needs a restricted broker and model port")
    if not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 120:
        raise ContractError("benchmark solve timeout must be between 1 and 120 seconds")
    if any(value is not None and not isinstance(value, FrozenRecord)
           for value in (predecessor_context, panel_cell_binding, mechanism_provenance)):
        raise ContractError("solver context must be immutable")
    if (panel_cell_binding is None) != (mechanism_provenance is None):
        raise ContractError("linked solver requires both panel binding and mechanism provenance")
    session = RunSession(task, package_digest=required_text(package_digest, "package digest"), arm=arm,
                         objective=objective, slots=(_ANALYSIS_SLOT, _FINAL_SLOT), execution_limit=1,
                         sidecar=sidecar, verifier=audit_verifier, required_audit=("measurement",))
    try:
        artifacts = _public_artifacts(broker, task.identity, public_inputs)
    except Exception as exc:
        session.controller_failure(driver_id="benchmark_solver", error_type=type(exc).__name__)
        return BenchmarkSolveResult(session, (), None, None, None, None, "input_preflight_failed")
    workflow = ModularWorkflow(session)
    common = {
        "solver": "public-benchmark-solve-v1",
        "public_artifacts": _model_public_artifacts(artifacts),
        "predecessor_context": predecessor_context.data() if predecessor_context else None,
        "panel_cell": panel_cell_binding.data() if panel_cell_binding else None,
        "mechanism_provenance": mechanism_provenance.data() if mechanism_provenance else None,
    }
    try:
        analysis = workflow.invoke_model(
            _ANALYSIS_SLOT, model,
            instruction=("Write a Python analysis program for the supplied public task and only the named /input files. "
                         "Return a JSON object with exactly analysis and program. The program must print concise, "
                         "task-relevant observations to stdout. It cannot determine scientific validity or a score."),
            module_context=FrozenRecord.from_dict(common),
        )
    except Exception as exc:
        if not session._terminal:
            session.controller_failure(driver_id="benchmark_solver", error_type=type(exc).__name__)
        return BenchmarkSolveResult(session, artifacts, None, None, None, None, "analysis_model_failed")
    try:
        program = _program_from(analysis)
    except ContractError as exc:
        session.driver_failure(driver_id="benchmark_solver", response=analysis, error_type=type(exc).__name__)
        return BenchmarkSolveResult(session, artifacts, analysis, None, None, None, "analysis_rejected")
    try:
        execution = session.execute(program, broker=broker, image=image, inputs=public_inputs,
                                    timeout_seconds=timeout_seconds)
    except Exception as exc:
        if not session._terminal:
            session.controller_failure(driver_id="benchmark_solver", error_type=type(exc).__name__)
        return BenchmarkSolveResult(session, artifacts, analysis, None, None, None, "execution_setup_failed")
    if execution.status in {"unavailable", "rejected"}:
        # RunSession is terminal for infrastructure/untrusted-mount failures;
        # preserve the attempt as a denominator row without inventing an answer.
        return BenchmarkSolveResult(session, artifacts, analysis, execution, None, None,
                                    "execution_" + execution.status)
    if not _execution_inputs_match(artifacts, execution):
        session.controller_failure(driver_id="benchmark_solver", error_type="InputArtifactDrift")
        return BenchmarkSolveResult(session, artifacts, analysis, execution, None, None, "input_artifact_drift")
    # ``RunSession`` owns the program file. Hash its exact bytes (including
    # platform newline encoding), then require the broker's receipt to bind it.
    program_sha256 = hashlib.sha256((sidecar / "analysis-1.py").read_bytes()).hexdigest()
    if execution.artifact is None or execution.artifact.sha256 != program_sha256:
        session.controller_failure(driver_id="benchmark_solver", error_type="ExecutionProgramDrift")
        return BenchmarkSolveResult(session, artifacts, analysis, execution, None, None, "execution_program_drift")
    execution_feedback = [{"execution_digest": execution.content_hash, "status": execution.status,
                           "stdout": execution.record.data().get("stdout", ""),
                           "stderr": execution.record.data().get("stderr", ""),
                           "program_sha256": execution.artifact.sha256}]
    final_context = {
        **common,
        "analysis": analysis.data(),
        "analysis_digest": analysis.content_hash,
        "analysis_program_sha256": program_sha256,
        "execution_digest": execution.content_hash,
        "execution_status": execution.status,
        "execution_input_artifacts": execution.record.data()["input_artifacts"],
        "execution_feedback": execution_feedback,
        "required_objective_digest": objective.content_hash,
    }
    try:
        answer = workflow.invoke_model(
            _FINAL_SLOT, model,
            instruction=("Give the benchmark answer using only the public task, prior immutable context, and the "
                         "recorded execution feedback. Return exactly objective_digest, outcome, evidence_ids, "
                         "conclusion, and programme_complete. Copy module_context.required_objective_digest exactly "
                         "into objective_digest. Set outcome to unknown, "
                         "evidence_ids to [], programme_complete to false, and put the actual answer in conclusion. "
                         "A failed or timed out execution remains unresolved and is never scientific validation."),
            module_context=FrozenRecord.from_dict(final_context),
        )
    except Exception as exc:
        if not session._terminal:
            session.controller_failure(driver_id="benchmark_solver", error_type=type(exc).__name__)
        return BenchmarkSolveResult(session, artifacts, analysis, execution, None, None, "answer_model_failed")
    try:
        _candidate_from(answer, objective)
    except ContractError as exc:
        session.driver_failure(driver_id="benchmark_solver", response=answer, error_type=type(exc).__name__)
        return BenchmarkSolveResult(session, artifacts, analysis, execution, answer, None, "answer_rejected")
    decision = session.finish(answer)
    return BenchmarkSolveResult(session, artifacts, analysis, execution, answer, decision,
                                 "execution_" + execution.status)


def run_benchmark_solve_in_session(*, session: RunSession, workflow: ModularWorkflow,
                                   public_inputs: Mapping[str, Path], image: str,
                                   broker: DockerExecutionBroker, model: ModelPort,
                                   analysis_slot: str, final_slot: str,
                                   joint_mechanism: FrozenRecord,
                                   panel_cell_binding: FrozenRecord,
                                   driver_id: str = "combination_benchmark_solver",
                                   timeout_seconds: int = 20) -> BenchmarkSolveResult:
    """Run the public solve as the final two slots of an existing session.

    Combination drivers use this narrow seam so their actual module state and
    the benchmark solve share one immutable run lock and trace.  It is not a
    generic resume API and never creates a second ``RunSession``.
    """
    if (not isinstance(session, RunSession) or not isinstance(workflow, ModularWorkflow)
            or workflow.session is not session or not isinstance(joint_mechanism, FrozenRecord)
            or not isinstance(panel_cell_binding, FrozenRecord) or not isinstance(driver_id, str) or not driver_id):
        raise ContractError("in-session solve requires its active workflow and frozen bindings")
    if (not isinstance(broker, DockerExecutionBroker) or not callable(model)
            or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 120):
        raise ContractError("in-session solve needs a restricted broker, model, and bounded timeout")
    if session._terminal or session.slots[session._next_call:] != (analysis_slot, final_slot):
        raise ContractError("in-session solve must own the remaining two frozen slots")
    if session.execution_limit != session._attempts + 1:
        raise ContractError("in-session solve requires exactly one remaining execution")
    try:
        artifacts = _public_artifacts(broker, session.task.identity, public_inputs)
    except Exception as exc:
        session.controller_failure(driver_id=driver_id, error_type=type(exc).__name__)
        return BenchmarkSolveResult(session, (), None, None, None, None, "input_preflight_failed")
    common = {
        "solver": "public-benchmark-solve-v1",
        "public_artifacts": _model_public_artifacts(artifacts),
        "panel_cell": panel_cell_binding.data(),
        "joint_mechanism": joint_mechanism.data(),
        "joint_mechanism_digest": joint_mechanism.content_hash,
    }
    try:
        analysis = workflow.invoke_model(analysis_slot, model, instruction=(
            "Write a Python analysis program for the supplied public task and only the named /input files. "
            "Use the supplied joint mechanism context only as train-only reasoning context. "
            "Return exactly analysis and program; the program must print concise task-relevant observations."),
            module_context=FrozenRecord.from_dict(common))
    except Exception as exc:
        if not session._terminal:
            session.controller_failure(driver_id=driver_id, error_type=type(exc).__name__)
        return BenchmarkSolveResult(session, artifacts, None, None, None, None, "analysis_model_failed")
    try:
        program = _program_from(analysis)
    except ContractError as exc:
        session.driver_failure(driver_id=driver_id, response=analysis, error_type=type(exc).__name__)
        return BenchmarkSolveResult(session, artifacts, analysis, None, None, None, "analysis_rejected")
    try:
        execution = session.execute(program, broker=broker, image=image, inputs=public_inputs,
                                    timeout_seconds=timeout_seconds)
    except Exception as exc:
        if not session._terminal:
            session.controller_failure(driver_id=driver_id, error_type=type(exc).__name__)
        return BenchmarkSolveResult(session, artifacts, analysis, None, None, None, "execution_setup_failed")
    if execution.status in {"unavailable", "rejected"}:
        return BenchmarkSolveResult(session, artifacts, analysis, execution, None, None,
                                    "execution_" + execution.status)
    if not _execution_inputs_match(artifacts, execution):
        session.controller_failure(driver_id=driver_id, error_type="InputArtifactDrift")
        return BenchmarkSolveResult(session, artifacts, analysis, execution, None, None, "input_artifact_drift")
    program_sha256 = hashlib.sha256((session.sidecar / f"analysis-{session._attempts}.py").read_bytes()).hexdigest()
    if execution.artifact is None or execution.artifact.sha256 != program_sha256:
        session.controller_failure(driver_id=driver_id, error_type="ExecutionProgramDrift")
        return BenchmarkSolveResult(session, artifacts, analysis, execution, None, None, "execution_program_drift")
    final_context = {**common, "analysis": analysis.data(), "analysis_digest": analysis.content_hash,
        "analysis_program_sha256": program_sha256, "execution_digest": execution.content_hash,
        "execution_status": execution.status, "execution_input_artifacts": execution.record.data()["input_artifacts"],
        "execution_feedback": [{"execution_digest": execution.content_hash, "status": execution.status,
            "stdout": execution.record.data().get("stdout", ""), "stderr": execution.record.data().get("stderr", ""),
            "program_sha256": execution.artifact.sha256}],
        "required_objective_digest": session.objective.content_hash}
    try:
        answer = workflow.invoke_model(final_slot, model, instruction=(
            "Give the benchmark answer using only the public task, joint mechanism context, and recorded execution feedback. "
            "Return exactly objective_digest, outcome, evidence_ids, conclusion, and programme_complete. "
            "Copy module_context.required_objective_digest; set outcome to unknown, evidence_ids to [], and programme_complete to false."),
            module_context=FrozenRecord.from_dict(final_context))
    except Exception as exc:
        if not session._terminal:
            session.controller_failure(driver_id=driver_id, error_type=type(exc).__name__)
        return BenchmarkSolveResult(session, artifacts, analysis, execution, None, None, "answer_model_failed")
    try:
        _candidate_from(answer, session.objective)
    except ContractError as exc:
        session.driver_failure(driver_id=driver_id, response=answer, error_type=type(exc).__name__)
        return BenchmarkSolveResult(session, artifacts, analysis, execution, answer, None, "answer_rejected")
    decision = session.finish(answer)
    return BenchmarkSolveResult(session, artifacts, analysis, execution, answer, decision,
                                "execution_" + execution.status)


def _public_artifacts(broker: DockerExecutionBroker, identity: DataIdentity,
                      public_inputs: Mapping[str, Path]) -> tuple[ArtifactReceipt, ...]:
    if not isinstance(public_inputs, Mapping) or not public_inputs:
        raise ContractError("benchmark solve needs named public input artifacts")
    return broker.validate_inputs(identity, public_inputs)


def _model_public_artifacts(artifacts: tuple[ArtifactReceipt, ...]) -> list[dict[str, object]]:
    """Expose the broker's exact read-only container paths to the solver."""
    return [{"artifact": artifact.record.data(), "container_path": "/input/" + artifact.artifact_id}
            for artifact in artifacts]


def _program_from(response: FrozenRecord) -> str:
    body = response.data()
    if set(body) != {"analysis", "program"}:
        raise ContractError("analysis response must contain exactly analysis and program")
    analysis, program = body["analysis"], body["program"]
    if not isinstance(analysis, str) or not analysis.strip() or len(analysis.encode("utf-8")) > _MAX_TEXT_BYTES:
        raise ContractError("analysis must be bounded nonempty text")
    if not isinstance(program, str) or not program.strip() or len(program.encode("utf-8")) > _MAX_PROGRAM_BYTES:
        raise ContractError("program must be bounded nonempty text")
    return program


def _candidate_from(response: FrozenRecord, objective: FrozenRecord) -> None:
    body = response.data()
    if set(body) != {"objective_digest", "outcome", "evidence_ids", "conclusion", "programme_complete"}:
        raise ContractError("final answer response must use the exact candidate protocol")
    if body["objective_digest"] != objective.content_hash or body["outcome"] != "unknown" or body["evidence_ids"] != [] or body["programme_complete"] is not False:
        raise ContractError("final answer candidate drifts from the train-only protocol")
    if not isinstance(body["conclusion"], str) or not body["conclusion"].strip() or len(body["conclusion"].encode("utf-8")) > _MAX_TEXT_BYTES:
        raise ContractError("benchmark conclusion must be bounded nonempty text")


def _execution_inputs_match(artifacts: tuple[ArtifactReceipt, ...], execution: ExecutionReceipt) -> bool:
    actual = execution.record.data().get("input_artifacts")
    expected = {artifact.artifact_id: artifact.record.data() for artifact in artifacts}
    return actual == expected


def verify_benchmark_solve_trace(path: Path, task: PublicTask) -> FrozenRecord:
    """Add solver-specific task binding on top of common protocol replay."""
    if not isinstance(task, PublicTask):
        raise ContractError("protocol trace needs the prepared source task")
    base = verify_common_protocol_trace(path)
    events = [FrozenRecord(line).data() for line in path.read_text(encoding="utf-8").splitlines()]
    lock = events[0]["data"]
    if lock.get("task_digest") != task.content_hash or lock.get("identity") != task.identity.data():
        raise ContractError("protocol trace source task binding drifted")
    stages = [event["stage"] for event in events]
    terminal = stages[-1]
    if terminal == "final_decision":
        expected = ["objective_lock", "model_request", "model_response", "execution_request", "execution_result", "model_request", "model_response", "final_decision"]
        if stages != expected:
            raise ContractError("successful solve protocol has an unexpected stage schedule")
        final_response = FrozenRecord.from_dict(events[-2]["data"]["response"])
        terminal_data = events[-1]["data"]
        if terminal_data.get("candidate_digest") != final_response.content_hash or terminal_data.get("identity") != task.identity.data():
            raise ContractError("terminal decision does not bind the final model candidate")
    return FrozenRecord.from_dict({"schema": "benchmark-solve-protocol-trace-v1", "task_digest": task.content_hash,
        "identity": task.identity.data(), "trace_digest": base.data()["trace"]["trace_digest"], "terminal": terminal,
        "stages": stages})
