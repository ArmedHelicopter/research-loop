"""Durable research-version boundaries; retrieved material cannot rewrite a goal."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Mapping

from research_loop.modular.artifact_catalogue import ArtifactCatalogue, source_snapshot
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError


_PARENT = "research-version-parent.json"
_CHILD = "research-version-child.json"


def _safe(path: Path) -> Path:
    path = Path(path)
    attrs = path.parent.stat().st_file_attributes if hasattr(path.parent.stat(), "st_file_attributes") else 0
    if path.is_symlink() or path.parent.is_symlink() or attrs & 0x400:
        raise ContractError("research version path cannot be a link or junction")
    return path


def _snapshot(path: Path, record: FrozenRecord) -> dict[str, Any]:
    path = _safe(path)
    raw = path.read_bytes()
    expected = (record.encoded + "\n").encode("utf-8")
    if raw != expected:
        raise ContractError("research version disk bytes differ from frozen record")
    return {"path": path.name, "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw), "record_digest": record.content_hash}


def _publish(path: Path, record: FrozenRecord) -> dict[str, Any]:
    """Publish one file after its bytes reach disk; retain a failed prefix."""
    path = _safe(path)
    if path.exists():
        raise ContractError("research version output already exists")
    partial = path.with_name(path.name + ".partial")
    if partial.exists():
        raise ContractError("research version partial output requires inspection")
    try:
        with partial.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(record.encoded + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        # Hard-link publication is exclusive: unlike replace(), it cannot win a
        # race by overwriting another producer's final name.
        os.link(partial, path)
        partial.unlink()
    except Exception:
        # Do not remove a partial write: it is an auditable incomplete prefix.
        raise
    return _snapshot(path, record)


class ResearchVersionBoundary:
    def __init__(self, session):
        self.session = session
        self.parent = FrozenRecord.from_dict({"schema": "research-version-v1", "identity": session.task.identity.data(),
            "task_digest": session.task.content_hash, "objective": session.objective.data(), "lock_digest": session.lock.content_hash})
        self.path = session.sidecar / _PARENT
        self.child_path = session.sidecar / _CHILD
        root = Path(__file__).parent
        self.sources = {name: source_snapshot(root / name) for name in
                        ("research_versions.py", "runtime.py", "workflow.py", "contracts.py", "retrieval_final_panel_drivers.py")}
        self.source = self.sources["research_versions.py"]
        self.parent_snapshot = _publish(self.path, self.parent)
        self.child_snapshot = None
        self.parent_artifact = None
        self.child_artifact = None
        self.state = "running"
        self.child = None
        self.session._record("research_version_parent_persisted", {"parent_digest": self.parent.content_hash,
            "file": self.parent_snapshot})
        self.parent_artifact = self._register("research_version_parent", self.parent_snapshot)
        self._transition("running", "initial_freeze")
        session.bind_research_version(self)

    def _register(self, kind: str, snapshot: Mapping[str, Any], extra_parents=()):
        register = getattr(self.session, "record_artifact", None)
        if not callable(register):
            if hasattr(self.session, "artifacts"):
                raise ContractError("research version requires runtime artifact registration")
            return None
        parents = (() if kind == "research_version_parent" or self.parent_artifact is None else (self.parent_artifact.content_hash,)) + tuple(extra_parents)
        return register(kind=kind, module="M1", payload={"file": dict(snapshot), "source_pins": self.sources}, parents=parents,
                        status="produced" if "M1" in self.session.arm.data()["enabled"] else "not_applied",
                        producer_source=self.source)

    def _assert_source(self) -> None:
        if any(source_snapshot(Path(row["path"])) != row for row in self.sources.values()):
            raise ContractError("research version behavior source changed")

    def _assert_disk(self) -> None:
        self._assert_source()
        if hasattr(self.session, "artifacts"):
            self.session.artifacts.verify()
        if _snapshot(self.path, self.parent) != self.parent_snapshot:
            raise ContractError("research version parent snapshot changed")
        if self.child is None:
            if self.child_path.exists():
                raise ContractError("research version child exists without a frozen child")
        elif self.child_snapshot is None or _snapshot(self.child_path, self.child) != self.child_snapshot:
            raise ContractError("research version child snapshot changed")

    def _transition(self, state, reason):
        self.assert_immutable()
        before = self.state
        self.session._record("research_version_transition", {"parent_digest": self.parent.content_hash,
            "from": before, "to": state, "reason": reason})
        self.state = state

    def assert_immutable(self):
        self._assert_disk()
        if self.session.objective.data() != self.parent.data()["objective"]:
            raise ContractError("research version objective changed")

    def require_research(self):
        self.assert_immutable()
        if self.state != "running":
            raise ContractError("research version is not running")

    def replace_objective(self, objective):
        self.assert_immutable()
        self.session._record("research_objective_mutation_refused", {"parent_digest": self.parent.content_hash,
            "proposed_objective_digest": objective.content_hash})
        raise ContractError("current research objective is immutable")

    def conflict(self, subject):
        self.require_research()
        self._transition("needs_review", subject.content_hash)

    def pause_and_freeze(self, objective, authority, authorization):
        self.require_research()
        if not isinstance(authorization, FrozenRecord):
            raise ContractError("research version authorization must be frozen")
        if objective.content_hash == self.session.objective.content_hash:
            raise ContractError("new version requires a distinct objective")
        subject = FrozenRecord.from_dict({"identity": self.session.task.identity.data(), "task_digest": self.session.task.content_hash,
            "parent_digest": self.parent.content_hash, "old_objective_digest": self.session.objective.content_hash,
            "new_objective": objective.data(), "authorization": authorization.data()})
        checked = authority.freeze_version(subject)
        expected = FrozenRecord.from_dict({"schema": "independent-research-version-freeze-v1", "subject_digest": subject.content_hash,
            "authorized": True, "scientific_verified": False})
        if not isinstance(checked, FrozenRecord) or checked.content_hash != expected.content_hash:
            raise ContractError("new research version lacks independent authorization")
        self.assert_immutable()
        child = FrozenRecord.from_dict({"schema": "research-version-child-v1", **subject.data(),
            "freeze_receipt": checked.data(), "state": "frozen_not_started"})
        child_snapshot = _publish(self.child_path, child)
        self.child, self.child_snapshot = child, child_snapshot
        self.session._record("research_version_child_persisted", {"parent_digest": self.parent.content_hash,
            "child_digest": child.content_hash, "file": child_snapshot})
        authority_artifact = authorization.data().get("authority_artifact")
        if authority_artifact is not None and not isinstance(authority_artifact, str):
            raise ContractError("research version authorization trace reference is malformed")
        self.child_artifact = self._register("research_version_child", child_snapshot,
                                             (() if authority_artifact is None else (authority_artifact,)))
        self._transition("paused", subject.content_hash)
        self.session._record("research_version_child_frozen", self.child.data())

    def start_child(self):
        raise ContractError("child research requires separate execution authorization")

    def data(self):
        self.assert_immutable()
        return {"parent_digest": self.parent.content_hash, "state": self.state,
            "objective_digest": self.session.objective.content_hash,
            "child": self.child.data() if self.child else None}


def _catalogue(sidecar: Path, identity) -> ArtifactCatalogue:
    path = sidecar / "artifacts.jsonl"
    try:
        first = FrozenRecord(path.read_text(encoding="utf-8").splitlines()[0]).data()["descriptor"]
        return ArtifactCatalogue(path, identity=identity, **first["binding"], producer_source=first["producer_source"])
    except (IndexError, KeyError, OSError, TypeError, ValueError) as exc:
        raise ContractError("research version catalogue has no original binding") from exc


def verify_research_version_artifacts(sidecar: Path, *, identity, task_digest: str,
                                      lock: Mapping[str, Any], events: tuple[Mapping[str, Any], ...]) -> FrozenRecord:
    """Read-only Q8.6 consumer gate, anchored in independent cell/task expectations."""
    sidecar = Path(sidecar)
    if any(sidecar.glob("research-version-*.json.partial")):
        raise ContractError("research version retains an incomplete file prefix")
    lock_record = FrozenRecord.from_dict(dict(lock))
    parent = FrozenRecord.from_dict({"schema": "research-version-v1", "identity": identity.data(),
        "task_digest": task_digest, "objective": lock["objective"], "lock_digest": lock_record.content_hash})
    parent_snapshot = _snapshot(sidecar / _PARENT, parent)
    parent_events = [row for row in events if row.get("stage") == "research_version_parent_persisted"]
    if len(parent_events) != 1 or parent_events[0].get("data") != {"parent_digest": parent.content_hash, "file": parent_snapshot}:
        raise ContractError("research version parent is not trace-bound")
    catalogue = _catalogue(sidecar, identity)
    if not catalogue.seal_path.exists():
        raise ContractError("research version catalogue is not sealed")
    records = catalogue.records()
    by_kind = {kind: [record for record in records if record.data()["kind"] == kind]
               for kind in ("research_version_parent", "research_version_child")}
    if len(by_kind["research_version_parent"]) != 1:
        raise ContractError("research version parent descriptor is missing or duplicated")
    parent_descriptor = by_kind["research_version_parent"][0]
    root = Path(__file__).parent
    expected_pins = {name: source_snapshot(root / name) for name in
                     ("research_versions.py", "runtime.py", "workflow.py", "contracts.py", "retrieval_final_panel_drivers.py")}
    if parent_descriptor.data()["payload"]["canonical"] != {"file": parent_snapshot, "source_pins": expected_pins}:
        raise ContractError("research version parent descriptor bytes differ")
    parent_event = FrozenRecord.from_dict(parent_events[0])
    trace_parent = next((record.content_hash for record in records
                         if record.data()["kind"] == "trace_event"
                         and record.data()["payload"]["canonical"] == parent_event.data()), None)
    if trace_parent is None or trace_parent not in parent_descriptor.data()["parents"]:
        raise ContractError("research version parent lacks its exact trace parent")
    transitions = [row["data"] for row in events if row.get("stage") == "research_version_transition"]
    initial = {"parent_digest": parent.content_hash, "from": "running", "to": "running", "reason": "initial_freeze"}
    if not transitions or transitions[0] != initial:
        raise ContractError("research version initial transition differs")
    state = transitions[-1]["to"]
    child_path = sidecar / _CHILD
    child_events = [row for row in events if row.get("stage") == "research_version_child_persisted"]
    frozen_events = [row for row in events if row.get("stage") == "research_version_child_frozen"]
    if state != "paused":
        if child_path.exists() or by_kind["research_version_child"] or child_events or frozen_events:
            raise ContractError("nonpaused research version has a child output")
    else:
        if len(by_kind["research_version_child"]) != 1 or len(child_events) != 1 or len(frozen_events) != 1:
            raise ContractError("paused research version lacks a complete child output")
        child = FrozenRecord(child_path.read_text(encoding="utf-8").removesuffix("\n"))
        child_snapshot = _snapshot(child_path, child)
        child_descriptor = by_kind["research_version_child"][0]
        if child_descriptor.data()["payload"]["canonical"] != {"file": child_snapshot, "source_pins": expected_pins}:
            raise ContractError("research version child descriptor differs from parent edge")
        if child_events[0].get("data") != {"parent_digest": parent.content_hash, "child_digest": child.content_hash, "file": child_snapshot}:
            raise ContractError("research version child is not trace-bound")
        if frozen_events[0].get("data") != child.data():
            raise ContractError("research version child frozen record differs")
        authorization = child.data().get("authorization")
        child_subject = FrozenRecord.from_dict({k: v for k, v in child.data().items() if k not in {"schema", "freeze_receipt", "state"}})
        source_events = [row for row in events if row.get("stage") == "q86_source_authority"]
        if len(source_events) != 1 or not isinstance(authorization, dict) or set(authorization) != {"schema", "subject", "receipt", "authority_artifact"}:
            raise ContractError("research version child lacks independent origin authorization")
        source = source_events[0]["data"]
        authority_event = FrozenRecord.from_dict(source_events[0])
        authority_descriptor = next((record.content_hash for record in records if record.data()["kind"] == "trace_event"
            and record.data()["payload"]["canonical"] == authority_event.data()), None)
        child_event = FrozenRecord.from_dict(child_events[0])
        child_trace_descriptor = next((record.content_hash for record in records if record.data()["kind"] == "trace_event"
            and record.data()["payload"]["canonical"] == child_event.data()), None)
        expected_authorization = {"schema": "q86-origin-authorization-v1", "subject": source["subject"], "receipt": source["receipt"],
            "authority_artifact": authority_descriptor}
        if authorization != expected_authorization:
            raise ContractError("research version child origin authorization differs")
        if set(child_descriptor.data()["parents"]) != {parent_descriptor.content_hash, authority_descriptor, child_trace_descriptor}:
            raise ContractError("research version child lacks exact parent, authority and persistence edges")
        source_subject = FrozenRecord.from_dict(source["subject"])
        source_receipt = FrozenRecord.from_dict(source["receipt"])
        expected_source_receipt = FrozenRecord.from_dict({"schema": "q8-origin-qualification-v1", "subject_digest": source_subject.content_hash,
            "caller_public_train_qualified": True, "scientific_verified": False})
        if source_receipt.content_hash != expected_source_receipt.content_hash or source_subject.data().get("identity") != identity.data() or source_subject.data().get("task_digest") != task_digest:
            raise ContractError("research version origin receipt or subject binding differs")
        request = source_subject.data().get("request")
        if not isinstance(request, dict) or request.get("operation") != "request_new_version" or request.get("caller_authorized") is not True:
            raise ContractError("paused research version lacks the locked new-version request")
        expected_child_subject = FrozenRecord.from_dict({"identity": identity.data(), "task_digest": task_digest,
            "parent_digest": parent.content_hash, "old_objective_digest": FrozenRecord.from_dict(lock["objective"]).content_hash,
            "new_objective": request.get("proposed_objective"), "authorization": expected_authorization})
        if child_subject != expected_child_subject:
            raise ContractError("research version child subject differs from locked request and parent")
        child_subject = FrozenRecord.from_dict({k: v for k, v in child.data().items() if k not in {"schema", "freeze_receipt", "state"}})
        receipt = FrozenRecord.from_dict(child.data()["freeze_receipt"])
        expected = FrozenRecord.from_dict({"schema": "independent-research-version-freeze-v1", "subject_digest": child_subject.content_hash,
            "authorized": True, "scientific_verified": False})
        if receipt.content_hash != expected.content_hash or transitions[-1].get("reason") != child_subject.content_hash:
            raise ContractError("research version child receipt or transition differs")
    return FrozenRecord.from_dict({"schema": "research-version-artifact-verification-v1", "parent_digest": parent.content_hash,
        "state": state, "child_present": state == "paused", "scientific_verified": False})
