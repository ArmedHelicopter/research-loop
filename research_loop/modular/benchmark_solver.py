"""Train-only public-task solve path with a restricted execution boundary.

This module is deliberately narrower than scoring: it turns a prepared public
task, public data artifacts, and a frozen model schedule into an analysis
program plus a benchmark answer.  A Docker exit status is retained as execution
evidence only.  No score, audit admission, or scientific outcome is inferred
here.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from research_loop.modular.benchmarks.execution import ArtifactReceipt, DockerExecutionBroker, ExecutionReceipt
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask, required_text
from research_loop.modular.runtime import AuditVerifier, RunSession
from research_loop.modular.workflow import ModularWorkflow
from research_loop.ontology import ContractError


ModelPort = Callable[[FrozenRecord], FrozenRecord]
_ANALYSIS_SLOT = "analysis_program"
_FINAL_SLOT = "final_answer"
_MAX_PROGRAM_BYTES = 48_000
_MAX_TEXT_BYTES = 16_000


@dataclass(frozen=True)
class BenchmarkSolveResult:
    """Trace-bound result of one scheduled solve attempt, never a score."""

    session: RunSession
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
                        predecessor_context: FrozenRecord | None = None) -> BenchmarkSolveResult:
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
    if predecessor_context is not None and not isinstance(predecessor_context, FrozenRecord):
        raise ContractError("predecessor context must be immutable")
    artifacts = _public_artifacts(broker, task.identity, public_inputs)
    session = RunSession(task, package_digest=required_text(package_digest, "package digest"), arm=arm,
                         objective=objective, slots=(_ANALYSIS_SLOT, _FINAL_SLOT), execution_limit=1,
                         sidecar=sidecar, verifier=audit_verifier, required_audit=("measurement",))
    workflow = ModularWorkflow(session)
    common = {
        "solver": "public-benchmark-solve-v1",
        "public_artifacts": [artifact.record.data() for artifact in artifacts],
        "predecessor_context": predecessor_context.data() if predecessor_context else None,
    }
    analysis = workflow.invoke_model(
        _ANALYSIS_SLOT, model,
        instruction=("Write a Python analysis program for the supplied public task and only the named /input files. "
                     "Return a JSON object with exactly analysis and program. The program must print concise, "
                     "task-relevant observations to stdout. It cannot determine scientific validity or a score."),
        module_context=FrozenRecord.from_dict(common),
    )
    try:
        program = _program_from(analysis)
    except ContractError as exc:
        session.driver_failure(driver_id="benchmark_solver", response=analysis, error_type=type(exc).__name__)
        return BenchmarkSolveResult(session, artifacts, analysis, None, None, None, "analysis_rejected")
    execution = session.execute(program, broker=broker, image=image, inputs=public_inputs,
                                timeout_seconds=timeout_seconds)
    if execution.status in {"unavailable", "rejected"}:
        # RunSession is terminal for infrastructure/untrusted-mount failures;
        # preserve the attempt as a denominator row without inventing an answer.
        return BenchmarkSolveResult(session, artifacts, analysis, execution, None, None,
                                    "execution_" + execution.status)
    if not _execution_inputs_match(artifacts, execution):
        session.controller_failure(driver_id="benchmark_solver", error_type="InputArtifactDrift")
        return BenchmarkSolveResult(session, artifacts, analysis, execution, None, None, "input_artifact_drift")
    final_context = {
        **common,
        "analysis_digest": analysis.content_hash,
        "execution_digest": execution.content_hash,
        "execution_status": execution.status,
        "execution_input_artifacts": execution.record.data()["input_artifacts"],
    }
    answer = workflow.invoke_model(
        _FINAL_SLOT, model,
        instruction=("Give the benchmark answer using only the public task, prior immutable context, and the "
                     "recorded execution feedback. Return exactly answer and rationale. Treat a failed or timed "
                     "out execution as unresolved; do not claim scientific validation or programme completion."),
        module_context=FrozenRecord.from_dict(final_context),
    )
    try:
        answer_text = _answer_from(answer)
    except ContractError as exc:
        session.driver_failure(driver_id="benchmark_solver", response=answer, error_type=type(exc).__name__)
        return BenchmarkSolveResult(session, artifacts, analysis, execution, answer, None, "answer_rejected")
    candidate = FrozenRecord.from_dict({
        "objective_digest": objective.content_hash,
        "outcome": "unknown",
        "evidence_ids": [],
        "conclusion": answer_text,
        "programme_complete": False,
    })
    decision = session.finish(candidate)
    return BenchmarkSolveResult(session, artifacts, analysis, execution, answer, decision,
                                "execution_" + execution.status)


def _public_artifacts(broker: DockerExecutionBroker, identity: DataIdentity,
                      public_inputs: Mapping[str, Path]) -> tuple[ArtifactReceipt, ...]:
    if not isinstance(public_inputs, Mapping) or not public_inputs:
        raise ContractError("benchmark solve needs named public input artifacts")
    return broker.validate_inputs(identity, public_inputs)


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


def _answer_from(response: FrozenRecord) -> str:
    body = response.data()
    if set(body) != {"answer", "rationale"}:
        raise ContractError("final answer response must contain exactly answer and rationale")
    answer, rationale = body["answer"], body["rationale"]
    if not isinstance(answer, str) or not answer.strip() or len(answer.encode("utf-8")) > _MAX_TEXT_BYTES:
        raise ContractError("benchmark answer must be bounded nonempty text")
    if not isinstance(rationale, str) or not rationale.strip() or len(rationale.encode("utf-8")) > _MAX_TEXT_BYTES:
        raise ContractError("benchmark rationale must be bounded nonempty text")
    return answer


def _execution_inputs_match(artifacts: tuple[ArtifactReceipt, ...], execution: ExecutionReceipt) -> bool:
    actual = execution.record.data().get("input_artifacts")
    expected = {artifact.artifact_id: artifact.record.data() for artifact in artifacts}
    return actual == expected
