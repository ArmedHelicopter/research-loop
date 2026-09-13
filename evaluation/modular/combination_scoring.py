"""Signed adapted scoring for one replay-verified M4+M5 combination cell.

This reuses the existing frozen single-candidate rubric transport.  It does not
read references, expose joint controller material to the scorer, or make a
scientific or calibration claim.
"""
from __future__ import annotations

import hashlib
import hmac
import math
from typing import Any, Mapping

from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from evaluation.modular.scoring_service import FrozenRubricTransport, ScorerConfig
from research_loop.modular.benchmarks.scoring import blade_adapted_score, discovery_adapted_score
from research_loop.modular.combination_benchmark_driver import (CombinationBenchmarkCellResult,
    verify_m4_m5_combination_benchmark_cell)
from research_loop.modular.combination_panels import CombinationPanel
from research_loop.modular.contracts import FrozenRecord, PublicTask, required_text
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.panel_receipts import PanelCell, ScientificScorerReceipt
from research_loop.ontology import ContractError, canonical

_DIMENSIONS = {"discoverybench": ("context", "variable_f1", "relation"), "blade": ("cvars", "transform", "model")}
_METRICS = {"discoverybench": "discovery_adapted_score", "blade": "blade_adapted_score"}


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ContractError(f"{field} must be a digest")
    return value


def _signed_body(receipt: FrozenRecord, keys: Mapping[str, bytes], *, message: str) -> dict[str, Any]:
    envelope = receipt.data()
    if set(envelope) != {"body", "mac"} or not isinstance(envelope["body"], dict):
        raise ContractError(f"{message} envelope is malformed")
    body, authority = envelope["body"], envelope["body"].get("authority")
    key = keys.get(authority) if isinstance(keys, Mapping) else None
    if not isinstance(key, bytes) or not hmac.compare_digest(envelope["mac"], hmac.new(key, canonical(body).encode(), hashlib.sha256).hexdigest()):
        raise ContractError(f"{message} signature is untrusted")
    return body


def _panel_cell_digest(cell: PanelCell) -> str:
    return hashlib.sha256(canonical({"cell_key": list(cell.key), "scenario_digest": cell.scenario_digest,
        "package_digest": cell.package_digest, "arm": cell.runtime_arm.data()}).encode()).hexdigest()


def _candidate(result: CombinationBenchmarkCellResult) -> tuple[dict[str, Any], dict[str, Any]]:
    solver = result.solver
    if result.runtime.status != "succeeded" or solver is None or solver.status != "execution_succeeded":
        raise ContractError("only a successful combination execution may be scored")
    if solver.analysis is None or solver.answer is None or solver.execution is None or solver.execution.artifact is None:
        raise ContractError("combination execution lacks candidate or artifact")
    analysis, answer, execution = solver.analysis.data(), solver.answer.data(), solver.execution
    if set(analysis) != {"analysis", "program"} or any(not isinstance(analysis[key], str) or not analysis[key] for key in analysis):
        raise ContractError("combination solver analysis is not bounded")
    program = solver.session.sidecar / "analysis-1.py"
    if not program.is_file() or program.read_text(encoding="utf-8") != analysis["program"]:
        raise ContractError("combination program does not match solver journal")
    program_digest = hashlib.sha256(program.read_bytes()).hexdigest()
    if program_digest != execution.artifact.sha256:
        raise ContractError("combination program was not the executed artifact")
    answer_data = answer
    if not isinstance(answer_data.get("conclusion"), str) or not answer_data["conclusion"].strip():
        raise ContractError("combination answer lacks conclusion")
    feedback = {key: execution.record.data().get(key, "") for key in ("status", "exit_code", "stdout", "stderr")}
    candidate = {"analysis": analysis["analysis"], "program": analysis["program"],
                 "answer": answer_data["conclusion"], "execution_feedback": feedback}
    return candidate, {"solver_trace_digest": FrozenRecord((solver.session.sidecar / "trace.jsonl").read_text(encoding="utf-8").splitlines()[-1]).content_hash,
                       "analysis_digest": solver.analysis.content_hash, "answer_digest": solver.answer.content_hash,
                       "execution_digest": execution.content_hash, "executed_program_sha256": program_digest}


