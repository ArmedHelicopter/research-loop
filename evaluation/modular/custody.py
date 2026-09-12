"""Metadata-only custody for modular benchmark experiments.

This is a controller-side boundary, not an operating-system sandbox.  It records
only names, relative paths and hashes; callers must arrange separate mounts and
process permissions for a real private evaluator.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.benchmarks.catalog import REQUIRED_BENCHMARKS, SUPPORTED_BENCHMARKS
from evaluation.modular.calibration import verify_calibration_receipt
from research_loop.ontology import ContractError, canonical, digest

SCHEMA = "modular-custody-v2"
DOMAINS = frozenset({"train", "validation", "quarantine"})


def _sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _safe_name(value: str, field: str) -> str:
    if not value or any(char in value for char in "/\\\x00"):
        raise ContractError(f"invalid {field}")
    return value


def _is_digest(value: str) -> bool:
    return re.fullmatch(r"[0-9a-f]{64}", value) is not None


@dataclass(frozen=True)
class InventoryItem:
    """A task-like public data unit without reading its content."""

    benchmark: str
    task_id: str
    source_group: str
    official_split: str
    relative_path: str
    content_hashes: tuple[str, ...]
    exposure: str = "unknown"  # exposed or unknown; qualification is separate

    def __post_init__(self) -> None:
        for field in ("benchmark", "task_id", "source_group"):
            _safe_name(getattr(self, field), field)
        if self.benchmark not in SUPPORTED_BENCHMARKS:
            raise ContractError("unsupported benchmark inventory metadata")
        if (not self.official_split or "\\" in self.official_split or "\x00" in self.official_split
                or not self.relative_path or "\\" in self.relative_path or "\x00" in self.relative_path):
            raise ContractError("invalid inventory path metadata")
        if self.exposure not in {"exposed", "unknown"}:
            raise ContractError("invalid exposure state")
        if not self.content_hashes or any(len(value) != 64 for value in self.content_hashes):
            raise ContractError("inventory item needs content hashes")

    def data(self) -> dict[str, Any]:
        return {**asdict(self), "content_hashes": list(self.content_hashes)}

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "InventoryItem":
        expected = {"benchmark", "task_id", "source_group", "official_split", "relative_path", "content_hashes", "exposure"}
        if set(value) != expected or not isinstance(value["content_hashes"], list):
            raise ContractError("invalid inventory item")
        return cls(**{**value, "content_hashes": tuple(value["content_hashes"])})


def _discovery_source_group(kind: str, directory_name: str) -> str:
    """Keep numbered variants of one DiscoveryBench source family together."""
    family = re.sub(r"(?:_\d+)+$", "", directory_name)
    return f"discoverybench:{kind}:{family}"


def discover_inventory(root: Path) -> list[InventoryItem]:
    """Inventory the two local snapshots without opening task, reference or CSV text."""
    root = root.resolve()
    discovery = root / "discovery" / "upstream" / "discoverybench"
    blade = root / "scienceagent" / "work" / "BLADE" / "blade_bench" / "datasets"
    if not discovery.is_dir() or not blade.is_dir():
        raise ContractError("expected DiscoveryBench and BLADE snapshots")
    result: list[InventoryItem] = []
    # Official DiscoveryBench type/split paths are preserved.  Dataset directory
    # names, not metadata JSON contents, provide the source grouping.
    for kind in ("synth", "real"):
        for split in ("train", "dev", "test"):
            split_root = discovery / kind / split
            if not split_root.is_dir():
                continue
            for directory in sorted((path for path in split_root.iterdir() if path.is_dir()), key=lambda path: path.name):
                files = [path for path in directory.rglob("*") if path.is_file()]
                if not files:
                    continue
                hashes = tuple(sorted(_sha256(path) for path in files))
                relative = directory.relative_to(discovery).as_posix()
                result.append(InventoryItem(
                    "discoverybench", relative.replace("/", ":"), _discovery_source_group(kind, directory.name),
                    f"{kind}/{split}", relative, hashes, "unknown",
                ))
    # BLADE has no train/dev/test directory split in this snapshot.  A complete
    # file triplet proves only local shape, never independent provenance or
    # non-exposure, so every BLADE directory starts quarantined.
    for directory in sorted((path for path in blade.iterdir() if path.is_dir()), key=lambda path: path.name):
        files = [path for path in directory.iterdir() if path.is_file()]
        result.append(InventoryItem(
            "blade", directory.name, f"blade:{directory.name}", "unsplit",
            directory.name, tuple(sorted(_sha256(path) for path in files)), "unknown",
        ))
    return result


def build_known_inventory(root: Path) -> list[InventoryItem]:
    """Apply only documented historical exposure from the 2026-09-12 batch."""
    items = discover_inventory(root)
    blade_exposed = {"fish", "hurricane", "boxes", "affairs", "teachingratings", "caschools", "amtl", "mortgage", "reading", "panda_nuts", "crofoot"}
    # The historical runner selected the first sorted directory in each semantic
    # domain, then the first twelve sorted domains.  This is derived from the
    # public directory names only; it deliberately does not parse task metadata.
    test_items = sorted((item for item in items if item.benchmark == "discoverybench" and item.official_split == "synth/test"), key=lambda item: item.relative_path)
    by_domain: dict[str, InventoryItem] = {}
    for item in test_items:
        dataset = item.relative_path.rsplit("/", 1)[-1]
        domain = re.sub(r"_[0-9]+_[0-9]+$", "", dataset)
        by_domain.setdefault(domain, item)
    discovery_test = [by_domain[domain] for domain in sorted(by_domain)[:12]]
    selected = {item.task_id for item in discovery_test}
    return [InventoryItem(**{**item.data(), "content_hashes": tuple(item.content_hashes), "exposure": "exposed" if item.task_id in selected or (item.benchmark == "blade" and item.task_id in blade_exposed) else item.exposure}) for item in items]


class _UnionFind:
    def __init__(self, values: Iterable[str]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def join(self, left: str, right: str) -> None:
        left, right = self.find(left), self.find(right)
        if left != right:
            self.parent[max(left, right)] = min(left, right)


def _merged_groups(items: list[InventoryItem]) -> dict[str, str]:
    """Merge items sharing an asserted source group or any hashed file."""
    ids = [f"{item.benchmark}:{item.task_id}" for item in items]
    union = _UnionFind(ids)
    by_group: dict[str, str] = {}
    by_hash: dict[str, str] = {}
    for item, item_id in zip(items, ids, strict=True):
        if item.source_group in by_group:
            union.join(item_id, by_group[item.source_group])
        else:
            by_group[item.source_group] = item_id
        for value in item.content_hashes:
            if value in by_hash:
                union.join(item_id, by_hash[value])
            else:
                by_hash[value] = item_id
    return {item_id: union.find(item_id) for item_id in ids}


@contextmanager
def _writer_lock(path: Path):
    """Serialize controller writes across processes on Windows and POSIX."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class CustodyStore:
    """Durable custody state with deterministic allocation and one-use leases."""
    def __init__(self, path: Path, *, calibration_keys: dict[str, bytes] | None = None,
                 signing_authority_id: str | None = None, signing_key: bytes | None = None) -> None:
        self.path = path
        # These keys are deployment configuration, never receipt input.  The
        # command-line metadata tool intentionally has none and cannot lease.
        self._calibration_keys = dict(calibration_keys or {})
        if (signing_authority_id is None) != (signing_key is None):
            raise ContractError("custody signing authority id and key must be configured together")
        if signing_authority_id is not None:
            _safe_name(signing_authority_id, "custody signing authority")
            if not isinstance(signing_key, bytes) or len(signing_key) < 32:
                raise ContractError("custody signing key must have at least 32 bytes")
        self._signing_authority_id, self._signing_key = signing_authority_id, signing_key
        self.state = self._load()
        self._loaded_digest = digest(self.state) if path.exists() else None

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema": SCHEMA, "inventory": [], "inventory_digest": None, "attestations": {}, "split": None, "leases": {}}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if set(data) != {"schema", "inventory", "inventory_digest", "attestations", "split", "leases"} or data["schema"] != SCHEMA:
            raise ContractError("unsupported custody state")
        if data["inventory_digest"] is not None and digest(data["inventory"]) != data["inventory_digest"]:
            raise ContractError("persisted inventory digest mismatch")
        if data["split"] is not None:
            split = dict(data["split"])
            recorded_digest = split.pop("digest", None)
            if recorded_digest != digest(split) or split.get("inventory_digest") != data["inventory_digest"]:
                raise ContractError("persisted split digest mismatch")
        return data

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _writer_lock(self.path.with_suffix(self.path.suffix + ".lock")):
            current = self._load() if self.path.exists() else None
            current_digest = digest(current) if current is not None else None
            if current_digest != self._loaded_digest:
                self.state = current if current is not None else self._load()
                self._loaded_digest = current_digest
                raise ContractError("custody changed in another controller; stale write refused")
            encoded = canonical(self.state)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
            self._loaded_digest = digest(self.state)

    def inventory(self, items: Iterable[InventoryItem]) -> str:
        rows = sorted((item.data() for item in items), key=lambda row: (row["benchmark"], row["task_id"]))
        for row in rows:
            InventoryItem.parse(row)
        inventory_digest = digest(rows)
        if self.state["inventory_digest"] not in {None, inventory_digest}:
            raise ContractError("inventory drift; create a new custody state")
        self.state["inventory"] = rows
        self.state["inventory_digest"] = inventory_digest
        self._save()
        return inventory_digest

    def attest_independent_clean(self, *, item_ids: list[str], custodian_id: str,
                                 source_qualification_digest: str,
                                 exposure_qualification_digest: str,
                                 tested_arm_ids: list[str]) -> dict[str, Any]:
        """Record an external-custodian proof before any split is frozen.

        This API does not authenticate a human or process.  The caller must use
        an independently authenticated custody service in deployment; the fields
        below make its proof and its separation from tested arms auditable.
        """
        if self.state["split"] is not None:
            raise ContractError("cannot change exposure qualification after split")
        _safe_name(custodian_id, "custodian id")
        if (not item_ids or len(set(item_ids)) != len(item_ids) or not tested_arm_ids
                or any(not _is_digest(value)
                       for value in (source_qualification_digest, exposure_qualification_digest))
                or custodian_id in tested_arm_ids):
            raise ContractError("invalid independent custody attestation")
        for arm in tested_arm_ids:
            _safe_name(arm, "tested arm")
        known = {f"{row['benchmark']}:{row['task_id']}" for row in self.state["inventory"]}
        if not set(item_ids) <= known:
            raise ContractError("attestation references unknown inventory item")
        record = {"items": sorted(item_ids), "custodian_id": custodian_id,
                  "source_qualification_digest": source_qualification_digest,
                  "exposure_qualification_digest": exposure_qualification_digest,
                  "tested_arm_ids": sorted(tested_arm_ids)}
        record["digest"] = digest(record)
        for item_id in record["items"]:
            existing = self.state["attestations"].get(item_id)
            if existing is not None and existing != record:
                raise ContractError("custody attestation drift")
            self.state["attestations"][item_id] = record
        self._save()
        return record

    def split(self, *, seed: str, validation_percent: int = 30,
              train_only_item_ids: list[str] | None = None,
              train_only_reason_commitment: str | None = None) -> dict[str, Any]:
        """Freeze allocation, optionally pre-registering full groups as train-only.

        A train-only declaration is a voluntary loss of validation eligibility;
        it is neither an exposure assertion nor an independent-clean proof.
        """
        if not self.state["inventory_digest"]:
            raise ContractError("inventory required before split")
        if not isinstance(validation_percent, int) or not 1 <= validation_percent <= 100:
            raise ContractError("validation percent must be 1..100")
        items = [InventoryItem.parse(row) for row in self.state["inventory"]]
        groups = _merged_groups(items)
        known = set(groups)
        if train_only_item_ids is None:
            if train_only_reason_commitment is not None:
                raise ContractError("train-only reason requires declared item ids")
            declaration = None
            train_only_groups: set[str] = set()
        else:
            if (not train_only_item_ids or len(set(train_only_item_ids)) != len(train_only_item_ids)
                    or any(not isinstance(item_id, str) for item_id in train_only_item_ids)
                    or not set(train_only_item_ids) <= known or not _is_digest(train_only_reason_commitment or "")):
                raise ContractError("invalid train-only declaration")
            declared = sorted(train_only_item_ids)
            train_only_groups = {groups[item_id] for item_id in declared}
            # Persist all group members, so an abbreviated caller list cannot
            # make a connected member appear validation-eligible later.
            declaration = {"item_ids": declared, "group_ids": sorted(train_only_groups),
                           "reason_commitment": train_only_reason_commitment}
        allocation: dict[str, str] = {}
        for gid in set(groups.values()):
            members = [item for item in items if groups[f"{item.benchmark}:{item.task_id}"] == gid]
            if gid in train_only_groups or any(item.exposure == "exposed" for item in members):
                allocation[gid] = "train"
            elif not all(f"{item.benchmark}:{item.task_id}" in self.state["attestations"] for item in members):
                allocation[gid] = "quarantine"
            else:
                bucket = int(hashlib.sha256(f"{seed}:{gid}".encode()).hexdigest(), 16) % 100
                allocation[gid] = "validation" if bucket < validation_percent else "train"
        rows = []
        for item in items:
            item_id = f"{item.benchmark}:{item.task_id}"
            qualified = item_id in self.state["attestations"]
            rows.append({"item": item_id, "group": groups[item_id], "domain": allocation[groups[item_id]], "official_split": item.official_split, "exposure": item.exposure, "custodian_qualified": qualified})
        payload = {"seed": seed, "validation_percent": validation_percent, "inventory_digest": self.state["inventory_digest"], "rows": sorted(rows, key=lambda row: row["item"])}
        # Preserve the pre-existing canonical payload and digest when callers
        # make no declaration.  Old persisted split files remain valid.
        if declaration is not None:
            payload["train_only_declaration"] = declaration
        split_digest = digest(payload)
        if self.state["split"] is not None and self.state["split"]["digest"] != split_digest:
            raise ContractError("split drift or reallocation refused")
        self.state["split"] = {"digest": split_digest, **payload}
        self._save()
        return self.state["split"]

    def export_train(self) -> list[DataIdentity]:
        if self.state["split"] is None:
            raise ContractError("split required before export")
        items = {f"{row['benchmark']}:{row['task_id']}": InventoryItem.parse(row) for row in self.state["inventory"]}
        result = []
        for row in self.state["split"]["rows"]:
            if row["domain"] != "train":
                continue
            item = items[row["item"]]
            result.append(DataIdentity(item.benchmark, item.task_id, row["group"], self.state["inventory_digest"], self.state["split"]["digest"], "train"))
        return result

    def qualify_stage(self, *, stage: str, panel_digest: str, candidate_digest: str | None = None,
                      group_ids: list[str], arm_schedule: list[str],
                      scorer_digest: str | None = None, protocol_digest: str | None = None,
                      calibration_receipt: FrozenRecord | None = None,
                      required_benchmarks: tuple[str, ...] = REQUIRED_BENCHMARKS) -> dict[str, Any]:
        """Return explicit metadata status or a signed scorer-calibration qualification."""
        if self.state["split"] is None:
            raise ContractError("split required before stage qualification")
        _safe_name(stage, "stage")
        if (not _is_digest(panel_digest) or candidate_digest is not None and not _is_digest(candidate_digest)
                or len(set(group_ids)) != len(group_ids) or not group_ids
                or not arm_schedule or len(set(arm_schedule)) != len(arm_schedule)):
            raise ContractError("invalid stage qualification request")
        for arm in arm_schedule:
            _safe_name(arm, "arm")
        required_benchmarks = tuple(required_benchmarks)
        if (not required_benchmarks or len(set(required_benchmarks)) != len(required_benchmarks)
                or not set(required_benchmarks) <= set(SUPPORTED_BENCHMARKS)
                or not set(REQUIRED_BENCHMARKS) <= set(required_benchmarks)):
            raise ContractError("required benchmark set must be supported and include the core pair")
        valid = {row["group"] for row in self.state["split"]["rows"] if row["domain"] == "validation"}
        if not set(group_ids) <= valid:
            raise ContractError("stage qualification includes non-validation group")
        used = set().union(*(set(lease["groups"]) for lease in self.state["leases"].values()), set())
        if used & set(group_ids):
            raise ContractError("validation group already allocated or consumed")
        base = {"stage": stage, "panel_digest": panel_digest, "candidate_digest": candidate_digest,
                "groups": sorted(group_ids),
                "arm_schedule": list(arm_schedule), "arm_schedule_digest": digest(list(arm_schedule)),
                "split_digest": self.state["split"]["digest"],
                "required_benchmarks": list(required_benchmarks)}
        if calibration_receipt is None:
            if scorer_digest is not None or protocol_digest is not None:
                raise ContractError("scorer and protocol binding require a signed calibration receipt")
            return {**base, "qualified": False, "qualification": "metadata_only",
                    "metadata_authenticated": False, "calibration_eligible": False}
        if not self._calibration_keys:
            raise ContractError("validation qualification requires configured trusted calibration keys")
        if scorer_digest is None or protocol_digest is None:
            raise ContractError("validation qualification requires scorer and protocol digests")
        calibration = verify_calibration_receipt(calibration_receipt, self._calibration_keys,
                                                  panel_digest=panel_digest, scorer_digest=scorer_digest,
                                                  protocol_digest=protocol_digest,
                                                  required_benchmarks=required_benchmarks)
        return {**base, "qualified": True, "qualification": "calibration_eligible",
                "metadata_authenticated": True, "calibration_eligible": True,
                "scorer_digest": scorer_digest, "protocol_digest": protocol_digest,
                "calibration_receipt_digest": calibration_receipt.content_hash,
                "criteria_digest": calibration["criteria_digest"],
                "calibration_authority": calibration["authority"]}

    def lease_validation(self, *, stage: str, panel_digest: str,
                         group_ids: list[str], arm_schedule: list[str], candidate_digest: str | None = None,
                         scorer_digest: str | None = None, protocol_digest: str | None = None,
                         calibration_receipt: FrozenRecord | None = None,
                         required_benchmarks: tuple[str, ...] = REQUIRED_BENCHMARKS) -> dict[str, Any]:
        if self.state["split"] is None:
            raise ContractError("split required before lease")
        if calibration_receipt is None or scorer_digest is None or protocol_digest is None or not _is_digest(candidate_digest or ""):
            raise ContractError("validation lease requires signed scorer calibration")
        lease_id = digest({"stage": stage, "panel": panel_digest, "candidate": candidate_digest, "groups": sorted(group_ids), "arms": arm_schedule, "split": self.state["split"]["digest"], "scorer": scorer_digest, "protocol": protocol_digest, "calibration": calibration_receipt.content_hash})
        if lease_id in self.state["leases"]:
            raise ContractError("validation lease is one-use")
        qualification = self.qualify_stage(stage=stage, panel_digest=panel_digest, candidate_digest=candidate_digest,
                                           group_ids=group_ids, arm_schedule=arm_schedule,
                                           scorer_digest=scorer_digest, protocol_digest=protocol_digest,
                                           calibration_receipt=calibration_receipt,
                                           required_benchmarks=required_benchmarks)
        lease = {"id": lease_id, **qualification, "panel_validated": False, "status": "active"}
        self.state["leases"][lease_id] = lease
        self._save()
        return lease

    def lease_panel(self, panel: Any, *, calibration_receipt: FrozenRecord,
                    protocol_digest: str) -> dict[str, Any]:
        """Lease only a panel whose task identities belong to this frozen split.

        Raw ``lease_validation`` remains a metadata compatibility API.  Its
        lease can never be signed for panel acceptance; this entry verifies the
        real inventory/split membership before allowing that later receipt.
        """
        from research_loop.modular.panel_receipts import FrozenPanel
        from research_loop.modular.combination_panels import CombinationPanel
        if not isinstance(panel, (FrozenPanel, CombinationPanel)) or panel.domain != "validation":
            raise ContractError("panel lease requires a frozen validation panel")
        if self.state["split"] is None:
            raise ContractError("split required before panel lease")
        items = {f"{row['benchmark']}:{row['task_id']}": InventoryItem.parse(row)
                 for row in self.state["inventory"]}
        split_rows = {row["item"]: row for row in self.state["split"]["rows"]}
        identities = []
        for cell in panel.cells:
            identity, item_id = cell.identity, f"{cell.identity.benchmark}:{cell.identity.task_id}"
            item, row = items.get(item_id), split_rows.get(item_id)
            if (item is None or row is None or identity.dataset_version != self.state["inventory_digest"]
                    or identity.split_id != self.state["split"]["digest"]
                    or identity.group_id != row["group"] or row["domain"] != "validation"):
                raise ContractError("panel task identity is not a validation member of this custody split")
            identities.append(identity.data())
        groups = list(panel.validation_groups)
        if set(groups) != {row["group"] for row in split_rows.values()
                           if row["item"] in {f"{cell.identity.benchmark}:{cell.identity.task_id}" for cell in panel.cells}}:
            raise ContractError("panel groups do not exactly match its custody task identities")
        lease = self.lease_validation(stage=panel.stage, panel_digest=panel.digest,
                                      candidate_digest=panel.candidate_digest, group_ids=groups,
                                      arm_schedule=list(panel.arm_schedule),
                                      scorer_digest=panel.cells[0].scorer_digest,
                                      protocol_digest=protocol_digest,
                                      calibration_receipt=calibration_receipt,
                                      required_benchmarks=panel.required_benchmarks)
        lease["panel_validated"] = True
        lease["task_identities_digest"] = digest(sorted(identities, key=canonical))
        self._save()
        return dict(lease)

    def consume_validation(self, lease_id: str, *, panel_digest: str, arm_schedule: list[str]) -> dict[str, Any]:
        lease = self.state["leases"].get(lease_id)
        if lease is None or lease["status"] != "active":
            raise ContractError("unknown or consumed validation lease")
        if lease["panel_digest"] != panel_digest or lease["arm_schedule"] != arm_schedule:
            raise ContractError("lease panel or arm schedule mismatch")
        lease["status"] = "consumed"
        self._save()
        return dict(lease)

    def issued_validation_receipt(self, lease_id: str) -> FrozenRecord:
        """Sign only this store's already-consumed, calibrated lease state."""
        if self._signing_authority_id is None or self._signing_key is None:
            raise ContractError("custody issued receipt requires configured signing authority")
        lease = self.state["leases"].get(lease_id)
        if (lease is None or lease.get("status") != "consumed" or lease.get("qualification") != "calibration_eligible"
                or lease.get("panel_validated") is not True):
            raise ContractError("only a consumed calibration-eligible custody lease can be issued")
        required = {"id", "stage", "panel_digest", "candidate_digest", "groups", "arm_schedule", "arm_schedule_digest",
                    "split_digest", "qualified", "qualification", "metadata_authenticated", "calibration_eligible",
                    "scorer_digest", "protocol_digest", "calibration_receipt_digest", "criteria_digest", "calibration_authority", "required_benchmarks", "panel_validated", "task_identities_digest", "status"}
        if set(lease) != required:
            raise ContractError("stored custody lease has unsupported fields")
        body = {"schema": "custody-panel-lease-v2", "lease_id": lease["id"], "stage": lease["stage"],
                "panel_digest": lease["panel_digest"], "candidate_digest": lease["candidate_digest"],
                "groups": lease["groups"], "arm_schedule": lease["arm_schedule"], "split_digest": lease["split_digest"],
                "scorer_digest": lease["scorer_digest"], "protocol_digest": lease["protocol_digest"],
                "calibration_receipt_digest": lease["calibration_receipt_digest"],
                "criteria_digest": lease["criteria_digest"],
                "required_benchmarks": lease["required_benchmarks"],
                "task_identities_digest": lease["task_identities_digest"],
                "status": "consumed", "authority": self._signing_authority_id}
        return FrozenRecord.from_dict({"body": body, "mac": hmac.new(self._signing_key, canonical(body).encode(), hashlib.sha256).hexdigest()})



