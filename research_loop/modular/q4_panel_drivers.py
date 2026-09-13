"""Closed production review drivers for the remaining Q4 interventions."""
from __future__ import annotations

from typing import Any, Mapping, TYPE_CHECKING

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.modules.predictions import freeze_shared_experiment
from research_loop.modular.scenarios_review import Q4ReviewMaterial
from research_loop.ontology import ContractError

if TYPE_CHECKING:
    from research_loop.modular.modules.improvement import CandidatePackage
    from research_loop.modular.panel_receipts import PanelCell
    from research_loop.modular.panel_runner import ModelPort
    from research_loop.modular.workflow import ModularWorkflow, WorkflowResult


_QUESTIONS = {
    "mechanism": "What causal mechanism could produce the supplied public evidence, and what observation would falsify it?",
    "alternative": "State a distinct alternative explanation and an observable that separates it from the supplied public evidence.",
    "measurement": "Identify a plausible measurement failure and a public check that would distinguish it from the stated mechanism.",
    "experiment": "Propose one discriminating experiment with a predeclared observable and failure condition.",
    "counterexample": "Assess the supplied public evidence for a concrete counterexample; report none when none is supported.",
    "generic": "Assess the supplied public evidence and identify a concrete concern only when supported.",
}


def _binding(cell: "PanelCell", scenario: FrozenRecord) -> dict[str, Any]:
    return {"experiment_id": cell.coverage_id, "variant": cell.variant, "replicate": cell.replicate,
            "arm_id": cell.arm_id, "scenario_digest": scenario.content_hash}


def _material(workflow: "ModularWorkflow", scenario: FrozenRecord) -> Mapping[str, Any]:
    controller = scenario.data().get("controller_input", {})
    body = controller.get("q4_review_material") if isinstance(controller, Mapping) else None
    material_digest = controller.get("q4_review_material_digest") if isinstance(controller, Mapping) else None
    if (not isinstance(body, Mapping) or not isinstance(material_digest, str)
            or scenario.data()["base"].get("evidence") != material_digest
            or FrozenRecord.from_dict(dict(body)).content_hash != material_digest):
        raise ContractError("Q4 scenario lacks material bound to base evidence")
    checked = Q4ReviewMaterial(FrozenRecord.from_dict(dict(body)), task_identity=workflow.session.task.identity.data())
    return checked.data()


def _review(response: FrozenRecord, *, m4: bool) -> tuple[FrozenRecord, tuple[Mapping[str, Any], ...]]:
    body = response.data()
    if m4:
        if set(body) != {"review", "prediction_candidates"} or not isinstance(body["review"], Mapping) or not isinstance(body["prediction_candidates"], list) or not body["prediction_candidates"] or any(not isinstance(item, Mapping) for item in body["prediction_candidates"]):
            raise ContractError("Q4.1 M4 response requires a review and operational prediction candidates")
        return FrozenRecord.from_dict(dict(body["review"])), tuple(dict(item) for item in body["prediction_candidates"])
    return response, ()


def _final(workflow: "ModularWorkflow", *, cell: "PanelCell", scenario: FrozenRecord, model: "ModelPort",
           package: "CandidatePackage", stage: "WorkflowResult", review_context: Mapping[str, Any]) -> FrozenRecord:
    candidate = workflow.invoke_model("final", model, instruction=(
        "Return the bounded candidate record for this train-only run; unknown is allowed. "
        "Copy required_objective_digest exactly into objective_digest; do not calculate or alter it."),
        module_context=FrozenRecord.from_dict({"panel_cell": _binding(cell, scenario),
            "candidate_package": package.record.data(), "required_objective_digest": workflow.session.objective.content_hash,
            "driver_stage": stage.detail.data()["stage"], "review_record": dict(review_context)}))
    if candidate.data().get("objective_digest") != workflow.session.objective.content_hash:
        raise ContractError("Q4 final must copy required_objective_digest exactly")
    return candidate


