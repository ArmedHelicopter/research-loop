"""Restricted metadata extraction for already-received extended snapshots.

The command is deliberately a custody-side process.  It may parse private rows
to derive opaque connectivity tokens, but writes only counts, fixed artifact
hashes, schema digests, and opaque group tokens.  It neither projects tasks nor
changes a custody state, exposure flag, or split.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from evaluation.modular.extended_ingestion import _inside, _json_lines, _receipt
from research_loop.modular.source_ingestion import SOURCE_SNAPSHOTS
from research_loop.ontology import ContractError, canonical, digest


_SCHEMA = "extended-custodian-metadata-receipt-v1"
_SOURCES = ("scicode", "scienceagentbench")


def _opaque(kind: str, value: object) -> str:
    return f"opaque-{kind}-v1-{digest(value)}"


def _sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


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


@dataclass(frozen=True)
class _Record:
    token: str
    artifact: str
    schema_descriptor: tuple[tuple[str, str], ...]
    substep_count: int
    factors: tuple[tuple[str, str], ...]


def _schema_descriptor(value: object, path: str = "$") -> tuple[tuple[str, str], ...]:
    """Return type/key shape only; primitive values never cross the boundary."""
    if isinstance(value, Mapping):
        result = [(path, "object")]
        for key in sorted(value):
            if not isinstance(key, str):
                raise ContractError("private record schema key must be a string")
            result.extend(_schema_descriptor(value[key], f"{path}.{key}"))
        return tuple(result)
    if isinstance(value, list):
        result = [(path, "array")]
        for item in value:
            result.extend(_schema_descriptor(item, f"{path}[]"))
        return tuple(sorted(set(result)))
    return ((path, type(value).__name__),)


def _scicode_records(snapshot: Path) -> list[_Record]:
    result: list[_Record] = []
    seen_problem_tokens: set[str] = set()
    for filename in ("problems_dev.jsonl", "problems_test.jsonl"):
        for _number, raw, row in _json_lines(_inside(snapshot, filename)):
            problem = row.get("problem_id")
            steps = row.get("sub_steps")
            if not isinstance(problem, str) or not problem or not isinstance(steps, list) or not steps:
                raise ContractError("SciCode private schema lacks an atomic main-problem/substep record")
            # A raw record is one indivisible main problem and all dependent
            # substeps.  The record token is opaque, while a duplicate source
            # identifier is rejected inside custody rather than exported.
            problem_token = _opaque("scicode-problem", problem)
            if problem_token in seen_problem_tokens:
                raise ContractError("SciCode private snapshot has duplicate main-problem identity")
            seen_problem_tokens.add(problem_token)
            result.append(_Record(_opaque("record", {"source": "scicode", "sha256": hashlib.sha256(raw).hexdigest()}),
                                  filename, _schema_descriptor(row), len(steps),
                                  (("received_artifact", _opaque("factor", {"artifact": filename})),)))
    return result


def _scienceagentbench_records(snapshot: Path) -> list[_Record]:
    path = _inside(snapshot, "ScienceAgentBench.csv")
    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
    except (OSError, csv.Error) as exc:
        raise ContractError("invalid ScienceAgentBench private CSV") from exc
    if not rows or any(not isinstance(row, Mapping) for row in rows):
        raise ContractError("ScienceAgentBench private CSV has no records")
    result = []
    for row in rows:
        factors = []
        for field in ("github_name", "src_file_or_path", "dataset_folder_tree"):
            value = row.get(field)
            if isinstance(value, str) and value.strip().lower() not in {"", "n/a", "na", "none", "null", "-"}:
                # Exact metadata equality is sufficient to form a conservative
                # edge; the unhashed repository/path/tree value never leaves
                # this custody process.
                factors.append((field, _opaque("factor", {"field": field, "value": value.strip()})))
        result.append(_Record(_opaque("record", {"source": "scienceagentbench", "row": digest(row)}),
                              "ScienceAgentBench.csv", _schema_descriptor(row), 0, tuple(factors)))
    return result


def _source_summary(source: str, private_store: Path) -> dict[str, Any]:
    spec = SOURCE_SNAPSHOTS[source]
    snapshot = private_store / "snapshots" / source / spec.revision
    receipt = _receipt(snapshot, source)
    records = _scicode_records(snapshot) if source == "scicode" else _scienceagentbench_records(snapshot)
    if not records:
        raise ContractError("private source produced no metadata records")

    # Link only actual received-artifact and row-level provenance metadata.
    # The source release scopes this receipt, but does not by itself establish
    # that every task shares a scientific data family.  This rejects a split by
    # bare problem number while avoiding a fabricated all-release lineage.
    union = _UnionFind(record.token for record in records)
    first_by_factor: dict[tuple[str, str], str] = {}
    for record in records:
        for factor in record.factors:
            existing = first_by_factor.setdefault(factor, record.token)
            union.join(existing, record.token)
    components: dict[str, list[_Record]] = {}
    for record in records:
        components.setdefault(union.find(record.token), []).append(record)
    schema_digest = digest(sorted({entry for record in records for entry in record.schema_descriptor}))
    artifacts = [{"source_path": item["source_path"], "size_bytes": item["size_bytes"],
                  "local_sha256": item["local_sha256"]} for item in receipt["artifacts"]]
    return {
        "source": source,
        "repository": spec.repository,
        "revision": spec.revision,
        "received_artifacts": artifacts,
        "record_count": len(records),
        "schema_descriptor_digest": schema_digest,
        "dependent_substep_count": sum(record.substep_count for record in records),
        "components": [{
            "group_token": _opaque("source-family", {"source": source, "revision": spec.revision,
                                                        "members": sorted(record.token for record in members)}),
            "member_count": len(members),
            "constraint_kinds": sorted({"atomic_dependent_substeps" if record.substep_count else ""
                                        for record in members} | {kind for record in members for kind, _token in record.factors} - {""}),
        } for _root, members in sorted(components.items())],
        "family_evidence_status": ("received_artifact_and_atomic_substeps_closure_no_cross_record_provenance"
                                   if source == "scicode" else
                                   "exact_dataset_tree_repository_and_source_path_closure_no_publication_lineage"),
        "split_eligibility": "not_eligible_without_independent_family_partition_and_exposure_attestation",
    }


def extract_extended_custody_metadata(*, private_store: Path, live_metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Derive a non-content receipt without mutating the private source store."""
    if not isinstance(live_metadata, Mapping) or live_metadata.get("schema") != "extended-source-inventory-metadata-v1":
        raise ContractError("live extended inventory metadata is required")
    expected_pins = {source: SOURCE_SNAPSHOTS[source].revision for source in _SOURCES}
    if live_metadata.get("source_pins") != expected_pins:
        raise ContractError("live metadata does not bind the received snapshots")
    if live_metadata.get("split_assigned") is not False or live_metadata.get("exposure_counts") != {"unknown": 182}:
        raise ContractError("metadata extraction requires the unchanged unsplit unknown-exposure inventory")
    summaries = [_source_summary(source, private_store) for source in _SOURCES]
    if {row["source"] for row in summaries} != set(_SOURCES):
        raise ContractError("custodian receipt source coverage drift")
    return {
        "schema": _SCHEMA,
        "live_inventory_binding": {"inventory_digest": live_metadata["inventory_digest"],
                                   "custody_state_sha256": live_metadata["custody_state_sha256"],
                                   "source_pins": expected_pins},
        "read_scope": "private_schema_provenance_paths_and_content_hashes_only",
        "raw_private_payload_returned": False,
        "optimizer_access": "none",
        "mutated_private_store": False,
        "mutated_custody_state": False,
        "sources": summaries,
        "decision": "source_family_closure_recorded_exposure_remains_unknown",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit an opaque, metadata-only extended-source custody receipt.")
    parser.add_argument("--private-store", required=True, type=Path)
    parser.add_argument("--live-metadata", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    private = args.private_store.resolve()
    output = args.output.resolve()
    if output.is_relative_to(private) or output.exists():
        raise ContractError("custodian receipt output must be a new file outside private storage")
    try:
        live = json.loads(args.live_metadata.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ContractError("invalid live metadata input") from exc
    receipt = extract_extended_custody_metadata(private_store=private, live_metadata=live)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(canonical(receipt) + "\n", encoding="utf-8", newline="\n")
    print(canonical({"schema": _SCHEMA, "receipt_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                     "raw_private_payload_returned": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
