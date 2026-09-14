"""Offline, authenticated C5 selected-snapshot registration seam.

This does not write an ArtifactCatalogue.  It produces one canonical record for
a later catalogue adapter, and only obtains snapshots through the complete-run
authentication entry point.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from research_loop.modular.artifact_subjects import JointBundleSubject
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.joint_deployment import JointDeploymentBundle
from research_loop.modular.artifact_catalogue import source_snapshot
from research_loop.ontology import ContractError


@dataclass(frozen=True)
class RegisteredSelectedBundle:
    """Canonical registration consistency wrapper; it does not authenticate a run."""
    record: FrozenRecord

    def __post_init__(self):
        if type(self.record) is not FrozenRecord:
            raise ContractError("registered selected bundle requires a canonical record")
        data = self.record.data()
        fields = {"schema", "snapshot", "snapshot_digest", "bundle_digest", "components", "history", "targets",
                  "protocol_digest", "selection_digest", "package_digest", "typed_edges", "scientific_validated",
                  "acceptance_verified", "deployment_authorized", "producer_source"}
        if set(data) != fields or data["schema"] != "c5-selected-artifact-registration-v1":
            raise ContractError("selected artifact registration schema differs")
        if FrozenRecord.from_dict(data["snapshot"]).content_hash != data["snapshot_digest"]:
            raise ContractError("registered selected snapshot digest differs")
        if set(data["components"]) != {f"M{i}" for i in range(1, 10)}:
            raise ContractError("registered selected bundle lacks a component")
        identities = {DataIdentity.parse(data["history"]), *(DataIdentity.parse(row) for row in data["targets"])}
        if any(item.domain != "train" for item in identities) or len(identities) != len(data["targets"]) + 1:
            raise ContractError("registered selected bundle has invalid TRAIN provenance")
        if any(data[name] is not False for name in ("scientific_validated", "acceptance_verified", "deployment_authorized")):
            raise ContractError("registration cannot grant scientific or deployment authority")
        snapshot = data["snapshot"]
        if any(data[name] != snapshot[name] for name in ("bundle_digest", "protocol_digest", "selection_digest", "package_digest")):
            raise ContractError("registered selected snapshot bindings differ")
        if data["components"] != snapshot["component_digests"] or data["history"] is None or data["targets"] == []:
            raise ContractError("registered selected provenance differs")
        if data["producer_source"] != source_snapshot(Path(__file__)):
            raise ContractError("registered adapter source differs")
        if data["typed_edges"] != [{"kind": "derived_from", "component_digest": data["components"][name], "bundle_digest": data["bundle_digest"]}
                                   for name in sorted(data["components"])]:
            raise ContractError("registered selected bundle edges differ")


def _registration_record(snapshot: FrozenRecord, protocol, parent: JointDeploymentBundle, timeout_seconds: int) -> RegisteredSelectedBundle:
    """Pure projection-to-registration constructor; no writes or run authentication."""
    subject = JointBundleSubject.from_selected_snapshot(snapshot, protocol, parent=parent, timeout_seconds=timeout_seconds)
    data = snapshot.data(); p = protocol.record.data()
    return RegisteredSelectedBundle(FrozenRecord.from_dict({
        "schema": "c5-selected-artifact-registration-v1", "snapshot": snapshot.data(),
        "snapshot_digest": snapshot.content_hash, "bundle_digest": subject.digest,
        "components": subject.component_digests, "history": p["history"]["identity"],
        "targets": [row["identity"] for row in p["targets"]], "protocol_digest": protocol.digest,
        "selection_digest": data["selection_digest"], "package_digest": data["package_digest"],
        "typed_edges": [{"kind": "derived_from", "component_digest": subject.component_digests[name], "bundle_digest": subject.digest}
                        for name in sorted(subject.component_digests)],
        "scientific_validated": False, "acceptance_verified": False, "deployment_authorized": False,
        "producer_source": source_snapshot(Path(__file__)),
    }))


def register_authenticated_selected_run(path: Path, run, *, parent: JointDeploymentBundle, execution_authority_keys, scorer_authority_keys) -> RegisteredSelectedBundle:
    """Authenticate a complete run, then preserve its complete selected projection.

    The caller supplies the same authorities required by the C5 selection
    entrypoint.  This function has no `_project` or arbitrary-snapshot input.
    """
    from research_loop.modular.joint_selected_snapshot import freeze_selected_joint_snapshot
    if type(parent) is not JointDeploymentBundle:
        raise ContractError("selected artifact registration requires typed preceding bundle")
    snapshot = freeze_selected_joint_snapshot(run, parent=parent,
        execution_authority_keys=execution_authority_keys, scorer_authority_keys=scorer_authority_keys)
    result = _registration_record(snapshot, run.plan.protocol, parent, run.plan.data()["timeout_seconds"])
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(result.record.encoded + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return result


def verify_registration(path: Path, run, *, parent: JointDeploymentBundle, execution_authority_keys, scorer_authority_keys) -> RegisteredSelectedBundle:
    """Re-authenticate the run and exactly compare the independently persisted record."""
    raw = Path(path).read_bytes().decode("utf-8")
    if not raw.endswith("\n") or raw.count("\n") != 1:
        raise ContractError("registration file must contain one complete canonical record")
    persisted = RegisteredSelectedBundle(FrozenRecord(raw[:-1]))
    from research_loop.modular.joint_selected_snapshot import freeze_selected_joint_snapshot
    snapshot = freeze_selected_joint_snapshot(run, parent=parent,
        execution_authority_keys=execution_authority_keys, scorer_authority_keys=scorer_authority_keys)
    rebuilt = _registration_record(snapshot, run.plan.protocol, parent, run.plan.data()["timeout_seconds"])
    if persisted != rebuilt:
        raise ContractError("persisted selected artifact registration differs from reauthenticated run")
    return persisted
