import pytest

from research_loop.modular.c5_frozen_handoff import (
    JointClosure, JointComponent, C5Arm, prepare_joint_train_handoff, freeze_c5_validation_panel,
)
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.ontology import ContractError


H = "a" * 64


def package(task: DataIdentity, value: str) -> CandidatePackage:
    return CandidatePackage.create(manifest=TrainingManifest.freeze([task]), parent_digest=None,
                                   changes={"memory": {"mode": value}}, search_cost=0)


def closure(component_id: str, package: CandidatePackage) -> JointClosure:
    return JointClosure((JointComponent(component_id, package, FrozenRecord.from_dict({"version": component_id}),
                                        FrozenRecord.from_dict({"view": component_id})),),
                        FrozenRecord.from_dict({"baseline": "fixed"}), FrozenRecord.from_dict({"budget": "fixed"}))


def handoff(target: str, closures: dict[str, JointClosure]):
    receipts = {name: FrozenRecord.from_dict({"receipt": name}) for name in closures}
    receipt_digest = FrozenRecord.from_dict({"receipts": {name: receipts[name].content_hash for name in sorted(receipts)}}).content_hash
    panel = FrozenRecord.from_dict({"schema": "joint-train-candidate-panel-v1", "domain": "train",
                                    "arm_ids": sorted(closures), "evidence_path_digest": "b" * 64})
    rule = FrozenRecord.from_dict({"schema": "joint-train-selection-rule-v1", "rule_id": "fixture",
                                   "candidate_panel_digest": panel.content_hash,
                                   "candidate_receipts_digest": receipt_digest, "selected_arm": target})
    return prepare_joint_train_handoff(selection_rule=rule, candidate_panel=panel, candidate_receipts=receipts,
                                       target_arm=target, closures=closures)


def test_prepared_handoff_rejects_target_replacement_and_is_not_admitted():
    task = DataIdentity("blade", "train", "train-group", "inventory", H, "train")
    target = package(task, "target"); control = package(task, "control"); ablation = package(task, "ablation")
    prepared = handoff("target", {"target": closure("target", target), "control": closure("control", control),
                                  "ablation": closure("ablation", ablation)})
    assert prepared.admission_status == "unavailable_no_typed_joint_train_verifier"
    with pytest.raises(ContractError, match="target arm"):
        freeze_c5_validation_panel(prepared, target_arm="control", arms=(
            C5Arm("target", "target"), C5Arm("control", "control"), C5Arm("ablation", "ablation")),
            identities=(DataIdentity("blade", "v", "g", "inventory", H, "validation"),))


def test_c5_panel_requires_complete_paired_grid_and_never_authorizes_acceptance():
    task = DataIdentity("blade", "train", "train-group", "inventory", H, "train")
    packages = {name: package(task, name) for name in ("target", "baseline", "control", "ablation")}
    prepared = handoff("target", {name: closure(name, value) for name, value in packages.items()})
    panel = freeze_c5_validation_panel(prepared, target_arm="target", arms=(C5Arm("target", "target"),
        C5Arm("baseline", "baseline"), C5Arm("control", "control"), C5Arm("ablation", "ablation")),
        identities=(DataIdentity("blade", "v1", "shared", "inventory", H, "validation"),
                    DataIdentity("discoverybench", "v2", "shared", "inventory", H, "validation")))
    assert panel.acceptance_authorized is False and panel.custody_lease_authorized is False
    with pytest.raises(ContractError, match="exactly cover"):
        freeze_c5_validation_panel(prepared, target_arm="target", arms=(C5Arm("target", "target"),
            C5Arm("control", "control"), C5Arm("ablation", "ablation")), identities=panel.identities)
