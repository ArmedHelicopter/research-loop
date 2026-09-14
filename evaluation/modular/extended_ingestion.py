"""Controller-only import and train projection for pinned extended sources.

This module is deliberately downstream of :mod:`source_ingestion` and writes
through ``CustodyStore.inventory``.  It reads raw source records only while
running in the controller process.  Its import result contains counts and
digests, never task text, source paths, answers, annotations, or evaluator
material.  Receiving a snapshot is not a qualification or an isolation claim.
"""

from __future__ import annotations

import csv
import hashlib
import json
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from evaluation.modular.custody import CustodyStore, InventoryItem
from research_loop.modular.benchmarks.scicode import SciCodeAdapter
from research_loop.modular.benchmarks.scienceagentbench import ScienceAgentBenchAdapter
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.source_ingestion import SOURCE_SNAPSHOTS
from research_loop.ontology import ContractError, canonical, digest


_RECEIPT_SCHEMA = "pinned-source-snapshot-receipt-v1"
_PUBLIC_SCICODE = {"problem_id", "sub_steps", "required_dependencies"}
_PUBLIC_SCICODE_STEP = {"step_description_prompt", "function_header", "return_line", "step_background"}
_PUBLIC_SAB = {"task_inst", "dataset_folder_tree", "dataset_preview", "output_fname", "domain_knowledge"}


def _token(prefix: str, value: object) -> str:
    return f"{prefix}-{hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()}"


def _safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or "\\" in value or ":" in value or ".." in path.parts
            or "." in path.parts or any(not part or part != part.strip() for part in path.parts)):
        raise ContractError("unsafe extended source relative path")
    return value


def _inside(root: Path, relative: str) -> Path:
    _safe_relative(relative)
    root = root.absolute()
    if not root.is_dir() or _reparse(root):
        raise ContractError("extended source root is not a concrete directory")
    candidate = root / Path(*PurePosixPath(relative).parts)
    cursor = candidate
    while cursor != root.parent:
        if _reparse(cursor):
            raise ContractError("extended source path contains a symlink or reparse point")
        cursor = cursor.parent
    candidate = candidate.resolve(strict=True)
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise ContractError("extended source artifact escaped snapshot root")
    return candidate


