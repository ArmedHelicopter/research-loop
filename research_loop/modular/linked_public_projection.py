"""Closed model-visible projection of verified linked mechanism provenance.

The full provenance record remains controller/scorer-only.  This module derives a
small, schema-checked public context from it; it never accepts caller summaries
or forwards precursor model requests.
"""
from __future__ import annotations

from typing import Any, Mapping

from research_loop.modular.contracts import FrozenRecord, PublicTask
from research_loop.modular.modules.predictions import PredictionRegistry
from research_loop.modular.modules.review import ReviewEngine
from research_loop.modular.panel_receipts import PanelCell, opaque_panel_cell_binding
from research_loop.ontology import ContractError

_SUPPORTED = frozenset({"Q1.5", "Q3.1", "Q4.3"})


def project_linked_public_context(*, provenance: FrozenRecord, cell: PanelCell,
                                  task: PublicTask, scenario: FrozenRecord) -> FrozenRecord:
    """Return the only predecessor record that a linked solver may expose.

    The projection is deterministically rebuilt from a full, already verified
    provenance receipt.  It contains actual typed mechanism outputs, not a
    callback-owned summary or a prior request envelope.
    """
    body = _verified_body(provenance, cell=cell, task=task, scenario=scenario)
    responses = _responses(body["responses"])
    final = _response(responses, "final")
    coverage = cell.coverage_id
    if coverage == "Q1.5":
        material = _q15_material(body["mechanism_stages"], responses)
    elif coverage == "Q3.1":
        material = _q31_material(task, body["mechanism_stages"], responses)
    elif coverage == "Q4.3":
        material = _q43_material(body["mechanism_stages"], responses)
    else:  # guarded above, retained for a closed extension point
        raise ContractError("linked public projection does not support this mechanism")
    return FrozenRecord.from_dict({
        "schema": "linked-public-mechanism-context-v1",
        "mechanism": coverage,
        "identity": task.identity.data(),
        "task_digest": task.content_hash,
        "scenario_digest": scenario.content_hash,
        "opaque_panel_cell": opaque_panel_cell_binding(cell),
        "full_provenance_digest": provenance.content_hash,
        "mechanism_material": material,
        "final_candidate": final,
    })


def verify_linked_public_context(*, projection: FrozenRecord, provenance: FrozenRecord,
                                  cell: PanelCell, task: PublicTask,
                                  scenario: FrozenRecord) -> FrozenRecord:
    """Fail closed unless a solver-visible record exactly rebuilds from provenance."""
    if not isinstance(projection, FrozenRecord):
        raise ContractError("linked public projection must be frozen")
    expected = project_linked_public_context(provenance=provenance, cell=cell, task=task, scenario=scenario)
    if projection.content_hash != expected.content_hash:
        raise ContractError("linked public projection is not the exact verified reconstruction")
    return expected


def _full_binding(cell: PanelCell) -> dict[str, Any]:
    return {"schema": "benchmark-cell-binding-v1", "cell_key": list(cell.key),
            "identity": cell.identity.data(), "task_digest": cell.task_digest,
            "scenario_digest": cell.scenario_digest, "package_digest": cell.package_digest,
            "arm": cell.runtime_arm.data()}


def _verified_body(provenance: FrozenRecord, *, cell: PanelCell, task: PublicTask,
                   scenario: FrozenRecord) -> dict[str, Any]:
    if not isinstance(provenance, FrozenRecord) or cell.coverage_id not in _SUPPORTED:
        raise ContractError("linked public projection needs supported frozen provenance")
    body = provenance.data()
    required = {"schema", "panel_cell", "identity", "task_digest", "scenario_digest", "package_digest", "arm",
                "runtime_trace_digest", "runtime_output_digest", "mechanism_stages", "responses"}
    if set(body) != required or body["schema"] != "verified-mechanism-provenance-v1":
        raise ContractError("linked provenance has an unexpected schema")
    if (body["panel_cell"] != _full_binding(cell) or body["identity"] != task.identity.data()
            or body["task_digest"] != task.content_hash or body["scenario_digest"] != scenario.content_hash
            or body["package_digest"] != cell.package_digest or body["arm"] != cell.runtime_arm.data()):
        raise ContractError("linked provenance does not bind this cell")
    if not isinstance(body["mechanism_stages"], list) or not body["mechanism_stages"] or not isinstance(body["responses"], list):
        raise ContractError("linked provenance lacks typed mechanism evidence")
    return body


