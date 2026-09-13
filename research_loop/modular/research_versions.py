"""Durable research-version boundaries; retrieved material cannot rewrite a goal."""
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError


class ResearchVersionBoundary:
    def __init__(self, session):
        self.session = session
        self.parent = FrozenRecord.from_dict({"schema": "research-version-v1", "identity": session.task.identity.data(),
            "task_digest": session.task.content_hash, "objective": session.objective.data(), "lock_digest": session.lock.content_hash})
        self.path = session.sidecar / "research-version-parent.json"
        self._write(self.path, self.parent)
        self.state = "running"
        self.child = None
        self._transition("running", "initial_freeze")
        session.bind_research_version(self)

    @staticmethod
    def _write(path, record):
        import os
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(record.encoded + "\n"); stream.flush(); os.fsync(stream.fileno())

    def _transition(self, state, reason):
        self.assert_immutable()
        before = self.state; self.state = state
        self.session._record("research_version_transition", {"parent_digest": self.parent.content_hash,
            "from": before, "to": state, "reason": reason})

    def assert_immutable(self):
        if self.path.read_text(encoding="utf-8") != self.parent.encoded + "\n" or self.session.objective.data() != self.parent.data()["objective"]:
            raise ContractError("research version objective changed")

    def require_research(self):
        self.assert_immutable()
        if self.state != "running": raise ContractError("research version is not running")

    def replace_objective(self, objective):
        self.session._record("research_objective_mutation_refused", {"parent_digest": self.parent.content_hash,
            "proposed_objective_digest": objective.content_hash})
        raise ContractError("current research objective is immutable")

    def conflict(self, subject):
        self.require_research()
        self._transition("needs_review", subject.content_hash)

    def pause_and_freeze(self, objective, authority, authorization):
        self.require_research()
        if objective.content_hash == self.session.objective.content_hash: raise ContractError("new version requires a distinct objective")
        subject = FrozenRecord.from_dict({"identity": self.session.task.identity.data(), "task_digest": self.session.task.content_hash,
            "parent_digest": self.parent.content_hash, "old_objective_digest": self.session.objective.content_hash,
            "new_objective": objective.data(), "authorization": authorization.data()})
        # Authority is a caller port; the model response and source text cannot supply it.
        checked = authority.freeze_version(subject)
        expected = FrozenRecord.from_dict({"schema": "independent-research-version-freeze-v1", "subject_digest": subject.content_hash,
            "authorized": True, "scientific_verified": False})
        if not isinstance(checked, FrozenRecord) or checked.content_hash != expected.content_hash:
            raise ContractError("new research version lacks independent authorization")
        self._transition("paused", subject.content_hash)
        self.child = FrozenRecord.from_dict({"schema": "research-version-child-v1", **subject.data(),
            "freeze_receipt": checked.data(), "state": "frozen_not_started"})
        self._write(self.session.sidecar / "research-version-child.json", self.child)
        self.session._record("research_version_child_frozen", self.child.data())

    def start_child(self):
        raise ContractError("child research requires separate execution authorization")

    def data(self):
        self.assert_immutable()
        return {"parent_digest": self.parent.content_hash, "state": self.state,
            "objective_digest": self.session.objective.content_hash,
            "child": self.child.data() if self.child else None}
