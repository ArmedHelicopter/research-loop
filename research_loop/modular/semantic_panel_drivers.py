"""Caller-bound production drivers for Q2.2 and Q6.4 completion semantics.

The drivers use the closed semantic scorer contract for actual model responses.
They deliberately do not treat this in-process model path as independent
calibration, validation, or a scientific completion decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping

from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask, required_text
from research_loop.modular.panel_receipts import opaque_panel_cell_binding
from research_loop.modular.semantics import (
    alternative_request,
    assess_alternatives,
    frozen_completion_semantics,
    judge_completion,
    score_completion,
    semantic_request,
)
from research_loop.ontology import ContractError


_Q22 = ("affirm", "negate", "quote", "counterfactual", "local")
_Q64 = ("negation", "quotation", "alternative")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{name} must be a mapping")
    return value


def _digest(value: Any, name: str) -> str:
    value = required_text(value, name)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ContractError(f"{name} must be a sha256 digest")
    return value


def _evidence(value: Any) -> dict[str, str]:
    material = _mapping(value, "public evidence")
    if not material:
        raise ContractError("public evidence cannot be empty")
    return {required_text(key, "public evidence id"): required_text(item, "public evidence")
            for key, item in material.items()}


def _answer(value: Any, identity: DataIdentity) -> dict[str, Any]:
    body = dict(_mapping(value, "caller answer"))
    if set(body) != {"source_id", "raw_answer", "public_evidence"}:
        raise ContractError("caller answer has an incomplete schema")
    if body["source_id"] != identity.group_id:
        raise ContractError("caller answer source does not bind this task")
    return {"source_id": required_text(body["source_id"], "caller answer source"),
            "raw_answer": required_text(body["raw_answer"], "raw answer"),
            "public_evidence": _evidence(body["public_evidence"])}


def _semantics(value: Any | None) -> FrozenRecord:
    if value is None:
        return frozen_completion_semantics()
    if not isinstance(value, FrozenRecord):
        raise ContractError("completion semantics must be frozen")
    # ``semantic_request`` is the public validator for this closed contract.
    return value


def _q64_item(value: Any, identity: DataIdentity) -> dict[str, Any]:
    body = dict(_mapping(value, "Q6.4 caller material"))
    if set(body) != {"first", "second", "legacy_diagnostic"}:
        raise ContractError("Q6.4 caller material has an incomplete schema")
    diagnostic = dict(_mapping(body["legacy_diagnostic"], "legacy diagnostic"))
    if set(diagnostic) != {"status", "record_digest"} or diagnostic["status"] != "legacy-unmodified":
        raise ContractError("Q6.4 legacy material is diagnostic-only and must remain unmodified")
    return {"first": _answer(body["first"], identity), "second": _answer(body["second"], identity),
            "legacy_diagnostic": {"status": "legacy-unmodified",
                                  "record_digest": _digest(diagnostic["record_digest"], "legacy record digest")}}


def freeze_semantic_panel_bundle(task: PublicTask, *, q22: Mapping[str, Mapping[str, Any]],
                                 q64: Mapping[str, Mapping[str, Any]],
                                 p0_control_digest: str, semantics: FrozenRecord | None = None) -> FrozenRecord:
    """Freeze caller-provided, source-bound public scorer material.

    No answer carries an expected semantic interpretation, outcome, arm, or
    historical score.  Q6.4 keeps only an opaque legacy record digest for
    diagnostics; it never enters a model request or score calculation.
    """
    if not isinstance(task, PublicTask) or not isinstance(q22, Mapping) or not isinstance(q64, Mapping):
        raise ContractError("semantic panel bundle needs a public task and variant mappings")
    if set(q22) != set(_Q22) or set(q64) != set(_Q64):
        raise ContractError("semantic panel bundle variant coverage mismatch")
    frozen = _semantics(semantics)
    answers = {name: _answer(row, task.identity) for name, row in q22.items()}
    reassessments = {name: _q64_item(row, task.identity) for name, row in q64.items()}
    # Reject an arbitrary lookalike rubric before any future model request.
    for answer in [*answers.values(), *(row[side] for row in reassessments.values() for side in ("first", "second"))]:
        semantic_request(task, frozen, raw_answer=answer["raw_answer"], public_evidence=answer["public_evidence"])
    return FrozenRecord.from_dict({"schema": "semantic-panel-bundle-v1", "identity": task.identity.data(),
        "payload_digest": task.payload.content_hash, "p0_control_digest": _digest(p0_control_digest, "P0 control digest"),
        "semantics": frozen.data(), "q22": answers, "q64": reassessments})


def semantic_panel_injection(experiment_id: str, variant: str, *, task: FrozenRecord,
                             evidence: FrozenRecord) -> Mapping[str, Any]:
    """Project a previously frozen caller bundle into a controller scenario."""
    if experiment_id not in {"Q2.2", "Q6.4"}:
        raise ContractError("semantic panel injection only covers Q2.2 and Q6.4")
    public = PublicTask(DataIdentity.parse(task.data()["identity"]), FrozenRecord.from_dict(task.data()["payload"]))
    body = evidence.data()
    if body.get("schema") != "semantic-panel-bundle-v1":
        raise ContractError("semantic panel requires caller-frozen semantic material")
    bundle = freeze_semantic_panel_bundle(public, q22=body.get("q22", {}), q64=body.get("q64", {}),
        p0_control_digest=body.get("p0_control_digest"),
        semantics=FrozenRecord.from_dict(_mapping(body.get("semantics"), "completion semantics")))
    variants = bundle.data()["q22" if experiment_id == "Q2.2" else "q64"]
    if variant not in variants:
        raise ContractError("semantic panel variant is not registered")
    return {"schema": "semantic-panel-controller-v1", "bundle": bundle.data()}


def _material(task: PublicTask, scenario: FrozenRecord, *, experiment_id: str, variant: str) -> tuple[FrozenRecord, Any, str]:
    controller = _mapping(scenario.data().get("controller_input"), "controller input")
    if controller.get("schema") != "semantic-panel-controller-v1":
        raise ContractError("typed semantic panel material is required")
    bundle = FrozenRecord.from_dict(dict(_mapping(controller.get("bundle"), "semantic bundle")))
    body = bundle.data()
    remade = freeze_semantic_panel_bundle(task, q22=body.get("q22", {}), q64=body.get("q64", {}),
        p0_control_digest=body.get("p0_control_digest"),
        semantics=FrozenRecord.from_dict(_mapping(body.get("semantics"), "completion semantics")))
    if remade.content_hash != bundle.content_hash or scenario.data().get("base", {}).get("evidence") != bundle.content_hash:
        raise ContractError("scenario does not bind its caller semantic material")
    key = "q22" if experiment_id == "Q2.2" else "q64"
    if variant not in body[key]:
        raise ContractError("semantic material variant is not registered")
    return FrozenRecord.from_dict(body["semantics"]), body[key][variant], body["p0_control_digest"]


def _candidate(response: FrozenRecord, objective_digest: str) -> FrozenRecord:
    body = response.data()
    if (set(body) != {"objective_digest", "outcome", "evidence_ids", "conclusion", "programme_complete"}
            or body.get("objective_digest") != objective_digest
            or body.get("outcome") not in {"positive", "negative", "unknown", "invalid", "withdrawn"}
            or not isinstance(body.get("evidence_ids"), list)
            or any(not isinstance(value, str) or not value for value in body["evidence_ids"])
            or len(set(body["evidence_ids"])) != len(body["evidence_ids"])
            or not isinstance(body.get("conclusion"), str) or not body["conclusion"].strip()
            or body.get("programme_complete") is not False):
        raise ContractError("semantic panel final candidate has an invalid bounded schema")
    return response


def _semantic_score(workflow, *, slot: str, alternative_slot: str, model, task: PublicTask,
                    semantics: FrozenRecord, answer: Mapping[str, Any], binding: Mapping[str, str],
                    p0_control_digest: str) -> tuple[FrozenRecord, FrozenRecord, FrozenRecord, FrozenRecord, FrozenRecord]:
    request = semantic_request(task, semantics, raw_answer=answer["raw_answer"], public_evidence=answer["public_evidence"])
    response = workflow.invoke_model(slot, model,
        instruction="Interpret only the supplied raw answer under the frozen public completion-semantics schema. Return the exact semantic judge response schema.",
        evidence_only=True, module_context=FrozenRecord.from_dict({"panel_cell": dict(binding), "p0_control_digest": p0_control_digest,
            "semantic_request": request.data()}))
    judgement = judge_completion(request, lambda _request: response)
    alternatives = alternative_request(request, judgement)
    alternative_response = workflow.invoke_model(alternative_slot, model,
        instruction="Assess only the supplied candidate specifications under the frozen public schema. Return the exact alternative assessment response schema.",
        evidence_only=True, module_context=FrozenRecord.from_dict({"panel_cell": dict(binding), "p0_control_digest": p0_control_digest,
            "alternative_request": alternatives.data()}))
    assessment = assess_alternatives(alternatives, lambda _request: alternative_response)
    return (score_completion(judgement, semantics=semantics, request=request, alternative_assessment=assessment),
            judgement, assessment, response, alternative_response)


@dataclass(frozen=True)
class Q22CompletionSemanticsDriver:
    experiment_id: str = "Q2.2"
    slots: tuple[str, ...] = ("semantic_judgement", "alternative_analysis", "final")
    execution_limit: int = 0
    docker_execution: str = "not_requested_by_driver"

    def slots_for(self, cell) -> tuple[str, ...]:
        return self.slots

    def run(self, workflow, *, cell, scenario: FrozenRecord, model, package):
        semantics, answer, p0_control_digest = _material(workflow.session.task, scenario, experiment_id=self.experiment_id, variant=cell.variant)
        binding = opaque_panel_cell_binding(cell)
        score, judgement, assessment, response, alternative_response = _semantic_score(workflow, slot="semantic_judgement", alternative_slot="alternative_analysis",
            model=model, task=workflow.session.task, semantics=semantics, answer=answer, binding=binding, p0_control_digest=p0_control_digest)
        trace = workflow._trace("semantic_completion", "executed", semantics_digest=semantics.content_hash,
            semantic_score=score.data(), judgement_digest=judgement.content_hash, alternative_assessment_digest=assessment.content_hash,
            scorer_boundary="same_model_engineering_seam_not_independent_calibration")
        final = workflow.invoke_model("final", model,
            instruction="Return the bounded train-only candidate record. Copy required_objective_digest exactly; a semantic score is not scientific evidence.",
            module_context=FrozenRecord.from_dict({"panel_cell": dict(binding), "p0_control_digest": p0_control_digest,
                "required_objective_digest": workflow.session.objective.content_hash,
                "public_material": {"raw_answer": answer["raw_answer"], "public_evidence": answer["public_evidence"]},
                "semantic_score": score.data()}))
        return trace, _candidate(final, workflow.session.objective.content_hash), (response, alternative_response, final)


@dataclass(frozen=True)
class Q64ScorerRepairDriver:
    experiment_id: str = "Q6.4"
    slots: tuple[str, ...] = ("first_semantic_judgement", "first_alternative_analysis", "second_semantic_judgement",
                              "second_alternative_analysis", "final")
    execution_limit: int = 0
    docker_execution: str = "not_requested_by_driver"

    def slots_for(self, cell) -> tuple[str, ...]:
        return self.slots

    def run(self, workflow, *, cell, scenario: FrozenRecord, model, package):
        semantics, material, p0_control_digest = _material(workflow.session.task, scenario, experiment_id=self.experiment_id, variant=cell.variant)
        binding = opaque_panel_cell_binding(cell)
        first, first_judgement, first_assessment, first_response, first_alternative_response = _semantic_score(workflow, slot="first_semantic_judgement",
            alternative_slot="first_alternative_analysis", model=model, task=workflow.session.task, semantics=semantics,
            answer=material["first"], binding=binding, p0_control_digest=p0_control_digest)
        second, second_judgement, second_assessment, second_response, second_alternative_response = _semantic_score(workflow, slot="second_semantic_judgement",
            alternative_slot="second_alternative_analysis", model=model, task=workflow.session.task, semantics=semantics,
            answer=material["second"], binding=binding, p0_control_digest=p0_control_digest)
        trace = workflow._trace("semantic_reassessment", "executed", semantics_digest=semantics.content_hash,
            first_score=first.data(), second_score=second.data(), first_judgement_digest=first_judgement.content_hash,
            second_judgement_digest=second_judgement.content_hash, first_alternative_assessment_digest=first_assessment.content_hash,
            second_alternative_assessment_digest=second_assessment.content_hash,
            legacy_diagnostic_digest=material["legacy_diagnostic"]["record_digest"],
            legacy_role="diagnostic_only_not_used_for_scoring",
            scorer_boundary="same_model_engineering_seam_not_independent_calibration")
        final = workflow.invoke_model("final", model,
            instruction="Return the bounded train-only candidate record. Copy required_objective_digest exactly; new semantic reassessments are not scientific evidence.",
            module_context=FrozenRecord.from_dict({"panel_cell": dict(binding), "p0_control_digest": p0_control_digest,
                "required_objective_digest": workflow.session.objective.content_hash,
                "first_public_material": {"raw_answer": material["first"]["raw_answer"], "public_evidence": material["first"]["public_evidence"]},
                "second_public_material": {"raw_answer": material["second"]["raw_answer"], "public_evidence": material["second"]["public_evidence"]},
                "semantic_scores": [first.data(), second.data()]}))
        return trace, _candidate(final, workflow.session.objective.content_hash), (
            first_response, first_alternative_response, second_response, second_alternative_response, final)


def install_drivers(target: MutableMapping[str, Any]):
    """Explicit registration hook for the owning integration change."""
    target.update({"Q2.2": Q22CompletionSemanticsDriver(), "Q6.4": Q64ScorerRepairDriver()})
    return target
