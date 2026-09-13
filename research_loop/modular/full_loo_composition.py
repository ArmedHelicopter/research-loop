"""Frozen C4 full/leave-one-out composition for the nine-module bundle.

This is a TRAIN-only planning and composition seam.  It deliberately has no
model, reference, scorer, validation, or deployment port: those are injected
by the existing restricted builders, Docker runner, and independent scorer.
The record is useful only when the caller binds those ports to every frozen
cell.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError


MODULES = ("M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9")
SCHEMA = "c4-full-loo-composition-v2"
LEGACY_SCHEMA = "c4-full-loo-composition-v1"
EXPOSURE_CLASS = "c4-history-build-target-boundary-v1"

# An on level must be removed at both stages for a whole-pipeline F-Mi.  M9 is
# intentionally history/build-only: it selects a fixed candidate before target
# I/O and must not learn from a target result.  M8 is target-only.  That is a
# real boundary, so M8 target changes share a candidate with identical history
# inputs; a target bit may never cause a fresh build.
BOUNDARIES = {
    "M1": ("history_build", "target"), "M2": ("history_build", "target"),
    "M3": ("history_build", "target"), "M4": ("history_build", "target"),
    "M5": ("history_build", "target"), "M6": ("history_build", "target"),
    "M7": ("history_build", "target"), "M8": ("target",),
    "M9": ("history_build",),
}

_MODULE_OPERATIONS = {
    "M1": "admission", "M2": "subject_bound_evidence", "M3": "lineage_context",
    "M4": "frozen_prediction", "M5": "independent_review", "M6": "provenance_retrieval",
    "M7": "bounded_exploration", "M8": "bounded_scheduler", "M9": "history_candidate_selection",
}
_CONTROL_OPERATIONS = (
    "ordinary_plan", "ordinary_retrieval", "ordinary_critique_a", "ordinary_critique_b",
    "ordinary_execution", "ordinary_revision",
)
_HISTORY_SLOT_SCHEDULE = ("plan_or_prediction", "review_a", "review_b", "bounded_choice", "candidate_procedure")
_TARGET_SLOT_SCHEDULE = ("plan_or_prediction", "review_a", "review_b", "bounded_choice", "solver_analysis", "solver_final")


def _bits(enabled: Iterable[str]) -> dict[str, int]:
    active = set(enabled)
    return {name: int(name in active) for name in MODULES}


def _levels(enabled: Iterable[str], stage: str) -> dict[str, int]:
    active = set(enabled)
    return {name: int(name in active and stage in BOUNDARIES[name]) for name in MODULES}


def _bindings(active: set[str], procedure: str, stage: str, schema: str) -> list[dict]:
    """Every operation states the next consumer before any fresh execution."""
    ordinary = procedure in {"baseline_b0", "ordinary_matched_control"}
    staged = {name for name in active if stage in BOUNDARIES[name]}
    names = {
        "M1": "ordinary_admission" if ordinary or "M1" not in staged else "admission",
        "M2": "ordinary_evidence" if ordinary or "M2" not in active else "subject_bound_evidence",
        "M3": "ordinary_context" if ordinary or "M3" not in active else "lineage_context",
        "M4": "ordinary_plan" if ordinary or "M4" not in active else "frozen_prediction",
        "M5": "ordinary_critique" if ordinary or "M5" not in active else "independent_review",
        "M6": "ordinary_retrieval" if ordinary or "M6" not in active else "provenance_retrieval",
        "M7": "ordinary_choice" if ordinary or "M7" not in active else "bounded_exploration",
        "M8": "ordinary_execution_schedule" if ordinary or "M8" not in staged else "bounded_scheduler",
        "M9": "ordinary_history_candidate" if ordinary or "M9" not in active else "history_candidate_selection",
    }
    if procedure == "baseline_b0" and stage == "target":
        return [{"operation": "baseline_solver", "purpose": "reference_answer", "output_consumer": "common_solve"}]
    rows = [
        {"operation": names["M1"], "purpose": "admit_work", "output_consumer": names["M2"]},
        {"operation": names["M2"], "purpose": "bind_subject_evidence", "output_consumer": names["M3"]},
        {"operation": names["M3"], "purpose": "construct_lineage_context", "output_consumer": names["M4"]},
        {"operation": names["M4"], "purpose": "freeze_prediction_before_measurement", "output_consumer": names["M5"]},
        {"operation": names["M5"] + "_a", "purpose": "sealed_independent_review", "output_consumer": names["M5"] + "_reveal"},
        {"operation": names["M5"] + "_b", "purpose": "sealed_independent_review", "output_consumer": names["M5"] + "_reveal"},
        {"operation": names["M5"] + "_reveal", "purpose": "reveal_after_both_seals", "output_consumer": names["M6"]},
        {"operation": names["M6"], "purpose": "fixed_three_lane_retrieval", "output_consumer": names["M7"]},
        {"operation": names["M7"], "purpose": "choose_before_new_auxiliary_measurement", "output_consumer": names["M8"]},
        {"operation": names["M8"], "purpose": "run_selected_auxiliary_measurements", "output_consumer": "common_solve"},
    ]
    if stage == "history_build":
        rows.append({"operation": names["M9"], "purpose": "freeze_train_candidate", "output_consumer": "candidate_package"})
    if schema == SCHEMA:
        if "M4" not in staged:
            rows[3]["purpose"] = "ordinary_plan_before_measurement"
        if "M5" not in staged:
            rows[4].update(purpose="ordinary_first_critique", output_consumer=names["M5"] + "_b")
            rows[5]["purpose"] = "ordinary_sequential_critique_with_first_response"
            rows[6]["purpose"] = "assemble_ordinary_revision_context"
    return rows


def _arm(*, arm_id: str, procedure: str, enabled: Iterable[str], comparison: str,
         history_binding_digest: str, builder_digest: str, history_input_budget: int,
         schema: str, removal: str | None = None, status: str = "executable", reason: str | None = None) -> dict:
    active = tuple(sorted(enabled))
    row = {
        "id": arm_id, "status": status, "procedure": procedure, "comparison": comparison,
        "arm_bits": _bits(active), "history_build_levels": _levels(active, "history_build"),
        "target_levels": _levels(active, "target"), "exposure_class": EXPOSURE_CLASS,
        "candidate_selection_stage": "history_build_only",
        "history_candidate_procedure": "m9_train_optimizer" if "M9" in active else "ordinary_history_candidate",
        "history_binding_digest": history_binding_digest, "builder_digest": builder_digest,
        "history_input_budget": history_input_budget,
        # The strong control and every LOO retain these exact opportunities.
        # Their ordinary procedures are not aliases for an off module.
        "history_slot_schedule": list(_HISTORY_SLOT_SCHEDULE),
        "target_slot_schedule": (["solver_analysis", "solver_final"] if procedure == "baseline_b0"
                                 else list(_TARGET_SLOT_SCHEDULE)),
        "history_operation_bindings": ([] if status != "executable" else _bindings(active, procedure, "history_build", schema)),
        "target_operation_bindings": ([] if status != "executable" else _bindings(active, procedure, "target", schema)),
        "operations": ([] if status != "executable" else
                       list(_CONTROL_OPERATIONS) if procedure == "ordinary_matched_control" else
                       [] if procedure == "baseline_b0" else
                       [_MODULE_OPERATIONS[m] for m in MODULES if m in active]),
    }
    if removal is not None:
        row["removed_module"] = removal
        row["estimand"] = "whole_pipeline_full_minus_" + removal
    if reason is not None:
        row["reason"] = reason
    return row


def derive_allocation(cells: Iterable[Mapping[str, object]], *, target_count: int) -> dict:
    """Calculate, rather than hand-copy, the resource denominator from recipes."""
    if type(target_count) is not int or target_count < 1:
        raise ContractError("positive frozen TRAIN target count required")
    cells = tuple(cells)
    executable = [dict(c) for c in cells if c.get("status") == "executable"]
    # Procedure identity is in the key, so B0 and the useful control cannot
    # silently share a no-module candidate.
    keys = {candidate_build_key(c) for c in executable}
    by_key = {candidate_build_key(c): c for c in executable}
    target_cells = len(executable) * target_count
    # Each canonical build has the same one-plan/two-review/one-choice/one-
    # candidate schedule.  Each full/LOO/strong-control target has six slots;
    # B0 remains a separately reported two-slot reference procedure.
    build_slots = len(by_key) * len(_HISTORY_SLOT_SCHEDULE)
    b0_cells = [c for c in executable if c["procedure"] == "baseline_b0"]
    strong_cells = [c for c in executable if c["procedure"] != "baseline_b0"]
    target_model_calls = target_count * (len(strong_cells) * len(_TARGET_SLOT_SCHEDULE) + len(b0_cells) * 2)
    # Actual restricted auxiliary executions are selected after the frozen
    # prediction/review/choice stages.  Fixed three-lane retrieval is issued
    # prospectively for every non-B0 build/target recipe.  Qualification is a
    # common independent safety boundary and covers every build and target.
    retrieval_recipes = len(by_key) + len(strong_cells) * target_count
    return {
        "target_count": target_count, "executable_arm_procedures": len(executable),
        "structural_arm_procedures": len(cells) - len(executable),
        "unique_canonical_builds": len(keys), "builder_proposals": len(keys),
        "builder_executions": len(keys), "history_model_calls": build_slots, "target_cells": target_cells,
        "target_model_calls": target_model_calls, "model_calls": build_slots + target_model_calls,
        "independent_source_qualification_calls": 2 * (len(by_key) + target_cells),
        "corpus_qualification_calls": 2 * retrieval_recipes,
        "retrieval_requests": 3 * retrieval_recipes,
        "history_auxiliary_docker_attempts": 2 * len(by_key),
        "target_auxiliary_docker_attempts": 2 * len(strong_cells) * target_count,
        "auxiliary_docker_attempts": 2 * retrieval_recipes, "solver_docker_attempts": target_cells,
        "docker_attempts": 2 * retrieval_recipes + target_cells, "scorer_calls": target_cells,
        "paid_calls": 0,
    }


@dataclass(frozen=True)
class FrozenFullLooPlan:
    record: FrozenRecord

    def __post_init__(self) -> None:
        if not isinstance(self.record, FrozenRecord):
            raise ContractError("C4 requires an immutable frozen record")
        validate_full_loo(self.record)

    @property
    def digest(self) -> str:
        return self.record.content_hash

    def data(self) -> dict:
        return self.record.data()


def _make_record(*, baseline_digest: str, train_task_digests: Iterable[str], issue_contract_ids: Iterable[str],
                 history_binding_digest: str, builder_digest: str, history_input_budget: int, schema: str = SCHEMA) -> FrozenRecord:
    """Freeze full, every requested LOO, B0, and the useful matched control."""
    tasks = tuple(train_task_digests)
    issues = tuple(issue_contract_ids)
    if len(tasks) != 2 or len(set(tasks)) != 2 or any(not isinstance(x, str) or len(x) != 64 for x in tasks):
        raise ContractError("C4 initial engineering slice requires two distinct TRAIN task digests")
    if len(issues) != 48 or len(set(issues)) != 48 or any(not isinstance(x, str) or not x for x in issues):
        raise ContractError("all 48 original issue contracts must remain frozen")
    compatibility = default_compatibility(baseline_digest)
    full = set(MODULES)
    if any(not isinstance(value, str) or len(value) != 64 for value in (history_binding_digest, builder_digest)) or type(history_input_budget) is not int or history_input_budget < 1:
        raise ContractError("C4 requires frozen history binding, builder version, and input budget")
    common = {"history_binding_digest": history_binding_digest, "builder_digest": builder_digest, "history_input_budget": history_input_budget, "schema": schema}
    cells = [_arm(arm_id="full", procedure="full_bundle", enabled=full, comparison="F", **common)]
    for module in MODULES:
        enabled = full - {module}
        try:
            compatibility.arm(enabled)
        except ContractError as exc:
            # A process-local set iteration error is not a canonical structural
            # reason. v2 records every missing direct dependency in fixed order.
            reason = str(exc) if schema == LEGACY_SCHEMA else "; ".join(
                spec['id'] + ' requires ' + ','.join(sorted(set(spec['requires']) - enabled))
                for spec in compatibility.manifest().data()['modules']
                if spec['id'] in enabled and set(spec['requires']) - enabled)
            cells.append(_arm(arm_id="without-" + module, procedure="unavailable", enabled=enabled,
                              **common,
                              comparison="F-minus", removal=module, status="structurally_unavailable", reason=reason))
        else:
            cells.append(_arm(arm_id="without-" + module, procedure="full_loo", enabled=enabled, **common,
                              comparison="F-minus", removal=module))
    cells += [
        _arm(arm_id="B0", procedure="baseline_b0", enabled=(), comparison="F-versus-B0", **common),
        _arm(arm_id="ordinary-control", procedure="ordinary_matched_control", enabled=(), comparison="F-versus-ordinary-control", **common),
    ]
    allocation = derive_allocation(cells, target_count=len(tasks))
    body = {
        "schema": schema, "domain": "train", "baseline_digest": baseline_digest,
        "compatibility": compatibility.manifest().data(), "modules": list(MODULES),
        "boundaries": {k: list(v) for k, v in BOUNDARIES.items()}, "cells": cells,
        "train_task_digests": list(tasks), "issue_contract_ids": list(issues), "allocation": allocation,
        "candidate_sharing_rule": "same exposure class and identical complete history/build factor settings only",
        "prediction_review_order": ("freeze_predictions_before_fresh_measurements_and_seal_reviews_before_cross_review_reveal" if schema == LEGACY_SCHEMA else
            "freeze_before_fresh_measurements; independent_reviews_seal_both_before_reveal; ordinary_critiques_are_sequential"),
        "scorer_scope": "independent_synthetic_train_only_v1", "validation_opened": False,
        "scientific_effectiveness_proven": False,
    }
    return FrozenRecord.from_dict(body)


def freeze_full_loo(*, baseline_digest: str, train_task_digests: Iterable[str], issue_contract_ids: Iterable[str],
                    history_binding_digest: str = "d" * 64, builder_digest: str = "e" * 64, history_input_budget: int = 4096) -> FrozenFullLooPlan:
    return FrozenFullLooPlan(_make_record(baseline_digest=baseline_digest, train_task_digests=train_task_digests,
                                          issue_contract_ids=issue_contract_ids, history_binding_digest=history_binding_digest,
                                          builder_digest=builder_digest, history_input_budget=history_input_budget))


def validate_full_loo(record: FrozenRecord) -> None:
    body = record.data()
    required = {"schema", "domain", "baseline_digest", "compatibility", "modules", "boundaries", "cells",
                "train_task_digests", "issue_contract_ids", "allocation", "candidate_sharing_rule",
                "prediction_review_order", "scorer_scope", "validation_opened", "scientific_effectiveness_proven"}
    if set(body) != required or body["schema"] not in {SCHEMA, LEGACY_SCHEMA} or body["domain"] != "train" or body["modules"] != list(MODULES):
        raise ContractError("C4 plan schema or domain drift")
    if body["boundaries"] != {k: list(v) for k, v in BOUNDARIES.items()}:
        raise ContractError("per-module history/build versus target boundary drift")
    first = body["cells"][0]
    rebuilt = _make_record(baseline_digest=body["baseline_digest"], train_task_digests=body["train_task_digests"], issue_contract_ids=body["issue_contract_ids"], history_binding_digest=first["history_binding_digest"], builder_digest=first["builder_digest"], history_input_budget=first["history_input_budget"], schema=body['schema'])
    if body['schema'] == LEGACY_SCHEMA:
        old = next(row for row in body['cells'] if row['id'] == 'without-M2')
        if old['reason'] not in {'M3 requires M2', 'M9 requires M2'}:
            raise ContractError('unknown legacy structural dependency reason')
        data = rebuilt.data()
        next(row for row in data['cells'] if row['id'] == 'without-M2')['reason'] = old['reason']
        rebuilt = FrozenRecord.from_dict(data)
    if rebuilt != record:
        raise ContractError("C4 cells, allocation, controls, or frozen policy drift")


def candidate_build_key(cell: Mapping[str, object]) -> tuple:
    """The only permitted candidate-sharing key for a composed target cell."""
    if cell.get("status") != "executable":
        raise ContractError("structural arm has no candidate build")
    return (cell.get("exposure_class"), cell.get("history_binding_digest"), cell.get("builder_digest"),
            cell.get("history_input_budget"), tuple(cell.get("history_slot_schedule", [])),
            tuple((r["operation"], r["purpose"], r["output_consumer"]) for r in cell.get("history_operation_bindings", [])),
            cell.get("history_candidate_procedure"), tuple(sorted(dict(cell["history_build_levels"]).items())))


def compose_common_solve_inputs(cell: Mapping[str, object], outputs: Mapping[str, object]) -> FrozenRecord:
    """Reject a solve that drops an enabled module or smuggles one into a control."""
    if cell.get("status") != "executable":
        raise ContractError("structural arm cannot reach the common solve")
    expected = tuple(cell["operations"])
    if tuple(outputs) != expected:
        raise ContractError("common solve must receive exactly the declared procedure outputs")
    if cell["procedure"] in {"baseline_b0", "ordinary_matched_control"}:
        if any(value in _MODULE_OPERATIONS.values() for value in outputs):
            raise ContractError("off control may not perform an on-module operation")
    return FrozenRecord.from_dict({"schema": "c4-common-solve-input-v1", "cell_id": cell["id"],
                                    "procedure": cell["procedure"], "operations": list(expected),
                                    "outputs": dict(outputs)})
