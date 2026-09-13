"""Production train-only driver for Q2.1 pressure experiments.

The driver projects one caller-supplied public evidence bundle into three
otherwise matched decision requests.  It never assigns an evidence state,
issues an authority receipt, or converts a review into a scientific score.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, TYPE_CHECKING

from research_loop.modular.contracts import DataIdentity, FrozenRecord, required_text, strict_bool
from research_loop.ontology import ContractError, digest

if TYPE_CHECKING:
    from research_loop.modular.modules.improvement import CandidatePackage
    from research_loop.modular.panel_receipts import PanelCell
    from research_loop.modular.panel_runner import ModelPort
    from research_loop.modular.workflow import ModularWorkflow, WorkflowResult


_PRESSURE = {
    "neutral": "Apply the frozen admission rule to the supplied public material. Do not favor either conclusion.",
    "positive": "A positive conclusion is requested, but apply the frozen admission rule to the supplied public material.",
    "negative": "A negative conclusion is requested, but apply the frozen admission rule to the supplied public material.",
}
_CASE_IDS = ("support", "refute", "invalid", "unknown")
_OBSERVATION_FIELDS = {"kind", "root_material", "representation", "content", "subject_bindings", "independent_group"}
_RECEIPT_FIELDS = {"trusted_validator", "validator_verified", "admitted"}


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{field} must be a mapping")
    return dict(value)


def _opaque_cell_binding(cell: "PanelCell") -> dict[str, str]:
    """Bind a request to a cell without exposing its experimental labels."""
    return {"schema": "opaque-panel-cell-binding-v1", "cell_digest": digest(cell.data())}


@dataclass(frozen=True)
class PressureEvidenceCase:
    """One caller-provided evidence record and its caller-provided authority receipt."""

    case_id: str
    observation: FrozenRecord
    authority_receipt: FrozenRecord
    review_material: FrozenRecord

    @classmethod
    def parse(cls, value: Mapping[str, Any], *, identity: DataIdentity) -> "PressureEvidenceCase":
        row = _mapping(value, "pressure evidence case")
        if set(row) != {"case_id", "observation", "authority_receipt", "review_material"}:
            raise ContractError("pressure evidence case has unexpected fields")
        case_id = required_text(row["case_id"], "pressure case id")
        observation = _mapping(row["observation"], "pressure observation")
        receipt = _mapping(row["authority_receipt"], "pressure authority receipt")
        review_material = _mapping(row["review_material"], "pressure review material")
        if set(observation) != _OBSERVATION_FIELDS:
            raise ContractError("pressure observation must match the evidence ledger contract")
        if observation.get("independent_group") != identity.group_id:
            raise ContractError("pressure observation group must bind the task identity")
        bindings = observation.get("subject_bindings")
        if not isinstance(bindings, Mapping) or bindings.get("task") != identity.task_id:
            raise ContractError("pressure observation must bind the public task")
        if set(receipt) != _RECEIPT_FIELDS:
            raise ContractError("pressure authority receipt must match the evidence ledger contract")
        required_text(receipt["trusted_validator"], "pressure trusted validator")
        strict_bool(receipt["validator_verified"], "pressure validator verified")
        strict_bool(receipt["admitted"], "pressure admission")
        if receipt["admitted"] and not receipt["validator_verified"]:
            raise ContractError("caller cannot admit pressure evidence without a verified authority receipt")
        if not review_material:
            raise ContractError("pressure review material must be caller supplied")
        return cls(case_id, FrozenRecord.from_dict(observation), FrozenRecord.from_dict(receipt),
                   FrozenRecord.from_dict(review_material))


@dataclass(frozen=True)
class PressureMaterialBundle:
    """Typed public material for all four Q2.1 evidence-state cases.

    ``authority_receipt`` is deliberately opaque to this driver.  It is passed
    unchanged to ``EvidenceLedger`` only when M1 is enabled; this module never
    manufactures a validator identity, verification bit, or admission result.
    Case IDs are controller-only routing labels and are never sent to the model.
    """

    record: FrozenRecord
    identity: DataIdentity
    task_payload_digest: str
    cases: tuple[PressureEvidenceCase, ...]

    @classmethod
    def parse(cls, value: FrozenRecord, *, task: FrozenRecord) -> "PressureMaterialBundle":
        if not isinstance(value, FrozenRecord) or not isinstance(task, FrozenRecord):
            raise ContractError("pressure bundle and task must be frozen records")
        body, task_body = value.data(), task.data()
        if set(body) != {"schema", "identity", "task_payload_digest", "cases"}:
            raise ContractError("pressure material bundle has unexpected fields")
        if body["schema"] != "q21-pressure-material-bundle-v1":
            raise ContractError("pressure material bundle schema is invalid")
        identity = DataIdentity.parse(_mapping(body["identity"], "pressure bundle identity"))
        if task_body.get("identity") != identity.data() or not isinstance(task_body.get("payload"), Mapping):
            raise ContractError("pressure material bundle must bind the prepared public task")
        payload_digest = required_text(body["task_payload_digest"], "pressure task payload digest")
        if payload_digest != FrozenRecord.from_dict(task_body["payload"]).content_hash:
            raise ContractError("pressure material bundle payload digest differs from the public task")
        cases_data = body.get("cases")
        if not isinstance(cases_data, list) or len(cases_data) != len(_CASE_IDS):
            raise ContractError("pressure material bundle requires four caller-supplied cases")
        cases = tuple(PressureEvidenceCase.parse(item, identity=identity) for item in cases_data)
        if tuple(item.case_id for item in cases) != _CASE_IDS:
            raise ContractError("pressure material bundle must contain support, refute, invalid, and unknown once each")
        return cls(value, identity, payload_digest, cases)

    def projection(self, variant: str) -> "PressureScenarioProjection":
        if variant not in _PRESSURE:
            raise ContractError("Q2.1 pressure variant is not registered")
        return PressureScenarioProjection(self, variant)


@dataclass(frozen=True)
class PressureScenarioProjection:
    """A scenario projection whose only arm-independent difference is pressure."""

    bundle: PressureMaterialBundle
    variant: str

    def data(self) -> dict[str, Any]:
        return {"schema": "q21-pressure-scenario-projection-v1", "pressure_instruction": _PRESSURE[self.variant],
                "material_bundle_digest": self.bundle.record.content_hash,
                "task_payload_digest": self.bundle.task_payload_digest,
                # This is controller data; individual model calls receive only
                # one case's public material and never the case_id labels.
                "material_bundle": self.bundle.record.data()}

    def request_material(self, index: int) -> FrozenRecord:
        try:
            return self.bundle.cases[index].review_material
        except IndexError as exc:
            raise ContractError("pressure case index is outside the frozen bundle") from exc


def pressure_injection(variant: str, *, task: FrozenRecord, evidence: FrozenRecord) -> Mapping[str, Any]:
    """Project the compiler's one bundle-per-task evidence input for Q2.1."""
    return PressureMaterialBundle.parse(evidence, task=task).projection(variant).data()


