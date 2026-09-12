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
_SURFACE_KEYS = {
    "prompt": frozenset({"template", "instructions", "style"}),
    "memory": frozenset({"mode", "lesson", "facts"}),
    "config": frozenset({"max_steps", "revision_limit", "temperature"}),
}


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} must be nonempty text")
    return value


def _digest(value: Any, field: str) -> str:
    value = _text(value, field)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ContractError(f"{field} must be a sha256 digest")
    return value


def _strict_int(value: Any, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ContractError(f"{field} must be a nonnegative integer, not a boolean")
    return value


def _validate_builder_source(source: Any) -> dict[str, Any]:
    required = {"entrypoint", "surface", "key", "value"}
    if not isinstance(source, Mapping) or set(source) != required:
        raise ContractError("builder DSL has an exact four-field schema")
    result = dict(source)
    if _text(result["entrypoint"], "builder entrypoint") != "emit_literal_change_v1":
        raise ContractError("unsupported builder DSL entrypoint")
    surface = _text(result["surface"], "builder surface")
    if surface not in {"prompt", "memory"}:
        raise ContractError("builder DSL may change only prompt or memory")
    key = _text(result["key"], "builder key")
    if key not in _SURFACE_KEYS[surface]:
        raise ContractError("builder DSL change key is not allowlisted")
    if not isinstance(result["value"], str):
        raise ContractError("builder DSL literal value must be text")
    return result


def _validate_changes(changes: Any, phase: str) -> dict[str, Any]:
    if not isinstance(changes, Mapping) or not changes or set(changes) - _SURFACES:
        raise ContractError("candidate changes are limited to prompt, memory, and config")
    copied = dict(changes)
    if phase == "metaprogram":
        if set(copied) != {"config"} or not isinstance(copied["config"], Mapping) or set(copied["config"]) != {"candidate_builder_dsl"}:
            raise ContractError("meta candidates may carry only their restricted builder DSL")
        _validate_builder_source(copied["config"]["candidate_builder_dsl"])
        return copied
    for surface, value in copied.items():
        if not isinstance(value, Mapping) or not value or set(value) - _SURFACE_KEYS[surface]:
            raise ContractError(f"{surface} changes are outside the runtime allowlist")
        for key, item in value.items():
            if surface == "config" and key in {"max_steps", "revision_limit"}:
                _strict_int(item, f"config.{key}")
            elif surface == "config" and key == "temperature":
                if type(item) not in {int, float} or not 0 <= item <= 2:
                    raise ContractError("config.temperature must be a finite scalar")
            elif not isinstance(item, str):
                raise ContractError(f"{surface}.{key} must be text")
    return copied


@dataclass(frozen=True)
class TrainingManifest:
    record: FrozenRecord

    def __post_init__(self) -> None:
        if not isinstance(self.record, FrozenRecord):
            raise ContractError("training manifest requires an immutable record")
        data = self.record.data()
        if set(data) != {"domain", "identities"} or data["domain"] != "train" or not isinstance(data["identities"], list) or not data["identities"]:
            raise ContractError("training manifest has an invalid schema")
        seen = set()
        for item in data["identities"]:
            identity = DataIdentity.parse(item)
            identity.require_train()
            encoded = canonical(identity.data())
            if encoded in seen:
                raise ContractError("training manifest contains duplicate tasks")
            seen.add(encoded)

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

    def __post_init__(self) -> None:
        if not isinstance(self.record, FrozenRecord):
            raise ContractError("candidate package requires an immutable record")
        data = self.record.data()
        phase = data.get("phase")
        base = {"parent_digest", "training_manifest", "training_manifest_digest", "changes", "search_cost", "phase"}
        required = base | ({"builder_source_digest", "builder_entrypoint"} if phase == "metaprogram" else set())
        if phase not in _PHASES or set(data) != required:
            raise ContractError("candidate package has an invalid schema")
        if data["parent_digest"] is not None:
            _digest(data["parent_digest"], "parent_digest")
        manifest = TrainingManifest(FrozenRecord.from_dict(data["training_manifest"]))
        if _digest(data["training_manifest_digest"], "training_manifest_digest") != manifest.content_hash:
            raise ContractError("candidate package training manifest drift")
        _strict_int(data["search_cost"], "search_cost")
        changes = _validate_changes(data["changes"], phase)
        if phase == "metaprogram":
            source = _validate_builder_source(changes["config"]["candidate_builder_dsl"])
            if _digest(data["builder_source_digest"], "builder_source_digest") != digest(source):
                raise ContractError("meta candidate builder source drift")
            if _text(data["builder_entrypoint"], "builder_entrypoint") != source["entrypoint"]:
                raise ContractError("meta candidate builder entrypoint drift")

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
        _validate_changes(changes, phase)
        _strict_int(search_cost, "search_cost")
        if phase not in _PHASES:
            raise ContractError("unknown candidate phase")
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
        package = CandidatePackage(package.record)
        if package.record.data()["phase"] != "candidate":
            raise ContractError("ordinary optimizer cannot register a meta-program candidate")
        with self._db:
            self._db.execute("INSERT OR IGNORE INTO candidates(digest, record) VALUES (?, ?)", (package.digest, package.record.encoded))
        return package

    def propose(self, builder: CandidateBuilder, manifest: TrainingManifest, parent: CandidatePackage,
                changes: Mapping[str, Any], *, search_cost: int) -> CandidatePackage:
        candidate = builder.build(manifest, parent, changes, search_cost=search_cost)
        candidate = CandidatePackage(candidate.record)
        if (candidate.record.data()["phase"] != "candidate" or candidate.parent_digest != parent.digest
                or candidate.record.data()["training_manifest_digest"] != manifest.content_hash
                or candidate.record.data()["search_cost"] != search_cost):
            raise ContractError("CandidateBuilder returned a package outside its train-only contract")
        return self.register(candidate)

    def compare_train(self, baseline: CandidatePackage, candidate: CandidatePackage) -> None:
        baseline, candidate = CandidatePackage(baseline.record), CandidatePackage(candidate.record)
        if baseline.record.data()["training_manifest_digest"] != candidate.record.data()["training_manifest_digest"]:
            raise ContractError("train comparison must share a frozen training manifest")
        if baseline.record.data()["search_cost"] != candidate.record.data()["search_cost"]:
            raise ContractError("train comparison requires matched search cost")
        with self._db:
            self._db.execute("INSERT OR IGNORE INTO comparisons(candidate, baseline) VALUES (?, ?)", (candidate.digest, baseline.digest))

    def close(self) -> None:
        self._db.close()


@dataclass(frozen=True)
class FrozenBuilderVersion:
    """A deliberately small executable DSL, never arbitrary host source code."""

    record: FrozenRecord

    def __post_init__(self) -> None:
        if not isinstance(self.record, FrozenRecord):
            raise ContractError("builder version requires an immutable record")
        _validate_builder_source(self.record.data())

    @classmethod
    def freeze(cls, source: Mapping[str, Any]) -> "FrozenBuilderVersion":
        return cls(FrozenRecord.from_dict(_validate_builder_source(source)))

    @property
    def digest(self) -> str:
        return self.record.content_hash

    @property
    def entrypoint(self) -> str:
        return self.record.data()["entrypoint"]


@dataclass(frozen=True)
class BuilderRunReceipt:
    record: FrozenRecord

    def __post_init__(self) -> None:
        if not isinstance(self.record, FrozenRecord):
            raise ContractError("builder run receipt requires an immutable record")
        data = self.record.data()
        required = {"builder_digest", "builder_source", "builder_entrypoint", "parent_package_digest", "training_manifest_digest", "output_candidate_digest", "search_cost"}
        if set(data) != required:
            raise ContractError("builder run receipt has an invalid schema")
        source = _validate_builder_source(data["builder_source"])
        if (_digest(data["builder_digest"], "builder_digest") != digest(source)
                or _text(data["builder_entrypoint"], "builder_entrypoint") != source["entrypoint"]):
            raise ContractError("builder run receipt source drift")
        for field in ("parent_package_digest", "training_manifest_digest", "output_candidate_digest"):
            _digest(data[field], field)
        _strict_int(data["search_cost"], "search_cost")

    @property
    def output_candidate_digest(self) -> str:
        return self.record.data()["output_candidate_digest"]


class RestrictedBuilderPort:
    """Actually interprets a frozen builder DSL using only a train manifest."""

    def execute(self, builder: FrozenBuilderVersion, manifest: TrainingManifest, parent: CandidatePackage,
                *, expected_builder_digest: str, expected_entrypoint: str, search_cost: int) -> tuple[CandidatePackage, BuilderRunReceipt]:
        if not isinstance(builder, FrozenBuilderVersion) or builder.digest != _digest(expected_builder_digest, "expected_builder_digest"):
            raise ContractError("CandidateBuilder source drift")
        if builder.entrypoint != _text(expected_entrypoint, "expected_entrypoint"):
            raise ContractError("CandidateBuilder entrypoint drift")
        if not isinstance(parent, CandidatePackage):
            raise ContractError("builder run requires an immutable parent package")
        for identity in manifest.identities():
            identity.require_train()
        source = builder.record.data()
        # This is the complete DSL interpreter. It has no filesystem, network,
        # process, validation, task-generation, scorer, or promotion capability.
        changes = {source["surface"]: {source["key"]: source["value"]}}
        output = CandidatePackage.create(parent_digest=parent.digest, manifest=manifest, changes=changes, search_cost=search_cost)
        receipt = BuilderRunReceipt(FrozenRecord.from_dict({
            "builder_digest": builder.digest, "builder_source": source, "builder_entrypoint": builder.entrypoint,
            "parent_package_digest": parent.digest, "training_manifest_digest": manifest.content_hash,
            "output_candidate_digest": output.digest, "search_cost": search_cost,
        }))
        return output, receipt


@dataclass(frozen=True)
class MetaBuilderCandidate:
    """A validation-bound proposal to replace the next-round builder version."""

    package: CandidatePackage
    parent_builder_digest: str
    next_builder: FrozenBuilderVersion

    def __post_init__(self) -> None:
        if not isinstance(self.package, CandidatePackage) or not isinstance(self.next_builder, FrozenBuilderVersion):
            raise ContractError("meta builder candidate requires immutable package and builder")
        if _digest(self.parent_builder_digest, "parent_builder_digest") != self.parent_builder_digest:
            raise ContractError("meta builder parent digest is invalid")
        data = self.package.record.data()
        if (data["phase"] != "metaprogram" or data["builder_source_digest"] != self.next_builder.digest
                or data["builder_entrypoint"] != self.next_builder.entrypoint):
            raise ContractError("meta builder candidate source drift")

    @classmethod
    def propose(cls, *, parent_package: CandidatePackage, parent_builder: FrozenBuilderVersion,
                next_builder: FrozenBuilderVersion, manifest: TrainingManifest, search_cost: int) -> "MetaBuilderCandidate":
        for identity in manifest.identities():
            identity.require_train()
        package = CandidatePackage.create(
            parent_digest=parent_package.digest, manifest=manifest,
            changes={"config": {"candidate_builder_dsl": next_builder.record.data()}}, search_cost=search_cost,
            phase="metaprogram", builder_source_digest=next_builder.digest, builder_entrypoint=next_builder.entrypoint,
        )
        return cls(package, parent_builder.digest, next_builder)


class BuilderRegistry:
    """Separate persistent control plane: only independent meta acceptance changes it."""

    def __init__(self, db_path: Path, authority: "AcceptanceAuthority", initial: FrozenBuilderVersion) -> None:
        self._db = sqlite3.connect(str(db_path))
        self._authority = authority
        self._db.execute("CREATE TABLE IF NOT EXISTS builder_versions (digest TEXT PRIMARY KEY, record TEXT NOT NULL)")
        self._db.execute("CREATE TABLE IF NOT EXISTS builder_state (slot INTEGER PRIMARY KEY CHECK(slot=1), digest TEXT NOT NULL)")
        self._db.execute("CREATE TABLE IF NOT EXISTS consumed_meta_receipts (id TEXT PRIMARY KEY)")
        self._store(initial)
        row = self._db.execute("SELECT digest FROM builder_state WHERE slot=1").fetchone()
        if row is None:
            with self._db:
                self._db.execute("INSERT INTO builder_state(slot, digest) VALUES(1, ?)", (initial.digest,))
        elif self._load(row[0]) is None:
            raise ContractError("persisted active CandidateBuilder is missing")
        self._db.commit()

    def _store(self, builder: FrozenBuilderVersion) -> None:
        self._db.execute("INSERT OR IGNORE INTO builder_versions(digest, record) VALUES (?, ?)", (builder.digest, builder.record.encoded))

    def _load(self, value: str) -> FrozenBuilderVersion | None:
        row = self._db.execute("SELECT record FROM builder_versions WHERE digest=?", (value,)).fetchone()
        return FrozenBuilderVersion(FrozenRecord(row[0])) if row else None

    def active(self) -> FrozenBuilderVersion:
        value = self._db.execute("SELECT digest FROM builder_state WHERE slot=1").fetchone()[0]
        builder = self._load(value)
        if builder is None:
            raise ContractError("active CandidateBuilder is missing")
        return builder

    def activate_meta(self, meta: MetaBuilderCandidate, receipt: "AcceptanceReceipt") -> FrozenBuilderVersion:
        self._authority.verify(receipt)
        if self._db.execute("SELECT 1 FROM consumed_meta_receipts WHERE id=?", (receipt.receipt_id,)).fetchone():
            raise ContractError("meta acceptance receipt was already consumed")
        active = self.active()
        data = receipt.record.data()
        if (meta.parent_builder_digest != active.digest or data["candidate_digest"] != meta.package.digest
                or data["expected_active_digest"] != meta.package.parent_digest
                or meta.package.record.data()["builder_source_digest"] != meta.next_builder.digest
                or meta.package.record.data()["builder_entrypoint"] != meta.next_builder.entrypoint):
            raise ContractError("meta builder acceptance is stale or source drifted")
        self._store(meta.next_builder)
        with self._db:
            self._db.execute("UPDATE builder_state SET digest=? WHERE slot=1", (meta.next_builder.digest,))
            self._db.execute("INSERT INTO consumed_meta_receipts(id) VALUES (?)", (receipt.receipt_id,))
        return meta.next_builder

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
