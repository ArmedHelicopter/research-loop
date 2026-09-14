"""Typed subjects and edges for future artifact-catalogue integration.

This module deliberately does not authenticate runs.  It binds canonical values
that an authenticated root snapshot factory has already produced.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.joint_deployment import JointComponentVersion, JointDeploymentBundle
from research_loop.modular.joint_train_protocol import FrozenJointTrainProtocol
from research_loop.modular.modules.improvement import TrainingManifest
from research_loop.ontology import ContractError


def _digest(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ContractError(f"{name} must be a sha256 digest")
    return value


def _train_identities(manifests: Iterable[TrainingManifest]) -> frozenset[DataIdentity]:
    result: set[DataIdentity] = set()
    for manifest in manifests:
        if type(manifest) is not TrainingManifest:
            raise ContractError("artifact subject requires typed TRAIN provenance")
        for identity in manifest.identities():
            identity.require_train()
            result.add(identity)
    if not result:
        raise ContractError("artifact subject requires TRAIN provenance")
    return frozenset(result)


@dataclass(frozen=True)
class ArtifactSubject:
    """Canonical subject record for catalogue descriptors, without run authentication."""
    record: FrozenRecord

    def __post_init__(self) -> None:
        if type(self.record) is not FrozenRecord:
            raise ContractError("artifact subject requires a canonical record")
        data = self.record.data()
        kind = data.get("kind")
        common = {"schema", "kind", "identities", "payload_digest"}
        if kind == "task_output":
            if data.get("schema") != "artifact-subject-v1" or set(data) != common or not isinstance(data["identities"], list) or len(data["identities"]) != 1:
                raise ContractError("task output subject has an invalid schema")
            DataIdentity.parse(data["identities"][0])
            _digest(data["payload_digest"], "payload_digest")
        elif kind in {"candidate_component", "joint_bundle"}:
            required = common | {"history", "targets", "selection_digest", "protocol_digest"}
            if kind == "candidate_component": required |= {"component_id", "component_digest"}
            else: required |= {"bundle_digest", "component_digests"}
            if data.get("schema") != "artifact-subject-v1" or set(data) != required or data["identities"] != []:
                raise ContractError("TRAIN artifact subject has an invalid schema")
            history = DataIdentity.parse(data["history"]); history.require_train()
            targets = tuple(DataIdentity.parse(item) for item in data["targets"])
            if not targets or any(item.domain != "train" for item in targets):
                raise ContractError("selection targets must be nonempty TRAIN identities")
            if len(set(targets)) != len(targets) or history in targets or list(targets) != sorted(targets, key=lambda item: FrozenRecord.from_dict(item.data()).content_hash):
                raise ContractError("artifact subject has duplicate or overlapping task identities")
            for field in ("payload_digest", "selection_digest", "protocol_digest"):
                _digest(data[field], field)
            if kind == "candidate_component":
                if data["component_id"] not in {f"M{i}" for i in range(1, 10)}: raise ContractError("component subject id is invalid")
                _digest(data["component_digest"], "component_digest")
            else:
                _digest(data["bundle_digest"], "bundle_digest")
                if set(data["component_digests"]) != {f"M{i}" for i in range(1, 10)}:
                    raise ContractError("joint bundle subject lacks exact module inventory")
                for digest in data["component_digests"].values(): _digest(digest, "component_digest")
        else:
            raise ContractError("artifact subject kind is invalid")

    @property
    def digest(self) -> str: return self.record.content_hash

    @classmethod
    def task_output(cls, identity: DataIdentity, payload: FrozenRecord) -> "ArtifactSubject":
        if type(identity) is not DataIdentity or type(payload) is not FrozenRecord:
            raise ContractError("task output subject requires typed identity and payload")
        return cls(FrozenRecord.from_dict({"schema": "artifact-subject-v1", "kind": "task_output",
            "identities": [identity.data()], "payload_digest": payload.content_hash}))

    @classmethod
    def candidate_component(cls, component: "CandidateComponentSubject", *, history: DataIdentity,
                            targets: Iterable[DataIdentity], selection_digest: str, protocol_digest: str) -> "ArtifactSubject":
        if type(component) is not CandidateComponentSubject or type(history) is not DataIdentity:
            raise ContractError("component subject requires typed component and history")
        identities = tuple(sorted(targets, key=lambda item: FrozenRecord.from_dict(item.data()).content_hash))
        if component.train_identities != {history, *identities}:
            raise ContractError("component subject provenance differs from frozen TRAIN component")
        return cls(FrozenRecord.from_dict({"schema": "artifact-subject-v1", "kind": "candidate_component",
            "identities": [], "payload_digest": component.digest, "history": history.data(),
            "targets": [item.data() for item in identities], "selection_digest": _digest(selection_digest, "selection_digest"),
            "protocol_digest": _digest(protocol_digest, "protocol_digest"), "component_id": component.component.module_id,
            "component_digest": component.digest}))

    @classmethod
    def joint_bundle(cls, bundle: "JointBundleSubject", *, history: DataIdentity, targets: Iterable[DataIdentity],
                     selection_digest: str, protocol_digest: str) -> "ArtifactSubject":
        if type(bundle) is not JointBundleSubject or type(history) is not DataIdentity:
            raise ContractError("bundle subject requires typed bundle and history")
        identities = tuple(sorted(targets, key=lambda item: FrozenRecord.from_dict(item.data()).content_hash))
        if bundle.train_identities != {history, *identities}:
            raise ContractError("bundle subject provenance differs from frozen TRAIN bundle")
        return cls(FrozenRecord.from_dict({"schema": "artifact-subject-v1", "kind": "joint_bundle",
            "identities": [], "payload_digest": bundle.digest, "history": history.data(),
            "targets": [item.data() for item in identities], "selection_digest": _digest(selection_digest, "selection_digest"),
            "protocol_digest": _digest(protocol_digest, "protocol_digest"), "bundle_digest": bundle.digest,
            "component_digests": bundle.component_digests}))


@dataclass(frozen=True)
class TaskOutputSubject:
    """A concrete task payload; task evidence can address only this subject."""
    identity: DataIdentity
    payload: FrozenRecord

    def __post_init__(self) -> None:
        if type(self.identity) is not DataIdentity or type(self.payload) is not FrozenRecord:
            raise ContractError("task output requires typed identity and canonical payload")

    @property
    def digest(self) -> str:
        return FrozenRecord.from_dict({"identity": self.identity.data(), "payload": self.payload.data()}).content_hash


@dataclass(frozen=True)
class CandidateComponentSubject:
    component: JointComponentVersion

    def __post_init__(self) -> None:
        if type(self.component) is not JointComponentVersion:
            raise ContractError("candidate component requires an exact component version")

    @property
    def digest(self) -> str:
        return self.component.digest

    @property
    def train_identities(self) -> frozenset[DataIdentity]:
        return _train_identities((TrainingManifest(FrozenRecord.from_dict(self.component.record.data()["training_manifest"])),))


@dataclass(frozen=True)
class JointBundleSubject:
    bundle: JointDeploymentBundle

    def __post_init__(self) -> None:
        if type(self.bundle) is not JointDeploymentBundle:
            raise ContractError("joint bundle requires an exact deployment bundle")
        components = self.bundle.components()
        if set(components) != {f"M{i}" for i in range(1, 10)}:
            raise ContractError("joint bundle must contain the complete M1 through M9 inventory")

    @property
    def digest(self) -> str:
        return self.bundle.digest

    @property
    def component_digests(self) -> dict[str, str]:
        return {name: component.digest for name, component in self.bundle.components().items()}

    @property
    def train_identities(self) -> frozenset[DataIdentity]:
        return _train_identities(TrainingManifest(FrozenRecord.from_dict(component.record.data()["training_manifest"]))
                                 for component in self.bundle.components().values())

    @classmethod
    def from_selected_snapshot(cls, snapshot: FrozenRecord, protocol: FrozenJointTrainProtocol) -> "JointBundleSubject":
        """Bind the exact C5 selected snapshot without treating it as a run receipt."""
        if type(snapshot) is not FrozenRecord or type(protocol) is not FrozenJointTrainProtocol:
            raise ContractError("selected snapshot and protocol require exact typed records")
        protocol.__post_init__()
        data = snapshot.data()
        required = {"schema", "protocol_digest", "selection", "selection_digest", "selected_subject_digest",
                    "package_digest", "parent_digest", "bundle", "bundle_digest", "component_digests",
                    "training_provenance", "status", "validation_access_authorized", "acceptance_verified",
                    "deployment_authorized"}
        if (set(data) != required or data["schema"] != "c5-selected-joint-snapshot-v1"
                or data["protocol_digest"] != protocol.digest):
            raise ContractError("selected snapshot schema is invalid")
        bundle = JointDeploymentBundle(FrozenRecord.from_dict(data["bundle"]))
        subject = cls(bundle)
        if data["bundle_digest"] != subject.digest or data["component_digests"] != subject.component_digests:
            raise ContractError("selected snapshot bundle or component digest differs")
        p = protocol.record.data()
        expected = {DataIdentity.parse(row["identity"]) for row in [p["history"], *p["targets"]]}
        manifest = TrainingManifest(FrozenRecord.from_dict(data["training_provenance"]))
        if set(manifest.identities()) != expected or subject.train_identities != expected:
            raise ContractError("selected snapshot TRAIN provenance is not in the bundle")
        choice = FrozenRecord.from_dict(data["selection"])
        selected = choice.data().get("selected_subject")
        recipes = {row["recipe"]["id"]: row["recipe"] for row in p["catalogue"]["recipes"]}
        if (choice.content_hash != data["selection_digest"] or choice.data().get("protocol_digest") != protocol.digest
                or choice.data().get("selected_subject_digest") != data["selected_subject_digest"]
                or not isinstance(selected, dict) or FrozenRecord.from_dict(selected).content_hash != data["selected_subject_digest"]
                or selected.get("recipe") != recipes.get(choice.data().get("selected_arm"))
                or selected.get("package_digest") != data["package_digest"]):
            raise ContractError("selected snapshot selection binding differs")
        for name, component in bundle.components().items():
            body = component.record.data()
            selected_package = body["state"].get("selected_package")
            if (body["config"].get("module_id") != name or body["state"].get("selection_digest") != data["selection_digest"]
                    or not isinstance(selected_package, dict)
                    or FrozenRecord.from_dict(selected_package).content_hash != data["package_digest"]):
                raise ContractError("selected snapshot component state differs")
        return subject


@dataclass(frozen=True)
class TaskEvidenceEdge:
    relation: str
    subject: TaskOutputSubject
    evidence: TaskOutputSubject

    def __post_init__(self) -> None:
        if self.relation not in {"supports", "refutes"}:
            raise ContractError("task evidence relation must support or refute")
        if type(self.subject) is not TaskOutputSubject or type(self.evidence) is not TaskOutputSubject:
            raise ContractError("task evidence requires task-output subjects")
        if self.subject.identity != self.evidence.identity:
            raise ContractError("task evidence cannot cross task subjects")


@dataclass(frozen=True)
class TrainSelectionControl:
    """A cross-task TRAIN selection control, never task evidence."""
    source: CandidateComponentSubject | JointBundleSubject
    target: DataIdentity

    def __post_init__(self) -> None:
        if type(self.source) not in {CandidateComponentSubject, JointBundleSubject} or type(self.target) is not DataIdentity:
            raise ContractError("selection control requires typed source and target")
        self.target.require_train()
        if self.target not in self.source.train_identities:
            raise ContractError("selection control target is absent from frozen train provenance")


@dataclass(frozen=True)
class ConfigurationUse:
    """A frozen TRAIN candidate/bundle may be consumed by a distinct task."""
    source: CandidateComponentSubject | JointBundleSubject
    target: TaskOutputSubject

    def __post_init__(self) -> None:
        if type(self.source) not in {CandidateComponentSubject, JointBundleSubject} or type(self.target) is not TaskOutputSubject:
            raise ContractError("configuration use requires typed source and task output")
        if not self.source.train_identities:
            raise ContractError("configuration use requires frozen TRAIN provenance")
