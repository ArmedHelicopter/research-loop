"""Shared v1 boundaries for module, benchmark and evaluation implementations.

Objects store canonical JSON rather than references to mutable caller dictionaries.
Identity tags describe provenance; access enforcement belongs to the custody broker.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Mapping

from research_loop.ontology import ContractError, canonical, digest


@lru_cache(maxsize=16)
def _large_record_digest(encoded: str) -> str:
    # Cache only this pure value computation. File reads, source checks and
    # validation leases still run at their existing call sites. The key is the
    # complete current string, never a path, object id or claimed digest.
    return digest(json.loads(encoded))


def required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} must be nonempty text")
    return value


def strict_bool(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise ContractError(f"{field} must be a literal boolean")
    return value


@dataclass(frozen=True)
class FrozenRecord:
    encoded: str

    def __post_init__(self) -> None:
        try:
            decoded = json.loads(self.encoded)
            if not isinstance(decoded, dict) or canonical(decoded) != self.encoded:
                raise ContractError("record must be a canonical JSON object")
        except (ValueError, TypeError) as exc:
            raise ContractError("invalid immutable record") from exc

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> FrozenRecord:
        return cls(canonical(dict(value)))

    def data(self) -> dict[str, Any]:
        return json.loads(self.encoded)

    @property
    def content_hash(self) -> str:
        if (type(self) is FrozenRecord and type(self.encoded) is str
                and 4096 <= len(self.encoded) <= 524288):
            return _large_record_digest(self.encoded)
        return digest(self.data())


@dataclass(frozen=True)
class DataIdentity:
    benchmark: str
    task_id: str
    group_id: str
    dataset_version: str
    split_id: str
    domain: str

    def __post_init__(self) -> None:
        for name in ("benchmark", "task_id", "group_id", "dataset_version", "split_id"):
            required_text(getattr(self, name), name)
        if self.domain not in {"train", "validation"}:
            raise ContractError("data domain must be train or validation")

    def data(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def parse(cls, value: dict[str, Any]) -> DataIdentity:
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ContractError("invalid data identity fields")
        return cls(**value)

    def require_train(self) -> None:
        if self.domain != "train":
            raise ContractError("optimization accepts training provenance only")


@dataclass(frozen=True)
class PublicTask:
    identity: DataIdentity
    payload: FrozenRecord

    def __post_init__(self) -> None:
        if not isinstance(self.identity, DataIdentity) or not isinstance(self.payload, FrozenRecord):
            raise ContractError("public task requires typed identity and immutable payload")

    @classmethod
    def create(cls, identity: DataIdentity, payload: Mapping[str, Any]) -> PublicTask:
        return cls(identity, FrozenRecord.from_dict(payload))

    def data(self) -> dict[str, Any]:
        return {"identity": self.identity.data(), "payload": self.payload.data()}

    @property
    def content_hash(self) -> str:
        return digest(self.data())
