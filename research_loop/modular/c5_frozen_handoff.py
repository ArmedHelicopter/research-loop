"""C5 wave-1 provenance objects; no lease, scoring, acceptance, or deployment port."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from research_loop.modular.contracts import DataIdentity, FrozenRecord, required_text
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.ontology import ContractError


def _digest(value: str, field: str) -> str:
    required_text(value, field)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ContractError(f"{field} must be a sha256 digest")
    return value


@dataclass(frozen=True)
class JointComponent:
    component_id: str
    package: CandidatePackage
    config: FrozenRecord
    state_view: FrozenRecord

    def __post_init__(self) -> None:
        required_text(self.component_id, "component id")
        if not isinstance(self.package, CandidatePackage) or not isinstance(self.config, FrozenRecord) or not isinstance(self.state_view, FrozenRecord):
            raise ContractError("joint component needs typed package, config, and state view")

    def data(self) -> dict:
        return {"component_id": self.component_id, "package_digest": self.package.digest,
                "config_digest": self.config.content_hash, "state_view_digest": self.state_view.content_hash}


@dataclass(frozen=True)
class JointClosure:
    components: tuple[JointComponent, ...]
    background: FrozenRecord
    resource_schedule: FrozenRecord

    def __post_init__(self) -> None:
        object.__setattr__(self, "components", tuple(self.components))
        if not self.components or len({item.component_id for item in self.components}) != len(self.components):
            raise ContractError("joint closure needs unique complete components")
        if not isinstance(self.background, FrozenRecord) or not isinstance(self.resource_schedule, FrozenRecord):
            raise ContractError("joint closure needs frozen background and resource schedule")

    @property
    def digest(self) -> str:
        return FrozenRecord.from_dict({"schema": "c5-joint-closure-v1", "components": [item.data() for item in sorted(self.components, key=lambda item: item.component_id)],
            "background_digest": self.background.content_hash, "resource_schedule_digest": self.resource_schedule.content_hash}).content_hash


@dataclass(frozen=True)
class TrainSelectedJointBundle:
    record: FrozenRecord
    target_arm: str
    closures: Mapping[str, JointClosure]

    @property
    def admission_status(self) -> str:
        return "unavailable_no_typed_joint_train_verifier"

    @property
    def target_digest(self) -> str:
        return self.closures[self.target_arm].digest


def prepare_joint_train_handoff(*, selection_rule: FrozenRecord, candidate_panel: FrozenRecord,
                                candidate_receipts: Mapping[str, FrozenRecord], target_arm: str,
                                closures: Mapping[str, JointClosure]) -> TrainSelectedJointBundle:
    """Freeze a structurally complete train handoff without claiming selection admission.

    A later wave must supply a typed verifier adapter for the comparable joint
    controller evidence. This function intentionally has no boolean/callback
    trust input and cannot produce a validation-eligible or deployable object.
    """
    if not isinstance(selection_rule, FrozenRecord) or not isinstance(candidate_panel, FrozenRecord):
        raise ContractError("joint handoff requires frozen train rule and panel evidence")
    if not candidate_receipts or set(candidate_receipts) != set(closures) or target_arm not in closures:
        raise ContractError("joint handoff needs exact target and complete candidate closure set")
    if any(not isinstance(value, FrozenRecord) for value in candidate_receipts.values()) or any(not isinstance(value, JointClosure) for value in closures.values()):
        raise ContractError("joint handoff needs typed candidate receipts and closures")
    if any("validation" in value.encoded.lower() for value in candidate_receipts.values()):
        raise ContractError("joint handoff cannot consume validation evidence")
    receipts = FrozenRecord.from_dict({"receipts": {name: candidate_receipts[name].content_hash for name in sorted(candidate_receipts)}})
    panel = candidate_panel.data(); rule = selection_rule.data()
    if set(panel) != {"schema", "domain", "arm_ids", "evidence_path_digest"} or panel.get("schema") != "joint-train-candidate-panel-v1" or panel.get("domain") != "train" or tuple(panel.get("arm_ids", ())) != tuple(sorted(closures)):
        raise ContractError("joint candidate panel is not a complete frozen train panel")
    _digest(panel["evidence_path_digest"], "candidate evidence path digest")
    if set(rule) != {"schema", "rule_id", "candidate_panel_digest", "candidate_receipts_digest", "selected_arm"} or rule.get("schema") != "joint-train-selection-rule-v1" or rule.get("selected_arm") != target_arm or rule.get("candidate_panel_digest") != candidate_panel.content_hash or rule.get("candidate_receipts_digest") != receipts.content_hash:
        raise ContractError("joint selection rule does not bind the exact train evidence and target")
    required_text(rule["rule_id"], "joint selection rule id")
    record = FrozenRecord.from_dict({"schema": "c5-prepared-train-handoff-v1", "selection_rule_digest": selection_rule.content_hash,
        "candidate_panel_digest": candidate_panel.content_hash, "candidate_receipts_digest": receipts.content_hash,
        "target_arm": target_arm, "target_closure_digest": closures[target_arm].digest,
        "closures": {name: closures[name].digest for name in sorted(closures)},
        "admission_status": "unavailable_no_typed_joint_train_verifier", "validation_eligible": False,
        "acceptance_authorized": False, "deployment_authorized": False})
    return TrainSelectedJointBundle(record, target_arm, dict(closures))


@dataclass(frozen=True)
class C5Arm:
    arm_id: str
    role: str

    def __post_init__(self) -> None:
        required_text(self.arm_id, "C5 arm id")
        if self.role not in {"target", "baseline", "control", "ablation"}:
            raise ContractError("unknown C5 arm role")


@dataclass(frozen=True)
class C5ValidationPanel:
    record: FrozenRecord
    handoff: TrainSelectedJointBundle
    identities: tuple[DataIdentity, ...]

    @property
    def acceptance_authorized(self) -> bool:
        return False

    @property
    def custody_lease_authorized(self) -> bool:
        return False


def freeze_c5_validation_panel(handoff: TrainSelectedJointBundle, *, target_arm: str,
                               arms: Sequence[C5Arm], identities: Sequence[DataIdentity]) -> C5ValidationPanel:
    if not isinstance(handoff, TrainSelectedJointBundle) or target_arm != handoff.target_arm:
        raise ContractError("C5 target arm must equal the frozen train target arm")
    arms, identities = tuple(arms), tuple(identities)
    if not arms or len({arm.arm_id for arm in arms}) != len(arms) or {arm.arm_id for arm in arms} != set(handoff.closures):
        raise ContractError("C5 arms must exactly cover the frozen closures")
    if any(not isinstance(arm, C5Arm) for arm in arms) or sum(arm.role == "target" for arm in arms) != 1 or next(arm.arm_id for arm in arms if arm.role == "target") != target_arm or not {"baseline", "control", "ablation"} <= {arm.role for arm in arms}:
        raise ContractError("C5 panel needs one frozen target and every required role")
    if not identities or len(set(identities)) != len(identities) or any(not isinstance(identity, DataIdentity) or identity.domain != "validation" for identity in identities):
        raise ContractError("C5 panel needs unique typed validation identities")
    groups = {identity.group_id for identity in identities}
    if len(groups) != 1 or {identity.benchmark for identity in identities} != {"blade", "discoverybench"}:
        raise ContractError("C5 panel needs one paired source group across the core benchmarks")
    record = FrozenRecord.from_dict({"schema": "c5-validation-panel-v1", "stage": "C5", "handoff_digest": handoff.record.content_hash,
        "target_arm": target_arm, "target_closure_digest": handoff.target_digest,
        "arms": [{"arm_id": arm.arm_id, "role": arm.role, "closure_digest": handoff.closures[arm.arm_id].digest} for arm in sorted(arms, key=lambda arm: arm.arm_id)],
        "identities": [identity.data() for identity in sorted(identities, key=lambda item: (item.benchmark, item.task_id))],
        "validation_eligible": False, "acceptance_authorized": False, "deployment_authorized": False})
    return C5ValidationPanel(record, handoff, identities)
