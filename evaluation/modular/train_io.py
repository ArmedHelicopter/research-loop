"""Train-only public packet export.  It never enumerates validation identities."""
from __future__ import annotations

import csv, hashlib, io, json, os, stat
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


def _safe_path(path: Path) -> Path:
    """Reject every existing reparse component before resolving or reading it."""
    path = Path(path)
    if ".." in path.parts:
        raise ContractError("primary source/output paths cannot traverse parents")
    path = path.absolute()
    for item in (path, *path.parents):
        try:
            if _reparse(item):
                raise ContractError("primary source/output path contains a link or reparse point")
        except FileNotFoundError:
            continue
    return path


def _safe_under(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative or any(part in {"", ".", ".."} for part in relative.split("/")):
        raise ContractError("unsafe custody relative path")
    root = _safe_path(root).resolve(strict=True)
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
    path = _safe_path(path)
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


def prepare_primary_public_task(identity: DataIdentity, row: Mapping[str, Any], raw: Mapping[str, Any], csv_bytes: bytes) -> PublicTask:
    """Shared pure allowlist projection from a caller-verified source buffer."""
    if identity.benchmark == "discoverybench":
        query = raw.get("queries", [None])[0]
        datasets = raw.get("datasets")
        if not isinstance(query, Mapping) or not isinstance(datasets, list) or not datasets:
            raise ContractError("Discovery public metadata is incomplete")
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
        question, difficulty = query.get("question"), query.get("difficulty")
        if not isinstance(question, str) or not question:
            raise ContractError("Discovery public query is incomplete")
        return DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id, "question": question,
            "difficulty": difficulty if isinstance(difficulty, str) else None,
            "source_kind": "synthetic" if kind == "synth" else "real", "dataset": public_datasets})
    if identity.benchmark == "blade":
        questions = raw.get("research_questions", raw.get("research_question"))
        question = questions[0] if isinstance(questions, list) and questions else questions
        data_desc = raw.get("data_desc")
        description = data_desc.get("dataset_description") if isinstance(data_desc, Mapping) else data_desc
        header = next(csv.reader(io.StringIO(csv_bytes.decode("utf-8"), newline="")), [])
        if not isinstance(question, str) or not isinstance(description, str) or not header or any(not isinstance(value, str) or not value for value in header):
            raise ContractError("BLADE public metadata is incomplete")
        return BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": identity.task_id,
            "research_question": question, "data_schema": [{"name": name, "description": None, "dtype": None} for name in header],
            "task_instructions": description})
    raise ContractError("unsupported benchmark in custody export")


@dataclass(frozen=True)
class PrimaryTrainSource:
    """Controller-only source buffers; never passed to the model or packet consumer."""
    task: PublicTask
    anchor: FrozenRecord
    metadata: bytes
    csv: bytes
    receipt: FrozenRecord

    @property
    def public(self) -> bytes:
        return canonical({"task": self.task.data(), "receipt": self.receipt.data()}).encode("utf-8")


def primary_train_allocations(custody: CustodyExportPort, item_ids: Sequence[str]):
    """Validate the whole TRAIN selection before reading any snapshot content."""
    if (not item_ids or any(type(item) is not str or not item for item in item_ids)
            or len(set(item_ids)) != len(item_ids)):
        raise ContractError("export requires an exact nonempty train item allowlist")
    identities = custody.export_train()
    state = custody.state
    if not isinstance(state, Mapping) or not isinstance(state.get("inventory"), list) or not isinstance(state.get("split"), Mapping):
        raise ContractError("custody state is incomplete")
    try:
        rows = state["inventory"]
        inventory = {f"{row['benchmark']}:{row['task_id']}": row for row in rows}
        split_rows = state["split"]["rows"]
        splits = {row["item"]: row for row in split_rows}
        exported = {f"{identity.benchmark}:{identity.task_id}": identity for identity in identities}
        if len(inventory) != len(rows) or len(splits) != len(split_rows) or len(exported) != len(identities):
            raise ContractError("custody contains duplicate identities or allocation rows")
        if digest(sorted(rows, key=lambda row: (row["benchmark"], row["task_id"]))) != state["inventory_digest"]:
            raise ContractError("custody inventory digest drift")
        # Minimal test ports use a rows-only split. CustodyStore uses the full
        # frozen allocation payload, including seed and inventory version.
        split_body = {key: value for key, value in state["split"].items() if key != "digest"}
        split_material = split_rows if set(split_body) == {"rows"} else split_body
        if digest(split_material) != state["split"]["digest"]:
            raise ContractError("custody split digest drift")
        if not set(item_ids) <= set(exported):
            raise ContractError("requested item is not in custody train export")
        selected = []
        for key in item_ids:
            identity = exported[key]
            if type(identity) is not DataIdentity:
                raise ContractError("custody requires exact typed identities")
            identity.require_train()
            row, split = inventory[key], splits[key]
            if (split["domain"] != "train" or split["group"] != identity.group_id
                    or split["official_split"] != row["official_split"]
                    or identity.dataset_version != state["inventory_digest"]
                    or identity.split_id != state["split"]["digest"]):
                raise ContractError("custody export identity is not an exact frozen train allocation")
            selected.append((identity, FrozenRecord.from_dict(row), FrozenRecord.from_dict(split)))
        return tuple(selected)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ContractError("custody allocation schema is incomplete") from exc


