"""Closed production review drivers for the remaining Q4 interventions."""
from __future__ import annotations

from typing import Any, Mapping, TYPE_CHECKING

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.modules.predictions import freeze_shared_experiment
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


def _public_evidence(workflow: "ModularWorkflow") -> FrozenRecord:
    """The prepared task payload is the only evidence this driver can expose."""
    return FrozenRecord.from_dict(workflow.session.task.payload.data())


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
                     material: str, m5: bool, m4: bool = False) -> FrozenRecord:
    # Deliberately exclude controller data, reviewer/provider identity, variant
    # labels and any response.  The blind call receives only public material.
    context = {"review_phase": "initial_blind", "public_evidence": evidence.data(), "public_evidence_digest": evidence.content_hash,
        "assigned_review_material": material, "assigned_question": question,
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
        m5, m4, evidence = "M5" in workflow.enabled, "M4" in workflow.enabled, _public_evidence(workflow)
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
            raw = workflow.invoke_model(f"initial_{number}", model, instruction="Answer only the assigned review question from the supplied public evidence.",
                module_context=_initial_context(cell=cell, scenario=scenario, evidence=evidence, question=_QUESTIONS[name],
                    material="same-model sample" if cell.variant == "independent_samples" else "assigned review question", m5=m5, m4=m4), evidence_only=True)
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
            "review_id": review_id, "public_evidence": evidence.data(), "initial_answers": [item.data() for item in responses],
            "sealed_submissions": [item.data() for item in submissions] if m5 else [],
            "prediction_plan": prediction.data() if prediction else None,
            "limitation": "same-model samples and role prompts do not establish independent training priors"}
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
        m5, evidence = "M5" in workflow.enabled, _public_evidence(workflow)
        name = cell.variant
        question = _QUESTIONS.get(name, _QUESTIONS["generic"])
        review_id = None
        if m5:
            review = workflow.reviews.open(task_binding=workflow.session.task.content_hash, evidence_snapshot=evidence.content_hash,
                roles=[{"role_id": "assigned_review", "question": question}], budget_units=1)
            review_id = review.review_id
        answer = workflow.invoke_model("initial", model, instruction="Answer only the assigned review question from the supplied public evidence.",
            module_context=_initial_context(cell=cell, scenario=scenario, evidence=evidence, question=question,
                material="assigned role material", m5=m5), evidence_only=True)
        submission = None
        if m5:
            submission = workflow.reviews.submit(review_id, role_id="assigned_review", reviewer_id="q42-reviewer", response=answer.data(), cost_units=1)
            workflow.revealed = FrozenRecord.from_dict({"review_id": review_id, "submissions": [item.data() for item in workflow.reviews.reveal(review_id)]})
        review_context = {"experiment": self.experiment_id, "m5_enabled": m5, "review_id": review_id,
            "public_evidence": evidence.data(), "role_material": question, "initial_answer": answer.data(),
            "sealed_submission": submission.data() if submission else None}
        stage = workflow._trace("stage_7" if m5 else "operation_m5_control", "executed", **review_context)
        final = _final(workflow, cell=cell, scenario=scenario, model=model, package=package, stage=stage, review_context=review_context)
        return stage, final, (answer, final)


