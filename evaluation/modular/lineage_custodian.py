"""Read-only, fixed-location lineage audit; no source payload export or leases."""
from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import importlib.metadata
import io
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

from evaluation.modular.canonical_lineage import (
    KINDS, SOURCES, Record, empty_references, match_records, normalize_reference, record_token, validate_graph,
)
from evaluation.modular.custody import InventoryItem, SCHEMA as CUSTODY_SCHEMA
from evaluation.modular.extended_ingestion import _inside, _receipt
from evaluation.modular.fresh_airs_custodian import CustodyError, _check, _write_new
from evaluation.modular.fresh_airs_hf_custodian import metadata_contract, safe_error, validate_public as validate_airs
from evaluation.modular.lineage_metadata_fields import CONTAINERS, REFERENCE_FIELDS, extract_metadata_references
from evaluation.modular.train_io import _public_file, _safe_under, _sha
from research_loop.modular.source_ingestion import SOURCE_SNAPSHOTS
from research_loop.ontology import digest

CONFIG_KEYS = {"schema", "snapshot_root", "custody_state", "extended_private_root", "extended_public_receipt",
               "extended_live_metadata", "airs_private_root", "airs_public_receipt", "source_license_metadata"}
SCHEMA = "canonical-lineage-custodian-receipt-v1"


def _csv(path):
    csv.field_size_limit(256 * 1024 * 1024)
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _jsonl(path):
    result = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise CustodyError()
                result.append(row)
    return result


def _binding():
    return {"source_pin_hashes": [], "metadata_container_hashes": [], "data_artifact_hashes": [],
            "metadata_file_count": 0, "data_artifact_file_count": 0,
            "records_missing_metadata_file": 0, "records_without_received_data_artifact": 0,
            "empty_data_artifact_file_count": 0, "source_pin_established": False,
            "source_license_metadata_hashes": [], "per_record_terms_qualification": "not_established"}


class Audit:
    def __init__(self):
        self.reads = {}
        self.bindings = {source: _binding() for source in SOURCES}

    def bind_read(self, path, kind):
        path = path.resolve(strict=True)
        sha = _sha(path)
        old = self.reads.get(path)
        if old is not None and old != (kind, sha):
            raise CustodyError()
        self.reads[path] = (kind, sha)
        return sha

    def metadata(self, source, path):
        sha = self.bind_read(path, "metadata_container")
        self.bindings[source]["metadata_container_hashes"].append(sha)
        self.bindings[source]["metadata_file_count"] += 1
        return sha

    def artifact(self, source, path, refs):
        sha = self.bind_read(path, "data_artifact")
        self.bindings[source]["data_artifact_hashes"].append(sha)
        self.bindings[source]["data_artifact_file_count"] += 1
        if path.stat().st_size:
            kind, token = normalize_reference(sha, "data_artifact_sha256")
            refs[kind].add(token)
        else:
            self.bindings[source]["empty_data_artifact_file_count"] += 1

    def finish(self):
        for path, (_kind, sha) in self.reads.items():
            if _sha(path) != sha:
                raise CustodyError()
        for value in self.bindings.values():
            for key in ("source_pin_hashes", "metadata_container_hashes", "data_artifact_hashes", "source_license_metadata_hashes"):
                value[key] = sorted(set(value[key]))
        return [{"locator_sha256": digest(str(path)), "content_sha256": sha,
                 "kind": kind} for path, (kind, sha) in sorted(self.reads.items(), key=lambda entry: str(entry[0]))]


def _merge_refs(refs, raw):
    selected, unresolved, license_declared = extract_metadata_references(raw)
    for kind in KINDS:
        refs[kind].update(selected[kind])
    return unresolved, license_declared


def _git_pin(root):
    # Only the fixed checkout's HEAD is queried; stderr and arbitrary text stay
    # private. A missing .git is a pin gap, not permission to guess a revision.
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, timeout=15)
    value = result.stdout.decode("ascii", errors="ignore").strip()
    return value if result.returncode == 0 and len(value) == 40 and all(c in "0123456789abcdef" for c in value) else None