def derive_combination_score_input(*, panel: CombinationPanel, result: CombinationBenchmarkCellResult,
                                   task: PublicTask, scenario: FrozenRecord, package: CandidatePackage) -> FrozenRecord:
    """Rebuild the only evaluator candidate after complete shared-session replay."""
    if not isinstance(panel, CombinationPanel) or panel.domain != "train" or result.cell not in panel.cells:
        raise ContractError("combination score input requires a frozen train panel cell")
    verification = verify_m4_m5_combination_benchmark_cell(result, panel=panel, task=task, scenario=scenario, package=package).data()
    if verification.get("engineering_verified") is not True or result.joint_mechanism is None:
        raise ContractError("combination score input requires an executed joint mechanism")
    candidate, evidence = _candidate(result)
    solver = result.solver
    assert solver is not None
    body = {"schema": "combination-benchmark-score-input-v1", "panel_digest": panel.digest,
            "design_digest": panel.design.content_hash, "obligation_id": panel.obligation_id,
            "cell_key": list(result.cell.key), "identity": result.cell.identity.data(),
            "panel_cell_digest": _panel_cell_digest(result.cell), "task_digest": result.cell.task_digest,
            "scenario_digest": result.cell.scenario_digest, "package_digest": result.cell.package_digest,
            "arm_digest": result.cell.runtime_arm.content_hash, "scorer_digest": result.cell.scorer_digest,
            "objective_digest": solver.session.objective.content_hash, "runtime_trace_digest": result.runtime.trace_digest,
            "runtime_output_digest": result.runtime.output_digest, "joint_mechanism_digest": result.joint_mechanism.content_hash,
            **evidence, "candidate": candidate, "candidate_digest": hashlib.sha256(canonical(candidate).encode()).hexdigest(),
            "status": "combination_execution_succeeded", "scientific_validity": "not_measured"}
    return FrozenRecord.from_dict(body)


def issue_combination_score_input(*, panel: CombinationPanel, result: CombinationBenchmarkCellResult,
                                  task: PublicTask, scenario: FrozenRecord, package: CandidatePackage,
                                  authority: LinkedExecutionAuthority) -> FrozenRecord:
    if not isinstance(authority, LinkedExecutionAuthority):
        raise ContractError("combination score input needs an execution authority")
    return authority.issue(derive_combination_score_input(panel=panel, result=result, task=task, scenario=scenario, package=package).data())


def verify_combination_score_input(receipt: FrozenRecord, *, authority_keys: Mapping[str, bytes],
                                   panel: CombinationPanel, cell: PanelCell) -> FrozenRecord:
    body = _signed_body(receipt, authority_keys, message="combination score input")
    required = {"schema", "authority", "panel_digest", "design_digest", "obligation_id", "cell_key", "identity", "panel_cell_digest", "task_digest", "scenario_digest", "package_digest", "arm_digest", "scorer_digest", "objective_digest", "runtime_trace_digest", "runtime_output_digest", "joint_mechanism_digest", "solver_trace_digest", "analysis_digest", "answer_digest", "execution_digest", "executed_program_sha256", "candidate", "candidate_digest", "status", "scientific_validity"}
    if set(body) != required or body["schema"] != "combination-benchmark-score-input-v1" or body["status"] != "combination_execution_succeeded" or body["scientific_validity"] != "not_measured":
        raise ContractError("combination score input contract drift")
    if cell not in panel.cells or panel.domain != "train" or body["panel_digest"] != panel.digest or body["design_digest"] != panel.design.content_hash or body["obligation_id"] != panel.obligation_id:
        raise ContractError("combination score input panel binding drift")
    if body["cell_key"] != list(cell.key) or body["identity"] != cell.identity.data() or body["panel_cell_digest"] != _panel_cell_digest(cell):
        raise ContractError("combination score input cell binding drift")
    if body["task_digest"] != cell.task_digest or body["scenario_digest"] != cell.scenario_digest or body["package_digest"] != cell.package_digest or body["arm_digest"] != cell.runtime_arm.content_hash:
        raise ContractError("combination score input frozen cell drift")
    candidate = body["candidate"]
    if (not isinstance(candidate, Mapping) or set(candidate) != {"analysis", "program", "answer", "execution_feedback"}
            or any(not isinstance(candidate[key], str) or not candidate[key] for key in ("analysis", "program", "answer"))
            or not isinstance(candidate["execution_feedback"], Mapping) or set(candidate["execution_feedback"]) != {"status", "exit_code", "stdout", "stderr"}):
        raise ContractError("combination scorer candidate leaks or is malformed")
    if hashlib.sha256(canonical(candidate).encode()).hexdigest() != body["candidate_digest"]:
        raise ContractError("combination candidate digest drift")
    for field in required - {"schema", "authority", "cell_key", "identity", "candidate", "status", "scientific_validity", "obligation_id"}:
        if field != "runtime_output_digest" or body[field] is not None:
            _digest(body[field], field)
    return FrozenRecord.from_dict(body)


