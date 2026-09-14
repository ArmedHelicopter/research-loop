"""M2: append-only evidence roots and revisioned claim relations.

The ledgers can use a JSONL sidecar.  The sidecar is an audit log, rather than
an authority boundary: custody still owns filesystem permissions and identity.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from research_loop.modular.contracts import DataIdentity, FrozenRecord, required_text, strict_bool
from research_loop.ontology import ContractError, canonical, digest


def _mapping(value: Any, field: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{field} must be a mapping")
    result: dict[str, str] = {}
    for key, item in value.items():
        result[required_text(key, f"{field} key")] = required_text(item, f"{field} value")
    return result


def _identity_data(identity: DataIdentity) -> dict[str, str]:
    return identity.data()


def _same_identity(value: Any, identity: DataIdentity) -> None:
    if value != _identity_data(identity):
        raise ContractError("ledger event has a different data identity")


@dataclass(frozen=True)
class EvidenceRecord:
    root_id: str
    record_id: str
    identity: DataIdentity
    independent_group: str
    subject_bindings: tuple[tuple[str, str], ...]
    representation: str
    admitted: bool
    payload: FrozenRecord

    def data(self) -> dict[str, Any]:
        return {
            "root_id": self.root_id, "record_id": self.record_id,
            "identity": self.identity.data(), "independent_group": self.independent_group,
            "subject_bindings": dict(self.subject_bindings), "representation": self.representation,
            "admitted": self.admitted, "payload": self.payload.data(),
        }


@dataclass(frozen=True)
class ClaimRecord:
    claim_id: str
    identity: DataIdentity
    statement: str
    subject_bindings: tuple[tuple[str, str], ...]
    revision: int
    support_roots: tuple[str, ...]
    refute_roots: tuple[str, ...]
    depends_on: tuple[str, ...]
    needs_review: bool
    status: str

    def data(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id, "identity": self.identity.data(), "statement": self.statement,
            "subject_bindings": dict(self.subject_bindings), "revision": self.revision,
            "support_roots": list(self.support_roots), "refute_roots": list(self.refute_roots),
            "depends_on": list(self.depends_on), "needs_review": self.needs_review,
            "status": self.status,
        }


@dataclass(frozen=True)
class ClaimRevision:
    claim: ClaimRecord
    needs_review: bool


class _JsonlLog:
    def __init__(self, path: Path | None, event_sink: Callable[[FrozenRecord], None] | None = None,
                 on_failure: Callable[[], None] | None = None) -> None:
        self.path = path
        self.event_sink = event_sink
        self.on_failure = on_failure
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.touch()

    def append(self, event: Mapping[str, Any]) -> None:
        try:
            self._append(event)
        except Exception:
            if self.on_failure is not None:
                self.on_failure()
            raise

    def _append(self, event: Mapping[str, Any]) -> None:
        if self.path is not None:
            encoded = canonical(dict(event)) + "\n"
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        # The durable source event precedes its derived audit record. A failed
        # sink propagates; the owning run must stop and retain the visible gap.
        if self.event_sink is not None:
            self.event_sink(FrozenRecord.from_dict(event))

    def events(self) -> list[dict[str, Any]]:
        if self.path is None:
            return []
        result: list[dict[str, Any]] = []
        for number, raw in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                parsed = json.loads(raw)
                if not isinstance(parsed, dict) or canonical(parsed) != raw:
                    raise ValueError
            except (ValueError, TypeError) as exc:
                raise ContractError(f"invalid canonical JSONL event at line {number}") from exc
            result.append(parsed)
        return result


class EvidenceLedger:
    def __init__(self, identity: DataIdentity, *, storage_path: Path | None = None,
                 event_sink: Callable[[FrozenRecord], None] | None = None,
                 on_failure: Callable[[], None] | None = None) -> None:
        self.identity = identity
        self._records: dict[str, EvidenceRecord] = {}
        self._roots: dict[str, set[str]] = {}
        self._withdrawn: set[str] = set()
        self._log = _JsonlLog(storage_path, event_sink, on_failure)
        for event in self._log.events():
            self._apply_event(event, persist=False)

    @property
    def version(self) -> str:
        return digest(self.snapshot().data())

    def append(self, observation: Mapping[str, Any], execution_receipt: Mapping[str, Any]) -> EvidenceRecord:
        if not isinstance(observation, Mapping) or not isinstance(execution_receipt, Mapping):
            raise ContractError("evidence append requires observation and execution receipt mappings")
        allowed = {"kind", "root_material", "representation", "content", "subject_bindings", "independent_group"}
        if set(observation) != allowed:
            raise ContractError("unexpected or missing observation fields")
        if set(execution_receipt) != {"trusted_validator", "validator_verified", "admitted"}:
            raise ContractError("unexpected or missing execution receipt fields")
        if observation["kind"] not in {"observation", "measurement", "artifact"}:
            raise ContractError("unknown evidence kind")
        representation = observation["representation"]
        if representation not in {"raw", "report", "summary"}:
            raise ContractError("unknown evidence representation")
        root_material = observation["root_material"]
        content = observation["content"]
        if not isinstance(root_material, Mapping) or not root_material or not isinstance(content, Mapping):
            raise ContractError("evidence root material and content must be object records")
        bindings = _mapping(observation["subject_bindings"], "subject bindings")
        group = required_text(observation["independent_group"], "independent group")
        if group != self.identity.group_id:
            raise ContractError("evidence independent group must match its data identity")
        required_text(execution_receipt["trusted_validator"], "trusted validator")
        strict_bool(execution_receipt["validator_verified"], "validator verified")
        strict_bool(execution_receipt["admitted"], "evidence admitted")
        if execution_receipt["admitted"] and not execution_receipt["validator_verified"]:
            raise ContractError("admitted evidence requires a verified trusted-validator receipt")
        root_id = digest({"identity": self.identity.data(), "group": group, "bindings": bindings, "root": dict(root_material)})
        if representation == "summary" and root_id not in self._roots:
            raise ContractError("a summary cannot create an evidence root")
        admitted = execution_receipt["admitted"]
        payload = FrozenRecord.from_dict({
            "kind": observation["kind"], "root_material": dict(root_material), "content": dict(content),
            "trusted_validator": execution_receipt["trusted_validator"],
            "validator_verified": execution_receipt["validator_verified"],
        })
        event = {
            "event": "append", "identity": self.identity.data(), "root_id": root_id,
            "record_id": digest({"root_id": root_id, "representation": representation, "payload": payload.data()}),
            "independent_group": group, "subject_bindings": bindings, "representation": representation,
            "admitted": admitted, "payload": payload.data(),
        }
        return self._apply_event(event, persist=True)

    def withdraw(self, root_id: str, reason: str) -> None:
        root_id = required_text(root_id, "root id")
        required_text(reason, "withdrawal reason")
        if root_id not in self._roots:
            raise ContractError("unknown evidence root")
        self._apply_event({"event": "withdraw", "identity": self.identity.data(), "root_id": root_id, "reason": reason}, persist=True)

    def roots(self, *, admitted_only: bool = True, active_only: bool = True) -> tuple[EvidenceRecord, ...]:
        items: list[EvidenceRecord] = []
        for root_id, record_ids in self._roots.items():
            if active_only and root_id in self._withdrawn:
                continue
            # A replay in a different process must select the same original
            # representative, independent of Python's randomized set order.
            records = sorted((self._records[item] for item in record_ids),
                             key=lambda item: (item.representation != "raw", item.record_id))
            non_summaries = [item for item in records if item.representation != "summary"]
            selected = next((item for item in non_summaries if item.admitted), non_summaries[0] if non_summaries else None)
            if selected is not None and (not admitted_only or selected.admitted):
                items.append(selected)
        return tuple(sorted(items, key=lambda item: item.root_id))

    def record(self, root_id: str) -> EvidenceRecord:
        records = self._roots.get(root_id)
        if not records:
            raise ContractError("unknown evidence root")
        return self._records[sorted(records)[0]]

    def is_active_admitted(self, root_id: str) -> bool:
        return root_id not in self._withdrawn and any(item.admitted for item in (self._records[key] for key in self._roots.get(root_id, set())))

    def snapshot(self) -> FrozenRecord:
        return FrozenRecord.from_dict({
            "identity": self.identity.data(), "records": [self._records[key].data() for key in sorted(self._records)],
            "withdrawn": sorted(self._withdrawn),
        })

    def _apply_event(self, event: Mapping[str, Any], *, persist: bool) -> EvidenceRecord | None:
        _same_identity(event.get("identity"), self.identity)
        kind = event.get("event")
        if kind == "withdraw":
            root_id = required_text(event.get("root_id"), "root id")
            required_text(event.get("reason"), "withdrawal reason")
            if root_id not in self._roots:
                raise ContractError("withdrawal references an unknown root")
            self._withdrawn.add(root_id)
            if persist:
                self._log.append(event)
            return None
        if kind != "append":
            raise ContractError("unknown evidence ledger event")
        root_id = required_text(event.get("root_id"), "root id")
        record_id = required_text(event.get("record_id"), "record id")
        group = required_text(event.get("independent_group"), "independent group")
        if group != self.identity.group_id:
            raise ContractError("persisted evidence group mismatch")
        bindings = _mapping(event.get("subject_bindings"), "subject bindings")
        representation = event.get("representation")
        if representation not in {"raw", "report", "summary"}:
            raise ContractError("persisted evidence representation invalid")
        strict_bool(event.get("admitted"), "evidence admitted")
        payload = FrozenRecord.from_dict(event.get("payload"))
        expected_record = digest({"root_id": root_id, "representation": representation, "payload": payload.data()})
        if record_id != expected_record:
            raise ContractError("evidence record id does not bind its immutable payload")
        record = EvidenceRecord(root_id, record_id, self.identity, group, tuple(sorted(bindings.items())), representation, event["admitted"], payload)
        existing = self._records.get(record_id)
        if existing is not None and existing != record:
            raise ContractError("evidence record id collision")
        self._records[record_id] = record
        self._roots.setdefault(root_id, set()).add(record_id)
        if persist:
            self._log.append(event)
        return record


class ClaimLedger:
    def __init__(self, evidence: EvidenceLedger, *, storage_path: Path | None = None,
                 event_sink: Callable[[FrozenRecord], None] | None = None,
                 on_failure: Callable[[], None] | None = None) -> None:
        self.evidence = evidence
        self.identity = evidence.identity
        self._claims: dict[str, ClaimRecord] = {}
        self._log = _JsonlLog(storage_path, event_sink, on_failure)
        for event in self._log.events():
            self._apply_event(event, persist=False)

    def create(self, statement: str, *, subject_bindings: Mapping[str, str]) -> ClaimRecord:
        bindings = _mapping(subject_bindings, "claim subject bindings")
        claim_id = digest({"identity": self.identity.data(), "statement": required_text(statement, "claim statement"), "bindings": bindings})
        event = {"event": "create", "identity": self.identity.data(), "claim_id": claim_id, "statement": statement, "subject_bindings": bindings}
        result = self._apply_event(event, persist=True)
        assert isinstance(result, ClaimRecord)
        return result

    def apply(self, claim_id: str, review: Mapping[str, Any], *, expected_revision: int) -> ClaimRevision:
        claim_id = required_text(claim_id, "claim id")
        if type(expected_revision) is not int or expected_revision < 0:
            raise ContractError("expected revision must be a nonnegative integer")
        if set(review) != {"supports", "refutes", "subject_bindings"}:
            raise ContractError("unexpected or missing review fields")
        supports = self._root_list(review["supports"])
        refutes = self._root_list(review["refutes"])
        if set(supports) & set(refutes):
            raise ContractError("one evidence root cannot both support and refute one claim revision")
        bindings = _mapping(review["subject_bindings"], "review subject bindings")
        event = {"event": "apply", "identity": self.identity.data(), "claim_id": claim_id,
                 "expected_revision": expected_revision, "supports": list(supports), "refutes": list(refutes),
                 "subject_bindings": bindings}
        result = self._apply_event(event, persist=True)
        assert isinstance(result, ClaimRevision)
        return result

    def link_dependencies(self, claim_id: str, depends_on: Sequence[str], *, expected_revision: int) -> ClaimRevision:
        """Persist explicit claim-to-claim edges; no text is inferred as support."""
        claim_id = required_text(claim_id, "claim id")
        if type(expected_revision) is not int or expected_revision < 0:
            raise ContractError("expected revision must be a nonnegative integer")
        dependencies = self._claim_list(depends_on, claim_id=claim_id)
        event = {"event": "dependency_update", "identity": self.identity.data(), "claim_id": claim_id,
                 "expected_revision": expected_revision, "depends_on": list(dependencies)}
        result = self._apply_event(event, persist=True)
        assert isinstance(result, ClaimRevision)
        return result

    def mark_unattributed_summary(self, claim_id: str, summary: str, *, expected_revision: int) -> ClaimRevision:
        """An unknown-provenance summary can request review, never become support."""
        event = {"event": "summary_notice", "identity": self.identity.data(), "claim_id": required_text(claim_id, "claim id"),
                 "summary_hash": digest({"summary": required_text(summary, "summary")}), "expected_revision": expected_revision}
        result = self._apply_event(event, persist=True)
        assert isinstance(result, ClaimRevision)
        return result

    def refresh_after_withdrawal(self) -> tuple[ClaimRevision, ...]:
        changed: list[ClaimRevision] = []
        changed_ids: set[str] = set()
        for claim in list(self._claims.values()):
            active_support = tuple(root for root in claim.support_roots if self.evidence.is_active_admitted(root))
            active_refute = tuple(root for root in claim.refute_roots if self.evidence.is_active_admitted(root))
            if active_support != claim.support_roots or active_refute != claim.refute_roots:
                next_claim = self._make_claim(claim.claim_id, claim.statement, dict(claim.subject_bindings), claim.revision + 1, active_support, active_refute, claim.depends_on, True)
                self._replace_refresh(claim, next_claim, event_type="withdrawal_refresh")
                changed.append(ClaimRevision(next_claim, True)); changed_ids.add(claim.claim_id)
        changed.extend(self._propagate_dependents(changed_ids))
        return tuple(changed)

    def _propagate_dependents(self, changed_ids: set[str]) -> list[ClaimRevision]:
        changed: list[ClaimRevision] = []
        # A changed upstream revision invalidates every dependent interpretation,
        # but independent root chains on that downstream claim remain retained.
        while changed_ids:
            upstream = changed_ids
            changed_ids = set()
            for claim in list(self._claims.values()):
                if claim.claim_id in upstream or not set(claim.depends_on) & upstream:
                    continue
                next_claim = self._make_claim(claim.claim_id, claim.statement, dict(claim.subject_bindings), claim.revision + 1,
                                              claim.support_roots, claim.refute_roots, claim.depends_on, True)
                self._replace_refresh(claim, next_claim, event_type="dependency_refresh")
                changed.append(ClaimRevision(next_claim, True)); changed_ids.add(claim.claim_id)
        return changed

    def claims(self) -> tuple[ClaimRecord, ...]:
        return tuple(sorted(self._claims.values(), key=lambda claim: claim.claim_id))

    def snapshot(self) -> FrozenRecord:
        return FrozenRecord.from_dict({"identity": self.identity.data(), "claims": [claim.data() for claim in self.claims()], "evidence_version": self.evidence.version})

    def _root_list(self, value: Any, *, require_active: bool = True) -> tuple[str, ...]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise ContractError("review roots must be a list")
        roots = tuple(required_text(item, "evidence root") for item in value)
        if len(set(roots)) != len(roots):
            raise ContractError("duplicate evidence root in review")
        for root in roots:
            self.evidence.record(root)
            if require_active and not self.evidence.is_active_admitted(root):
                raise ContractError("claim relation needs active admitted evidence")
        return roots

    def _claim_list(self, value: Any, *, claim_id: str | None = None) -> tuple[str, ...]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise ContractError("claim dependencies must be a list")
        claims = tuple(required_text(item, "dependent claim") for item in value)
        if len(set(claims)) != len(claims) or (claim_id is not None and claim_id in claims):
            raise ContractError("invalid claim dependency")
        for item in claims:
            if item not in self._claims:
                raise ContractError("claim dependency references unknown claim")
        return tuple(sorted(claims))

    def _make_claim(self, claim_id: str, statement: str, bindings: Mapping[str, str], revision: int, supports: Sequence[str], refutes: Sequence[str], depends_on: Sequence[str] = (), needs_review: bool = False) -> ClaimRecord:
        if type(revision) is not int or revision < 0:
            raise ContractError("invalid claim revision")
        active_support = tuple(sorted(supports))
        active_refute = tuple(sorted(refutes))
        status = "undetermined" if active_support and active_refute else "supported" if active_support else "refuted" if active_refute else "undetermined"
        dependencies = self._claim_list(depends_on, claim_id=claim_id)
        if type(needs_review) is not bool:
            raise ContractError("claim needs review must be a literal boolean")
        return ClaimRecord(claim_id, self.identity, required_text(statement, "claim statement"), tuple(sorted(_mapping(bindings, "claim subject bindings").items())), revision, active_support, active_refute, dependencies, needs_review, status)

    def _replace_refresh(self, current: ClaimRecord, replacement: ClaimRecord, *, event_type: str) -> None:
        self._claims[current.claim_id] = replacement
        self._log.append({"event": event_type, "identity": self.identity.data(), "prior_revision": current.revision, "claim": replacement.data()})

    def _apply_event(self, event: Mapping[str, Any], *, persist: bool) -> ClaimRecord | ClaimRevision | None:
        _same_identity(event.get("identity"), self.identity)
        event_type = event.get("event")
        if event_type == "create":
            claim_id = required_text(event.get("claim_id"), "claim id")
            statement = required_text(event.get("statement"), "claim statement")
            bindings = _mapping(event.get("subject_bindings"), "claim subject bindings")
            expected = digest({"identity": self.identity.data(), "statement": statement, "bindings": bindings})
            if claim_id != expected:
                raise ContractError("claim id does not bind statement and identity")
            claim = self._make_claim(claim_id, statement, bindings, 0, (), ())
            existing = self._claims.get(claim_id)
            if existing is not None and existing != claim:
                raise ContractError("claim id collision")
            self._claims[claim_id] = claim
            if persist:
                self._log.append(event)
            return claim
        if event_type == "apply":
            claim_id = required_text(event.get("claim_id"), "claim id")
            current = self._claims.get(claim_id)
            if current is None:
                raise ContractError("review references unknown claim")
            expected_revision = event.get("expected_revision")
            if type(expected_revision) is not int or expected_revision != current.revision:
                raise ContractError("claim revision conflict")
            bindings = _mapping(event.get("subject_bindings"), "review subject bindings")
            if bindings != dict(current.subject_bindings):
                raise ContractError("claim review subject bindings mismatch")
            # Journal replay may encounter a relation that was valid when it was
            # appended but whose root was subsequently withdrawn.  It must retain
            # that historical relation long enough for a later refresh event to
            # record the revision; new writes still require active admission.
            supports = self._root_list(event.get("supports"), require_active=persist)
            refutes = self._root_list(event.get("refutes"), require_active=persist)
            for root in supports + refutes:
                if dict(self.evidence.record(root).subject_bindings) != bindings:
                    raise ContractError("cross-subject evidence cannot update a claim")
            if set(supports) & set(refutes):
                raise ContractError("review assigns a root to both relations")
            next_claim = self._make_claim(claim_id, current.statement, bindings, current.revision + 1, supports, refutes, current.depends_on, False)
            self._claims[claim_id] = next_claim
            revision = ClaimRevision(next_claim, False)
            if persist:
                self._log.append(event)
                self._propagate_dependents({claim_id})
            return revision
        if event_type == "dependency_update":
            claim_id = required_text(event.get("claim_id"), "claim id")
            current = self._claims.get(claim_id)
            if current is None:
                raise ContractError("dependency update references unknown claim")
            expected_revision = event.get("expected_revision")
            if type(expected_revision) is not int or expected_revision != current.revision:
                raise ContractError("claim revision conflict")
            dependencies = self._claim_list(event.get("depends_on"), claim_id=claim_id)
            for dependency in dependencies:
                if dict(self._claims[dependency].subject_bindings) != dict(current.subject_bindings):
                    raise ContractError("cross-subject claim dependency")
            if self._reaches(claim_id, dependencies):
                raise ContractError("claim dependency cycle")
            next_claim = self._make_claim(claim_id, current.statement, dict(current.subject_bindings), current.revision + 1,
                                          current.support_roots, current.refute_roots, dependencies, True)
            self._claims[claim_id] = next_claim
            result = ClaimRevision(next_claim, True)
            if persist:
                self._log.append(event)
                self._propagate_dependents({claim_id})
            return result
        if event_type == "summary_notice":
            claim_id = required_text(event.get("claim_id"), "claim id")
            current = self._claims.get(claim_id)
            if current is None:
                raise ContractError("summary notice references unknown claim")
            if type(event.get("expected_revision")) is not int or event["expected_revision"] != current.revision:
                raise ContractError("claim revision conflict")
            required_text(event.get("summary_hash"), "summary hash")
            next_claim = self._make_claim(claim_id, current.statement, dict(current.subject_bindings), current.revision + 1,
                                          current.support_roots, current.refute_roots, current.depends_on, True)
            self._claims[claim_id] = next_claim
            result = ClaimRevision(next_claim, True)
            if persist:
                self._log.append(event)
                self._propagate_dependents({claim_id})
            return result
        if event_type in {"withdrawal_refresh", "dependency_refresh"}:
            claim_data = event.get("claim")
            if not isinstance(claim_data, Mapping):
                raise ContractError("invalid persisted withdrawal refresh")
            current_id = required_text(claim_data.get("claim_id"), "claim id")
            current = self._claims.get(current_id)
            if current is None or event.get("prior_revision") != current.revision:
                raise ContractError("claim propagation has no continuous prior revision")
            identity = DataIdentity.parse(dict(claim_data.get("identity", {}))); _same_identity(identity.data(), self.identity)
            if required_text(claim_data.get("statement"), "claim statement") != current.statement or _mapping(claim_data.get("subject_bindings"), "claim subject bindings") != dict(current.subject_bindings):
                raise ContractError("claim propagation changes bound claim structure")
            supports = self._root_list(claim_data.get("support_roots"))
            refutes = self._root_list(claim_data.get("refute_roots"))
            dependencies = self._claim_list(claim_data.get("depends_on"), claim_id=current_id)
            if dependencies != current.depends_on or type(claim_data.get("needs_review")) is not bool or not claim_data["needs_review"]:
                raise ContractError("claim propagation changes unsupported claim structure")
            expected_support = tuple(root for root in current.support_roots if self.evidence.is_active_admitted(root))
            expected_refute = tuple(root for root in current.refute_roots if self.evidence.is_active_admitted(root))
            if supports != expected_support or refutes != expected_refute:
                raise ContractError("claim propagation does not match active evidence")
            claim = self._make_claim(
                current_id, current.statement, dict(current.subject_bindings),
                claim_data.get("revision"), supports, refutes, dependencies, True,
            )
            if claim.revision != current.revision + 1 or claim.status != claim_data.get("status"):
                raise ContractError("claim propagation revision or status invalid")
            self._claims[claim.claim_id] = claim
            return ClaimRevision(claim, True)
        raise ContractError("unknown claim ledger event")

    def _reaches(self, target: str, dependencies: Sequence[str]) -> bool:
        pending = list(dependencies); seen: set[str] = set()
        while pending:
            item = pending.pop()
            if item == target:
                return True
            if item not in seen:
                seen.add(item); pending.extend(self._claims[item].depends_on)
        return False
