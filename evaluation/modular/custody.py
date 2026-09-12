"""Metadata-only custody for modular benchmark experiments.

This is a controller-side boundary, not an operating-system sandbox.  It records
only names, relative paths and hashes; callers must arrange separate mounts and
process permissions for a real private evaluator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from research_loop.modular.contracts import DataIdentity
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
    # The historical Discovery runner selected first twelve sorted synth/test
    # dataset directories.  This reproduces its selection from names only.
    discovery_test = sorted((item for item in items if item.benchmark == "discoverybench" and item.official_split == "synth/test"), key=lambda item: item.relative_path)[:12]
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


class CustodyStore:
    """Durable custody state with deterministic allocation and one-use leases."""
    def __init__(self, path: Path) -> None:
        self.path = path
        self.state = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema": SCHEMA, "inventory": [], "inventory_digest": None, "attestations": {}, "split": None, "leases": {}}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if set(data) != {"schema", "inventory", "inventory_digest", "attestations", "split", "leases"} or data["schema"] != SCHEMA:
            raise ContractError("unsupported custody state")
        return data

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = canonical(self.state)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(encoded, encoding="utf-8")
        temporary.replace(self.path)

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

    def split(self, *, seed: str, validation_percent: int = 30) -> dict[str, Any]:
        if not self.state["inventory_digest"]:
            raise ContractError("inventory required before split")
        if not isinstance(validation_percent, int) or not 1 <= validation_percent <= 100:
            raise ContractError("validation percent must be 1..100")
        items = [InventoryItem.parse(row) for row in self.state["inventory"]]
        groups = _merged_groups(items)
        allocation: dict[str, str] = {}
        for item in items:
            gid = groups[f"{item.benchmark}:{item.task_id}"]
            if item.exposure == "exposed":
                allocation[gid] = "train"
            elif f"{item.benchmark}:{item.task_id}" not in self.state["attestations"]:
                allocation.setdefault(gid, "quarantine")
            elif allocation.get(gid) != "train":
                bucket = int(hashlib.sha256(f"{seed}:{gid}".encode()).hexdigest(), 16) % 100
                allocation[gid] = "validation" if bucket < validation_percent else "train"
        rows = []
        for item in items:
            item_id = f"{item.benchmark}:{item.task_id}"
            qualified = item_id in self.state["attestations"]
            rows.append({"item": item_id, "group": groups[item_id], "domain": allocation[groups[item_id]], "official_split": item.official_split, "exposure": item.exposure, "custodian_qualified": qualified})
        payload = {"seed": seed, "validation_percent": validation_percent, "inventory_digest": self.state["inventory_digest"], "rows": sorted(rows, key=lambda row: row["item"])}
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
            result.append(DataIdentity(item.benchmark, item.task_id, row["group"], self.state["inventory_digest"], item.official_split, "train"))
        return result

    def qualify_stage(self, *, stage: str, panel_digest: str, group_ids: list[str], arm_schedule: list[str]) -> dict[str, Any]:
        """Check a frozen panel before issuing its one-use validation capability."""
        if self.state["split"] is None:
            raise ContractError("split required before stage qualification")
        _safe_name(stage, "stage")
        if (not _is_digest(panel_digest) or len(set(group_ids)) != len(group_ids) or not group_ids
                or not arm_schedule or len(set(arm_schedule)) != len(arm_schedule)):
            raise ContractError("invalid stage qualification request")
        for arm in arm_schedule:
            _safe_name(arm, "arm")
        valid = {row["group"] for row in self.state["split"]["rows"] if row["domain"] == "validation"}
        if not set(group_ids) <= valid:
            raise ContractError("stage qualification includes non-validation group")
        used = set().union(*(set(lease["groups"]) for lease in self.state["leases"].values()), set())
        if used & set(group_ids):
            raise ContractError("validation group already allocated or consumed")
        return {"stage": stage, "panel_digest": panel_digest, "groups": sorted(group_ids),
                "arm_schedule": list(arm_schedule), "arm_schedule_digest": digest(list(arm_schedule)),
                "split_digest": self.state["split"]["digest"], "qualified": True}

    def lease_validation(self, *, stage: str, panel_digest: str, group_ids: list[str], arm_schedule: list[str]) -> dict[str, Any]:
        if self.state["split"] is None:
            raise ContractError("split required before lease")
        lease_id = digest({"stage": stage, "panel": panel_digest, "groups": sorted(group_ids), "arms": arm_schedule, "split": self.state["split"]["digest"]})
        if lease_id in self.state["leases"]:
            raise ContractError("validation lease is one-use")
        qualification = self.qualify_stage(stage=stage, panel_digest=panel_digest, group_ids=group_ids, arm_schedule=arm_schedule)
        lease = {"id": lease_id, **qualification, "status": "active"}
        self.state["leases"][lease_id] = lease
        self._save()
        return lease

    def consume_validation(self, lease_id: str, *, panel_digest: str, arm_schedule: list[str]) -> dict[str, Any]:
        lease = self.state["leases"].get(lease_id)
        if lease is None or lease["status"] != "active":
            raise ContractError("unknown or consumed validation lease")
        if lease["panel_digest"] != panel_digest or lease["arm_schedule"] != arm_schedule:
            raise ContractError("lease panel or arm schedule mismatch")
        lease["status"] = "consumed"
        self._save()
        return dict(lease)


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