def read_primary_train_sources(custody: CustodyExportPort, snapshot_root: Path,
                               item_ids: Sequence[str]) -> tuple[PrimaryTrainSource, ...]:
    snapshot_root = _safe_path(snapshot_root)
    allocations = primary_train_allocations(custody, item_ids)
    result = []
    for identity, frozen_row, allocation in allocations:
        row = frozen_row.data()
        expected = set(row["content_hashes"])
        if identity.benchmark == "discoverybench":
            source = _safe_under(snapshot_root / "discovery" / "upstream" / "discoverybench", row["relative_path"])
            candidates = sorted(source.glob("metadata_*.json"))
            if not candidates:
                raise ContractError("Discovery public metadata is missing")
            metadata = _public_file(candidates[0], expected)
        elif identity.benchmark == "blade":
            source = _safe_under(snapshot_root / "scienceagent" / "work" / "BLADE" / "blade_bench" / "datasets", row["relative_path"])
            metadata = _public_file(source / "info.json", expected)
        else:
            raise ContractError("unsupported benchmark in custody export")
        metadata_bytes = metadata.read_bytes()
        try:
            raw = json.loads(metadata_bytes.decode("utf-8"))
            if type(raw) is not dict:
                raise ContractError("public source metadata must be an object")
            data_name = raw["datasets"][0]["name"] if identity.benchmark == "discoverybench" else "data.csv"
            if (type(data_name) is not str or not data_name or data_name in {".", ".."}
                    or Path(data_name).name != data_name or "/" in data_name or "\\" in data_name):
                raise ContractError("public dataset name is unsafe")
            data = _public_file(source / data_name, expected)
            csv_bytes = data.read_bytes()
            metadata_sha, csv_sha = hashlib.sha256(metadata_bytes).hexdigest(), hashlib.sha256(csv_bytes).hexdigest()
            if metadata_sha not in expected or csv_sha not in expected:
                raise ContractError("source buffer hash drift after inventory check")
            task = prepare_primary_public_task(identity, row, raw, csv_bytes)
        except (KeyError, IndexError, TypeError, UnicodeError, ValueError) as exc:
            raise ContractError("public source projection is unreadable") from exc
        selector = {"metadata_file": metadata.name, "metadata_sha256": metadata_sha, "query_index": 0}
        receipt_body = {"identity": identity.data(), "source_group": identity.group_id,
            "official_split": row["official_split"], "split_digest": identity.split_id,
            "csv_sha256": csv_sha, "packet_hash": task.content_hash}
        if identity.benchmark == "discoverybench":
            receipt_body["source_selector"] = selector
        anchor = FrozenRecord.from_dict({"schema": "legacy-primary-source-v2", "identity": identity.data(),
            "inventory_digest": identity.dataset_version, "split_digest": identity.split_id,
            "inventory_row": row, "allocation": allocation.data(), "source_selector": selector,
            "metadata": {"file": metadata.name, "sha256": metadata_sha, "bytes": len(metadata_bytes)},
            "csv": {"file": data.name, "sha256": csv_sha, "bytes": len(csv_bytes)}})
        result.append(PrimaryTrainSource(task, anchor, metadata_bytes, csv_bytes, FrozenRecord.from_dict(receipt_body)))
    return tuple(result)


class TrainPacketExporter:
    def __init__(self, custody: CustodyExportPort, snapshot_root: Path, output_root: Path) -> None:
        self.custody = custody
        self.snapshot_root, self.output_root = _safe_path(snapshot_root), _safe_path(output_root)

    def export(self, item_ids: Sequence[str]) -> tuple[PublicTrainPacket, ...]:
        _safe_path(self.output_root)
        sources = read_primary_train_sources(self.custody, self.snapshot_root, item_ids)
        packets = []
        from evaluation.modular.legacy_primary_packet_artifacts import write
        for source in sources:
            destination = self.output_root / source.task.identity.benchmark / digest(source.task.identity.data())
            write(destination, source)
            packets.append(PublicTrainPacket(source.task, destination / "public.json", destination / "data.csv", source.receipt))
        return tuple(packets)


def verify_primary_train_packets(packets, *, custody, snapshot_root, item_ids, output_root):
    """Actual controller gate: derive expectations from custody, never packet claims."""
    root = _safe_path(output_root)
    if type(packets) is not tuple or any(type(packet) is not PublicTrainPacket for packet in packets):
        raise ContractError("primary consumer requires exact immutable train packets")
    sources = read_primary_train_sources(custody, snapshot_root, item_ids)
    if len(packets) != len(sources):
        raise ContractError("primary consumer packet count differs from frozen selection")
    from evaluation.modular.legacy_primary_packet_artifacts import verify
    for packet, source in zip(packets, sources):
        destination = root / source.task.identity.benchmark / digest(source.task.identity.data())
        if (type(packet.task) is not PublicTask or type(packet.receipt) is not FrozenRecord
                or packet.task != source.task or packet.receipt != source.receipt
                or _safe_path(packet.packet_path) != destination / "public.json"
                or _safe_path(packet.csv_path) != destination / "data.csv"):
            raise ContractError("primary consumer packet fields differ from independent source")
        verify(destination, source)
    return sources