def primary_records(config, audit):
    state_path = Path(config["custody_state"])
    audit.bind_read(state_path, "custody_state")
    state = json.loads(state_path.read_bytes())
    if state.get("schema") != CUSTODY_SCHEMA or digest(state["inventory"]) != state.get("inventory_digest"):
        raise CustodyError()
    inventory = [InventoryItem.parse(row) for row in state["inventory"]]
    root = Path(config["snapshot_root"])
    roots = {"discoverybench": root / "discovery/upstream/discoverybench",
             "blade": root / "scienceagent/work/BLADE/blade_bench/datasets"}
    pins = {"discoverybench": _git_pin(roots["discoverybench"]), "blade": _git_pin(roots["blade"].parent.parent)}
    for source in roots:
        pin = pins[source]
        audit.bindings[source]["source_pin_established"] = pin is not None
        if pin is not None:
            audit.bindings[source]["source_pin_hashes"] = [digest(pin)]
    result = []
    for item in inventory:
        source = item.benchmark
        if source not in roots:
            raise CustodyError()
        directory = _safe_under(roots[source], item.relative_path)
        allowed = set(item.content_hashes)
        refs, unresolved, license_declared = empty_references(), 0, False
        data_paths = set()
        if source == "discoverybench":
            metadata_paths = sorted(directory.glob("metadata_*.json"))
            for path in metadata_paths:
                _public_file(path, allowed)
                audit.metadata(source, path)
                metadata = json.loads(path.read_bytes())
                count, declared = _merge_refs(refs, metadata)
                unresolved += count
                license_declared |= declared
                datasets = metadata.get("datasets", [])
                if not isinstance(datasets, list):
                    raise CustodyError()
                for dataset in datasets:
                    if not isinstance(dataset, dict):
                        raise CustodyError()
                    name = dataset.get("name")
                    if not isinstance(name, str) or not name or Path(name).name != name or "/" in name or "\\" in name:
                        raise CustodyError()
                    path = directory / name
                    if path.suffix.lower() == ".csv" and path.is_file():
                        data_paths.add(_public_file(path, allowed))
        else:
            metadata_paths = [directory / "info.json"] if (directory / "info.json").is_file() else []
            for path in metadata_paths:
                _public_file(path, allowed)
                audit.metadata(source, path)
                count, declared = _merge_refs(refs, json.loads(path.read_bytes()))
                unresolved += count
                license_declared |= declared
            if (directory / "data.csv").is_file():
                data_paths.add(_public_file(directory / "data.csv", allowed))
        if not metadata_paths:
            audit.bindings[source]["records_missing_metadata_file"] += 1
        if not data_paths:
            audit.bindings[source]["records_without_received_data_artifact"] += 1
        for path in sorted(data_paths):
            audit.artifact(source, path, refs)
        pin = pins[source] or {"unresolved_pin_inventory_binding": state["inventory_digest"]}
        result.append(Record(source, record_token(source, pin, item.task_id),
                             {kind: frozenset(values) for kind, values in refs.items()},
                             digest({"source": source, "legacy_group": item.source_group}), unresolved, license_declared))
    return result, state["inventory_digest"]


def extended_records(config, audit):
    metadata_path, live_path = Path(config["extended_public_receipt"]), Path(config["extended_live_metadata"])
    audit.bind_read(metadata_path, "public_receipt")
    audit.bind_read(live_path, "public_receipt")
    public, live = json.loads(metadata_path.read_bytes()), json.loads(live_path.read_bytes())
    if public.get("schema") != "extended-custodian-metadata-receipt-v1" or live.get("schema") != "extended-source-inventory-metadata-v1":
        raise CustodyError()
    if public["live_inventory_binding"]["inventory_digest"] != live["inventory_digest"]:
        raise CustodyError()
    summary = {row["source"]: row for row in public["sources"]}
    result = []
    for source in ("scicode", "scienceagentbench"):
        spec = SOURCE_SNAPSHOTS[source]
        if summary[source]["revision"] != spec.revision or live["source_pins"][source] != spec.revision:
            raise CustodyError()
        snapshot = Path(config["extended_private_root"]) / "snapshots" / source / spec.revision
        receipt = _receipt(snapshot, source)
        audit.bind_read(snapshot / "snapshot-receipt.json", "public_receipt")
        for artifact in receipt["artifacts"]:
            # Container byte hashes are retained as integrity evidence; they do
            # not imply all rows share one scientific data artifact.
            audit.metadata(source, _inside(snapshot, artifact["source_path"]))
        rows = []
        if source == "scicode":
            for name in ("problems_dev.jsonl", "problems_test.jsonl"):
                rows.extend(_jsonl(_inside(snapshot, name)))
        else:
            rows = _csv(_inside(snapshot, "ScienceAgentBench.csv"))
        if len(rows) != summary[source]["record_count"]:
            raise CustodyError()
        audit.bindings[source]["source_pin_established"] = True
        audit.bindings[source]["source_pin_hashes"] = [digest(spec.revision)]
        audit.bindings[source]["records_without_received_data_artifact"] = len(rows)
        for index, row in enumerate(rows):
            refs, unresolved, declared = extract_metadata_references(row)
            # A full main problem (including its dependent substeps) is atomic.
            result.append(Record(source, record_token(source, spec.revision, index), refs, None, unresolved, declared))
    return result