def _reparse(path: Path) -> bool:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ContractError("extended source path is unavailable") from exc
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _receipt(snapshot: Path, source: str) -> Mapping[str, Any]:
    receipt_path = snapshot / "snapshot-receipt.json"
    if not receipt_path.is_file():
        raise ContractError("pinned source snapshot receipt is required")
    try:
        value = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ContractError("invalid pinned source snapshot receipt") from exc
    spec = SOURCE_SNAPSHOTS[source]
    required = {"schema", "source", "repository", "revision", "artifacts", "payload_returned", "access_isolation", "split_qualified", "task_projection_created"}
    if (not isinstance(value, Mapping) or set(value) != required or value["schema"] != _RECEIPT_SCHEMA
            or value["source"] != source or value["repository"] != spec.repository or value["revision"] != spec.revision
            or value["payload_returned"] is not False or value["access_isolation"] != "not_verified"
            or value["split_qualified"] is not False or value["task_projection_created"] is not False):
        raise ContractError("source receipt does not establish an eligible pinned snapshot")
    artifacts = value["artifacts"]
    if (not isinstance(artifacts, list) or len(artifacts) != len(spec.artifacts)
            or {a.get("source_path") for a in artifacts if isinstance(a, Mapping)} != {a.source_path for a in spec.artifacts}):
        raise ContractError("source receipt artifact inventory drift")
    specs = {item.source_path: item for item in spec.artifacts}
    for artifact in artifacts:
        expected = specs[artifact["source_path"]] if isinstance(artifact, Mapping) and artifact.get("source_path") in specs else None
        required_artifact = {"source_path", "size_bytes", "git_blob_sha1", "git_blob_sha1_kind", "lfs_sha256", "local_sha256", "local_hash_kind"}
        if (not isinstance(artifact, Mapping) or set(artifact) != required_artifact
                or not isinstance(artifact.get("size_bytes"), int)
                or not isinstance(artifact.get("local_sha256"), str) or len(artifact["local_sha256"]) != 64):
            raise ContractError("source receipt lacks immutable artifact digest")
        if (expected is None or artifact["size_bytes"] != expected.size_bytes
                or artifact.get("git_blob_sha1") != expected.git_blob_sha1
                or artifact.get("lfs_sha256") != expected.lfs_sha256):
            raise ContractError("source receipt conflicts with pinned artifact metadata")
        expected_git_kind = ("Git LFS pointer blob SHA-1 metadata; not verified against downloaded payload"
                             if expected.lfs_sha256 is not None else "Git blob SHA-1 verified against downloaded payload")
        if (artifact["git_blob_sha1_kind"] != expected_git_kind
                or artifact["local_hash_kind"] != "SHA-256 of private downloaded bytes"):
            raise ContractError("source receipt hash-kind metadata drift")
        local = _inside(snapshot, artifact["source_path"])
        content = local.read_bytes()
        if local.stat().st_size != artifact["size_bytes"] or hashlib.sha256(content).hexdigest() != artifact["local_sha256"]:
            raise ContractError("private snapshot artifact drift")
        if expected.lfs_sha256 is not None:
            if hashlib.sha256(content).hexdigest() != expected.lfs_sha256:
                raise ContractError("private LFS payload does not match fixed metadata")
        else:
            git_blob = hashlib.sha1(f"blob {len(content)}\0".encode("ascii") + content).hexdigest()
            if git_blob != expected.git_blob_sha1:
                raise ContractError("private Git blob does not match fixed metadata")
    return value


def _json_lines(path: Path) -> Iterable[tuple[int, bytes, Mapping[str, Any]]]:
    for number, raw in enumerate(path.read_bytes().splitlines(), start=1):
        if not raw:
            raise ContractError("empty source JSONL record")
        try:
            value = json.loads(raw)
        except ValueError as exc:
            raise ContractError("invalid source JSONL record") from exc
        if not isinstance(value, Mapping):
            raise ContractError("source JSONL record must be an object")
        yield number, raw, value


def _public_scicode(record: Mapping[str, Any]) -> Mapping[str, Any]:
    if not _PUBLIC_SCICODE <= set(record):
        raise ContractError("SciCode record lacks public projection fields")
    steps = record["sub_steps"]
    if not isinstance(steps, list) or not steps:
        raise ContractError("SciCode record has no substeps")
    projected = []
    for step in steps:
        if not isinstance(step, Mapping) or not _PUBLIC_SCICODE_STEP <= set(step):
            raise ContractError("SciCode substep lacks public projection fields")
        projected.append({key: step[key] for key in _PUBLIC_SCICODE_STEP})
    problem = record["problem_id"]
    if not isinstance(problem, str) or not problem or any(char in problem for char in "/\\\x00"):
        raise ContractError("SciCode problem identifier is unsafe")
    return {"problem_id": problem, "sub_steps": projected, "required_dependencies": record["required_dependencies"]}


def _public_sab(record: Mapping[str, Any]) -> Mapping[str, Any]:
    if not _PUBLIC_SAB <= set(record):
        raise ContractError("ScienceAgentBench record lacks public projection fields")
    return {key: record[key] for key in _PUBLIC_SAB}


def project_extended_public_record(source: str, record: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]]:
    """Pure shared source allowlist, without custody mutation or file output."""
    if source == "scicode":
        public = _public_scicode(record)
        return public["problem_id"], public
    if source == "scienceagentbench":
        public = _public_sab(record)
        return _token("scienceagentbench-task", public), public
    raise ContractError("unsupported extended public projection source")


