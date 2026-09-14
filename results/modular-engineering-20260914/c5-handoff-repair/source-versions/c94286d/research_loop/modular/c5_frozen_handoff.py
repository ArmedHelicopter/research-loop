"""C5 frozen preparation objects; no lease, scoring, acceptance, or deployment port."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Sequence

from research_loop.modular.combination_panels import CombinationPanel
from research_loop.modular.panel_receipts import RuntimeReceipt
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord, required_text
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.ontology import ContractError


def _digest(value: str, field: str) -> str:
    required_text(value, field)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ContractError(f"{field} must be a sha256 digest")
    return value


def _frozen_map(value: Mapping[str, object], field: str, *, nonempty: bool = True) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or (nonempty and not value):
        raise ContractError(f"{field} must be a nonempty mapping")
    copied = dict(value)
    if any(not isinstance(key, str) or not key for key in copied):
        raise ContractError(f"{field} keys must be nonempty text")
    return MappingProxyType(copied)


@dataclass(frozen=True)
class JointComponent:
    component_id: str
    package: CandidatePackage
    config: FrozenRecord
    state_view: FrozenRecord

    def __post_init__(self) -> None:
        if self.component_id not in {f"M{i}" for i in range(1, 10)}:
            raise ContractError("joint component must be a registered M1--M9 module")
        if not isinstance(self.package, CandidatePackage) or not isinstance(self.config, FrozenRecord) or not isinstance(self.state_view, FrozenRecord):
            raise ContractError("joint component needs typed package, config, and state view")

    def data(self) -> dict:
        return {"component_id": self.component_id, "package_digest": self.package.digest,
                "config_digest": self.config.content_hash, "state_view_digest": self.state_view.content_hash}


@dataclass(frozen=True)
class JointClosure:
    """One exact legal module closure, including P0 and fixed execution context."""
    components: Mapping[str, JointComponent]
    baseline: FrozenRecord
    background: FrozenRecord
    p0_control: FrozenRecord
    resource_schedule: FrozenRecord
    runtime_arm: FrozenRecord

    def __post_init__(self) -> None:
        components = _frozen_map(self.components, "joint components", nonempty=False)
        if any(not isinstance(item, JointComponent) or key != item.component_id for key, item in components.items()):
            raise ContractError("joint closure components must be keyed typed modules")
        for value in (self.baseline, self.background, self.p0_control, self.resource_schedule, self.runtime_arm):
            if not isinstance(value, FrozenRecord):
                raise ContractError("joint closure needs frozen baseline, background, P0, schedule, and arm")
        baseline = self.baseline.data()
        if set(baseline) != {"baseline_digest"}:
            raise ContractError("joint closure baseline must have one baseline digest")
        expected = default_compatibility(_digest(baseline["baseline_digest"], "baseline digest")).arm(components)
        if self.runtime_arm != expected:
            raise ContractError("joint closure is not the exact compatible dependency closure")
        if self.background.data().get("baseline_digest") != baseline["baseline_digest"]:
            raise ContractError("joint closure background differs from baseline")
        if self.p0_control.data().get("control_plane") != "always_enabled":
            raise ContractError("joint closure requires frozen always-enabled P0 control")
        object.__setattr__(self, "components", components)

    @property
    def digest(self) -> str:
        return FrozenRecord.from_dict({"schema": "c5-joint-closure-v2", "components": [self.components[key].data() for key in sorted(self.components)],
            "baseline_digest": self.baseline.content_hash, "background_digest": self.background.content_hash,
            "p0_control_digest": self.p0_control.content_hash, "resource_schedule_digest": self.resource_schedule.content_hash,
            "runtime_arm_digest": self.runtime_arm.content_hash}).content_hash


@dataclass(frozen=True)
class PreparedJointTrainHandoff:
    """A proposal bound to typed C2--C4 train source; it is not a selection."""
    record: FrozenRecord
    proposed_target_arm: str
    closures: Mapping[str, JointClosure]
    source_panel: CombinationPanel
    source_runtime_receipts: tuple[RuntimeReceipt, ...]

    def __post_init__(self) -> None:
        closures = _frozen_map(self.closures, "prepared closures")
        if any(not isinstance(value, JointClosure) for value in closures.values()) or self.proposed_target_arm not in closures:
            raise ContractError("prepared handoff needs a typed proposed target closure")
        object.__setattr__(self, "source_runtime_receipts", tuple(self.source_runtime_receipts))
        if not isinstance(self.source_panel, CombinationPanel) or any(not isinstance(row, RuntimeReceipt) for row in self.source_runtime_receipts):
            raise ContractError("prepared handoff requires typed joint train source panel")
        body = self.record.data()
        expected = {"schema": "c5-prepared-joint-train-handoff-v2", "source_panel_digest": self.source_panel.digest, "source_runtime_receipt_digests": [row.trace_digest for row in self.source_runtime_receipts],
            "proposed_target_arm": self.proposed_target_arm, "proposed_target_closure_digest": closures[self.proposed_target_arm].digest,
            "closures": {name: closures[name].digest for name in sorted(closures)},
            "source_verification_status": "requires_typed_joint_train_verifier", "admission_status": "unavailable_no_typed_joint_train_verifier",
            "validation_eligible": False, "acceptance_authorized": False, "deployment_authorized": False}
        if body != expected:
            raise ContractError("prepared handoff record does not bind its immutable source and closures")
        object.__setattr__(self, "closures", closures)

    @property
    def admission_status(self) -> str:
        return "unavailable_no_typed_joint_train_verifier"

    @property
    def proposed_target_digest(self) -> str:
        return self.closures[self.proposed_target_arm].digest


def prepare_joint_train_handoff(*, source_panel: CombinationPanel, source_runtime_receipts: Sequence[RuntimeReceipt], proposed_target_arm: str,
                                 closures: Mapping[str, JointClosure]) -> PreparedJointTrainHandoff:
    """Freeze a proposal from a real C2--C4 train panel, without accepting a winner claim.

    Current controllers expose typed panel structure but no independently consumable
    joint-train selection verifier. This boundary intentionally records that gap.
    """
    closures = _frozen_map(closures, "prepared closures")
    receipts = tuple(source_runtime_receipts)
    if not isinstance(source_panel, CombinationPanel) or source_panel.domain != "train" or source_panel.estimand not in {"joint_bundle", "leave_one_out_at_full"}:
        raise ContractError("prepared handoff requires a typed complete joint TRAIN panel")
    if any(not isinstance(row, RuntimeReceipt) for row in receipts) or {row.cell_key for row in receipts} != {cell.key for cell in source_panel.cells} or len({row.cell_key for row in receipts}) != len(receipts):
        raise ContractError("prepared handoff requires the exact typed original TRAIN runtime receipt set")
    if any(not isinstance(value, JointClosure) for value in closures.values()) or proposed_target_arm not in closures:
        raise ContractError("prepared handoff needs exact typed closures and proposed target")
    package_digests = {CandidatePackage(FrozenRecord.from_dict(value)).digest for value in source_panel.package_bundle.data()["packages"].values()}
    for closure in closures.values():
        if not {component.package.digest for component in closure.components.values()} <= package_digests:
            raise ContractError("prepared closure package is absent from the typed train panel")
    record = FrozenRecord.from_dict({"schema": "c5-prepared-joint-train-handoff-v2", "source_panel_digest": source_panel.digest, "source_runtime_receipt_digests": [row.trace_digest for row in receipts],
        "proposed_target_arm": proposed_target_arm, "proposed_target_closure_digest": closures[proposed_target_arm].digest,
        "closures": {name: closures[name].digest for name in sorted(closures)},
        "source_verification_status": "requires_typed_joint_train_verifier", "admission_status": "unavailable_no_typed_joint_train_verifier",
        "validation_eligible": False, "acceptance_authorized": False, "deployment_authorized": False})
    return PreparedJointTrainHandoff(record, proposed_target_arm, closures, source_panel, receipts)


@dataclass(frozen=True)
class C5Arm:
    arm_id: str
    role: str
    def __post_init__(self) -> None:
        required_text(self.arm_id, "C5 arm id")
        if self.role not in {"target", "baseline", "control", "ablation"}:
            raise ContractError("unknown C5 arm role")


@dataclass(frozen=True)
class C5Cell:
    arm_id: str
    identity: DataIdentity
    replicate: str
    def __post_init__(self) -> None:
        required_text(self.arm_id, "C5 cell arm")
        required_text(self.replicate, "C5 replicate")
        if not isinstance(self.identity, DataIdentity) or self.identity.domain != "validation":
            raise ContractError("C5 cell requires typed validation identity")


@dataclass(frozen=True)
class C5ValidationPanel:
    record: FrozenRecord
    handoff: PreparedJointTrainHandoff
    cells: tuple[C5Cell, ...]
    @property
    def acceptance_authorized(self) -> bool: return False
    @property
    def custody_lease_authorized(self) -> bool: return False


def freeze_c5_validation_panel(handoff: PreparedJointTrainHandoff, *, proposed_target_arm: str, arms: Sequence[C5Arm],
                               cells: Sequence[C5Cell], contrast_matrix: FrozenRecord, acceptance_criteria: FrozenRecord,
                               resource_schedule: FrozenRecord) -> C5ValidationPanel:
    if not isinstance(handoff, PreparedJointTrainHandoff) or proposed_target_arm != handoff.proposed_target_arm:
        raise ContractError("C5 proposed target must equal the frozen prepared target")
    arms, cells = tuple(arms), tuple(cells)
    if not arms or any(not isinstance(arm, C5Arm) for arm in arms) or len({arm.arm_id for arm in arms}) != len(arms) or {arm.arm_id for arm in arms} != set(handoff.closures):
        raise ContractError("C5 arms must exactly cover immutable prepared closures")
    by_role = {arm.role: arm.arm_id for arm in arms}
    if set(by_role) != {"target", "baseline", "control", "ablation"} or by_role["target"] != proposed_target_arm:
        raise ContractError("C5 panel needs exactly one fixed target and preregistered baseline/control/ablation")
    if not cells or any(not isinstance(cell, C5Cell) for cell in cells) or len({(cell.arm_id, cell.identity, cell.replicate) for cell in cells}) != len(cells):
        raise ContractError("C5 cells must be unique typed arm identity replicate entries")
    if any(cell.arm_id not in set(handoff.closures) for cell in cells):
        raise ContractError("C5 cell refers to an unprepared arm")
    groups: dict[tuple[str, str, str, str], list[C5Cell]] = {}
    for cell in cells:
        key = (cell.identity.benchmark, cell.identity.group_id, cell.identity.task_id, cell.replicate)
        groups.setdefault(key, []).append(cell)
    if {key[0] for key in groups} != {"blade", "discoverybench"} or any({row.arm_id for row in rows} != set(handoff.closures) or len(rows) != len(handoff.closures) for rows in groups.values()):
        raise ContractError("C5 requires every arm paired within each benchmark/source-group/task/replicate")
    if not isinstance(contrast_matrix, FrozenRecord) or not isinstance(acceptance_criteria, FrozenRecord) or not isinstance(resource_schedule, FrozenRecord):
        raise ContractError("C5 requires frozen joint-bundle contrasts, criteria, and schedule")
    contrast = contrast_matrix.data()
    if (set(contrast) != {"estimand", "target_arm", "coefficients"} or contrast["estimand"] != "joint_bundle"
            or contrast["target_arm"] != proposed_target_arm or not isinstance(contrast["coefficients"], dict)
            or set(contrast["coefficients"]) != set(handoff.closures)
            or any(type(value) not in {int, float} for value in contrast["coefficients"].values())
            or contrast["coefficients"][proposed_target_arm] != 1):
        raise ContractError("C5 contrast must canonically bind target-relative joint-bundle coefficients")
    record = FrozenRecord.from_dict({"schema": "c5-validation-panel-v2", "stage": "C5", "handoff_digest": handoff.record.content_hash,
        "proposed_target_arm": proposed_target_arm, "proposed_target_closure_digest": handoff.proposed_target_digest,
        "arms": [{"arm_id": arm.arm_id, "role": arm.role, "closure_digest": handoff.closures[arm.arm_id].digest} for arm in sorted(arms, key=lambda row: row.arm_id)],
        "cells": [{"arm_id": cell.arm_id, "identity": cell.identity.data(), "replicate": cell.replicate} for cell in sorted(cells, key=lambda row: (row.identity.benchmark, row.identity.group_id, row.identity.task_id, row.replicate, row.arm_id))],
        "contrast_matrix_digest": contrast_matrix.content_hash, "acceptance_criteria_digest": acceptance_criteria.content_hash,
        "resource_schedule_digest": resource_schedule.content_hash, "validation_eligible": False, "acceptance_authorized": False, "deployment_authorized": False})
    return C5ValidationPanel(record, handoff, cells)