def _initial_context(*, cell: "PanelCell", scenario: FrozenRecord, evidence: FrozenRecord, question: str,
                     material: Mapping[str, Any], m5: bool, m4: bool = False) -> FrozenRecord:
    # Deliberately exclude controller data, reviewer/provider identity, variant
    # labels and any response.  The blind call receives only public material.
    context = {"review_phase": "initial_blind", "public_evidence": evidence.data(), "public_evidence_digest": evidence.content_hash,
        "assigned_review_material": dict(material), "assigned_question": question,
        "m5_enabled": m5, "m4_enabled": m4}
    if not m5:
        context["control"] = "M5"
        context["control_notice"] = "M5 review intervention disabled; no peer response is exposed."
    return FrozenRecord.from_dict(context)


class Q41IndependenceDriver:
    """Q4.1 compares call sampling and assigned-question contexts, not priors."""
    experiment_id = "Q4.1"
    slots = ("initial_1", "initial_2", "initial_3", "initial_4", "final")
    execution_limit = 0
    docker_execution = "not_requested_by_driver"

    def slots_for(self, cell: "PanelCell") -> tuple[str, ...]:
        return (("initial_1", "final") if cell.variant == "single" else self.slots)

    def run(self, workflow: "ModularWorkflow", *, cell: "PanelCell", scenario: FrozenRecord,
            model: "ModelPort", package: "CandidatePackage") -> tuple["WorkflowResult", FrozenRecord, tuple[FrozenRecord, ...]]:
        material = _material(workflow, scenario)
        m5, m4, evidence = "M5" in workflow.enabled, "M4" in workflow.enabled, FrozenRecord.from_dict(material["public_evidence"])
        questions = (["mechanism"] if cell.variant in {"single", "independent_samples"}
                     else ["mechanism", "alternative", "measurement", "experiment"])
        if cell.variant == "independent_samples":
            questions = ["mechanism"] * 4
        review_id, submissions, responses, candidates = None, [], [], []
        if m5:
            review = workflow.reviews.open(task_binding=workflow.session.task.content_hash, evidence_snapshot=evidence.content_hash,
                roles=[{"role_id": f"review_{n}", "question": _QUESTIONS[name]} for n, name in enumerate(questions, 1)], budget_units=len(questions))
            review_id = review.review_id
        for number, name in enumerate(questions, 1):
            instruction = "Answer only the assigned review question from the supplied public evidence."
            if m4:
                instruction += (" Return exactly review plus prediction_candidates. review must be a valid review response. "
                    "prediction_candidates must contain at least two complete operational hypothesis branches with one shared intervention and discriminator.")
            raw = workflow.invoke_model(f"initial_{number}", model, instruction=instruction,
                module_context=_initial_context(cell=cell, scenario=scenario, evidence=evidence, question=_QUESTIONS[name],
                    material=material["summary_material"], m5=m5, m4=m4), evidence_only=True)
            answer, prediction_candidates = _review(raw, m4=m4); responses.append(raw)
            candidates.extend(prediction_candidates)
            if m5: submissions.append(workflow.reviews.submit(review_id, role_id=f"review_{number}", reviewer_id=f"q41-reviewer-{number}", response=answer.data(), cost_units=1))
        prediction = None
        if m4:
            if len(candidates) < 2:
                raise ContractError("Q4.1 M4 needs at least two actual prediction candidates")
            prediction = freeze_shared_experiment(workflow.predictions, str(evidence.data().get("research_question", "public review question")), candidates, budget_units=len(candidates))
        if m5:
            revealed = workflow.reviews.reveal(review_id)
            workflow.revealed = FrozenRecord.from_dict({"review_id": review_id, "submissions": [item.data() for item in revealed]})
        review_context = {"experiment": self.experiment_id, "m5_enabled": m5, "m4_enabled": m4,
            "review_id": review_id, "public_evidence_digest": evidence.content_hash,
            "decision_material": ({"kind": "sealed_review_submissions", "records": [item.data() for item in submissions]}
                                  if m5 else {"kind": "pre_registered_control_material", "record": material["summary_material"]}),
            "prediction_plan": prediction.data() if prediction else None,
            "scoring_status": "not_measured", "limitation": "same-model samples and role prompts do not establish independent training priors"}
        stage = workflow._trace("stage_7" if m5 else "operation_m5_control", "executed", **review_context)
        final = _final(workflow, cell=cell, scenario=scenario, model=model, package=package, stage=stage, review_context=review_context)
        return stage, final, tuple(responses + [final])