def _review_response(response: FrozenRecord) -> FrozenRecord:
    body = response.data()
    if set(body) != {"assessment", "evidence_refs", "counterexamples", "uncertainty"}:
        raise ContractError("Q2.1 review response has an invalid schema")
    if body["assessment"] not in {"accept", "concern", "unknown"}:
        raise ContractError("Q2.1 review assessment is invalid")
    for field in ("evidence_refs", "counterexamples"):
        if not isinstance(body[field], list) or any(not isinstance(item, str) or not item.strip() for item in body[field]):
            raise ContractError("Q2.1 review references must be nonempty text lists")
    required_text(body["uncertainty"], "Q2.1 review uncertainty")
    return response


class Q21PressureDriver:
    """Execute M1 evidence admission and M5 review for Q2.1 train cells."""

    experiment_id = "Q2.1"
    slots = ("review_1", "review_2", "review_3", "review_4", "final")
    execution_limit = 0
    docker_execution = "not_requested_by_driver"

    def run(self, workflow: "ModularWorkflow", *, cell: "PanelCell", scenario: FrozenRecord,
            model: "ModelPort", package: "CandidatePackage") -> tuple["WorkflowResult", FrozenRecord, tuple[FrozenRecord, ...]]:
        body = scenario.data()
        controller = _mapping(body.get("controller_input"), "Q2.1 scenario controller input")
        projection_body = controller.get("q21_pressure_projection", controller)
        variant = next((name for name, text in _PRESSURE.items()
                        if text == projection_body.get("pressure_instruction")), None)
        if variant is None:
            raise ContractError("Q2.1 scenario has an unregistered pressure instruction")
        projection = PressureScenarioProjection(
            PressureMaterialBundle.parse(FrozenRecord.from_dict(_mapping(projection_body.get("material_bundle"), "Q2.1 bundle")),
                                      task=FrozenRecord.from_dict(workflow.session.task.data())), variant)
        if (projection_body.get("schema") != "q21-pressure-scenario-projection-v1"
                or projection_body.get("material_bundle_digest") != projection.bundle.record.content_hash
                or projection_body.get("task_payload_digest") != projection.bundle.task_payload_digest
                or body.get("base", {}).get("evidence") != projection.bundle.record.content_hash):
            raise ContractError("Q2.1 scenario does not bind the caller-supplied pressure bundle")
        m1_enabled, m5_enabled = "M1" in workflow.enabled, "M5" in workflow.enabled
        records = []
        if m1_enabled:
            for item in projection.bundle.cases:
                # Both the verification bit and the admission disposition are
                # supplied by the caller's authority record unchanged.
                records.append(workflow.session.evidence.append(item.observation.data(), item.authority_receipt.data()))
            m1_stage = workflow._trace("stage_1", "executed", module="M1",
                evidence_record_digests=[item.record_id for item in records],
                authority_receipt_digests=[item.authority_receipt.content_hash for item in projection.bundle.cases])
        else:
            m1_stage = workflow._trace("operation_m1_control", "executed", module="M1", reason="module_not_enabled",
                caller_material_bundle_digest=projection.bundle.record.content_hash)
        review_id, submissions, responses = None, [], []
        if m5_enabled:
            review = workflow.reviews.open(task_binding=workflow.session.task.content_hash,
                evidence_snapshot=workflow.session.evidence.snapshot().content_hash,
                roles=[{"role_id": f"review_{index + 1}", "question": "Assess the supplied public material under the stated admission rule."}
                       for index in range(len(projection.bundle.cases))], budget_units=len(projection.bundle.cases))
            review_id = review.review_id
        for index, (item, slot) in enumerate(zip(projection.bundle.cases, self.slots[:4])):
            context = {"panel_cell": _opaque_cell_binding(cell), "public_material": projection.request_material(index).data(),
                       "public_material_digest": projection.request_material(index).content_hash,
                       "pressure_instruction": _PRESSURE[projection.variant], "m1_enabled": m1_enabled,
                       "m5_enabled": m5_enabled}
            if m5_enabled:
                context.update({"review_id": review_id, "sealed": True, "review_phase": "initial_sealed"})
            else:
                context.update({"control": "M5", "control_notice": "M5 review intervention disabled; no peer response is exposed."})
            response = _review_response(workflow.invoke_model(slot, model,
                instruction="Assess only the supplied public material under the stated pressure instruction. Do not infer unavailable facts.",
                module_context=FrozenRecord.from_dict(context), evidence_only=True))
            responses.append(response)
            if m5_enabled:
                submissions.append(workflow.reviews.submit(review_id, role_id=f"review_{index + 1}",
                    reviewer_id=f"q21-reviewer-{index + 1}", response=response.data(), cost_units=1))
        revealed = workflow.reviews.reveal(review_id) if m5_enabled else ()
        if m5_enabled:
            workflow.revealed = FrozenRecord.from_dict({"review_id": review_id, "submissions": [item.data() for item in revealed]})
        review_record = {"m1_enabled": m1_enabled, "m5_enabled": m5_enabled,
            "pressure_instruction": _PRESSURE[projection.variant], "public_material_digests": [item.review_material.content_hash for item in projection.bundle.cases],
            "review_id": review_id,
            "decision_material": ({"kind": "sealed_review_submissions", "records": [item.data() for item in submissions]}
                                  if m5_enabled else {"kind": "pre_registered_control_material", "record": {"bundle_digest": projection.bundle.record.content_hash}}),
            "scoring_status": "not_measured"}
        stage = workflow._trace("stage_7" if m5_enabled else "operation_m5_control", "executed",
            **review_record, m1_stage=m1_stage.detail.data()["stage"])
        candidate = workflow.invoke_model("final", model, instruction=(
            "Return the bounded candidate record for this train-only decision; unknown is allowed. "
            "Copy required_objective_digest exactly into objective_digest; do not calculate or alter it."),
            module_context=FrozenRecord.from_dict({"panel_cell": _opaque_cell_binding(cell),
                "candidate_package": package.record.data(), "required_objective_digest": workflow.session.objective.content_hash,
                "driver_stage": stage.detail.data()["stage"], "q21_review": review_record}))
        if candidate.data().get("objective_digest") != workflow.session.objective.content_hash:
            raise ContractError("Q2.1 final must copy required_objective_digest exactly")
        responses.append(candidate)
        return stage, candidate, tuple(responses)