def airs_records(config, audit):
    root = Path(config["airs_private_root"])
    public_path = Path(config["airs_public_receipt"])
    public_sha = audit.bind_read(public_path, "public_receipt")
    receipt = validate_airs(json.loads(public_path.read_bytes()))
    if _sha(root / "receipt.json") != public_sha:
        raise CustodyError()
    audit.bind_read(root / "receipt.json", "public_receipt")
    metadata_path = root / "metadata.bin"
    if audit.bind_read(metadata_path, "public_receipt") != receipt["metadata_sha256"]:
        raise CustodyError()
    revision, license_sha, _recognized, artifacts = metadata_contract(metadata_path)
    if revision != receipt["revision"] or len(artifacts) != receipt["payload_artifact_count"]:
        raise CustodyError()
    rows = []
    for index, artifact in enumerate(artifacts):
        if artifact["suffix"] != ".csv":
            raise CustodyError()
        path = root / f"payload-{index:04d}.bin"
        sha = audit.metadata("airsbench", path)
        if sha != receipt["payload_artifact_sha256"][index] or path.stat().st_size != artifact["size"]:
            raise CustodyError()
        rows.extend(_csv(path))
    if len(rows) != receipt["task_count"]:
        raise CustodyError()
    audit.bindings["airsbench"]["source_pin_established"] = True
    audit.bindings["airsbench"]["source_pin_hashes"] = [digest(revision)]
    audit.bindings["airsbench"]["source_license_metadata_hashes"] = [license_sha]
    audit.bindings["airsbench"]["records_without_received_data_artifact"] = len(rows)
    result = []
    for index, row in enumerate(rows):
        refs, unresolved, declared = extract_metadata_references(row)
        result.append(Record("airsbench", record_token("airsbench", revision, index), refs, None, unresolved, declared))
    return result


def source_license_bindings(config, audit):
    path = Path(config["source_license_metadata"])
    audit.bind_read(path, "public_receipt")
    value = json.loads(path.read_bytes())
    if value.get("schema") != "received-dataset-public-metadata-v1":
        raise CustodyError()
    for source in ("scicode", "scienceagentbench"):
        row = value["sources"][source]
        if row["received_snapshot_revision"] != SOURCE_SNAPSHOTS[source].revision:
            raise CustodyError()
        audit.bindings[source]["source_license_metadata_hashes"] = [digest(row["dataset_card_license_declaration"])]


