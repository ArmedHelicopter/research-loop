import pytest

from research_loop.modular.artifact_subjects import (ArtifactSubject, CandidateComponentSubject, ConfigurationUse, JointBundleSubject,
    TaskEvidenceEdge, TaskOutputSubject, TrainSelectionControl)
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.joint_deployment import JointComponentVersion, JointDeploymentBundle
from research_loop.modular.modules.improvement import TrainingManifest
from research_loop.ontology import ContractError


def identity(task="train-task", domain="train"):
    return DataIdentity("synthetic", task, "group", "v1", "split", domain)


def component(name, *train):
    return JointComponentVersion(FrozenRecord.from_dict({"schema": "joint-component-version-v1", "module_id": name,
        "source_files": {"module.py": "a" * 64}, "config": {"name": name}, "state": {"name": name},
        "training_manifest": TrainingManifest.freeze(train).record.data()}))


def bundle(*train, missing=None):
    components = {f"M{i}": component(f"M{i}", *train) for i in range(1, 10) if f"M{i}" != missing}
    # Construction accepts the normal production compatibility object; the subject adds the inventory check.
    return JointDeploymentBundle.create(parent_digest=None, baseline_digest="b" * 64, p0_digest="c" * 64,
        resource_schedule=FrozenRecord.from_dict({"schedule": "fixed"}), components=components)


def output(task="train-task", domain="train"):
    return TaskOutputSubject(identity(task, domain), FrozenRecord.from_dict({"answer": task}))


def test_task_evidence_is_same_canonical_subject_only():
    same = output()
    assert TaskEvidenceEdge("supports", same, same).relation == "supports"
    with pytest.raises(ContractError, match="cross task"):
        TaskEvidenceEdge("refutes", same, output("foreign"))


def test_train_selection_control_rejects_validation_and_missing_train_target():
    source = CandidateComponentSubject(component("M1", identity()))
    assert TrainSelectionControl(source, identity()).target.task_id == "train-task"
    with pytest.raises(ContractError, match="train provenance"):
        TrainSelectionControl(source, identity("foreign"))
    with pytest.raises(ContractError, match="training provenance"):
        TrainSelectionControl(source, identity("val-task", "validation"))


def test_bundle_subject_pins_complete_component_inventory_and_digest():
    subject = JointBundleSubject(bundle(identity()))
    assert set(subject.component_digests) == {f"M{i}" for i in range(1, 10)}
    with pytest.raises(ContractError, match="complete M1"):
        JointBundleSubject(bundle(identity(), missing="M9"))


def test_frozen_train_bundle_can_be_used_as_new_validation_configuration():
    subject = JointBundleSubject(bundle(identity()))
    edge = ConfigurationUse(subject, output("independent-val", "validation"))
    assert edge.target.identity.domain == "validation"


def test_canonical_subjects_bind_real_component_and_bundle_digests():
    train = identity(); target = identity("target")
    component_subject = CandidateComponentSubject(component("M1", train, target))
    candidate = ArtifactSubject.candidate_component(component_subject, history=train, targets=[target],
        selection_digest="d" * 64, protocol_digest="e" * 64)
    bundle_subject = JointBundleSubject(bundle(train, target))
    joint = ArtifactSubject.joint_bundle(bundle_subject, history=train, targets=[target],
        selection_digest="d" * 64, protocol_digest="e" * 64)
    assert candidate.record.data()["component_digest"] == component_subject.digest
    assert joint.record.data()["bundle_digest"] == bundle_subject.digest
