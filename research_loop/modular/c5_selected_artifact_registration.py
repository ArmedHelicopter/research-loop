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
import hashlib
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



def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _provenance_paths(path: Path) -> tuple[Path, Path]:
    return path.with_name(path.name + '.original'), path.with_name(path.name + '.provenance.json')


def _retain_registration_bytes(path: Path, record: FrozenRecord) -> FrozenRecord:
    """Complete only exact same-record retention; never overwrite evidence."""
    raw = path.read_bytes(); expected = record.encoded.encode('utf-8') + b'\n'
    if raw != expected:
        raise ContractError('selected registration bytes differ before retention')
    original, sidecar = _provenance_paths(path)
    if original.exists():
        if original.read_bytes() != raw:
            raise ContractError('existing selected registration original differs')
    else:
        with original.open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    body = {'schema':'c5-selected-registration-provenance-v1',
        'registration':{'path':str(path.resolve()),'sha256':_sha(raw),'bytes':len(raw)},
        'original':{'path':str(original.resolve()),'sha256':_sha(raw),'bytes':len(raw)},
        'registration_digest':record.content_hash,'producer_source':source_snapshot(Path(__file__)),
        'scope':'task_neutral_cross_task_selected_bundle','authorization':'none','scientific_status':'not_measured'}
    sealed=FrozenRecord.from_dict(body); expected_sidecar=sealed.encoded.encode('utf-8')+b'\n'
    if sidecar.exists():
        if sidecar.read_bytes() != expected_sidecar:
            raise ContractError('existing selected registration provenance differs')
    else:
        with sidecar.open('x',encoding='utf-8',newline='\n') as stream:
            stream.write(sealed.encoded+'\n'); stream.flush(); os.fsync(stream.fileno())
    return sealed

def _verify_retained_registration(path: Path, record: FrozenRecord) -> FrozenRecord:
    original, sidecar = _provenance_paths(path)
    try:
        raw=path.read_bytes(); original_raw=original.read_bytes(); sealed_raw=sidecar.read_bytes()
    except OSError as exc:
        raise ContractError('selected registration retention is incomplete') from exc
    if raw != record.encoded.encode('utf-8') + b'\n' or original_raw != raw:
        raise ContractError('selected registration original bytes differ')
    if not sealed_raw.endswith(b'\n') or sealed_raw.count(b'\n') != 1:
        raise ContractError('selected registration provenance is incomplete')
    sealed=FrozenRecord(sealed_raw[:-1].decode('utf-8')).data()
    expected={'schema':'c5-selected-registration-provenance-v1',
        'registration':{'path':str(path.resolve()),'sha256':_sha(raw),'bytes':len(raw)},
        'original':{'path':str(original.resolve()),'sha256':_sha(raw),'bytes':len(raw)},
        'registration_digest':record.content_hash,'producer_source':source_snapshot(Path(__file__)),
        'scope':'task_neutral_cross_task_selected_bundle','authorization':'none','scientific_status':'not_measured'}
    if sealed != expected or path.read_bytes()!=raw or original.read_bytes()!=original_raw or sidecar.read_bytes()!=sealed_raw:
        raise ContractError('selected registration provenance differs')
    return FrozenRecord.from_dict(sealed)

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
    expected = result.record.encoded.encode('utf-8') + b"\n"
    if target.exists():
        # A crash may have left only the target. Completion is permitted only
        # after fresh authentication reconstructed exactly these bytes.
        if target.read_bytes() != expected:
            raise ContractError('existing selected registration differs; retention cannot resume')
        original, sidecar = _provenance_paths(target)
        if original.exists() and sidecar.exists():
            _verify_retained_registration(target, result.record)
            raise FileExistsError(str(target))
    else:
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(result.record.encoded + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    held = _retain_registration_bytes(target, result.record)
    if held != _verify_retained_registration(target, result.record):
        raise ContractError('selected registration retention changed before return')
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
    _verify_retained_registration(Path(path), persisted.record)
    return persisted
