"""Custodian-side train reference extraction and scorer-only frozen lookup.

No reference contents are returned by the export API. This file boundary is not
an OS access boundary: the caller must keep the store outside solver mounts and
run its resolver in the evaluator process.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path
from typing import Mapping, Sequence

from evaluation.modular.train_io import CustodyExportPort, PublicTrainPacket, _reparse, _safe_under
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.ontology import ContractError, digest


BLADE_REFERENCE_FIELDS = (
    "conceptual_spec_json", "transform_spec_json", "model_spec_json",
    "annotate_cvar_spec_json", "annotate_transform_spec_json", "dependency_graph",
)


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _plain(path: Path) -> Path:
    path = Path(path).absolute()
    for cursor in (path, *path.parents):
        if cursor.exists() and _reparse(cursor):
            raise ContractError("reference source contains a symlink or reparse point")
    return path


def _read_bound(path: Path, hashes: set[str]) -> tuple[bytes, str]:
    path = _plain(path)
    if not path.is_file():
        raise ContractError("reference source is not a regular file")
    raw = path.read_bytes()
    source_hash = _hash(raw)
    if source_hash not in hashes:
        raise ContractError("reference source hash is not frozen")
    return raw, source_hash


def _object(raw: bytes) -> dict:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ContractError("reference metadata is not UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ContractError("reference metadata must be an object")
    return value


def _allocation(custody: CustodyExportPort, packets: Sequence[PublicTrainPacket]) -> list[dict]:
    # Validate the complete allowlist before any task/reference file is read.
    if not packets or any(not isinstance(packet, PublicTrainPacket) for packet in packets):
        raise ContractError("reference export needs prepared train packets")
    identities = [packet.task.identity for packet in packets]
    for identity in identities:
        identity.require_train()
    if len(set(identities)) != len(identities):
        raise ContractError("reference export has duplicate train identities")
    allowed = set(custody.export_train())
    state = custody.state
    if not isinstance(state.get("split"), Mapping):
        raise ContractError("reference export needs a frozen custody split")
    inventory = {f"{row['benchmark']}:{row['task_id']}": row for row in state["inventory"]}
    splits = {row["item"]: row for row in state["split"]["rows"]}
    result = []
    for packet in packets:
        identity = packet.task.identity
        key = f"{identity.benchmark}:{identity.task_id}"
        row, split = inventory.get(key), splits.get(key)
        receipt = packet.receipt.data()
        if (identity not in allowed or row is None or split is None or split["domain"] != "train"
                or split["group"] != identity.group_id or split["official_split"] != row["official_split"]
                or identity.dataset_version != state["inventory_digest"] or identity.split_id != state["split"]["digest"]
                or receipt.get("identity") != identity.data() or receipt.get("packet_hash") != packet.task.content_hash
                or receipt.get("split_digest") != identity.split_id):
            raise ContractError("reference packet differs from the exact custody train allocation")
        result.append(row)
    return result


def _discovery(snapshot: Path, row: Mapping, packet: PublicTrainPacket,
               answer_keys: Mapping[str, Mapping[str, str]]) -> tuple[list[dict], list[dict]]:
    directory = _safe_under(snapshot / "discovery" / "upstream" / "discoverybench", row["relative_path"])
    selector = packet.receipt.data().get("source_selector")
    if (not isinstance(selector, Mapping) or set(selector) != {"metadata_file", "metadata_sha256", "query_index"}
            or not isinstance(selector["metadata_file"], str) or Path(selector["metadata_file"]).name != selector["metadata_file"]
            or not selector["metadata_file"].startswith("metadata_") or not selector["metadata_file"].endswith(".json")
            or type(selector["query_index"]) is not int or selector["query_index"] != 0
            or selector["metadata_sha256"] not in row["content_hashes"]):
        raise ContractError("Discovery reference needs the exported exact source selector")
    raw, metadata_hash = _read_bound(directory / selector["metadata_file"], {selector["metadata_sha256"]})
    metadata = _object(raw)
    query = metadata.get("queries", [None])[0]
    if (not isinstance(query, Mapping) or query.get("question") != packet.task.payload.data().get("question")
            or type(metadata.get("id")) is not int or type(query.get("qid")) is not int):
        raise ContractError("Discovery reference query does not match the exported public task")
    kind = row["official_split"].split("/", 1)[0]
    descriptor = answer_keys.get(kind)
    if not isinstance(descriptor, Mapping) or set(descriptor) != {"path", "sha256", "encoding"}:
        raise ContractError("Discovery answer key requires an explicitly frozen descriptor")
    if descriptor["encoding"] not in {"utf-8-sig", "cp1252"}:
        raise ContractError("Discovery answer key encoding is not supported")
    key_raw, key_hash = _read_bound(Path(descriptor["path"]), {descriptor["sha256"]})
    try:
        reader = csv.DictReader(io.StringIO(key_raw.decode(descriptor["encoding"]), newline=""))
        if not {"dataset", "metadataid", "query_id", "gold_hypo"} <= set(reader.fieldnames or ()):
            raise ContractError("Discovery answer key schema is incomplete")
        matches = [item for item in reader if item["dataset"] == directory.name
                   and item["metadataid"] == str(metadata["id"]) and item["query_id"] == str(query["qid"])]
    except UnicodeError as exc:
        raise ContractError("Discovery answer key encoding mismatch") from exc
    if len(matches) != 1 or not matches[0]["gold_hypo"].strip():
        raise ContractError("Discovery train reference is empty or nonunique")
    return ([{"hypothesis": matches[0]["gold_hypo"]}],
            [{"role": "public_query", "sha256": metadata_hash}, {"role": "answer_key", "sha256": key_hash}])


def _blade(snapshot: Path, row: Mapping, packet: PublicTrainPacket) -> tuple[list[dict], list[dict]]:
    directory = _safe_under(snapshot / "scienceagent" / "work" / "BLADE" / "blade_bench" / "datasets", row["relative_path"])
    public_raw, public_hash = _read_bound(directory / "info.json", set(row["content_hashes"]))
    info = _object(public_raw)
    questions = info.get("research_questions", info.get("research_question"))
    question = questions[0] if isinstance(questions, list) and questions else questions
    if question != packet.task.payload.data().get("research_question"):
        raise ContractError("BLADE reference query does not match the exported public task")
    raw, source_hash = _read_bound(directory / "annotations.csv", set(row["content_hashes"]))
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
        if not {"spec_id", *BLADE_REFERENCE_FIELDS} <= set(reader.fieldnames or ()):
            raise ContractError("BLADE reference schema is incomplete")
        references, seen = [], set()
        for item in reader:
            spec = {field: json.loads(item[field]) for field in BLADE_REFERENCE_FIELDS if item[field].strip()}
            if not spec:
                continue
            spec_hash = digest(spec)
            if spec_hash in seen:
                continue
            seen.add(spec_hash)
            if not item["spec_id"].strip():
                raise ContractError("BLADE reference spec has no provenance identifier")
            references.append({"spec_id": item["spec_id"], **spec})
    except (ValueError, UnicodeError) as exc:
        raise ContractError("BLADE reference contains malformed JSON or text") from exc
    if not references:
        raise ContractError("BLADE reference set is empty")
    return references, [{"role": "public_query", "sha256": public_hash}, {"role": "complete_analysis_references", "sha256": source_hash}]


def prepare_train_reference_store(*, custody: CustodyExportPort, snapshot_root: Path,
                                  packets: Sequence[PublicTrainPacket], store_root: Path,
                                  discovery_answer_keys: Mapping[str, Mapping[str, str]]) -> FrozenRecord:
    """Write only allowlisted train references; return hashes/handles, no content.

    This is a custodian operation. Discovery's aggregate answer-key file is
    parsed here, never by the optimizer; only exact train rows enter the store.
    """
    rows = _allocation(custody, packets)
    destination = _plain(store_root)
    if destination.exists():
        raise ContractError("reference store must be a new immutable directory")
    snapshot = _plain(snapshot_root).resolve(strict=True)
    if (destination.is_relative_to(snapshot) or snapshot.is_relative_to(destination)
            or any(destination.is_relative_to(packet.packet_path.parent.absolute())
                   or packet.packet_path.parent.absolute().is_relative_to(destination) for packet in packets)):
        raise ContractError("reference store must be separate from source and public solver packets")
    records, manifest_rows = [], []
    for row, packet in zip(rows, packets, strict=True):
        if row["benchmark"] == "discoverybench":
            references, sources = _discovery(snapshot, row, packet, discovery_answer_keys)
        elif row["benchmark"] == "blade":
            references, sources = _blade(snapshot, row, packet)
        else:
            raise ContractError("reference store supports the frozen core benchmark pair only")
        identity_digest = digest(packet.task.identity.data())
        handle = _hash(os.urandom(32))
        reference = FrozenRecord.from_dict({"schema": "train-only-rubric-reference-v1", "split": "train",
            "benchmark": row["benchmark"], "task_handle_digest": _hash(handle.encode()),
            "identity_digest": identity_digest, "task_context": packet.task.payload.data(), "references": references})
        file_name = handle + ".json"
        records.append((file_name, reference))
        manifest_rows.append({"identity": packet.task.identity.data(), "identity_digest": identity_digest,
            "task_digest": packet.task.content_hash, "task_handle": handle, "file": file_name,
            "reference_sha256": _hash(reference.encoded.encode()), "sources": sources})
    manifest = FrozenRecord.from_dict({"schema": "frozen-train-reference-store-v1",
        "inventory_digest": custody.state["inventory_digest"], "split_digest": custody.state["split"]["digest"],
        "rows": manifest_rows, "scope": "train_only", "scientific_validity": "not_measured"})
    destination.mkdir(parents=True, exist_ok=False)
    for file_name, record in records:
        (destination / file_name).write_bytes(record.encoded.encode())
    (destination / "manifest.json").write_bytes(manifest.encoded.encode())
    return FrozenRecord.from_dict({"schema": "train-reference-publication-v1", "manifest_sha256": _hash(manifest.encoded.encode()),
        "inventory_digest": custody.state["inventory_digest"], "split_digest": custody.state["split"]["digest"],
        "task_handles": {row["identity_digest"]: row["task_handle"] for row in manifest_rows},
        "reference_count": len(records), "scope": "train_only", "scientific_validity": "not_measured"})


class FrozenTrainReferenceResolver:
    """Scorer-owned lookup that pins every file and rejects foreign identities."""
    def __init__(self, store_root: Path, *, manifest_sha256: str, inventory_digest: str, split_digest: str):
        self.root = _plain(store_root).resolve(strict=True)
        raw, _ = _read_bound(self.root / "manifest.json", {manifest_sha256})
        manifest = FrozenRecord(raw.decode()).data()
        if (set(manifest) != {"schema", "inventory_digest", "split_digest", "rows", "scope", "scientific_validity"}
                or manifest["schema"] != "frozen-train-reference-store-v1" or manifest["scope"] != "train_only"
                or manifest["scientific_validity"] != "not_measured" or manifest["inventory_digest"] != inventory_digest
                or manifest["split_digest"] != split_digest or not isinstance(manifest["rows"], list) or not manifest["rows"]):
            raise ContractError("frozen reference manifest scope or version mismatch")
        self._rows = {}
        for row in manifest["rows"]:
            identity = DataIdentity.parse(row["identity"])
            identity.require_train()
            if (identity.dataset_version != inventory_digest or identity.split_id != split_digest
                    or row["identity_digest"] != digest(identity.data()) or row["task_handle"] in self._rows
                    or row["file"] != row["task_handle"] + ".json"
                    or len(row["task_handle"]) != 64 or any(c not in "0123456789abcdef" for c in row["task_handle"])):
                raise ContractError("frozen reference manifest row binding mismatch")
            self._rows[row["task_handle"]] = row
        self._manifest_hash = manifest_sha256

    def __call__(self, task_handle: str, benchmark: str) -> FrozenRecord:
        row = self._rows.get(task_handle)
        if row is None or row["identity"]["benchmark"] != benchmark:
            raise ContractError("train reference handle is unavailable for this benchmark")
        _read_bound(self.root / "manifest.json", {self._manifest_hash})
        raw, _ = _read_bound(self.root / row["file"], {row["reference_sha256"]})
        reference = FrozenRecord(raw.decode())
        body = reference.data()
        if (body.get("identity_digest") != row["identity_digest"] or body.get("split") != "train"
                or body.get("benchmark") != benchmark or body.get("task_handle_digest") != _hash(task_handle.encode())
                or digest({"identity": row["identity"], "payload": body.get("task_context")}) != row["task_digest"]):
            raise ContractError("frozen reference file identity mismatch")
        return reference
