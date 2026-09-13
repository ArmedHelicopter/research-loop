"""Train-only adapted scoring over a signed, journal-derived linked cell.

The HMAC authority is a component boundary suitable for deterministic tests.
It is not a deployed process-isolation claim: production must keep the linked
execution authority, protected-reference resolver, evaluator model, and scorer
keys in independently operated services.
"""
from __future__ import annotations

import hashlib
import hmac
import math
from dataclasses import dataclass
from typing import Any, Mapping

from evaluation.modular.scoring_service import FrozenRubricTransport, ScorerConfig
from research_loop.modular.benchmark_cell import LinkedBenchmarkCellResult, verify_linked_benchmark_cell
from research_loop.modular.benchmarks.scoring import blade_adapted_score, discovery_adapted_score
from research_loop.modular.contracts import FrozenRecord, PublicTask, required_text
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.panel_receipts import FrozenPanel, PanelCell, ScientificScorerReceipt
from research_loop.ontology import ContractError, canonical


_DIMENSIONS = {"discoverybench": ("context", "variable_f1", "relation"), "blade": ("cvars", "transform", "model")}
_METRICS = {"discoverybench": "discovery_adapted_score", "blade": "blade_adapted_score"}


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_text(value: str) -> str:
    return _sha_bytes(value.encode("utf-8"))


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ContractError(f"{field} must be a sha256 digest")
    return value


@dataclass(frozen=True)
class LinkedExecutionAuthority:
    authority_id: str
    key: bytes

    def __post_init__(self) -> None:
        required_text(self.authority_id, "linked execution authority id")
        if not isinstance(self.key, bytes) or len(self.key) < 32:
            raise ContractError("linked execution authority key must have at least 32 bytes")

    def issue(self, body: Mapping[str, Any]) -> FrozenRecord:
        material = dict(body); material["authority"] = self.authority_id
        return FrozenRecord.from_dict({"body": material,
            "mac": hmac.new(self.key, canonical(material).encode(), hashlib.sha256).hexdigest()})


def issue_linked_score_input(*, panel: FrozenPanel, result: LinkedBenchmarkCellResult, task: PublicTask,
                             scenario: FrozenRecord, package: CandidatePackage,
                             authority: LinkedExecutionAuthority) -> FrozenRecord:
    """Sign the sole evaluator candidate after replaying both execution journals."""
    if not isinstance(authority, LinkedExecutionAuthority) or not isinstance(panel, FrozenPanel) or panel.domain != "train":
        raise ContractError("linked score input needs an independent execution authority")
    if {candidate.key: candidate for candidate in panel.cells}.get(result.cell.key) != result.cell:
        raise ContractError("linked score input cell is not an exact frozen panel member")
    verify_linked_benchmark_cell(result, task=task, scenario=scenario, package=package)
    solver = result.solver
    if result.status != "linked_succeeded" or solver is None or solver.status != "execution_succeeded":
        raise ContractError("only a successfully linked execution may receive an adapted score")
    if solver.analysis is None or solver.answer is None or solver.execution is None or solver.execution.artifact is None:
        raise ContractError("linked execution lacks analysis, answer, or execution evidence")
    analysis, answer, execution = solver.analysis.data(), solver.answer.data(), solver.execution
    if set(analysis) != {"analysis", "program"} or not all(isinstance(analysis[key], str) and analysis[key] for key in analysis):
        raise ContractError("linked solver analysis is not a bounded program candidate")
    program_path = solver.session.sidecar / "analysis-1.py"
    if not program_path.is_file() or program_path.read_text(encoding="utf-8") != analysis["program"]:
        raise ContractError("linked solver program file does not match its journal candidate")
    program_digest = _sha_bytes(program_path.read_bytes())
    if program_digest != execution.artifact.sha256:
        raise ContractError("linked solver program bytes do not match the executed artifact")
    answer_body = answer
    if not isinstance(answer_body.get("conclusion"), str) or not answer_body["conclusion"].strip():
        raise ContractError("linked solver answer lacks a conclusion")
    raw_execution = execution.record.data()
    feedback = {key: raw_execution.get(key, "") for key in ("status", "exit_code", "stdout", "stderr")}
    candidate = {"analysis": analysis["analysis"], "program": analysis["program"],
                 "answer": answer_body["conclusion"], "execution_feedback": feedback}
    candidate_digest = hashlib.sha256(canonical(candidate).encode()).hexdigest()
    body = {"schema": "linked-benchmark-score-input-v1", "panel_digest": panel.digest, "cell_key": list(result.cell.key),
            "identity": result.cell.identity.data(), "panel_cell_digest": hashlib.sha256(canonical({"cell_key": list(result.cell.key), "scenario_digest": result.cell.scenario_digest, "package_digest": result.cell.package_digest, "arm": result.cell.runtime_arm.data()}).encode()).hexdigest(),
            "task_digest": result.cell.task_digest, "scenario_digest": result.cell.scenario_digest,
            "package_digest": result.cell.package_digest, "arm_digest": result.cell.runtime_arm.content_hash,
            "objective_digest": solver.session.objective.content_hash,
            "mechanism_trace_digest": result.mechanism.runtime.trace_digest,
            "mechanism_output_digest": result.mechanism.runtime.output_digest,
            "solver_trace_digest": FrozenRecord((solver.session.sidecar / "trace.jsonl").read_text(encoding="utf-8").splitlines()[-1]).content_hash,
            "linked_receipt_digest": result.receipt.content_hash, "analysis_digest": solver.analysis.content_hash,
            "answer_digest": solver.answer.content_hash, "execution_digest": execution.content_hash,
            "executed_program_sha256": program_digest, "candidate": candidate, "candidate_digest": candidate_digest,
            "status": "linked_execution_succeeded", "scientific_validity": "not_measured"}
    return authority.issue(body)


