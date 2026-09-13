"""Closed production driver for Q1.5 historical-summary review order."""
from __future__ import annotations

from typing import TYPE_CHECKING

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.scenarios_history import Q15ReviewMaterial
from research_loop.ontology import ContractError

if TYPE_CHECKING:
    from research_loop.modular.modules.improvement import CandidatePackage
    from research_loop.modular.panel_receipts import PanelCell
    from research_loop.modular.panel_runner import ModelPort
    from research_loop.modular.workflow import ModularWorkflow, WorkflowResult


class Q15HistoryReviewDriver:
    """Run the two registered Q1.5 order variants without fixture callbacks."""
    experiment_id = "Q1.5"
    slots = ("initial_review", "reveal_review", "final")
    execution_limit = 0
    docker_execution = "not_requested_by_driver"

    def slots_for(self, cell: "PanelCell") -> tuple[str, ...]:
        return self.slots

    def run(self, workflow: "ModularWorkflow", *, cell: "PanelCell", scenario: FrozenRecord,
            model: "ModelPort", package: "CandidatePackage") -> tuple["WorkflowResult", FrozenRecord, tuple[FrozenRecord, ...]]:
        binding = {"experiment_id": cell.coverage_id, "variant": cell.variant,
                   "replicate": cell.replicate, "arm_id": cell.arm_id,
                   "scenario_digest": scenario.content_hash}
        scenario_body = scenario.data()
        controller = scenario_body["controller_input"]
        material = controller.get("q15_review_material")
        material_digest = controller.get("q15_review_material_digest")
        if (not isinstance(material, dict) or not isinstance(material_digest, str)
                or scenario_body["base"].get("evidence") != material_digest
                or FrozenRecord.from_dict(material).content_hash != material_digest):
            raise ContractError("Q1.5 scenario lacks material bound to base evidence")
        Q15ReviewMaterial(FrozenRecord.from_dict(material), task_identity=workflow.session.task.identity.data())
        public_evidence = FrozenRecord.from_dict(material["public_evidence"])
        history_summary = material["historical_summary"]
        controller_projection = {"fixture_only": controller.get("fixture_only"),
            "auxiliary": controller.get("auxiliary"), "q15_review_material_digest": material_digest}
        m5_enabled = "M5" in workflow.enabled
        first_has_summary = cell.variant == "summary_first"
        review_id = None
        submission = revision = None
        if m5_enabled:
            review = workflow.reviews.open(task_binding=workflow.session.task.content_hash,
                evidence_snapshot=public_evidence.content_hash,
                roles=[{"role_id": "evidence", "question": "What does the supplied public evidence justify?"}], budget_units=1)
            review_id = review.review_id
        initial_context = {"panel_cell": binding, "scenario_controller_input": controller_projection,
            "candidate_package": package.record.data(), "review_phase": "initial",
            "public_evidence": public_evidence.data(), "public_evidence_digest": public_evidence.content_hash,
            "historical_summary": history_summary if first_has_summary else None,
            "summary_visibility": "before_initial_review" if first_has_summary else "withheld_until_after_initial_review"}
        if m5_enabled:
            initial_context.update({"review_id": review_id, "sealed": True})
        else:
            initial_context.update({"control": "M5", "control_notice": "M5 review intervention disabled; no submission is sealed or revealed."})
        first = workflow.invoke_model("initial_review", model, instruction="Assess the supplied public evidence under the frozen objective.",
            module_context=FrozenRecord.from_dict(initial_context), evidence_only=True)
        if m5_enabled:
            submission = workflow.reviews.submit(review_id, role_id="evidence", reviewer_id="q15-evidence-reviewer",
                response=first.data(), cost_units=1)
            revealed = workflow.reviews.reveal(review_id)[0]
        else:
            revealed = None
        # ``summary_first`` consumed the only historical-summary exposure in
        # its first pass. The follow-up sees the sealed response and identical
        # evidence, but does not receive the prose again.
        reveal_context = {"panel_cell": binding, "scenario_controller_input": controller_projection,
            "candidate_package": package.record.data(), "review_phase": "after_initial_review",
            "public_evidence": public_evidence.data(), "public_evidence_digest": public_evidence.content_hash,
            "historical_summary": history_summary if not first_has_summary else None,
            "summary_visibility": "after_sealed_initial_review" if not first_has_summary else "already_visible_before_initial_review"}
        if m5_enabled:
            reveal_context.update({"review_id": review_id, "sealed_submission": revealed.data()})
        else:
            reveal_context.update({"control": "M5", "sealed_submission": None,
                "control_notice": "M5 review intervention disabled; prior response is not exposed."})
        second = workflow.invoke_model("reveal_review", model, instruction="Reassess only the same public evidence under the declared summary visibility.",
            module_context=FrozenRecord.from_dict(reveal_context))
        if m5_enabled:
            revision = workflow.reviews.revise_after_reveal(review_id, role_id="evidence", reviewer_id="q15-evidence-reviewer", response=second.data())
        review_context = {"m5_enabled": m5_enabled, "variant": cell.variant, "review_id": review_id,
            "public_evidence": public_evidence.data(), "history_summary": history_summary,
            "initial_submission": submission.data() if submission else None,
            "post_reveal_revision": revision.data() if revision else None}
        stage = workflow._trace("stage_9" if m5_enabled else "operation_m5_control", "executed", **review_context)
        candidate = workflow.invoke_model("final", model, instruction=(
            "Return the bounded candidate record for this train-only run; unknown is allowed. "
            "Copy required_objective_digest exactly into objective_digest; do not calculate or alter it."),
            module_context=FrozenRecord.from_dict({"panel_cell": binding, "candidate_package": package.record.data(),
                "required_objective_digest": workflow.session.objective.content_hash, "driver_stage": stage.detail.data()["stage"],
                "q15_review": review_context}))
        if candidate.data().get("objective_digest") != workflow.session.objective.content_hash:
            raise ContractError("Q1.5 final must copy required_objective_digest exactly")
        return stage, candidate, (first, second, candidate)