def _responses(value: list[Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for call in value:
        if (not isinstance(call, Mapping) or set(call) != {"slot", "request_digest", "request", "response_digest", "response", "status"}
                or call["status"] != "responded" or not isinstance(call["slot"], str)
                or not isinstance(call["response"], Mapping)):
            raise ContractError("linked public projection requires completed typed model calls")
        response = FrozenRecord.from_dict(call["response"])
        if response.content_hash != call["response_digest"] or call["slot"] in result:
            raise ContractError("linked public projection has an unbound model response")
        # Requests are deliberately inspected only to prove the slot is genuine;
        # they are never returned in public context.
        if not isinstance(call["request"], Mapping) or call["request"].get("slot") != call["slot"]:
            raise ContractError("linked public projection response has no matching request")
        result[call["slot"]] = response.data()
    return result


def _stage(stages: list[Any], *, names: set[str]) -> dict[str, Any]:
    matches = [entry for entry in stages if isinstance(entry, Mapping) and set(entry) == {"stage", "data"}
               and entry["stage"] in names and isinstance(entry["data"], Mapping)]
    if len(matches) != 1:
        raise ContractError("linked public projection requires one actual mechanism stage")
    return dict(matches[0]["data"])


def _response(calls: Mapping[str, dict[str, Any]], slot: str) -> dict[str, Any]:
    try:
        return dict(calls[slot])
    except KeyError as exc:
        raise ContractError("linked public projection lacks a required mechanism response") from exc


def _q15_material(stages: list[Any], calls: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    stage = _stage(stages, names={"stage_9", "operation_m5_control"})
    for key in ("public_evidence", "history_summary", "initial_submission", "post_reveal_revision"):
        if key not in stage:
            raise ContractError("Q1.5 mechanism stage lacks declared review material")
    public_evidence, history = stage["public_evidence"], stage["history_summary"]
    if not isinstance(public_evidence, Mapping) or not isinstance(history, str) or not history.strip():
        raise ContractError("Q1.5 mechanism stage has invalid public review material")
    first, second = _response(calls, "initial_review"), _response(calls, "reveal_review")
    if stage.get("initial_submission") is None or stage.get("post_reveal_revision") is None:
        return {"kind": "historical_review_control", "public_evidence": dict(public_evidence),
                "historical_summary": history, "sealed_review": None}
    initial, revision = stage["initial_submission"], stage["post_reveal_revision"]
    if not isinstance(initial, Mapping) or not isinstance(revision, Mapping):
        raise ContractError("Q1.5 sealed review material is malformed")
    for item, response in ((initial, first), (revision, second)):
        if not isinstance(item.get("response"), Mapping) or FrozenRecord.from_dict(item["response"]).data() != response:
            raise ContractError("Q1.5 review response is not the actual stage material")
        ReviewEngine._response(response)
    return {"kind": "historical_review", "public_evidence": dict(public_evidence), "historical_summary": history,
            "sealed_review": {"initial": first, "revision": second}}


def _q31_material(task: PublicTask, stages: list[Any], calls: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    stage = _stage(stages, names={"stage_1", "operation_m4_control"})
    proposal = _response(calls, "scenario")
    if "plan_digest" not in stage:
        if stage.get("response_digest") != FrozenRecord.from_dict(proposal).content_hash:
            raise ContractError("Q3.1 control stage does not bind its actual response")
        return {"kind": "prediction_control", "prediction_plan": None}
    if not isinstance(stage["plan_digest"], str):
        raise ContractError("Q3.1 prediction stage lacks a plan digest")
    if set(proposal) != {"question", "branches", "budget_units"}:
        raise ContractError("Q3.1 plan response has an unexpected schema")
    plan = PredictionRegistry(task.identity).freeze(proposal["question"], proposal["branches"], budget_units=proposal["budget_units"])
    if plan.payload.content_hash != stage["plan_digest"]:
        raise ContractError("Q3.1 public plan is not bound to the mechanism stage")
    return {"kind": "prediction_plan", "prediction_plan": plan.payload.data()}


def _q43_material(stages: list[Any], calls: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    stage = _stage(stages, names={"stage_7", "operation_m5_control"})
    submitted, revised = stage.get("initial_submissions"), stage.get("post_reveal_revisions")
    if submitted is None or revised is None:
        raise ContractError("Q4.3 mechanism stage lacks review records")
    if not isinstance(submitted, list) or not isinstance(revised, list):
        raise ContractError("Q4.3 review records are malformed")
    if not submitted and not revised:
        return {"kind": "sealed_review_control", "revealed_review": None}
    initial = [_response(calls, slot) for slot in ("mechanism_initial", "measurement_initial")]
    revisions = [_response(calls, slot) for slot in ("mechanism_revision", "measurement_revision")]
    for response in [*initial, *revisions]:
        ReviewEngine._response(response)
    if len(submitted) != len(initial) or len(revised) != len(revisions):
        raise ContractError("Q4.3 sealed review records are incomplete")
    for item, response in zip(submitted, initial):
        if not isinstance(item, Mapping) or not isinstance(item.get("response"), Mapping) or FrozenRecord.from_dict(item["response"]).data() != response:
            raise ContractError("Q4.3 submission is not bound to its model response")
    for item, response in zip(revised, revisions):
        if not isinstance(item, Mapping) or not isinstance(item.get("response"), Mapping) or FrozenRecord.from_dict(item["response"]).data() != response:
            raise ContractError("Q4.3 revision is not bound to its model response")
    return {"kind": "sealed_review", "revealed_review": {"initial": initial, "revisions": revisions}}