def validate_receipt(value):
    copy = dict(value)
    validate_graph(copy.pop("graph"))
    bindings = copy["source_bindings"]
    for source in SOURCES:
        if type(bindings[source]["source_pin_established"]) is not bool:
            raise CustodyError()
    check = {**copy, "source_bindings": {source: {**bindings[source], "source_pin_established": False} for source in SOURCES}}
    bind_spec = {"source_pin_hashes": ["sha"], "metadata_container_hashes": ["sha"], "data_artifact_hashes": ["sha"],
                 "metadata_file_count": "count", "data_artifact_file_count": "count", "records_missing_metadata_file": "count",
                 "records_without_received_data_artifact": "count", "empty_data_artifact_file_count": "count",
                 "source_pin_established": False, "source_license_metadata_hashes": ["sha"], "per_record_terms_qualification": "not_established"}
    spec = {"schema": SCHEMA, "inventory_digest": "sha", "config_sha256": "sha", "field_rules_sha256": "sha",
            "implementation_sha256": ["sha"], "runtime_metadata_sha256": "sha", "read_manifest_sha256": "sha",
            "read_file_count": "count", "read_files_unchanged": True, "source_bindings": {source: bind_spec for source in SOURCES},
            "raw_private_payload_returned": False, "current_process_payload_exported": False,
            "historical_exposure_status": "unknown_not_changed", "os_access_isolation_verified": False,
            "old_split_mutated": False, "validation_lease_issued": False}
    _check(check, spec)
    return value


def run(*, config_path, private_audit, output):
    config_path, private_audit, output = Path(config_path), Path(private_audit).resolve(), Path(output).resolve()
    if private_audit.exists() or output.exists() or output.is_relative_to(private_audit):
        raise CustodyError()
    config = json.loads(config_path.read_bytes())
    if set(config) != CONFIG_KEYS or config["schema"] != "canonical-lineage-input-locations-v1":
        raise CustodyError()
    for key in ("snapshot_root", "extended_private_root", "airs_private_root"):
        if output.is_relative_to(Path(config[key]).resolve()) or private_audit.is_relative_to(Path(config[key]).resolve()):
            raise CustodyError()
    private_audit.mkdir(parents=True)
    source_paths = [Path(__file__), Path(__file__).with_name("canonical_lineage.py"), Path(__file__).with_name("lineage_metadata_fields.py")]
    runtime = {"python_executable": sys.executable, "python_version": platform.python_version(),
               "pyyaml_version": importlib.metadata.version("PyYAML"),
               "pyyaml_location": str(importlib.metadata.distribution("PyYAML").locate_file(""))}
    _write_new(private_audit / "intent.json", {"schema": SCHEMA, "config_sha256": _sha(config_path),
                                              "implementation_sha256": [_sha(path) for path in source_paths],
                                              "runtime_metadata_sha256": digest(runtime)})
    _write_new(private_audit / "runtime.json", runtime)
    audit, stage = Audit(), "primary"
    try:
        primary, inventory_digest = primary_records(config, audit)
        stage = "extended"
        extended = extended_records(config, audit)
        stage = "airs"
        airs = airs_records(config, audit)
        stage = "license"
        source_license_bindings(config, audit)
        stage = "match"
        graph = match_records(primary + extended + airs)
        manifest = audit.finish()
        value = {"schema": SCHEMA, "inventory_digest": inventory_digest, "config_sha256": _sha(config_path),
                 "field_rules_sha256": digest({"fields": REFERENCE_FIELDS, "containers": CONTAINERS}),
                 "implementation_sha256": [_sha(path) for path in source_paths], "runtime_metadata_sha256": digest(runtime),
                 "read_manifest_sha256": digest(manifest), "read_file_count": len(manifest), "read_files_unchanged": True,
                 "source_bindings": audit.bindings, "graph": graph,
                 "raw_private_payload_returned": False, "current_process_payload_exported": False,
                 "historical_exposure_status": "unknown_not_changed", "os_access_isolation_verified": False,
                 "old_split_mutated": False, "validation_lease_issued": False}
        stage = "output"
        validate_receipt(value)
        _write_new(private_audit / "read-manifest.json", manifest)
        _write_new(private_audit / "receipt.json", value)
        _write_new(output, value)
        return value
    except BaseException as error:
        failure = {"schema": SCHEMA, "status": "failed", "stage": stage, **safe_error(error)}
        _write_new(private_audit / "failure.json", failure)
        _write_new(output.with_suffix(".failure.json"), failure)
        raise CustodyError() from None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Metadata-only canonical lineage custody audit")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--private-audit", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            run(config_path=args.config, private_audit=args.private_audit, output=args.output)
        print(json.dumps({"schema": SCHEMA, "status": "completed", "receipt_sha256": _sha(args.output)}, sort_keys=True))
        return 0
    except BaseException:
        print(json.dumps({"schema": SCHEMA, "status": "failed_details_suppressed"}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
