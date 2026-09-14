"""Durable research-version boundaries; retrieved material cannot rewrite a goal."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Mapping

from research_loop.modular.artifact_catalogue import source_snapshot
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError


_PARENT = "research-version-parent.json"
_CHILD = "research-version-child.json"
_INPUTS = "research-version-inputs.json"
_SOURCES = ("research_versions.py", "runtime.py", "workflow.py", "contracts.py", "artifact_catalogue.py",
            "retrieval_final_panel_drivers.py", "retrieval_panel_drivers.py", "recorded_retrieval.py",
            "retrieval_artifacts.py", "m6_public_inputs.py", "panel_runner.py", "panel_receipts.py", "research_version_verifier.py")


def _source_pins():
    root = Path(__file__).parent
    return {name: source_snapshot(_safe(root / name)) for name in _SOURCES}


def _safe(path: Path) -> Path:
    path = Path(path)
    # A junction can be hidden above the immediate parent on Windows.  Walk all
    # extant ancestors so the sidecar cannot escape through a redirected root.
    current = path.absolute()
    while True:
        try:
            stat = current.lstat()
        except FileNotFoundError:
            current = current.parent
            continue
        except OSError as exc:
            raise ContractError("research version path is inaccessible") from exc
        attrs = getattr(stat, "st_file_attributes", 0)
        if current.is_symlink() or getattr(current, "is_junction", lambda: False)() or attrs & 0x400:
            raise ContractError("research version path cannot be a link or junction")
        if current.parent == current:
            break
        current = current.parent
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
    _safe(partial)
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
    def __init__(self, session, *, cell=None, scenario=None):
        self.session = session
        self.failed = False
        self.inputs = self.inputs_snapshot = self.inputs_artifact = None
        self.state = "running"
        self.child = self.child_snapshot = self.child_artifact = self.parent_artifact = None
        try:
            self._initialize(cell, scenario)
        except Exception:
            self._fail()
            raise

    def _fail(self):
        self.failed = True
        self.session._terminal = True
        try:
            _safe(self.session.sidecar / "audit-failure.json")
        except ContractError:
            return  # Never write the failure marker through a redirected path.
        self.session._audit_failure()

    def _initialize(self, cell, scenario):
        session = self.session
        _safe(session.sidecar)
        if (cell is None) != (scenario is None):
            raise ContractError("research version requires both independent cell and scenario")
        self.sources = _source_pins()
        self.source = self.sources["research_versions.py"]
        if cell is not None:
            if not isinstance(scenario, FrozenRecord) or scenario.content_hash != cell.scenario_digest:
                raise ContractError("research version independent scenario differs")
            self.inputs = FrozenRecord.from_dict({"schema": "research-version-inputs-v1", "cell": cell.data(),
                "scenario": scenario.data(), "lock": session.lock.data(), "run_id": session.artifacts.binding["run_id"],
                "source_pins": self.sources})
            self.inputs_snapshot = _publish(session.sidecar / _INPUTS, self.inputs)
            session._record("research_version_inputs_persisted", {"file": self.inputs_snapshot})
            self.inputs_artifact = session.record_artifact(kind="research_version_inputs", module="P0",
                payload={"file": self.inputs_snapshot, "source_pins": self.sources}, producer_source=self.source)
        self.parent = FrozenRecord.from_dict({"schema": "research-version-v1", "identity": session.task.identity.data(),
            "task_digest": session.task.content_hash, "objective": session.objective.data(), "lock_digest": session.lock.content_hash})
        self.path = session.sidecar / _PARENT
        self.child_path = session.sidecar / _CHILD
        self.parent_snapshot = _publish(self.path, self.parent)
        self.child_snapshot = None
        self.parent_artifact = None
        self.child_artifact = None
        self.state = "running"
        self.child = None
        self.session._record("research_version_parent_persisted", {"parent_digest": self.parent.content_hash,
            "file": self.parent_snapshot})
        self.parent_artifact = self._register("research_version_parent", self.parent_snapshot,
            (() if self.inputs_artifact is None else (self.inputs_artifact.content_hash,)))
        self._transition("running", "initial_freeze")
        session.bind_research_version(self)

    def _register(self, kind: str, snapshot: Mapping[str, Any], extra_parents=()):
        register = getattr(self.session, "record_artifact", None)
        if not callable(register):
            raise ContractError("research version requires runtime artifact registration")
        parents = (() if kind == "research_version_parent" or self.parent_artifact is None else (self.parent_artifact.content_hash,)) + tuple(extra_parents)
        return register(kind=kind, module="M1", payload={"file": dict(snapshot), "source_pins": self.sources}, parents=parents,
                        status="produced" if "M1" in self.session.arm.data()["enabled"] else "not_applied",
                        producer_source=self.source)

    def _assert_source(self) -> None:
        if any(source_snapshot(_safe(Path(row["path"]))) != row for row in self.sources.values()):
            raise ContractError("research version behavior source changed")

    def _assert_disk(self) -> None:
        self._assert_source()
        if any(self.session.sidecar.glob("research-version-*.json.partial")):
            raise ContractError("research version has an incomplete file prefix")
        if hasattr(self.session, "artifacts"):
            # Compare original in-memory bytes BEFORE verify() reloads the disk
            # journal. A self-consistent rewrite must not replace live history.
            for path, records in ((self.session.sidecar / "trace.jsonl", self.session._events),
                                  (self.session.artifacts.path, self.session.artifacts._entries)):
                expected = "".join(row.encoded + "\n" for row in records).encode("utf-8")
                if _safe(path).read_bytes() != expected:
                    raise ContractError("research version live journal prefix changed")
            _safe(self.session.artifacts.seal_path)
            self.session.artifacts.verify()
        if self.inputs is not None and _snapshot(self.session.sidecar / _INPUTS, self.inputs) != self.inputs_snapshot:
            raise ContractError("research version independent inputs changed")
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
        if self.failed:
            raise ContractError("research version audit is terminal after failure")
        try:
            self._assert_disk()
            if self.session.objective.data() != self.parent.data()["objective"]:
                raise ContractError("research version objective changed")
        except Exception:
            self._fail()
            raise

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
        try:
            self._transition("needs_review", subject.content_hash)
        except Exception:
            self._fail()
            raise

    def qualify_origin(self, authority, subject):
        self.require_research()
        try:
            self.session._record("research_version_origin_attempt", {"subject": subject.data()})
            try:
                receipt = authority.qualify_origin(subject)
            except Exception as exc:
                self.session._record("research_version_origin_failure", {"subject_digest": subject.content_hash, "error_type": type(exc).__name__})
                raise
            self.session._record("research_version_origin_result", {"subject_digest": subject.content_hash,
                "receipt": receipt.data() if isinstance(receipt, FrozenRecord) else None, "returned_type": type(receipt).__name__})
            expected = {"schema": "q8-origin-qualification-v1", "subject_digest": subject.content_hash,
                "caller_public_train_qualified": True, "scientific_verified": False}
            if not isinstance(receipt, FrozenRecord) or receipt.data() != expected:
                raise ContractError("origin qualification drift")
            self.assert_immutable()
            return receipt
        except Exception:
            self._fail()
            raise

    def pause_and_freeze(self, objective, authority, authorization):
        self.require_research()
        self._validate_authorization(objective, authorization)
        if objective.content_hash == self.session.objective.content_hash:
            raise ContractError("new version requires a distinct objective")
        subject = FrozenRecord.from_dict({"identity": self.session.task.identity.data(), "task_digest": self.session.task.content_hash,
            "parent_digest": self.parent.content_hash, "old_objective_digest": self.session.objective.content_hash,
            "new_objective": objective.data(), "authorization": authorization.data()})
        try:
            self._freeze_child(subject, authority, authorization)
        except Exception:
            self._fail()
            raise

    def _validate_authorization(self, objective, authorization):
        error = "research version lacks independent authorization for this objective"
        if not isinstance(authorization, FrozenRecord):
            raise ContractError(error)
        body = authorization.data()
        if set(body) != {"schema", "subject", "receipt", "authority_artifact"} or body["schema"] != "q86-origin-authorization-v1":
            raise ContractError(error)
        source = body["subject"]
        if not isinstance(source, dict) or set(source) != {"kind", "identity", "task_digest", "source_bundle_digest", "visible_source_ids", "request"}:
            raise ContractError(error)
        request = source["request"]
        if (source["kind"] != "source_request" or source["identity"] != self.session.task.identity.data()
                or source["task_digest"] != self.session.task.content_hash or not isinstance(request, dict)
                or request.get("operation") != "request_new_version" or request.get("caller_authorized") is not True
                or request.get("source_id") not in source["visible_source_ids"] or request.get("proposed_objective") != objective.data()):
            raise ContractError(error)
        expected = {"schema": "q8-origin-qualification-v1", "subject_digest": FrozenRecord.from_dict(source).content_hash,
            "caller_public_train_qualified": True, "scientific_verified": False}
        matches = [(event, ref) for event, ref in zip(self.session._events, self.session._event_artifacts)
                   if event.data()["stage"] == "q86_source_authority"]
        if (body["receipt"] != expected or len(matches) != 1 or body["authority_artifact"] != matches[0][1]
                or matches[0][0].data()["data"] != {"subject": source, "receipt": expected}):
            raise ContractError(error)

    def _freeze_child(self, subject, authority, authorization):
        self.session._record("research_version_freeze_attempt", {"subject": subject.data()})
        try:
            checked = authority.freeze_version(subject)
        except Exception as exc:
            self.session._record("research_version_freeze_failure", {"subject_digest": subject.content_hash, "error_type": type(exc).__name__})
            raise
        self.session._record("research_version_freeze_result", {"subject_digest": subject.content_hash,
            "receipt": checked.data() if isinstance(checked, FrozenRecord) else None, "returned_type": type(checked).__name__})
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



from research_loop.modular.research_version_verifier import verify_research_version_artifacts