def prepare_extended_public_task(identity: DataIdentity, public: Mapping[str, Any]) -> PublicTask:
    """Run the existing adapters on the same pure projection for both brokers."""
    if identity.benchmark == "scicode":
        return SciCodeAdapter().prepare(identity, public)
    if identity.benchmark == "scienceagentbench":
        return ScienceAgentBenchAdapter().prepare(identity, {**public, "task_id": identity.task_id})
    raise ContractError("unsupported extended public adapter source")


def _sab_root(tree: object, task_token: str) -> str:
    """Use the source formatter's first tree line; unknown remains isolated."""
    if not isinstance(tree, str):
        return f"scienceagentbench:unknown:{task_token}"
    first = next((line for line in tree.splitlines() if line.strip()), "")
    # Official inference strips the first four tree-decoration characters.
    candidate = first[4:].strip() if len(first) >= 4 else ""
    path = PurePosixPath(candidate)
    if not candidate or path.is_absolute() or ".." in path.parts or "\\" in candidate or ":" in candidate or not path.parts:
        return f"scienceagentbench:unknown:{task_token}"
    return _token("scienceagentbench-root", path.parts[0])


@dataclass(frozen=True)
class ExtendedImport:
    inventory_digest: str
    receipt: FrozenRecord


class ExtendedInventoryImporter:
    """Private controller reader that delegates durable state to CustodyStore."""

    def __init__(self, private_store: Path) -> None:
        self.private_store = private_store

    def import_into(self, custody: CustodyStore, sources: Sequence[str] = ("scicode", "scienceagentbench")) -> ExtendedImport:
        if not sources or len(set(sources)) != len(sources) or set(sources) - {"scicode", "scienceagentbench"}:
            raise ContractError("import requires a unique supported source allowlist")
        if custody.state["inventory_digest"] is not None:
            raise ContractError("extended import requires a new empty custody state; existing inventory is immutable")
        items: list[InventoryItem] = []
        counts: dict[str, int] = {}
        pins: dict[str, str] = {}
        for source in sources:
            spec = SOURCE_SNAPSHOTS[source]
            snapshot = self.private_store / "snapshots" / source / spec.revision
            _receipt(snapshot, source)
            if source == "scicode":
                source_items = self._scicode(snapshot)
            else:
                source_items = self._scienceagentbench(snapshot)
            items.extend(source_items)
            counts[source] = len(source_items)
            pins[source] = spec.revision
        if len({(item.benchmark, item.task_id) for item in items}) != len(items):
            raise ContractError("extended source task identity collision")
        inventory_digest = custody.inventory(items)
        receipt = FrozenRecord.from_dict({"schema": "extended-source-inventory-import-v1", "sources": list(sources),
            "source_pins": pins, "item_counts": counts, "inventory_digest": inventory_digest,
            "parent_inventory_digest": None, "raw_private_payload_returned": False,
            "access_isolation": "not_verified", "qualification": "quarantine_until_review"})
        return ExtendedImport(inventory_digest, receipt)

    def _scicode(self, snapshot: Path) -> list[InventoryItem]:
        result = []
        for split_file, split in (("problems_dev.jsonl", "dev"), ("problems_test.jsonl", "test")):
            path = _inside(snapshot, split_file)
            for _number, raw, record in _json_lines(path):
                public = _public_scicode(record)
                task_id = public["problem_id"]
                # One inventory member represents the main problem and its complete substep list.
                result.append(InventoryItem("scicode", task_id, _token("scicode-main", task_id), split,
                    split_file, (hashlib.sha256(raw).hexdigest(),), "unknown"))
        return result

    def _scienceagentbench(self, snapshot: Path) -> list[InventoryItem]:
        path = _inside(snapshot, "ScienceAgentBench.csv")
        try:
            with path.open("r", encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
        except (OSError, csv.Error) as exc:
            raise ContractError("invalid ScienceAgentBench CSV") from exc
        result = []
        for row in rows:
            public = _public_sab(row)
            task_id = _token("scienceagentbench-task", public)
            result.append(InventoryItem("scienceagentbench", task_id, _sab_root(public["dataset_folder_tree"], task_id), "validation",
                "ScienceAgentBench.csv", (hashlib.sha256(canonical(public).encode()).hexdigest(),), "unknown"))
        return result


class ExtendedTrainProjectionExporter:
    """Re-read controller source only to materialize an exact frozen train allowlist."""

    def __init__(self, custody: CustodyStore, private_store: Path, output_root: Path) -> None:
        self.custody, self.private_store, self.output_root = custody, private_store, output_root

    def export(self, item_ids: Sequence[str]) -> tuple[PublicTask, ...]:
        if not item_ids or len(set(item_ids)) != len(item_ids):
            raise ContractError("projection needs an exact nonempty train allowlist")
        identities = {f"{i.benchmark}:{i.task_id}": i for i in self.custody.export_train()}
        if not set(item_ids) <= set(identities):
            raise ContractError("projection allowlist includes a non-train identity")
        material = self._material_by_key({identity.benchmark for identity in identities.values() if f"{identity.benchmark}:{identity.task_id}" in item_ids})
        inventory = {f"{row['benchmark']}:{row['task_id']}": row for row in self.custody.state["inventory"]}
        tasks = []
        for item_id in item_ids:
            identity = identities[item_id]
            record = material.get(item_id)
            if record is None:
                raise ContractError("frozen train identity absent from source inventory")
            public, record_hash = record
            if record_hash not in set(inventory[item_id]["content_hashes"]):
                raise ContractError("source record no longer matches frozen inventory")
            task = prepare_extended_public_task(identity, public)
            self._write(task, record_hash)
            tasks.append(task)
        return tuple(tasks)

    def _material_by_key(self, benchmarks: set[str]) -> dict[str, tuple[Mapping[str, Any], str]]:
        result: dict[str, tuple[Mapping[str, Any], str]] = {}
        if "scicode" in benchmarks:
            scicode = SOURCE_SNAPSHOTS["scicode"]
            snapshot = self.private_store / "snapshots" / "scicode" / scicode.revision
            _receipt(snapshot, "scicode")
            for filename in ("problems_dev.jsonl", "problems_test.jsonl"):
                for _number, raw, record in _json_lines(_inside(snapshot, filename)):
                    public = _public_scicode(record)
                    result[f"scicode:{public['problem_id']}"] = (public, hashlib.sha256(raw).hexdigest())
        if "scienceagentbench" in benchmarks:
            sab = SOURCE_SNAPSHOTS["scienceagentbench"]
            snapshot = self.private_store / "snapshots" / "scienceagentbench" / sab.revision
            _receipt(snapshot, "scienceagentbench")
            with _inside(snapshot, "ScienceAgentBench.csv").open("r", encoding="utf-8", newline="") as stream:
                for row in csv.DictReader(stream):
                    public = _public_sab(row)
                    result[f"scienceagentbench:{_token('scienceagentbench-task', public)}"] = (public, hashlib.sha256(canonical(public).encode()).hexdigest())
        return result

    def _write(self, task: PublicTask, source_sha256: str) -> None:
        target = self.output_root / task.identity.benchmark / digest(task.identity.data())
        target.mkdir(parents=True, exist_ok=False)
        (target / "public.json").write_text(canonical(task.data()) + "\n", encoding="utf-8")
        (target / "receipt.json").write_text(canonical({"identity": task.identity.data(), "task_hash": task.content_hash,
            "public_projection_written": True, "public_projection_returned": True,
            "raw_private_payload_returned": False, "access_isolation": "not_verified"}) + "\n", encoding="utf-8")
        from evaluation.modular.legacy_extended_packet_artifacts import seal_packet
        seal_packet(target, task, source_sha256)