def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    inventory = sub.add_parser("inventory")
    inventory.add_argument("--snapshot", type=Path, required=True)
    split = sub.add_parser("split")
    split.add_argument("--seed", required=True)
    split.add_argument("--validation-percent", type=int, default=30)
    lease = sub.add_parser("lease")
    lease.add_argument("--stage", required=True)
    lease.add_argument("--panel-digest", required=True)
    lease.add_argument("--group", action="append", required=True)
    lease.add_argument("--arm", action="append", required=True)
    qualify = sub.add_parser("qualify")
    qualify.add_argument("--stage", required=True)
    qualify.add_argument("--panel-digest", required=True)
    qualify.add_argument("--group", action="append", required=True)
    qualify.add_argument("--arm", action="append", required=True)
    consume = sub.add_parser("consume")
    consume.add_argument("--lease", required=True)
    consume.add_argument("--panel-digest", required=True)
    consume.add_argument("--arm", action="append", required=True)
    sub.add_parser("export")
    attest = sub.add_parser("attest")
    attest.add_argument("--item", action="append", required=True)
    attest.add_argument("--custodian", required=True)
    attest.add_argument("--source-proof", required=True)
    attest.add_argument("--exposure-proof", required=True)
    attest.add_argument("--tested-arm", action="append", required=True)
    args = parser.parse_args()
    store = CustodyStore(args.state)
    if args.command == "inventory":
        result: Any = {"inventory_digest": store.inventory(build_known_inventory(args.snapshot))}
    elif args.command == "split":
        result = store.split(seed=args.seed, validation_percent=args.validation_percent)
    elif args.command == "export":
        result = [identity.data() for identity in store.export_train()]
    elif args.command == "attest":
        result = store.attest_independent_clean(item_ids=args.item, custodian_id=args.custodian,
                                                 source_qualification_digest=args.source_proof,
                                                 exposure_qualification_digest=args.exposure_proof,
                                                 tested_arm_ids=args.tested_arm)
    elif args.command == "qualify":
        result = store.qualify_stage(stage=args.stage, panel_digest=args.panel_digest,
                                     group_ids=args.group, arm_schedule=args.arm)
    elif args.command == "lease":
        result = store.lease_validation(stage=args.stage, panel_digest=args.panel_digest,
                                        group_ids=args.group, arm_schedule=args.arm)
    else:
        result = store.consume_validation(args.lease, panel_digest=args.panel_digest, arm_schedule=args.arm)
    print(canonical(result))


if __name__ == "__main__":
    _main()
