"""M9 train-only candidate improvement with independently authorised activation.

This module is an engineering boundary, not evidence of scientific improvement.
It never opens validation inputs or creates evaluation tasks.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.ontology import ContractError, canonical, digest


_SURFACES = frozenset({"prompt", "memory", "config"})
_PHASES = frozenset({"candidate", "metaprogram"})


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} must be nonempty text")
    return value


def _digest(value: Any, field: str) -> str:
    value = _text(value, field)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ContractError(f"{field} must be a sha256 digest")
    return value


@dataclass(frozen=True)
class TrainingManifest:
    record: FrozenRecord

    @classmethod
    def freeze(cls, identities: Sequence[DataIdentity]) -> "TrainingManifest":
        if not identities:
            raise ContractError("training manifest cannot be empty")
        copied = []
        seen = set()
        for identity in identities:
            if not isinstance(identity, DataIdentity):
                raise ContractError("training manifest requires DataIdentity values")
            identity.require_train()
            key = canonical(identity.data())
            if key in seen:
                raise ContractError("training manifest contains duplicate tasks")
            seen.add(key)
            copied.append(identity.data())
        return cls(FrozenRecord.from_dict({"domain": "train", "identities": copied}))

    @property
    def content_hash(self) -> str:
        return self.record.content_hash

    def identities(self) -> tuple[DataIdentity, ...]:
        return tuple(DataIdentity.parse(value) for value in self.record.data()["identities"])


@dataclass(frozen=True)
class CandidatePackage:
    record: FrozenRecord

    @classmethod
    def create(
        cls, *, parent_digest: str | None, manifest: TrainingManifest, changes: Mapping[str, Any],
        search_cost: int, phase: str = "candidate", builder_source_digest: str | None = None,
        builder_entrypoint: str | None = None,
    ) -> "CandidatePackage":
        if parent_digest is not None:
            _digest(parent_digest, "parent_digest")
        if not isinstance(manifest, TrainingManifest):
            raise ContractError("candidate requires a frozen training manifest")
        if not isinstance(changes, Mapping) or not changes or set(changes) - _SURFACES:
            raise ContractError("candidate changes are limited to prompt, memory, and config")
        if not isinstance(search_cost, int) or search_cost < 0:
            raise ContractError("search_cost must be a nonnegative integer")
        if phase not in _PHASES:
            raise ContractError("unknown candidate phase")
        for surface, value in changes.items():
            if not isinstance(value, Mapping):
                raise ContractError(f"{surface} changes must be a mapping")
        meta: dict[str, str] = {}
        if phase == "metaprogram":
            meta = {"builder_source_digest": _digest(builder_source_digest, "builder_source_digest"),
                    "builder_entrypoint": _text(builder_entrypoint, "builder_entrypoint")}
        elif builder_source_digest is not None or builder_entrypoint is not None:
            raise ContractError("ordinary candidate cannot carry CandidateBuilder source")
        record = {"parent_digest": parent_digest, "training_manifest": manifest.record.data(),
                  "training_manifest_digest": manifest.content_hash, "changes": dict(changes),
                  "search_cost": search_cost, "phase": phase, **meta}
        return cls(FrozenRecord.from_dict(record))

    @property
    def digest(self) -> str:
        return self.record.content_hash

    @property
    def parent_digest(self) -> str | None:
        return self.record.data()["parent_digest"]

    @property
    def memory_digest(self) -> str:
        return digest(self.record.data()["changes"].get("memory", {}))


class CandidateBuilder(Protocol):
    def build(self, manifest: TrainingManifest, parent: CandidatePackage, changes: Mapping[str, Any], *, search_cost: int) -> CandidatePackage: ...


@dataclass(frozen=True)
class BoundedCandidateBuilder:
    """A deterministic port: it accepts frozen train identities, never task generators."""

    phase: str = "candidate"
    source_digest: str | None = None
    entrypoint: str | None = None

    def build(self, manifest: TrainingManifest, parent: CandidatePackage, changes: Mapping[str, Any], *, search_cost: int) -> CandidatePackage:
        if not isinstance(parent, CandidatePackage):
            raise ContractError("CandidateBuilder needs an immutable parent package")
        # Re-read through the manifest to defend against an invalid hand-built record.
        for identity in manifest.identities():
            identity.require_train()
        return CandidatePackage.create(parent_digest=parent.digest, manifest=manifest, changes=changes,
                                       search_cost=search_cost, phase=self.phase,
                                       builder_source_digest=self.source_digest,
                                       builder_entrypoint=self.entrypoint)


class TrainOptimizer:
    """Persistent train-only candidate registry; it has no validation or deployment port."""

    def __init__(self, db_path: Path) -> None:
        self._db = sqlite3.connect(str(db_path))
        self._db.execute("CREATE TABLE IF NOT EXISTS candidates (digest TEXT PRIMARY KEY, record TEXT NOT NULL)")
        self._db.execute("CREATE TABLE IF NOT EXISTS comparisons (candidate TEXT PRIMARY KEY, baseline TEXT NOT NULL)")
        self._db.commit()

    def register(self, package: CandidatePackage) -> CandidatePackage:
        if not isinstance(package, CandidatePackage):
            raise ContractError("optimizer registers immutable packages only")
        with self._db:
            self._db.execute("INSERT OR IGNORE INTO candidates(digest, record) VALUES (?, ?)", (package.digest, package.record.encoded))
        return package

    def propose(self, builder: CandidateBuilder, manifest: TrainingManifest, parent: CandidatePackage,
                changes: Mapping[str, Any], *, search_cost: int) -> CandidatePackage:
        candidate = builder.build(manifest, parent, changes, search_cost=search_cost)
        return self.register(candidate)

    def compare_train(self, baseline: CandidatePackage, candidate: CandidatePackage) -> None:
        if baseline.record.data()["training_manifest_digest"] != candidate.record.data()["training_manifest_digest"]:
            raise ContractError("train comparison must share a frozen training manifest")
        if baseline.record.data()["search_cost"] != candidate.record.data()["search_cost"]:
            raise ContractError("train comparison requires matched search cost")
        with self._db:
            self._db.execute("INSERT OR IGNORE INTO comparisons(candidate, baseline) VALUES (?, ?)", (candidate.digest, baseline.digest))

    def close(self) -> None:
        self._db.close()


@dataclass(frozen=True)
class SignedValidation:
    """Opaque input from a separately configured validation service."""

    record: FrozenRecord
    signature: str


@dataclass(frozen=True)
class AcceptanceReceipt:
    record: FrozenRecord
    signature: str

    @property
    def receipt_id(self) -> str:
        return self.record.content_hash


@dataclass(frozen=True)
class RollbackAuthorization:
    record: FrozenRecord
    signature: str

    @property
    def receipt_id(self) -> str:
        return self.record.content_hash


class AcceptanceAuthority:
    """Trusted host-side signer. Optimizers never receive this key or its validator."""

    def __init__(self, trusted_key: bytes, validation_key: bytes, validator: Callable[[SignedValidation], Mapping[str, Any]]) -> None:
        if not isinstance(trusted_key, bytes) or not isinstance(validation_key, bytes) or min(len(trusted_key), len(validation_key)) < 16:
            raise ContractError("acceptance authority needs host-held acceptance and validation keys")
        self._key, self._validation_key = trusted_key, validation_key
        self._validator = validator

    def _sign(self, record: FrozenRecord) -> str:
        return hmac.new(self._key, record.encoded.encode("utf-8"), hashlib.sha256).hexdigest()

    def validate(self, candidate: CandidatePackage, expected_active_digest: str, validation: SignedValidation) -> AcceptanceReceipt:
        _digest(expected_active_digest, "expected_active_digest")
        expected_signature = hmac.new(self._validation_key, validation.record.encoded.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_signature, validation.signature):
            raise ContractError("validation receipt signature is invalid")
        decision = dict(self._validator(validation))
        required = {"validator_id", "candidate_digest", "expected_active_digest", "trial_digest", "domain", "offline", "decision"}
        if set(decision) != required or decision["candidate_digest"] != candidate.digest or decision["expected_active_digest"] != expected_active_digest:
            raise ContractError("independent validation decision does not bind candidate and active package")
        if decision["domain"] != "validation" or decision["offline"] is not False or decision["decision"] != "approved":
            raise ContractError("validation decision is not an online independent approval")
        for field in ("validator_id", "trial_digest"):
            _text(decision[field], field)
        return AcceptanceReceipt(FrozenRecord.from_dict(decision), self._sign(FrozenRecord.from_dict(decision)))

    def verify(self, receipt: AcceptanceReceipt) -> None:
        if not hmac.compare_digest(self._sign(receipt.record), receipt.signature):
            raise ContractError("acceptance receipt signature is invalid")

    def authorize_rollback(self, expected_active_digest: str, target_digest: str, reason: str) -> RollbackAuthorization:
        record = FrozenRecord.from_dict({"expected_active_digest": _digest(expected_active_digest, "expected_active_digest"),
                                         "target_digest": _digest(target_digest, "target_digest"), "reason": _text(reason, "reason")})
        return RollbackAuthorization(record, self._sign(record))

    def verify_rollback(self, authorization: RollbackAuthorization) -> None:
        if not hmac.compare_digest(self._sign(authorization.record), authorization.signature):
            raise ContractError("rollback authorization signature is invalid")


@dataclass(frozen=True)
class DeploymentAck:
    active_digest: str
    memory_digest: str
    online: bool


class DeploymentPort(Protocol):
    def activate(self, package: CandidatePackage, expected_active_digest: str) -> DeploymentAck: ...
    def current(self) -> DeploymentAck: ...


class ExecutionRuntime:
    """Single-writer persistent activation state, separate from optimizer and signer."""

    def __init__(self, db_path: Path, deployment: DeploymentPort, authority: AcceptanceAuthority, initial: CandidatePackage) -> None:
        self._db = sqlite3.connect(str(db_path))
        self._deployment, self._authority = deployment, authority
        self._db.execute("CREATE TABLE IF NOT EXISTS packages (digest TEXT PRIMARY KEY, record TEXT NOT NULL)")
        self._db.execute("CREATE TABLE IF NOT EXISTS used_receipts (id TEXT PRIMARY KEY)")
        self._db.execute("CREATE TABLE IF NOT EXISTS state (slot INTEGER PRIMARY KEY CHECK(slot=1), active_digest TEXT NOT NULL)")
        self._store(initial)
        row = self._db.execute("SELECT active_digest FROM state WHERE slot=1").fetchone()
        if row is None:
            with self._db:
                self._db.execute("INSERT INTO state(slot, active_digest) VALUES(1, ?)", (initial.digest,))
        elif row[0] != initial.digest and not self._package(row[0]):
            raise ContractError("persisted active package is unavailable")
        self._db.commit()

    def _store(self, package: CandidatePackage) -> None:
        self._db.execute("INSERT OR IGNORE INTO packages(digest, record) VALUES (?, ?)", (package.digest, package.record.encoded))

    def _package(self, package_digest: str) -> CandidatePackage | None:
        row = self._db.execute("SELECT record FROM packages WHERE digest=?", (package_digest,)).fetchone()
        return CandidatePackage(FrozenRecord(row[0])) if row else None

    def active(self) -> CandidatePackage:
        digest_value = self._db.execute("SELECT active_digest FROM state WHERE slot=1").fetchone()[0]
        package = self._package(digest_value)
        if package is None:
            raise ContractError("active package is missing")
        return package

    def activate(self, receipt: AcceptanceReceipt, candidate: CandidatePackage) -> DeploymentAck:
        self._authority.verify(receipt)
        active = self.active()
        data = receipt.record.data()
        if receipt.receipt_id in {row[0] for row in self._db.execute("SELECT id FROM used_receipts")}:
            raise ContractError("acceptance receipt was already consumed")
        if (data["candidate_digest"] != candidate.digest or data["expected_active_digest"] != active.digest
                or candidate.parent_digest != active.digest):
            raise ContractError("acceptance receipt is stale or binds another candidate")
        self._store(candidate)
        ack = self._deployment.activate(candidate, active.digest)
        if not ack.online or ack.active_digest != candidate.digest or ack.memory_digest != candidate.memory_digest:
            raise ContractError("deployment acknowledgement is offline or drifted")
        with self._db:
            self._db.execute("UPDATE state SET active_digest=? WHERE slot=1", (candidate.digest,))
            self._db.execute("INSERT INTO used_receipts(id) VALUES (?)", (receipt.receipt_id,))
        return ack

    def run_task(self, identity: DataIdentity, executor: Callable[[DataIdentity, CandidatePackage], Any]) -> FrozenRecord:
        active = self.active()
        ack = self._deployment.current()
        if not ack.online or ack.active_digest != active.digest or ack.memory_digest != active.memory_digest:
            raise ContractError("host deployment drift or offline state blocks task execution")
        return FrozenRecord.from_dict({"task": identity.data(), "active_digest": active.digest,
                                       "memory_digest": active.memory_digest, "result": executor(identity, active)})

    def rollback(self, authorization: RollbackAuthorization) -> DeploymentAck:
        self._authority.verify_rollback(authorization)
        if authorization.receipt_id in {row[0] for row in self._db.execute("SELECT id FROM used_receipts")}:
            raise ContractError("rollback authorization was already consumed")
        data = authorization.record.data()
        active = self.active()
        target = self._package(data["target_digest"])
        if data["expected_active_digest"] != active.digest or target is None or active.parent_digest != target.digest:
            raise ContractError("rollback must restore the active package parent")
        ack = self._deployment.activate(target, active.digest)
        if not ack.online or ack.active_digest != target.digest or ack.memory_digest != target.memory_digest:
            raise ContractError("rollback deployment acknowledgement drifted")
        with self._db:
            self._db.execute("UPDATE state SET active_digest=? WHERE slot=1", (target.digest,))
            self._db.execute("INSERT INTO used_receipts(id) VALUES (?)", (authorization.receipt_id,))
        return ack

    def close(self) -> None:
        self._db.close()
