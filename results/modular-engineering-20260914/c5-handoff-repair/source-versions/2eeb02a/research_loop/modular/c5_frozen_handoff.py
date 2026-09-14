"""Immutable C5 structural preparation, without selection or acceptance authority.

The only source adapter is the binding-only M4/M5 CombinationPanel runner.
Its whole-arm package projections are not independently versioned module builds.
Original TRAIN journals are replayed at preparation and again before C5 freeze.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from types import MappingProxyType
from typing import Mapping, Sequence

from research_loop.modular.combination_panels import CombinationPanel, CombinationPanelVerifier
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord, required_text
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.panel_receipts import RuntimeReceipt
from research_loop.ontology import ContractError, canonical

SOURCE_ADAPTER = "m4-m5-combination-binding-only-v1"
_ARMS = frozenset({"00", "01", "10", "11"})
_BENCHMARKS = frozenset({"blade", "discoverybench"})


def _map(value, field, *, empty=False):
    if not isinstance(value, Mapping) or (not empty and not value):
        raise ContractError(f"{field} requires a nonempty mapping")
    if any(not isinstance(k, str) or not k.strip() for k in value):
        raise ContractError(f"{field} requires text keys")
    return MappingProxyType(dict(value))


def _record(value, field):
    if type(value) is not FrozenRecord:
        raise ContractError(f"{field} requires an exact frozen record")
    return value.data()


def _package(value):
    if type(value) is not CandidatePackage or value.record.data()["phase"] != "candidate":
        raise ContractError("C5 source requires an ordinary whole-arm CandidatePackage; Q6.3 stays separate")
    return value.record.data()


def _component_records(package):
    changes = _package(package)["changes"]
    return (FrozenRecord.from_dict({"schema": "c5-whole-arm-config-projection-v1",
                "package_digest": package.digest, "changes": changes}),
            FrozenRecord.from_dict({"schema": "c5-whole-arm-state-projection-v1",
                "package_digest": package.digest, "memory": changes.get("memory", {})}))


@dataclass(frozen=True)
class JointComponent:
    """Enabled-module identity with exact projections of its whole-arm package.

    The source does not expose separate component builds. These fields cannot
    assert independent module configuration, state, or scientific qualification.
    """
    component_id: str
    package: CandidatePackage
    config: FrozenRecord
    state_view: FrozenRecord

    def __post_init__(self):
        if self.component_id not in {"M4", "M5"}:
            raise ContractError("this C5 source adapter supports only M4/M5 package projections")
        if (self.config, self.state_view) != _component_records(self.package):
            raise ContractError("component config/state must be exact whole-arm package projections")

    @classmethod
    def from_package(cls, component_id, package):
        return cls(component_id, package, *_component_records(package))

    def data(self):
        return {"component_id": self.component_id, "package_digest": self.package.digest,
                "config_digest": self.config.content_hash, "state_view_digest": self.state_view.content_hash}


@dataclass(frozen=True)
class JointClosure:
    components: Mapping[str, JointComponent]
    package: CandidatePackage
    baseline: FrozenRecord
    background: FrozenRecord
    p0_control: FrozenRecord
    resource_schedule: FrozenRecord
    runtime_arm: FrozenRecord

    def __post_init__(self):
        _package(self.package)  # B0 also has an exact whole-arm package.
        components = _map(self.components, "joint components", empty=True)
        if any(type(v) is not JointComponent or k != v.component_id or v.package != self.package
               for k, v in components.items()):
            raise ContractError("components must bind this exact whole-arm package")
        base = _record(self.baseline, "baseline")
        if set(base) != {"baseline_digest"}:
            raise ContractError("baseline needs exactly its source digest")
        digest = base["baseline_digest"]
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ContractError("baseline must be a sha256 digest")
        if self.runtime_arm != default_compatibility(digest).arm(components):
            raise ContractError("closure activation must exactly equal its compatible component set")
        background = _record(self.background, "background")
        if (set(background) != {"schema", "baseline_digest", "fixed_modules", "objective"}
                or background["schema"] != "c5-binding-source-background-v1"
                or background["baseline_digest"] != digest or background["fixed_modules"] != []
                or not isinstance(background["objective"], dict) or not background["objective"]):
            raise ContractError("closure needs the exact fixed source background and objective")
        p0 = _record(self.p0_control, "P0")
        if p0 != {"schema": "c5-binding-source-p0-v1", "control_plane": "always_enabled",
                  "required_audit": ["measurement"], "terminal_stage": "final_decision"}:
            raise ContractError("closure requires the exact always-enabled P0 contract")
        schedule = _record(self.resource_schedule, "resource schedule")
        if schedule != {"schema": "c5-binding-source-schedule-v1", "slots": ["combination"],
                        "execution_limit": 0, "context_budget": 12000}:
            raise ContractError("closure resource schedule is outside the supported source adapter")
        object.__setattr__(self, "components", components)

    @property
    def digest(self):
        return FrozenRecord.from_dict({"schema": "c5-joint-closure-v3", "source_adapter": SOURCE_ADAPTER,
            "component_binding_status": "whole_arm_package_projections_only",
            "components": [self.components[k].data() for k in sorted(self.components)],
            "package_digest": self.package.digest, "baseline_digest": self.baseline.content_hash,
            "background_digest": self.background.content_hash, "p0_control_digest": self.p0_control.content_hash,
            "resource_schedule_digest": self.resource_schedule.content_hash,
            "runtime_arm_digest": self.runtime_arm.content_hash}).content_hash


def _source(panel, receipts):
    """Replay actual typed journals, then recognize only the concrete adapter."""
    if (type(panel) is not CombinationPanel or panel.domain != "train"
            or panel.obligation_id != "pair:M4+M5" or panel.estimand != "interaction_on_scale"
            or set(panel.required_benchmarks) != _BENCHMARKS):
        raise ContractError("C5 source supports only the typed binding-only M4/M5 TRAIN panel")
    baseline = panel.design.data()["compatibility"]["baseline_digest"]
    if panel.design != default_compatibility(baseline).factorial(("M4", "M5")):
        raise ContractError("C5 source requires the exact complete M4/M5 factorial")
    if any(type(row) is not RuntimeReceipt or row.status != "succeeded" for row in receipts):
        raise ContractError("C5 preparation requires complete successful runtime journals; failures remain source evidence")
    CombinationPanelVerifier().verify(panel, receipts)
    cells = {cell.key: cell for cell in panel.cells}
    closures = {}
    journal_bytes = {}
    packages = panel.package_bundle.data()["packages"]
    for receipt in receipts:
        cell = cells[receipt.cell_key]
        # Capture canonical original records. A later source rewrite cannot
        # silently change this preparation; the handoff replays them at freeze.
        lines = receipt.trace_path.read_text(encoding="utf-8").splitlines()
        events = [FrozenRecord(line).data() for line in lines]
        journal_bytes[canonical(list(cell.key))] = lines
        if [e["stage"] for e in events] != ["objective_lock", "model_request", "model_response", "final_decision"]:
            raise ContractError("runtime is outside the binding-only source adapter")
        lock = events[0]["data"]
        package = CandidatePackage(FrozenRecord.from_dict(packages[cell.runtime_arm.content_hash]))
        context = events[1]["data"]["request"]["module_context"]
        scenario = {"schema": "combination-public-scenario-v1", "obligation_id": panel.obligation_id,
            "design_digest": panel.design.content_hash, "task_digest": cell.task_digest,
            "replicate": cell.replicate, "status": "predeclared"}
        expected_context = {"panel_cell": {"experiment_id": cell.coverage_id, "variant": cell.variant,
            "replicate": cell.replicate, "arm_id": cell.arm_id, "scenario_digest": cell.scenario_digest},
            "combination_scenario": scenario, "required_objective_digest": FrozenRecord.from_dict(lock["objective"]).content_hash,
            "candidate_package": package.record.data(), "package_application_status": "controller_binding_only_not_module_effect"}
        if context != expected_context or FrozenRecord.from_dict(scenario).content_hash != cell.scenario_digest:
            raise ContractError("source request does not bind the exact package and source scenario")
        closure = JointClosure({m: JointComponent.from_package(m, package) for m in cell.runtime_arm.data()["enabled"]}, package,
            FrozenRecord.from_dict({"baseline_digest": baseline}),
            FrozenRecord.from_dict({"schema": "c5-binding-source-background-v1", "baseline_digest": baseline,
                                   "fixed_modules": [], "objective": lock["objective"]}),
            FrozenRecord.from_dict({"schema": "c5-binding-source-p0-v1", "control_plane": "always_enabled",
                                   "required_audit": lock["required_audit"], "terminal_stage": events[-1]["stage"]}),
            FrozenRecord.from_dict({"schema": "c5-binding-source-schedule-v1", "slots": lock["slots"],
                                   "execution_limit": lock["execution_limit"], "context_budget": lock["context_budget"]}), cell.runtime_arm)
        if cell.arm_id in closures and closures[cell.arm_id] != closure:
            raise ContractError("one source arm has inconsistent package, P0, objective or resource schedule")
        closures[cell.arm_id] = closure
    if set(closures) != _ARMS or len({c.background for c in closures.values()}) != 1:
        raise ContractError("source must retain the complete four-arm grid with fixed background")
    return _map(closures, "source closures"), FrozenRecord.from_dict({"journals": journal_bytes})


def _handoff_record(panel, receipts, target, closures, journals):
    return FrozenRecord.from_dict({"schema": "c5-prepared-joint-train-handoff-v3", "source_adapter": SOURCE_ADAPTER,
        "source_panel_digest": panel.digest, "source_runtime_receipts": [
            {"cell_key": list(r.cell_key), "status": r.status, "trace_path": str(r.trace_path.resolve()),
             "trace_digest": r.trace_digest, "output_digest": r.output_digest, "failure_reason": r.failure_reason}
            for r in sorted(receipts, key=lambda r: r.cell_key)],
        "original_journals_digest": journals.content_hash, "proposed_target_arm": target,
        "proposed_target_closure_digest": closures[target].digest,
        "closures": {name: closures[name].digest for name in sorted(closures)},
        "source_verification_status": "binding_only_runtime_replayed_not_joint_train_selection",
        "admission_status": "unavailable_no_typed_joint_train_verifier", "preparation_only": True,
        "validation_eligible": False, "custody_lease_authorized": False,
        "acceptance_authorized": False, "deployment_authorized": False})


@dataclass(frozen=True)
class PreparedJointTrainHandoff:
    record: FrozenRecord
    proposed_target_arm: str
    closures: Mapping[str, JointClosure]
    source_panel: CombinationPanel
    source_runtime_receipts: tuple[RuntimeReceipt, ...]
    original_journals: FrozenRecord

    def __post_init__(self):
        closures = _map(self.closures, "prepared closures")
        receipts = tuple(self.source_runtime_receipts)
        expected, journals = _source(self.source_panel, receipts)
        if self.proposed_target_arm != "11" or dict(closures) != dict(expected):
            raise ContractError("proposed full target and every closure must exactly match their source arm")
        if self.original_journals != journals or self.record != _handoff_record(
                self.source_panel, receipts, self.proposed_target_arm, closures, journals):
            raise ContractError("prepared record differs from original source journals and exact closures")
        object.__setattr__(self, "closures", closures)
        object.__setattr__(self, "source_runtime_receipts", tuple(sorted(receipts, key=lambda r: r.cell_key)))

    @property
    def admission_status(self):
        return "unavailable_no_typed_joint_train_verifier"

    @property
    def proposed_target_digest(self):
        return self.closures[self.proposed_target_arm].digest


def prepare_joint_train_handoff(*, source_panel: CombinationPanel, source_runtime_receipts: Sequence[RuntimeReceipt],
                                proposed_target_arm: str, closures: Mapping[str, JointClosure] | None = None):
    receipts = tuple(source_runtime_receipts)
    source_closures, journals = _source(source_panel, receipts)
    if proposed_target_arm != "11":
        raise ContractError("supported source freezes the full M4/M5 target 11; it does not select an arm")
    chosen = source_closures if closures is None else closures
    # The constructor repeats the full source checks for direct construction.
    return PreparedJointTrainHandoff(_handoff_record(source_panel, receipts, proposed_target_arm, source_closures, journals),
        proposed_target_arm, chosen, source_panel, receipts, journals)


@dataclass(frozen=True)
class C5Arm:
    arm_id: str
    role: str

    def __post_init__(self):
        required_text(self.arm_id, "C5 arm id")
        if self.role not in {"target", "baseline", "control", "ablation"}:
            raise ContractError("unknown C5 arm role")


@dataclass(frozen=True)
class C5Cell:
    arm_id: str
    identity: DataIdentity
    replicate: str

    def __post_init__(self):
        required_text(self.arm_id, "C5 cell arm")
        required_text(self.replicate, "C5 replicate")
        if type(self.identity) is not DataIdentity or self.identity.domain != "validation":
            raise ContractError("C5 cell requires a typed validation identity")


def _number(value, *, low, high=None):
    return type(value) in {int, float} and isfinite(value) and value >= low and (high is None or value <= high)


def _criteria(record, comparisons):
    body = _record(record, "C5 criteria")
    fields = {"schema", "benchmarks", "missing_policy", "group_weighting", "decision_rule", "multiple_comparisons"}
    if (set(body) != fields or body["schema"] != "c5-prepared-acceptance-criteria-v1"
            or body["missing_policy"] != "any_missing_or_failed_cell_reject"
            or body["group_weighting"] != "task_replicate_mean_then_equal_group_mean"
            or body["decision_rule"] != "fixed_target_passes_every_comparison_in_each_benchmark"
            or not isinstance(body["benchmarks"], dict) or set(body["benchmarks"]) != _BENCHMARKS):
        raise ContractError("C5 needs concrete per-benchmark quality, safety, cost and failure criteria")
    for row in body["benchmarks"].values():
        fields = {"score_name", "score_range", "direction", "minimum_target_gain", "maximum_safety_regression",
                  "maximum_cost_ratio", "minimum_independent_groups"}
        if not isinstance(row, dict) or set(row) != fields:
            raise ContractError("C5 benchmark criteria are incomplete")
        required_text(row["score_name"], "C5 score name")
        bounds = row["score_range"]
        if (not isinstance(bounds, list) or len(bounds) != 2 or any(type(v) not in {int, float} or not isfinite(v) for v in bounds)
                or bounds[0] >= bounds[1] or row["direction"] != "higher_better"
                or not _number(row["minimum_target_gain"], low=0, high=bounds[1]-bounds[0])
                or not _number(row["maximum_safety_regression"], low=0, high=0)
                or not _number(row["maximum_cost_ratio"], low=0) or row["maximum_cost_ratio"] == 0
                or type(row["minimum_independent_groups"]) is not int or row["minimum_independent_groups"] < 2):
            raise ContractError("C5 benchmark criteria contain invalid thresholds or permit a safety regression")
    family = body["multiple_comparisons"]
    if (not isinstance(family, dict) or set(family) != {"method", "family_alpha", "comparison_count"}
            or family["method"] != "bonferroni" or not _number(family["family_alpha"], low=0, high=1)
            or family["family_alpha"] in {0, 1} or type(family["comparison_count"]) is not int
            or family["comparison_count"] != comparisons * len(_BENCHMARKS)):
        raise ContractError("C5 multiplicity family must bind every comparison in both benchmarks")


def _panel_record(handoff, target, arms, cells, contrasts, criteria, schedule):
    if type(handoff) is not PreparedJointTrainHandoff:
        raise ContractError("C5 needs an exact prepared TRAIN handoff")
    handoff.__post_init__()  # Original source drift invalidates every freeze path.
    if target != handoff.proposed_target_arm:
        raise ContractError("C5 target must equal the frozen prepared target")
    if (not arms or any(type(a) is not C5Arm for a in arms) or len({a.arm_id for a in arms}) != len(arms)
            or {a.arm_id for a in arms} != set(handoff.closures)):
        raise ContractError("C5 arms must exactly cover all immutable prepared closures")
    roles = {role: [a.arm_id for a in arms if a.role == role] for role in ("target", "baseline", "control", "ablation")}
    if roles["target"] != [target] or roles["baseline"] != ["00"] or not roles["control"] or not roles["ablation"]:
        raise ContractError("C5 needs exactly one frozen target and B0, with controls and ablations")
    if (not cells or any(type(c) is not C5Cell for c in cells)
            or len({(c.arm_id, c.identity, c.replicate) for c in cells}) != len(cells)):
        raise ContractError("C5 cells must be unique typed arm/identity/replicate entries")
    groups = {}
    train_groups = {(c.identity.benchmark, c.identity.group_id) for c in handoff.source_panel.cells}
    versions = {}
    for cell in cells:
        if (cell.arm_id not in handoff.closures or cell.identity.split_id != handoff.source_panel.split_digest
                or (cell.identity.benchmark, cell.identity.group_id) in train_groups):
            raise ContractError("C5 cell has an unknown arm, split drift, or a source TRAIN group")
        versions.setdefault(cell.identity.benchmark, set()).add(cell.identity.dataset_version)
        # Every DataIdentity field participates; matching names alone do not pair data.
        groups.setdefault((cell.identity, cell.replicate), []).append(cell.arm_id)
    if (set(versions) != _BENCHMARKS or any(len(v) != 1 for v in versions.values())
            or any(set(rows) != set(handoff.closures) or len(rows) != len(handoff.closures) for rows in groups.values())):
        raise ContractError("C5 requires a complete paired grid for each exact data identity and replicate")
    contrast = _record(contrasts, "C5 contrasts")
    expected_rows = [{"comparison_arm": a.arm_id, "comparison_role": a.role,
                      "coefficients": {name: (1 if name == target else -1 if name == a.arm_id else 0)
                                       for name in sorted(handoff.closures)}}
                     for a in sorted(arms, key=lambda a: a.arm_id) if a.arm_id != target]
    expected = {"schema": "c5-target-relative-contrasts-v1", "estimand": "joint_bundle",
                "target_arm": target, "rows": expected_rows}
    # Canonical JSON distinguishes bool from int and 1.0 from literal coefficients.
    if contrasts != FrozenRecord.from_dict(expected):
        raise ContractError("C5 requires one exact target-minus-comparator row for every B0/control/ablation")
    _criteria(criteria, len(expected_rows))
    _record(schedule, "C5 schedule")
    if any(schedule != closure.resource_schedule for closure in handoff.closures.values()):
        raise ContractError("C5 schedule must match every frozen source closure")
    return FrozenRecord.from_dict({"schema": "c5-validation-preparation-v3", "stage": "C5", "allocation_stage": "V_final",
        "handoff_digest": handoff.record.content_hash, "proposed_target_arm": target,
        "proposed_target_closure_digest": handoff.proposed_target_digest,
        "arms": [{"arm_id": a.arm_id, "role": a.role, "closure_digest": handoff.closures[a.arm_id].digest}
                 for a in sorted(arms, key=lambda a: a.arm_id)],
        "cells": [{"arm_id": c.arm_id, "identity": c.identity.data(), "replicate": c.replicate}
                  for c in sorted(cells, key=lambda c: (canonical(c.identity.data()), c.replicate, c.arm_id))],
        "contrast_matrix": contrast, "acceptance_criteria": criteria.data(), "resource_schedule": schedule.data(),
        "preparation_only": True, "validation_eligible": False, "custody_lease_authorized": False,
        "acceptance_authorized": False, "deployment_authorized": False})


@dataclass(frozen=True)
class C5ValidationPanel:
    record: FrozenRecord
    handoff: PreparedJointTrainHandoff
    proposed_target_arm: str
    arms: tuple[C5Arm, ...]
    cells: tuple[C5Cell, ...]
    contrast_matrix: FrozenRecord
    acceptance_criteria: FrozenRecord
    resource_schedule: FrozenRecord

    def __post_init__(self):
        arms, cells = tuple(self.arms), tuple(self.cells)
        expected = _panel_record(self.handoff, self.proposed_target_arm, arms, cells,
                                 self.contrast_matrix, self.acceptance_criteria, self.resource_schedule)
        if self.record != expected:
            raise ContractError("C5 record differs from its complete canonical preparation")
        object.__setattr__(self, "arms", arms)
        object.__setattr__(self, "cells", cells)

    @property
    def acceptance_authorized(self):
        return False

    @property
    def custody_lease_authorized(self):
        return False


def freeze_c5_validation_panel(handoff, *, proposed_target_arm, arms, cells, contrast_matrix,
                               acceptance_criteria, resource_schedule):
    arms, cells = tuple(arms), tuple(cells)
    record = _panel_record(handoff, proposed_target_arm, arms, cells, contrast_matrix, acceptance_criteria, resource_schedule)
    return C5ValidationPanel(record, handoff, proposed_target_arm, arms, cells,
                             contrast_matrix, acceptance_criteria, resource_schedule)