class CombinationAdaptedScoringService:
    """Independent adapted scorer for signed combination candidates only."""
    def __init__(self, *, config: ScorerConfig, evaluator: FrozenRubricTransport,
                 execution_authority_keys: Mapping[str, bytes], task_handles: Mapping[str, str],
                 scorer_authority: LinkedExecutionAuthority):
        if not isinstance(config, ScorerConfig) or not callable(evaluator) or not execution_authority_keys or not isinstance(scorer_authority, LinkedExecutionAuthority):
            raise ContractError("combination adapted scorer needs frozen dependencies")
        if scorer_authority.authority_id in execution_authority_keys or any(key == scorer_authority.key for key in execution_authority_keys.values()):
            raise ContractError("combination execution and scorer authorities must be distinct")
        self.config, self._evaluator, self._execution_keys, self._handles, self._authority = config, evaluator, dict(execution_authority_keys), dict(task_handles), scorer_authority

    def score_combination(self, *, panel: CombinationPanel, cell: PanelCell, score_input: FrozenRecord) -> ScientificScorerReceipt:
        source = verify_combination_score_input(score_input, authority_keys=self._execution_keys, panel=panel, cell=cell).data()
        if cell.identity.benchmark not in self.config.benchmarks or cell.scorer_digest != self.config.digest or source["scorer_digest"] != self.config.digest:
            raise ContractError("combination scorer configuration drift")
        identity_digest = hashlib.sha256(canonical(cell.identity.data()).encode()).hexdigest()
        handle = self._handles.get(identity_digest)
        if not isinstance(handle, str) or not handle:
            raise ContractError("combination train task is not delegated to scorer")
        request = FrozenRecord.from_dict({"schema": "adapted-rubric-evaluation-request-v1", "panel_digest": panel.digest,
            "scorer_config_digest": self.config.digest, "benchmark": cell.identity.benchmark, "task_handle": handle,
            "identity_digest": identity_digest, "candidate": source["candidate"], "candidate_digest": source["candidate_digest"]})
        response = self._evaluator(request).data()
        expected = {"schema", "panel_digest", "scorer_config_digest", "benchmark", "task_handle_digest", "candidate_digest", "dimensions", "evidence"}
        if set(response) != expected or response["schema"] != "adapted-rubric-evaluation-response-v1" or response["panel_digest"] != panel.digest or response["scorer_config_digest"] != self.config.digest or response["benchmark"] != cell.identity.benchmark or response["task_handle_digest"] != hashlib.sha256(handle.encode()).hexdigest() or response["candidate_digest"] != source["candidate_digest"]:
            raise ContractError("combination rubric response binding drift")
        dimensions = response["dimensions"]; names = _DIMENSIONS[cell.identity.benchmark]
        if not isinstance(dimensions, Mapping) or set(dimensions) != set(names) or any(type(dimensions[name]) not in (int, float) or not math.isfinite(dimensions[name]) or not 0 <= dimensions[name] <= 1 for name in names):
            raise ContractError("combination rubric dimensions drift")
        _evidence(response["evidence"], self.config)
        value = (discovery_adapted_score if cell.identity.benchmark == "discoverybench" else blade_adapted_score)(canonical(source["candidate"]), dimensions)["adapted_score"]
        body = {"schema": "combination-adapted-scored-cell-v1", "cell_key": list(cell.key), "panel_digest": panel.digest,
            "design_digest": panel.design.content_hash, "obligation_id": panel.obligation_id, "scorer_digest": self.config.digest,
            "scorer_config_digest": self.config.digest, "benchmark": cell.identity.benchmark, "combination_input_digest": score_input.content_hash,
            "runtime_trace_digest": source["runtime_trace_digest"], "runtime_output_digest": source["runtime_output_digest"],
            "joint_mechanism_digest": source["joint_mechanism_digest"], "solver_trace_digest": source["solver_trace_digest"],
            "candidate_digest": source["candidate_digest"], "metric": {"value": value, "direction": "higher_better", "value_range": [0.0, 1.0], "scale": "unit"},
            "dimensions": dict(dimensions), "evaluator_evidence": response["evidence"], "scientific_validity": "not_measured", "calibration": "not_measured"}
        return ScientificScorerReceipt(cell.key, self._authority.issue(body))


