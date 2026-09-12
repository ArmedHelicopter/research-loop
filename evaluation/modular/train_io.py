"""Train-only public packet export.  It never enumerates validation identities."""
from __future__ import annotations

import csv, hashlib, json, os, stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from research_loop.modular.benchmarks.blade import BladeAdapter
from research_loop.modular.benchmarks.discovery import DiscoveryBenchAdapter
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.ontology import ContractError, canonical, digest


class CustodyExportPort(Protocol):
    state: Mapping[str, Any]
    def export_train(self) -> list[DataIdentity]: ...


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _reparse(path: Path) -> bool:
    info = path.stat(follow_symlinks=False)
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _safe_under(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative or any(part in {"", ".", ".."} for part in relative.split("/")):
        raise ContractError("unsafe custody relative path")
    root = root.resolve(strict=True)
    if _reparse(root):
        raise ContractError("source root is a reparse path")
    candidate = root.joinpath(*relative.split("/"))
    cursor = candidate.absolute()
    while cursor != cursor.parent:
        if _reparse(cursor):
            raise ContractError("source path contains a symlink or reparse point")
        cursor = cursor.parent
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_dir():
        raise ContractError("custody source path is outside its root")
    return resolved


def _public_file(path: Path, expected_hashes: set[str]) -> Path:
    if _reparse(path) or not path.is_file() or any(token in path.name.lower() for token in ("answer", "annotation", "reference", "label", "scorer", "gold")):
        raise ContractError("non-public source file refused")
    if _sha(path) not in expected_hashes:
        raise ContractError("public source file hash is absent from frozen inventory")
    return path


@dataclass(frozen=True)
class PublicTrainPacket:
    task: PublicTask
    packet_path: Path
    csv_path: Path
    receipt: FrozenRecord


class TrainPacketExporter:
    def __init__(self, custody: CustodyExportPort, snapshot_root: Path, output_root: Path) -> None:
        self.custody, self.snapshot_root, self.output_root = custody, snapshot_root, output_root

    def export(self, item_ids: Sequence[str]) -> tuple[PublicTrainPacket, ...]:
        if not item_ids or len(set(item_ids)) != len(item_ids) or any(not isinstance(item, str) for item in item_ids):
            raise ContractError("export requires an exact nonempty train item allowlist")
        identities = self.custody.export_train()
        state = self.custody.state
        if not isinstance(state, Mapping) or not isinstance(state.get("inventory"), list) or not isinstance(state.get("split"), Mapping):
            raise ContractError("custody state is incomplete")
        inventory = {f"{row['benchmark']}:{row['task_id']}": row for row in state["inventory"]}
        splits = {row["item"]: row for row in state["split"].get("rows", []) if row.get("domain") == "train"}
        exported = {f"{identity.benchmark}:{identity.task_id}": identity for identity in identities}
        if not set(item_ids) <= set(exported):
            raise ContractError("requested item is not in custody train export")
        packets = []
        for key in item_ids:
            identity = exported[key]
            identity.require_train()
            key = f"{identity.benchmark}:{identity.task_id}"
            row = inventory.get(key)
            split = splits.get(key)
            if row is None or split is None or row.get("benchmark") != identity.benchmark or identity.dataset_version != state.get("inventory_digest") or identity.split_id != state["split"].get("digest"):
                raise ContractError("custody export identity is not an exact frozen train allocation")
            if split.get("group") != identity.group_id or split.get("official_split") != row.get("official_split"):
                raise ContractError("custody source group or official split drift")
            packet = self._one(identity, row, state["split"]["digest"])
            packets.append(packet)
        return tuple(packets)

    def _one(self, identity: DataIdentity, row: Mapping[str, Any], split_digest: str) -> PublicTrainPacket:
        expected = set(row["content_hashes"])
        if identity.benchmark == "discoverybench":
            source = _safe_under(self.snapshot_root / "discovery" / "upstream" / "discoverybench", row["relative_path"])
            metadata = _public_file(next(iter(sorted(source.glob("metadata_*.json")))), expected)
            raw = json.loads(metadata.read_text(encoding="utf-8"))
            query = raw.get("queries", [None])[0]
            datasets = raw.get("datasets")
            if not isinstance(query, Mapping) or not isinstance(datasets, list) or not datasets:
                raise ContractError("Discovery public metadata is incomplete")
            data_name = datasets[0].get("name") if isinstance(datasets[0], Mapping) else None
            if not isinstance(data_name, str) or Path(data_name).name != data_name:
                raise ContractError("Discovery public dataset name is unsafe")
            data = _public_file(source / data_name, expected)
            public_datasets = []
            for dataset in datasets:
                if not isinstance(dataset, Mapping):
                    raise ContractError("Discovery dataset descriptor is invalid")
                columns = dataset.get("columns", [])
                if not isinstance(columns, list):
                    raise ContractError("Discovery columns are invalid")
                dataset_name = dataset.get("name")
                if not isinstance(dataset_name, str) or not dataset_name:
                    raise ContractError("Discovery dataset descriptor has no public name")
                public_datasets.append({"name": dataset_name, "description": dataset.get("description") if isinstance(dataset.get("description"), str) else None,
                                        "columns": [{"name": col.get("name"), "description": col.get("description") if isinstance(col.get("description"), str) else None} for col in columns if isinstance(col, Mapping) and isinstance(col.get("name"), str) and col.get("name")]})
            kind = row["official_split"].split("/", 1)[0]
            question = query.get("question")
            if not isinstance(question, str) or not question:
                raise ContractError("Discovery public query is incomplete")
            difficulty = query.get("difficulty")
            task = DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id, "question": question, "difficulty": difficulty if isinstance(difficulty, str) else None, "source_kind": "synthetic" if kind == "synth" else "real", "dataset": public_datasets})
        elif identity.benchmark == "blade":
            source = _safe_under(self.snapshot_root / "scienceagent" / "work" / "BLADE" / "blade_bench" / "datasets", row["relative_path"])
            info = _public_file(source / "info.json", expected)
            data = _public_file(source / "data.csv", expected)
            raw = json.loads(info.read_text(encoding="utf-8"))
            questions = raw.get("research_questions", raw.get("research_question"))
            question = questions[0] if isinstance(questions, list) and questions else questions
            data_desc = raw.get("data_desc")
            description = data_desc.get("dataset_description") if isinstance(data_desc, Mapping) else data_desc
            with data.open("r", encoding="utf-8", newline="") as stream:
                header = next(csv.reader(stream), [])
            if not isinstance(question, str) or not isinstance(description, str) or not header or any(not isinstance(value, str) or not value for value in header):
                raise ContractError("BLADE public metadata is incomplete")
            task = BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": identity.task_id, "research_question": question, "data_schema": [{"name": name, "description": None, "dtype": None} for name in header], "task_instructions": description})
        else:
            raise ContractError("unsupported benchmark in custody export")
        destination = self.output_root / identity.benchmark / digest(identity.data())
        destination.mkdir(parents=True, exist_ok=False)
        csv_target = destination / "data.csv"
        csv_target.write_bytes(data.read_bytes())
        receipt = FrozenRecord.from_dict({"identity": identity.data(), "source_group": identity.group_id, "official_split": row["official_split"], "split_digest": split_digest, "csv_sha256": _sha(data), "packet_hash": task.content_hash})
        packet_path = destination / "public.json"
        packet_path.write_text(canonical({"task": task.data(), "receipt": receipt.data()}), encoding="utf-8")
        return PublicTrainPacket(task, packet_path, csv_target, receipt)