def verify_linked_score_input(receipt: FrozenRecord, *, authority_keys: Mapping[str, bytes],
                              panel: FrozenPanel, cell: PanelCell) -> FrozenRecord:
    envelope = receipt.data()
    if set(envelope) != {"body", "mac"} or not isinstance(envelope["body"], dict):
        raise ContractError("linked score input envelope is malformed")
    body, authority = envelope["body"], envelope["body"].get("authority")
    key = authority_keys.get(authority) if isinstance(authority_keys, Mapping) else None
    if not isinstance(key, bytes) or not hmac.compare_digest(envelope["mac"], hmac.new(key, canonical(body).encode(), hashlib.sha256).hexdigest()):
        raise ContractError("linked score input signature is untrusted")
    required = {"schema", "authority", "panel_digest", "cell_key", "identity", "panel_cell_digest", "task_digest", "scenario_digest", "package_digest", "arm_digest", "objective_digest", "mechanism_trace_digest", "mechanism_output_digest", "solver_trace_digest", "linked_receipt_digest", "analysis_digest", "answer_digest", "execution_digest", "executed_program_sha256", "candidate", "candidate_digest", "status", "scientific_validity"}
    if set(body) != required or body["schema"] != "linked-benchmark-score-input-v1" or body["status"] != "linked_execution_succeeded" or body["scientific_validity"] != "not_measured":
        raise ContractError("linked score input contract drift")
    if {item.key: item for item in panel.cells}.get(cell.key) != cell:
        raise ContractError("linked score input cell is not an exact frozen panel member")
    if panel.domain != "train" or cell.identity.domain != "train" or body["panel_digest"] != panel.digest or body["cell_key"] != list(cell.key) or body["identity"] != cell.identity.data():
        raise ContractError("linked score input is not bound to this train cell")
    if body["task_digest"] != cell.task_digest or body["scenario_digest"] != cell.scenario_digest or body["package_digest"] != cell.package_digest or body["arm_digest"] != cell.runtime_arm.content_hash:
        raise ContractError("linked score input cell binding drift")
    expected_cell = hashlib.sha256(canonical({"cell_key": list(cell.key), "scenario_digest": cell.scenario_digest, "package_digest": cell.package_digest, "arm": cell.runtime_arm.data()}).encode()).hexdigest()
    if body["panel_cell_digest"] != expected_cell:
        raise ContractError("linked score input panel cell digest drift")
    candidate = body["candidate"]
    if (not isinstance(candidate, Mapping) or set(candidate) != {"analysis", "program", "answer", "execution_feedback"}
            or not all(isinstance(candidate[key], str) and candidate[key] for key in ("analysis", "program", "answer"))
            or not isinstance(candidate["execution_feedback"], Mapping)
            or set(candidate["execution_feedback"]) != {"status", "exit_code", "stdout", "stderr"}):
        raise ContractError("linked evaluator candidate exposes forbidden controller material")
    if hashlib.sha256(canonical(candidate).encode()).hexdigest() != body["candidate_digest"]:
        raise ContractError("linked evaluator candidate digest drift")
    for name in ("task_digest", "scenario_digest", "package_digest", "arm_digest", "objective_digest", "mechanism_trace_digest", "mechanism_output_digest", "solver_trace_digest", "linked_receipt_digest", "analysis_digest", "answer_digest", "execution_digest", "executed_program_sha256", "candidate_digest"):
        _digest(body[name], name)
    return FrozenRecord.from_dict(body)