def verify_combination_adapted_receipt(receipt: ScientificScorerReceipt, *, authority_keys: Mapping[str, bytes],
                                        config: ScorerConfig, panel: CombinationPanel, cell: PanelCell,
                                        score_input: FrozenRecord, execution_authority_keys: Mapping[str, bytes]) -> FrozenRecord:
    if not isinstance(receipt, ScientificScorerReceipt) or receipt.cell_key != cell.key:
        raise ContractError("combination adapted receipt cell mismatch")
    body = _signed_body(receipt.receipt, authority_keys, message="combination adapted receipt")
    if body.get("authority") in execution_authority_keys or any(authority_keys.get(body.get("authority")) == key for key in execution_authority_keys.values()):
        raise ContractError("combination execution and scorer authorities must be distinct")
    source = verify_combination_score_input(score_input, authority_keys=execution_authority_keys, panel=panel, cell=cell).data()
    required = {"schema", "authority", "cell_key", "panel_digest", "design_digest", "obligation_id", "scorer_digest", "scorer_config_digest", "benchmark", "combination_input_digest", "runtime_trace_digest", "runtime_output_digest", "joint_mechanism_digest", "solver_trace_digest", "candidate_digest", "metric", "dimensions", "evaluator_evidence", "scientific_validity", "calibration"}
    if set(body) != required or body["schema"] != "combination-adapted-scored-cell-v1" or body["scientific_validity"] != "not_measured" or body["calibration"] != "not_measured":
        raise ContractError("combination adapted receipt contract drift")
    if (body["cell_key"] != list(cell.key) or body["panel_digest"] != panel.digest or body["design_digest"] != panel.design.content_hash or body["obligation_id"] != panel.obligation_id
            or body["scorer_digest"] != config.digest or body["scorer_config_digest"] != config.digest or body["benchmark"] != cell.identity.benchmark
            or body["combination_input_digest"] != score_input.content_hash):
        raise ContractError("combination adapted receipt binding drift")
    if any(body[field] != source[field] for field in ("runtime_trace_digest", "runtime_output_digest", "joint_mechanism_digest", "solver_trace_digest", "candidate_digest")):
        raise ContractError("combination adapted receipt source drift")
    metric = body["metric"]
    if not isinstance(metric, Mapping) or set(metric) != {"value", "direction", "value_range", "scale"} or metric["direction"] != "higher_better" or metric["value_range"] != [0.0, 1.0] or metric["scale"] != "unit" or type(metric["value"]) not in (int, float) or not math.isfinite(metric["value"]) or not 0 <= metric["value"] <= 1:
        raise ContractError("combination adapted metric drift")
    names = _DIMENSIONS[cell.identity.benchmark]; dims = body["dimensions"]
    if not isinstance(dims, Mapping) or set(dims) != set(names) or any(type(dims[name]) not in (int, float) or not math.isfinite(dims[name]) or not 0 <= dims[name] <= 1 for name in names):
        raise ContractError("combination adapted dimensions drift")
    actual = (discovery_adapted_score if cell.identity.benchmark == "discoverybench" else blade_adapted_score)(canonical(source["candidate"]), dims)["adapted_score"]
    if not math.isclose(metric["value"], actual, rel_tol=0.0, abs_tol=1e-12):
        raise ContractError("combination adapted aggregate drift")
    _evidence(body["evaluator_evidence"], config)
    return FrozenRecord.from_dict(body)


def _evidence(value: object, config: ScorerConfig) -> None:
    required = {"schema", "evaluator_id", "evaluator_version", "prompt_digest", "schema_digest", "output_digest", "reference_digest", "rubric_digest", "mode"}
    frozen = config.record.data()
    if not isinstance(value, Mapping) or set(value) != required or value["schema"] != "frozen-rubric-call-evidence-v1" or value["mode"] != "single_candidate_train_only" or value["evaluator_id"] != frozen["evaluator_id"] or value["evaluator_version"] != frozen["version"] or value["rubric_digest"] != frozen["rubric_digest"]:
        raise ContractError("combination evaluator evidence drift")
    for field in ("prompt_digest", "schema_digest", "output_digest", "reference_digest", "rubric_digest"):
        _digest(value[field], field)
