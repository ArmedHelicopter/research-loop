"""Append-only, verifiable provenance descriptors for run and external artifacts."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from research_loop.modular.contracts import DataIdentity, FrozenRecord, required_text
from research_loop.ontology import ContractError

STATUSES = frozenset({"produced", "failed", "rejected", "withdrawn", "superseded", "blocked"})

class ArtifactCatalogue:
    """A journal of descriptors; it never owns or replaces payload storage."""
    def __init__(self, path: Path, *, identity: DataIdentity, run_id: str | None, experiment_id: str | None, lock_digest: str | None):
        self.path, self.identity = path, identity
        self.binding = {"run_id": run_id, "experiment_id": experiment_id, "lock_digest": lock_digest}
        self._records: dict[str, FrozenRecord] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                record = FrozenRecord(line); self._records[record.content_hash] = record

    @classmethod
    def external(cls, path: Path, *, identity: DataIdentity, experiment_id: str | None = None) -> "ArtifactCatalogue":
        return cls(path, identity=identity, run_id=None, experiment_id=experiment_id, lock_digest=None)

    def append(self, *, kind: str, module: str | None, payload: FrozenRecord | Mapping[str, Any] | None,
               parents: Iterable[str] = (), status: str = "produced", producer_source: Mapping[str, Any] | None = None,
               config_refs: Iterable[str] = (), cost: Mapping[str, Any] | None = None,
               checks: Iterable[str] = (), optimizer_visible: bool = False, coverage: str = "covered") -> FrozenRecord:
        if status not in STATUSES: raise ContractError("artifact status is not recognized")
        if module is not None and module not in {f"M{i}" for i in range(1, 10)}: raise ContractError("artifact module must be M1 through M9 or explicitly uncovered")
        if coverage not in {"covered", "uncovered"} or (coverage == "uncovered" and module is not None): raise ContractError("unknown module/event must be explicitly uncovered")
        if self.identity.domain == "validation" and optimizer_visible: raise ContractError("validation artifacts cannot enter optimizer context")
        parent_ids = list(parents)
        if len(set(parent_ids)) != len(parent_ids) or any(p not in self._records for p in parent_ids): raise ContractError("artifact parent is missing from this immutable catalogue")
        if any(self._records[p].data()["identity"] != self.identity.data() for p in parent_ids): raise ContractError("cross-subject or cross-domain artifact parent")
        if payload is None: payload_digest, payload_bytes, payload_kind = None, None, "absent"
        else:
            frozen = payload if isinstance(payload, FrozenRecord) else FrozenRecord.from_dict(payload)
            payload_digest, payload_bytes, payload_kind = frozen.content_hash, len(frozen.encoded.encode("utf-8")), "canonical_json"
        cost_body = {"known": False, "units": None} if cost is None else dict(cost)
        if set(cost_body) != {"known", "units"} or type(cost_body["known"]) is not bool or (not cost_body["known"] and cost_body["units"] is not None): raise ContractError("artifact cost must preserve known versus unknown")
        source = dict(producer_source or {})
        if source and not all(isinstance(k, str) and isinstance(v, str) and v for k, v in source.items()): raise ContractError("producer source must contain only recorded nonempty text")
        descriptor = FrozenRecord.from_dict({"schema":"artifact-descriptor-v1", "kind":required_text(kind,"artifact kind"), "module":module, "coverage":coverage,
            "identity":self.identity.data(), "binding":self.binding, "payload":{"digest":payload_digest,"bytes":payload_bytes,"encoding":payload_kind},
            "parents":parent_ids, "status":status, "cost":cost_body, "checks":list(checks), "producer_source":source,
            "config_refs":list(config_refs), "optimizer_visible":optimizer_visible, "scientific_validated":False})
        if descriptor.content_hash in self._records: raise ContractError("catalogue is append-only; descriptor already exists")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a",encoding="utf-8",newline="\n") as stream:
            stream.write(descriptor.encoded+"\n"); stream.flush(); os.fsync(stream.fileno())
        self._records[descriptor.content_hash] = descriptor
        return descriptor

    def records(self) -> tuple[FrozenRecord, ...]: return tuple(self._records.values())

    def verify(self) -> None:
        seen: set[str] = set()
        for record in self._records.values():
            body = record.data()
            if body["identity"] != self.identity.data() or any(parent not in seen for parent in body["parents"]): raise ContractError("catalogue lineage is tampered or unordered")
            if body["status"] == "failed" and body["scientific_validated"]: raise ContractError("failed artifact cannot claim scientific validation")
            seen.add(record.content_hash)