class Q42RoleDriver:
    experiment_id = "Q4.2"
    slots = ("initial", "final")
    execution_limit = 0
    docker_execution = "not_requested_by_driver"

    def run(self, workflow: "ModularWorkflow", *, cell: "PanelCell", scenario: FrozenRecord,
            model: "ModelPort", package: "CandidatePackage") -> tuple["WorkflowResult", FrozenRecord, tuple[FrozenRecord, ...]]:
        material = _material(workflow, scenario)
        m5, evidence = "M5" in workflow.enabled, FrozenRecord.from_dict(material["public_evidence"])
        name = cell.variant
        question = _QUESTIONS.get(name, _QUESTIONS["generic"])
        review_id = None
        if m5:
            review = workflow.reviews.open(task_binding=workflow.session.task.content_hash, evidence_snapshot=evidence.content_hash,
                roles=[{"role_id": "assigned_review", "question": question}], budget_units=1)
            review_id = review.review_id
        answer = workflow.invoke_model("initial", model, instruction="Answer only the assigned review question from the supplied public evidence.",
            module_context=_initial_context(cell=cell, scenario=scenario, evidence=evidence, question=question,
                material=material["summary_material"], m5=m5), evidence_only=True)
        submission = None
        if m5:
            submission = workflow.reviews.submit(review_id, role_id="assigned_review", reviewer_id="q42-reviewer", response=answer.data(), cost_units=1)
            workflow.revealed = FrozenRecord.from_dict({"review_id": review_id, "submissions": [item.data() for item in workflow.reviews.reveal(review_id)]})
        review_context = {"experiment": self.experiment_id, "m5_enabled": m5, "review_id": review_id,
            "public_evidence_digest": evidence.content_hash, "role_material": question,
            "decision_material": ({"kind": "sealed_review_submission", "record": submission.data()} if submission
                                  else {"kind": "pre_registered_control_material", "record": material["summary_material"]}),
            "scoring_status": "not_measured"}
        stage = workflow._trace("stage_7" if m5 else "operation_m5_control", "executed", **review_context)
        final = _final(workflow, cell=cell, scenario=scenario, model=model, package=package, stage=stage, review_context=review_context)
        return stage, final, (answer, final)


class Q44CounterexampleDriver(Q42RoleDriver):
    experiment_id = "Q4.4"

    def run(self, workflow: "ModularWorkflow", *, cell: "PanelCell", scenario: FrozenRecord,
            model: "ModelPort", package: "CandidatePackage") -> tuple["WorkflowResult", FrozenRecord, tuple[FrozenRecord, ...]]:
        material = _material(workflow, scenario)
        m5, evidence = "M5" in workflow.enabled, FrozenRecord.from_dict(material["public_evidence"])
        question = _QUESTIONS["counterexample"]
        review_id = None
        if m5:
            review = workflow.reviews.open(task_binding=workflow.session.task.content_hash, evidence_snapshot=evidence.content_hash,
                roles=[{"role_id": "counterexample", "question": question}], budget_units=1)
            review_id = review.review_id
        answer = workflow.invoke_model("initial", model, instruction="Assess only the supplied public evidence for the requested counterexample.",
            module_context=_initial_context(cell=cell, scenario=scenario, evidence=evidence, question=question,
                material=material["counterexample_material"], m5=m5), evidence_only=True)
        submission = None
        if m5:
            submission = workflow.reviews.submit(review_id, role_id="counterexample", reviewer_id="q44-reviewer", response=answer.data(), cost_units=1)
            workflow.revealed = FrozenRecord.from_dict({"review_id": review_id, "submissions": [item.data() for item in workflow.reviews.reveal(review_id)]})
        review_context = {"experiment": self.experiment_id, "m5_enabled": m5, "review_id": review_id,
            "public_evidence_digest": evidence.content_hash, "counterexample_material": material["counterexample_material"],
            "decision_material": ({"kind": "sealed_review_submission", "record": submission.data()} if submission
                                  else {"kind": "pre_registered_control_material", "record": material["summary_material"]}),
            "scoring_status": "not_measured"}
        stage = workflow._trace("stage_7" if m5 else "operation_m5_control", "executed", **review_context)
        final = _final(workflow, cell=cell, scenario=scenario, model=model, package=package, stage=stage, review_context=review_context)
        return stage, final, (answer, final)