class Q44CounterexampleDriver(Q42RoleDriver):
    experiment_id = "Q4.4"

    def run(self, workflow: "ModularWorkflow", *, cell: "PanelCell", scenario: FrozenRecord,
            model: "ModelPort", package: "CandidatePackage") -> tuple["WorkflowResult", FrozenRecord, tuple[FrozenRecord, ...]]:
        m5, evidence = "M5" in workflow.enabled, _public_evidence(workflow)
        question = _QUESTIONS["counterexample"]
        review_id = None
        if m5:
            review = workflow.reviews.open(task_binding=workflow.session.task.content_hash, evidence_snapshot=evidence.content_hash,
                roles=[{"role_id": "counterexample", "question": question}], budget_units=1)
            review_id = review.review_id
        answer = workflow.invoke_model("initial", model, instruction="Assess only the supplied public evidence for the requested counterexample.",
            module_context=_initial_context(cell=cell, scenario=scenario, evidence=evidence, question=question,
                material="counterexample material", m5=m5), evidence_only=True)
        submission = None
        if m5:
            submission = workflow.reviews.submit(review_id, role_id="counterexample", reviewer_id="q44-reviewer", response=answer.data(), cost_units=1)
            workflow.revealed = FrozenRecord.from_dict({"review_id": review_id, "submissions": [item.data() for item in workflow.reviews.reveal(review_id)]})
        review_context = {"experiment": self.experiment_id, "m5_enabled": m5, "review_id": review_id,
            "public_evidence": evidence.data(), "counterexample_material": question, "initial_answer": answer.data(),
            "sealed_submission": submission.data() if submission else None}
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
        routes = getattr(model, "heterogeneous_reviewers", None)
        if not isinstance(routes, Mapping) or set(routes) != {"reviewer_one", "reviewer_two"}:
            raise ContractError("Q4.5 heterogeneous configuration is unsupported without two configured providers")
        checked = {}
        for name, route in routes.items():
            if not isinstance(route, Mapping) or set(route) != {"provider", "model_id", "callback"} or not callable(route["callback"]):
                raise ContractError("Q4.5 heterogeneous reviewer route is incomplete")
            if not isinstance(route["provider"], str) or not route["provider"] or not isinstance(route["model_id"], str) or not route["model_id"]:
                raise ContractError("Q4.5 heterogeneous reviewer provenance is incomplete")
            checked[name] = route
        if len({(row["provider"], row["model_id"]) for row in checked.values()}) < 2:
            raise ContractError("Q4.5 heterogeneous reviewers need distinct configured provider/model identities")
        return checked

    def run(self, workflow: "ModularWorkflow", *, cell: "PanelCell", scenario: FrozenRecord,
            model: "ModelPort", package: "CandidatePackage") -> tuple["WorkflowResult", FrozenRecord, tuple[FrozenRecord, ...]]:
        m5, evidence = "M5" in workflow.enabled, _public_evidence(workflow)
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
                    material="self-correction initial material", m5=m5), evidence_only=True)
            initials.append(answer)
            if m5: submissions.append(workflow.reviews.submit(review_id, role_id=name, reviewer_id=f"q45-{name}", response=answer.data(), cost_units=1))
        revealed = workflow.reviews.reveal(review_id) if m5 else ()
        for number, name in enumerate(names, 1):
            callback = routes[name]["callback"] if routes else model
            context = {"panel_cell": _binding(cell, scenario), "review_phase": "post_initial_revision",
                "public_evidence": evidence.data(), "public_evidence_digest": evidence.content_hash,
                "revision_material": "reconsider the actual initial review response", "m5_enabled": m5,
                "visible_reviews": [item.data() for item in revealed] if m5 else [initials[number - 1].data()]}
            if not m5:
                context.update({"control": "M5", "control_notice": "M5 review intervention disabled; only the caller's own prior response is supplied."})
            response = workflow.invoke_model(f"revision_{number}", callback, instruction="Revise only after considering the supplied prior review material.", module_context=FrozenRecord.from_dict(context))
            revisions.append(response)
            if m5: workflow.reviews.revise_after_reveal(review_id, role_id=name, reviewer_id=f"q45-{name}", response=response.data())
        review_context = {"experiment": self.experiment_id, "variant": cell.variant, "m5_enabled": m5, "review_id": review_id,
            "public_evidence": evidence.data(), "initial_answers": [item.data() for item in initials],
            "sealed_submissions": [item.data() for item in submissions] if m5 else [], "post_reveal_revisions": [item.data() for item in revisions],
            "heterogeneous_provider_configured": cell.variant == "heterogeneous"}
        stage = workflow._trace("stage_7" if m5 else "operation_m5_control", "executed", **review_context)
        final = _final(workflow, cell=cell, scenario=scenario, model=model, package=package, stage=stage, review_context=review_context)
        return stage, final, tuple(initials + revisions + [final])
