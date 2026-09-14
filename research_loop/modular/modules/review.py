"""M5: sealed independent review with an explicit reveal barrier.

The engine preserves submissions and evaluation receipts.  It cannot decide
whether a reviewer was scientifically correct: that classification may only
arrive through a separately trusted scorer receipt.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from research_loop.modular.contracts import DataIdentity, FrozenRecord, required_text, strict_bool
from research_loop.ontology import ContractError, canonical, digest


class _JsonlLog:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)

    def append(self, event: Mapping[str, Any]) -> None:
        if self.path is None:
            return
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical(dict(event)) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def events(self) -> list[dict[str, Any]]:
        if self.path is None:
            return []
        result = []
        for number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                event = json.loads(line)
                if not isinstance(event, dict) or canonical(event) != line:
                    raise ValueError
            except (ValueError, TypeError) as exc:
                raise ContractError(f"invalid canonical review event at line {number}") from exc
            result.append(event)
        return result


def _same_identity(value: Any, identity: DataIdentity) -> None:
    if value != identity.data():
        raise ContractError("review event has a different data identity")


@dataclass(frozen=True)
class ReviewRole:
    role_id: str
    question: str

    def data(self) -> dict[str, str]:
        return {"role_id": self.role_id, "question": self.question}


@dataclass(frozen=True)
class ReviewSession:
    review_id: str
    identity: DataIdentity
    task_binding: str
    evidence_snapshot: str
    roles: tuple[ReviewRole, ...]
    budget_units: int
    payload: FrozenRecord

    def data(self) -> dict[str, Any]:
        return {"review_id": self.review_id, "identity": self.identity.data(), "task_binding": self.task_binding,
                "evidence_snapshot": self.evidence_snapshot, "roles": [item.data() for item in self.roles],
                "budget_units": self.budget_units, "payload": self.payload.data()}


@dataclass(frozen=True)
class ReviewSubmission:
    review_id: str
    role_id: str
    reviewer_id: str
    response: FrozenRecord
    cost_units: int
    before_hash: str

    def data(self) -> dict[str, Any]:
        return {"review_id": self.review_id, "role_id": self.role_id, "reviewer_id": self.reviewer_id,
                "response": self.response.data(), "cost_units": self.cost_units, "before_hash": self.before_hash}


@dataclass(frozen=True)
class ReviewRevision:
    review_id: str
    role_id: str
    reviewer_id: str
    response: FrozenRecord
    after_hash: str

    def data(self) -> dict[str, Any]:
        return {"review_id": self.review_id, "role_id": self.role_id, "reviewer_id": self.reviewer_id,
                "response": self.response.data(), "after_hash": self.after_hash}


@dataclass(frozen=True)
class ReviewScoreReceipt:
    review_id: str
    scorer: str
    changes: tuple[tuple[str, str, str], ...]

    def data(self) -> dict[str, Any]:
        return {"review_id": self.review_id, "scorer": self.scorer,
                "changes": [{"role_id": role, "before": before, "after": after} for role, before, after in self.changes]}


class ReviewEngine:
    """A persistent review barrier, independent of any model provider."""

    def __init__(self, identity: DataIdentity, *, storage_path: Path | None = None,
                 event_sink: Callable[[FrozenRecord], None] | None = None,
                 reveal_sink: Callable[[FrozenRecord], None] | None = None) -> None:
        self.identity = identity
        self._sessions: dict[str, ReviewSession] = {}
        self._submissions: dict[tuple[str, str], ReviewSubmission] = {}
        self._revisions: dict[tuple[str, str], ReviewRevision] = {}
        self._scores: dict[str, ReviewScoreReceipt] = {}
        self._log = _JsonlLog(storage_path)
        self._event_sink = event_sink
        self._reveal_sink = reveal_sink
        for event in self._log.events():
            self._apply(event, persist=False)

    @staticmethod
    def _response(value: Any) -> FrozenRecord:
        if not isinstance(value, Mapping) or set(value) != {"assessment", "evidence_refs", "counterexamples", "uncertainty"}:
            raise ContractError("review response requires assessment, evidence refs, counterexamples, uncertainty")
        if value["assessment"] not in {"accept", "concern", "unknown"}:
            raise ContractError("review assessment must allow accept, concern, or unknown")
        for field in ("evidence_refs", "counterexamples"):
            if not isinstance(value[field], list) or any(not isinstance(item, str) or not item.strip() for item in value[field]):
                raise ContractError(f"review {field} must be a text list")
        required_text(value["uncertainty"], "review uncertainty")
        return FrozenRecord.from_dict(dict(value))

    def open(self, *, task_binding: str, evidence_snapshot: str, roles: Sequence[Mapping[str, Any]], budget_units: int) -> ReviewSession:
        if type(budget_units) is not int or budget_units <= 0:
            raise ContractError("review budget must be a positive integer")
        if not isinstance(roles, Sequence) or isinstance(roles, (str, bytes)) or not roles:
            raise ContractError("review requires explicit roles")
        parsed = []
        for item in roles:
            if not isinstance(item, Mapping) or set(item) != {"role_id", "question"}:
                raise ContractError("review role requires a concrete question")
            parsed.append(ReviewRole(required_text(item["role_id"], "role id"), required_text(item["question"], "role question")))
        if len(parsed) > budget_units or len({item.role_id for item in parsed}) != len(parsed):
            raise ContractError("review roles exceed budget or repeat a role")
        task_binding = required_text(task_binding, "task binding")
        evidence_snapshot = required_text(evidence_snapshot, "evidence snapshot")
        payload = FrozenRecord.from_dict({"task_binding": task_binding, "evidence_snapshot": evidence_snapshot,
                                          "roles": [item.data() for item in parsed], "budget_units": budget_units})
        review_id = digest({"identity": self.identity.data(), "payload": payload.data()})
        return self._apply({"event": "open", "identity": self.identity.data(), "review_id": review_id,
                            "task_binding": task_binding, "evidence_snapshot": evidence_snapshot,
                            "roles": [item.data() for item in parsed], "budget_units": budget_units}, persist=True)

    def submit(self, review_id: str, *, role_id: str, reviewer_id: str, response: Mapping[str, Any], cost_units: int) -> ReviewSubmission:
        session = self.session(review_id)
        role_id, reviewer_id = required_text(role_id, "role id"), required_text(reviewer_id, "reviewer id")
        if role_id not in {item.role_id for item in session.roles}:
            raise ContractError("submission role is not assigned to this review")
        if type(cost_units) is not int or cost_units <= 0:
            raise ContractError("submission cost must be a positive integer")
        if sum(item.cost_units for (saved, _), item in self._submissions.items() if saved == review_id) + cost_units > session.budget_units:
            raise ContractError("review budget exceeded")
        if any(item.reviewer_id == reviewer_id for (saved, _), item in self._submissions.items() if saved == review_id):
            raise ContractError("one reviewer cannot occupy repeated roles in a sealed review")
        payload = self._response(response)
        before_hash = digest({"review_id": review_id, "role_id": role_id, "reviewer_id": reviewer_id, "response": payload.data()})
        return self._apply({"event": "submit", "identity": self.identity.data(), "review_id": review_id,
                            "role_id": role_id, "reviewer_id": reviewer_id, "response": payload.data(),
                            "cost_units": cost_units, "before_hash": before_hash}, persist=True)

    def barrier_open(self, review_id: str) -> bool:
        session = self.session(review_id)
        return {role for saved, role in self._submissions if saved == review_id} == {item.role_id for item in session.roles}

    def reveal(self, review_id: str) -> tuple[ReviewSubmission, ...]:
        if not self.barrier_open(review_id):
            raise ContractError("sealed submissions remain unavailable until every role submits")
        result = tuple(self._submissions[(review_id, role.role_id)] for role in self.session(review_id).roles)
        if self._reveal_sink is not None:
            self._reveal_sink(FrozenRecord.from_dict({'schema': 'm5-reveal-output-v1', 'review_id': review_id,
                'submissions': [item.data() for item in result]}))
        return result

    def revise_after_reveal(self, review_id: str, *, role_id: str, reviewer_id: str, response: Mapping[str, Any]) -> ReviewRevision:
        if not self.barrier_open(review_id):
            raise ContractError("cannot revise before the sealed review barrier opens")
        previous = self._submissions.get((review_id, required_text(role_id, "role id")))
        if previous is None or previous.reviewer_id != required_text(reviewer_id, "reviewer id"):
            raise ContractError("revision must belong to the original role reviewer")
        payload = self._response(response)
        return self._apply({"event": "revise", "identity": self.identity.data(), "review_id": review_id,
                            "role_id": role_id, "reviewer_id": reviewer_id, "response": payload.data(),
                            "after_hash": digest({"before_hash": previous.before_hash, "response": payload.data()})}, persist=True)

    def record_score(self, review_id: str, *, changes: Sequence[Mapping[str, str]], scorer_receipt: Mapping[str, Any]) -> ReviewScoreReceipt:
        if not self.barrier_open(review_id):
            raise ContractError("score receipt requires completed sealed submissions")
        if set(scorer_receipt) != {"trusted_scorer", "verified"} or not strict_bool(scorer_receipt["verified"], "scorer verified"):
            raise ContractError("score receipt requires a verified trusted scorer")
        scorer = required_text(scorer_receipt["trusted_scorer"], "trusted scorer")
        roles = {item.role_id for item in self.session(review_id).roles}
        if not isinstance(changes, Sequence) or isinstance(changes, (str, bytes)):
            raise ContractError("score changes must be a list")
        parsed = []
        for item in changes:
            if not isinstance(item, Mapping) or set(item) != {"role_id", "before", "after"} or item["role_id"] not in roles:
                raise ContractError("score change is invalid")
            if item["before"] not in {"correct", "incorrect", "unknown"} or item["after"] not in {"correct", "incorrect", "unknown"}:
                raise ContractError("score classification is invalid")
            parsed.append((item["role_id"], item["before"], item["after"]))
        if {item[0] for item in parsed} != roles:
            raise ContractError("trusted scorer must classify every review role")
        return self._apply({"event": "score", "identity": self.identity.data(), "review_id": review_id,
                            "scorer": scorer, "changes": [{"role_id": a, "before": b, "after": c} for a, b, c in parsed]}, persist=True)

    def session(self, review_id: str) -> ReviewSession:
        try:
            return self._sessions[required_text(review_id, "review id")]
        except KeyError as exc:
            raise ContractError("unknown review session") from exc

    def _apply(self, event: Mapping[str, Any], *, persist: bool) -> Any:
        _same_identity(event.get("identity"), self.identity)
        kind = event.get("event")
        if kind == "open":
            roles = event.get("roles")
            if not isinstance(roles, list) or not roles:
                raise ContractError("persisted review roles invalid")
            parsed = tuple(ReviewRole(required_text(item.get("role_id"), "role id"), required_text(item.get("question"), "role question")) for item in roles if isinstance(item, Mapping))
            if len(parsed) != len(roles) or len({item.role_id for item in parsed}) != len(parsed):
                raise ContractError("persisted review roles invalid")
            budget = event.get("budget_units")
            if type(budget) is not int or budget <= 0 or len(parsed) > budget:
                raise ContractError("persisted review budget invalid")
            task, snapshot = required_text(event.get("task_binding"), "task binding"), required_text(event.get("evidence_snapshot"), "evidence snapshot")
            payload = FrozenRecord.from_dict({"task_binding": task, "evidence_snapshot": snapshot, "roles": [item.data() for item in parsed], "budget_units": budget})
            expected = digest({"identity": self.identity.data(), "payload": payload.data()})
            if event.get("review_id") != expected:
                raise ContractError("review id does not bind its immutable session")
            result = ReviewSession(expected, self.identity, task, snapshot, parsed, budget, payload)
            self._sessions[expected] = result
        elif kind == "submit":
            session = self.session(event.get("review_id")); role = required_text(event.get("role_id"), "role id")
            reviewer = required_text(event.get("reviewer_id"), "reviewer id"); cost = event.get("cost_units")
            if role not in {item.role_id for item in session.roles} or type(cost) is not int or cost <= 0:
                raise ContractError("persisted submission invalid")
            payload = self._response(event.get("response")); before = required_text(event.get("before_hash"), "before hash")
            expected = digest({"review_id": session.review_id, "role_id": role, "reviewer_id": reviewer, "response": payload.data()})
            if before != expected or (session.review_id, role) in self._submissions or any(item.reviewer_id == reviewer for (saved, _), item in self._submissions.items() if saved == session.review_id):
                raise ContractError("persisted submission conflicts")
            if sum(item.cost_units for (saved, _), item in self._submissions.items() if saved == session.review_id) + cost > session.budget_units:
                raise ContractError("persisted review budget exceeded")
            result = ReviewSubmission(session.review_id, role, reviewer, payload, cost, before); self._submissions[(session.review_id, role)] = result
        elif kind == "revise":
            session = self.session(event.get("review_id")); role = required_text(event.get("role_id"), "role id"); reviewer = required_text(event.get("reviewer_id"), "reviewer id")
            previous = self._submissions.get((session.review_id, role))
            if not self.barrier_open(session.review_id) or previous is None or previous.reviewer_id != reviewer:
                raise ContractError("persisted revision violates review barrier")
            payload = self._response(event.get("response")); after = required_text(event.get("after_hash"), "after hash")
            expected = digest({"before_hash": previous.before_hash, "response": payload.data()})
            if after != expected or (session.review_id, role) in self._revisions:
                raise ContractError("revision hash invalid")
            result = ReviewRevision(session.review_id, role, reviewer, payload, after); self._revisions[(session.review_id, role)] = result
        elif kind == "score":
            session = self.session(event.get("review_id")); changes = event.get("changes")
            if not self.barrier_open(session.review_id) or not isinstance(changes, list):
                raise ContractError("persisted score violates barrier")
            parsed = []
            for item in changes:
                if not isinstance(item, Mapping) or set(item) != {"role_id", "before", "after"} or item["role_id"] not in {x.role_id for x in session.roles} or item["before"] not in {"correct", "incorrect", "unknown"} or item["after"] not in {"correct", "incorrect", "unknown"}:
                    raise ContractError("persisted score invalid")
                parsed.append((item["role_id"], item["before"], item["after"]))
            if {item[0] for item in parsed} != {item.role_id for item in session.roles}:
                raise ContractError("persisted score lacks roles")
            if session.review_id in self._scores:
                raise ContractError("persisted score is duplicated")
            result = ReviewScoreReceipt(session.review_id, required_text(event.get("scorer"), "trusted scorer"), tuple(sorted(parsed))); self._scores[session.review_id] = result
        else:
            raise ContractError("unknown review event")
        if persist:
            self._log.append(event)
            if self._event_sink is not None:
                self._event_sink(FrozenRecord.from_dict(dict(event)))
        return result