class Q45SelfCorrectionDriver:
    experiment_id = "Q4.5"
    slots = ("initial_1", "initial_2", "revision_1", "revision_2", "final")
    execution_limit = 0
    docker_execution = "not_requested_by_driver"

    def slots_for(self, cell: "PanelCell") -> tuple[str, ...]:
        return self.slots if cell.variant == "heterogeneous" else ("initial_1", "revision_1", "final")

    @staticmethod
    def _routes(model: "ModelPort") -> Mapping[str, Mapping[str, Any]]:
        raise ContractError("Q4.5 heterogeneous configuration is unsupported without independently verified typed route evidence")

    def run(self, workflow: "ModularWorkflow", *, cell: "PanelCell", scenario: FrozenRecord,
            model: "ModelPort", package: "CandidatePackage") -> tuple["WorkflowResult", FrozenRecord, tuple[FrozenRecord, ...]]:
        material = _material(workflow, scenario)
        m5, evidence = "M5" in workflow.enabled, FrozenRecord.from_dict(material["public_evidence"])
        names = ("reviewer_one", "reviewer_two") if cell.variant == "heterogeneous" else ("reviewer_one",)
        routes = self._routes(model) if cell.variant == "heterogeneous" else {}
        review_id, submissions, initials, revisions = None, [], [], []
        if m5:
            review = workflow.reviews.open(task_binding=workflow.session.task.content_hash, evidence_snapshot=evidence.content_hash,
                roles=[{"role_id": name, "question": _QUESTIONS["generic"]} for name in names], budget_units=len(names))
            review_id = review.review_id
        for number, name in enumerate(names, 1):
            callback = routes[name]["callback"] if routes else model
            answer = workflow.invoke_model(f"initial_{number}", callback, instruction="Independently assess the supplied public evidence; identify a concern only when supported.",
                module_context=_initial_context(cell=cell, scenario=scenario, evidence=evidence, question=_QUESTIONS["generic"],
                    material={"blind_review": "public evidence only"}, m5=m5), evidence_only=True)
            initials.append(answer)
            if m5: submissions.append(workflow.reviews.submit(review_id, role_id=name, reviewer_id=f"q45-{name}", response=answer.data(), cost_units=1))
        revealed = workflow.reviews.reveal(review_id) if m5 else ()
        for number, name in enumerate(names, 1):
            callback = routes[name]["callback"] if routes else model
            context = {"panel_cell": _binding(cell, scenario), "review_phase": "post_initial_revision",
                "public_evidence": evidence.data(), "public_evidence_digest": evidence.content_hash,
                "initial_answer_material": material["initial_answer_material"], "summary_material": material["summary_material"], "m5_enabled": m5,
                "visible_reviews": [item.data() for item in revealed] if m5 else [initials[number - 1].data()]}
            if not m5:
                context.update({"control": "M5", "control_notice": "M5 review intervention disabled; only the caller's own prior response is supplied."})
            response = workflow.invoke_model(f"revision_{number}", callback, instruction="Revise only after considering the supplied prior review material.", module_context=FrozenRecord.from_dict(context))
            revisions.append(response)
            if m5: workflow.reviews.revise_after_reveal(review_id, role_id=name, reviewer_id=f"q45-{name}", response=response.data())
        review_context = {"experiment": self.experiment_id, "variant": cell.variant, "m5_enabled": m5, "review_id": review_id,
            "public_evidence_digest": evidence.content_hash,
            "decision_material": ({"kind": "sealed_review_revisions", "records": [item.data() for item in revisions]} if m5
                                  else {"kind": "pre_registered_control_material", "record": material["summary_material"]}),
            "heterogeneous_provider_configured": False, "scoring_status": "not_measured"}
        stage = workflow._trace("stage_7" if m5 else "operation_m5_control", "executed", **review_context)
        final = _final(workflow, cell=cell, scenario=scenario, model=model, package=package, stage=stage, review_context=review_context)
        return stage, final, tuple(initials + revisions + [final])