class LinkedAdaptedScoringService:
    """Scores only a signed train linked candidate; it cannot assert science."""
    def __init__(self, *, config: ScorerConfig, evaluator: FrozenRubricTransport,
                 execution_authority_keys: Mapping[str, bytes], task_handles: Mapping[str, str], scorer_authority: LinkedExecutionAuthority):
        if not isinstance(config, ScorerConfig) or not callable(evaluator) or not execution_authority_keys or not isinstance(scorer_authority, LinkedExecutionAuthority):
            raise ContractError("linked adapted scorer needs frozen typed dependencies")
        if scorer_authority.authority_id in execution_authority_keys or any(key == scorer_authority.key for key in execution_authority_keys.values()):
            raise ContractError("linked execution and scorer authorities must be distinct")
        self.config, self._evaluator, self._execution_keys, self._handles, self._authority = config, evaluator, dict(execution_authority_keys), dict(task_handles), scorer_authority

    def score_linked(self, *, panel: FrozenPanel, cell: PanelCell, linked_input: FrozenRecord) -> ScientificScorerReceipt:
        source = verify_linked_score_input(linked_input, authority_keys=self._execution_keys, panel=panel, cell=cell).data()
        if cell.identity.benchmark not in self.config.benchmarks or cell.scorer_digest != self.config.digest:
            raise ContractError("linked adapted scorer configuration drift")
        identity_digest = hashlib.sha256(canonical(cell.identity.data()).encode()).hexdigest()
        handle = self._handles.get(identity_digest)
        if not isinstance(handle, str) or not handle:
            raise ContractError("linked train task is not delegated to the scoring service")
        request = FrozenRecord.from_dict({"schema": "adapted-rubric-evaluation-request-v1", "panel_digest": panel.digest,
            "scorer_config_digest": self.config.digest, "benchmark": cell.identity.benchmark, "task_handle": handle,
            "identity_digest": identity_digest, "candidate": source["candidate"], "candidate_digest": source["candidate_digest"]})
        response = self._evaluator(request).data()
        required = {"schema", "panel_digest", "scorer_config_digest", "benchmark", "task_handle_digest", "candidate_digest", "dimensions", "evidence"}
        if set(response) != required or response["schema"] != "adapted-rubric-evaluation-response-v1" or response["panel_digest"] != panel.digest or response["scorer_config_digest"] != self.config.digest or response["benchmark"] != cell.identity.benchmark or response["candidate_digest"] != source["candidate_digest"] or response["task_handle_digest"] != _sha_text(handle):
            raise ContractError("linked rubric response does not bind the signed candidate")
        evidence = response["evidence"]
        expected_evidence = {"schema", "evaluator_id", "evaluator_version", "prompt_digest", "schema_digest", "output_digest", "reference_digest", "rubric_digest", "mode"}
        frozen = self.config.record.data()
        if (not isinstance(evidence, Mapping) or set(evidence) != expected_evidence
                or evidence.get("evaluator_id") != frozen["evaluator_id"] or evidence.get("evaluator_version") != frozen["version"]
                or evidence.get("rubric_digest") != frozen["rubric_digest"]):
            raise ContractError("linked rubric evaluator contract drift")
        dimensions = response["dimensions"]
        names = _DIMENSIONS[cell.identity.benchmark]
        if not isinstance(dimensions, Mapping) or set(dimensions) != set(names) or any(type(dimensions[name]) not in (int, float) or not math.isfinite(dimensions[name]) or not 0 <= dimensions[name] <= 1 for name in names):
            raise ContractError("linked rubric response dimensions drift")
        metric = (discovery_adapted_score if cell.identity.benchmark == "discoverybench" else blade_adapted_score)(canonical(source["candidate"]), dimensions)
        body = {"schema": "linked-adapted-scored-cell-v1", "cell_key": list(cell.key), "panel_digest": panel.digest,
            "scorer_digest": self.config.digest, "scorer_config_digest": self.config.digest, "benchmark": cell.identity.benchmark,
            "linked_input_digest": linked_input.content_hash, "linked_receipt_digest": source["linked_receipt_digest"],
            "mechanism_trace_digest": source["mechanism_trace_digest"], "solver_trace_digest": source["solver_trace_digest"], "candidate_digest": source["candidate_digest"],
            "metric": {"name": _METRICS[cell.identity.benchmark], "dimensions": dict(dimensions), "value": metric["adapted_score"], "direction": "higher_better", "value_range": [0.0, 1.0], "scale": "unit"},
            "evaluator_evidence": evidence, "scientific_validity": "not_measured", "calibration": "not_measured"}
        return ScientificScorerReceipt(cell.key, self._authority.issue(body))


def verify_linked_adapted_receipt(receipt: ScientificScorerReceipt, *, authority_keys: Mapping[str, bytes],
                                  config: ScorerConfig, panel: FrozenPanel, cell: PanelCell,
                                  linked_input: FrozenRecord, execution_authority_keys: Mapping[str, bytes]) -> FrozenRecord:
    """Verify a selection-consumable adapted receipt without granting science."""
    if not isinstance(receipt, ScientificScorerReceipt) or receipt.cell_key != cell.key:
        raise ContractError("linked adapted receipt cell mismatch")
    envelope = receipt.receipt.data()
    if set(envelope) != {"body", "mac"} or not isinstance(envelope["body"], dict):
        raise ContractError("linked adapted receipt envelope is malformed")
    body, authority = envelope["body"], envelope["body"].get("authority")
    key = authority_keys.get(authority) if isinstance(authority_keys, Mapping) else None
    if not isinstance(key, bytes) or not hmac.compare_digest(envelope["mac"], hmac.new(key, canonical(body).encode(), hashlib.sha256).hexdigest()):
        raise ContractError("linked adapted receipt signature is untrusted")
    if authority in execution_authority_keys or any(key == execution_key for execution_key in execution_authority_keys.values()):
        raise ContractError("linked execution and scorer authorities must be distinct")
    required = {"schema", "authority", "cell_key", "panel_digest", "scorer_digest", "scorer_config_digest", "benchmark", "linked_input_digest", "linked_receipt_digest", "mechanism_trace_digest", "solver_trace_digest", "candidate_digest", "metric", "evaluator_evidence", "scientific_validity", "calibration"}
    if set(body) != required or body["schema"] != "linked-adapted-scored-cell-v1" or body["scientific_validity"] != "not_measured" or body["calibration"] != "not_measured":
        raise ContractError("linked adapted receipt contract drift")
    source = verify_linked_score_input(linked_input, authority_keys=execution_authority_keys, panel=panel, cell=cell).data()
    if (body["cell_key"] != list(cell.key) or body["panel_digest"] != panel.digest or body["scorer_digest"] != config.digest
            or body["scorer_config_digest"] != config.digest or body["benchmark"] != cell.identity.benchmark
            or body["linked_input_digest"] != linked_input.content_hash):
        raise ContractError("linked adapted receipt binding drift")
    if (body["linked_receipt_digest"] != source["linked_receipt_digest"]
            or body["mechanism_trace_digest"] != source["mechanism_trace_digest"]
            or body["solver_trace_digest"] != source["solver_trace_digest"]
            or body["candidate_digest"] != source["candidate_digest"]):
        raise ContractError("linked adapted receipt source evidence drift")
    for field in ("linked_receipt_digest", "mechanism_trace_digest", "solver_trace_digest", "candidate_digest"):
        _digest(body[field], field)
    metric = body["metric"]
    names = _DIMENSIONS[cell.identity.benchmark]
    if (not isinstance(metric, Mapping) or set(metric) != {"name", "dimensions", "value", "direction", "value_range", "scale"}
            or metric["name"] != _METRICS[cell.identity.benchmark] or metric["direction"] != "higher_better"
            or metric["value_range"] != [0.0, 1.0] or metric["scale"] != "unit" or not isinstance(metric["dimensions"], Mapping)
            or set(metric["dimensions"]) != set(names) or type(metric["value"]) not in (int, float) or not math.isfinite(metric["value"]) or not 0 <= metric["value"] <= 1
            or any(type(metric["dimensions"][name]) not in (int, float) or not math.isfinite(metric["dimensions"][name]) or not 0 <= metric["dimensions"][name] <= 1 for name in names)):
        raise ContractError("linked adapted metric drift")
    actual = (discovery_adapted_score if cell.identity.benchmark == "discoverybench" else blade_adapted_score)(canonical(source["candidate"]), metric["dimensions"])["adapted_score"]
    if not math.isclose(metric["value"], actual, rel_tol=0.0, abs_tol=1e-12):
        raise ContractError("linked adapted metric aggregate drift")
    return FrozenRecord.from_dict(body)
