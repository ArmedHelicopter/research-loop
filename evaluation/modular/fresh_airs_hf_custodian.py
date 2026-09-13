"""Controlled alternate official AIRS release; fixed output, no source diagnostics."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from evaluation.modular.fresh_airs_custodian import (
    CustodyError, _check, _metadata_factors, _opaque, _read_baseline,
    _shape, _write_new, SHA,
)
from research_loop.ontology import canonical, digest

API_URL = "https://huggingface.co/api/datasets/facebook/airs-bench?blobs=true"
REPO = "facebook/airs-bench"
SCHEMA = "fresh-airs-hf-acquisition-v1"
PIN = re.compile(r"[0-9a-f]{40}\Z")
MAX_BYTES = 256 * 1024 * 1024
SPEC = {
    "schema": SCHEMA, "source": "airsbench", "official_repository": REPO,
    "source_pin_sha256": "sha", "metadata_sha256": "sha",
    "license_metadata_sha256": "sha", "repository_license_recognized_cc_by_nc_4_0": False,
    "payload_artifact_count": "count", "payload_total_bytes": "count",
    "payload_artifact_sha256": ["sha"], "task_count": "count",
    "metadata_shape_digest": "sha", "metadata_factor_count": "count",
    "metadata_components": [{"token": "token", "member_count": "count"}],
    "opaque_family_fingerprints": ["token"], "opaque_artifact_fingerprints": ["token"],
    "baseline_sha256": "sha", "baseline_family_count": "count",
    "baseline_comparable_family_count": "count", "baseline_artifact_count": "count",
    "baseline_publication_count": "count", "family_overlap_count": "count", "artifact_overlap_count": "count",
    "family_comparison_status": "exact_equalities_only_schema_domain_coverage_incomplete",
    "publication_overlap_status": "unknown_no_comparable_publication_mapping",
    "primary_benchmark_lineage_baseline_status": "unavailable",
    "lineage_status": "metadata_components_not_independence_proof",
    "upstream_dataset_payload_status": "not_acquired",
    "upstream_dataset_license_status": "unknown_requires_per_dataset_review",
    "runtime_adapter_status": "not_implemented_not_executed",
    "historical_exposure_status": "unknown", "current_process_payload_exported": False,
    "os_access_isolation_verified": False, "validation_eligible_count": 0,
    "split_created": False, "validation_lease_issued": False, "existing_custody_mutated": False,
    "fetch_event_count": "count", "fetch_event_chain_sha256": "sha",
}


def validate_public(value):
    if type(value) is not dict:
        raise CustodyError()
    base = dict(value)
    pin = base.pop("revision", None)
    if type(pin) is not str or not PIN.fullmatch(pin):
        raise CustodyError()
    recognized = base.get("repository_license_recognized_cc_by_nc_4_0")
    if type(recognized) is not bool:
        raise CustodyError()
    base["repository_license_recognized_cc_by_nc_4_0"] = False
    _check(base, SPEC)
    if digest(pin) != value["source_pin_sha256"]:
        raise CustodyError()
    if sum(x["member_count"] for x in value["metadata_components"]) != value["task_count"]:
        raise CustodyError()
    return value


def safe_error(error):
    # No exception type names, messages, URLs, headers or parser text escape.
    status = None
    if isinstance(error, urllib.error.HTTPError):
        kind, status = "http", int(error.code)
    elif isinstance(error, (TimeoutError, socket.timeout)):
        kind = "timeout"
    elif isinstance(error, ssl.SSLError):
        kind = "tls"
    elif isinstance(error, urllib.error.URLError):
        reason = error.reason
        kind = "tls" if isinstance(reason, ssl.SSLError) else "timeout" if isinstance(reason, (TimeoutError, socket.timeout)) else "network"
    elif isinstance(error, CustodyError):
        kind = "contract"
    elif isinstance(error, OSError):
        kind = "io"
    else:
        kind = "other"
    if status is not None and not 100 <= status <= 599:
        status = None
    return {"category": kind, "http_status": status, "timeout": kind == "timeout", "tls": kind == "tls"}


class OfficialTransport:
    def iter_bytes(self, url):
        if url != API_URL and not url.startswith("https://huggingface.co/datasets/facebook/airs-bench/resolve/"):
            raise CustodyError()
        req = urllib.request.Request(url, headers={"User-Agent": "research-loop-custodian"})
        with urllib.request.urlopen(req, timeout=45) as response:
            while block := response.read(65536):
                yield block


class Events:
    def __init__(self, root):
        self.root, self.count, self.previous, self.revision = root, 0, "0" * 64, None

    def add(self, event, **fields):
        self.count += 1
        path = self.root / f"event-{self.count:04d}.json"
        _write_new(path, {"event": event, "source": REPO, "revision": self.revision,
                          "utc": datetime.now(timezone.utc).isoformat(),
                          "previous_sha256": self.previous, **fields})
        self.previous = hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(root, events, kind, url, transport):
    events.add("fetch_started", artifact_kind=kind, url_sha256=digest(url))
    path, sha, size = root / f"{kind}.bin", hashlib.sha256(), 0
    with path.open("xb") as stream:
        for block in transport.iter_bytes(url):
            if type(block) is not bytes or not block:
                raise CustodyError()
            size += len(block)
            if size > MAX_BYTES:
                raise CustodyError()
            stream.write(block)
            sha.update(block)
        stream.flush()
        os.fsync(stream.fileno())
    events.add("fetch_completed", artifact_kind=kind, sha256=sha.hexdigest(), bytes=size)
    return path, sha.hexdigest(), size


def metadata_contract(path):
    value = json.loads(path.read_bytes())
    revision = value.get("sha")
    if value.get("id") != REPO or type(revision) is not str or not PIN.fullmatch(revision):
        raise CustodyError()
    license_value = value.get("cardData", {}).get("license")
    recognized = license_value == "cc-by-nc-4.0"
    artifacts = []
    for entry in value["siblings"]:
        name = entry["rfilename"]
        parts = PurePosixPath(name)
        if parts.is_absolute() or ".." in parts.parts or "\\" in name or ":" in name:
            raise CustodyError()
        if parts.suffix not in {".parquet", ".jsonl", ".json", ".csv"}:
            continue
        size = entry.get("size")
        blob = entry.get("blobId")
        lfs = entry.get("lfs")
        if type(size) is not int or not 0 < size <= MAX_BYTES:
            raise CustodyError()
        if lfs is not None:
            hash_value = lfs.get("sha256")
            if type(hash_value) is not str or not SHA.fullmatch(hash_value):
                raise CustodyError()
            hash_kind = "sha256"
        elif type(blob) is str and PIN.fullmatch(blob):
            hash_value, hash_kind = blob, "git"
        else:
            raise CustodyError()
        url = f"https://huggingface.co/datasets/{REPO}/resolve/{revision}/{urllib.parse.quote(name, safe='/')}?download=true"
        artifacts.append({"url": url, "suffix": parts.suffix, "size": size, "hash": hash_value, "kind": hash_kind})
    if not artifacts or len(artifacts) > 50 or sum(x["size"] for x in artifacts) > MAX_BYTES:
        raise CustodyError()
    return revision, digest(license_value), recognized, artifacts


def read_rows(path, suffix):
    if suffix == ".parquet":
        import pyarrow.parquet as pq
        rows = pq.read_table(path).to_pylist()
    elif suffix == ".jsonl":
        rows = [json.loads(line) for line in path.read_bytes().splitlines() if line.strip()]
    elif suffix == ".json":
        rows = json.loads(path.read_bytes())
        if isinstance(rows, dict):
            rows = rows.get("data", rows.get("tasks", rows.get("records")))
    else:
        import csv
        with path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
        raise CustodyError()
    return rows


def factors_from_row(row):
    result = _metadata_factors(row)
    # Task definitions can embed metadata.yaml in a mapping of file contents.
    # The dynamic file names stay private; no schema keys are exported.
    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if isinstance(key, str) and key.split("/")[-1] == "metadata.yaml" and isinstance(child, str):
                    import yaml
                    result.update(_metadata_factors(yaml.safe_load(child)))
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(row)
    return result


def metadata_probe(*, private_store, output, transport=None):
    root, output = Path(private_store).resolve(), Path(output).resolve()
    if root.exists() or output.exists() or output.is_relative_to(root) or root.is_relative_to(output.parent):
        raise CustodyError()
    root.mkdir(parents=True)
    events = Events(root)
    events.add("metadata_only_acquisition_intent")
    try:
        path, sha, _ = fetch(root, events, "metadata", API_URL, transport or OfficialTransport())
        revision, license_sha, recognized, artifacts = metadata_contract(path)
        events.revision = revision
        events.add("fixed_revision_bound_no_payload_fetched", metadata_sha256=sha)
        value = {"schema": "fresh-airs-hf-metadata-v1", "source": REPO, "revision": revision,
                 "metadata_sha256": sha, "license_metadata_sha256": license_sha,
                 "license_recognized_cc_by_nc_4_0": recognized,
                 "payload_contract_sha256": digest(artifacts),
                 "payload_artifact_count": len(artifacts), "payload_total_bytes": sum(x["size"] for x in artifacts),
                 "parquet_artifacts": sum(x["suffix"] == ".parquet" for x in artifacts),
                 "json_artifacts": sum(x["suffix"] in (".json", ".jsonl") for x in artifacts),
                 "csv_artifacts": sum(x["suffix"] == ".csv" for x in artifacts),
                 "task_payload_fetched": False, "raw_private_payload_returned": False,
                 "fetch_event_chain_sha256": events.previous}
        spec = {"schema": "fresh-airs-hf-metadata-v1", "source": REPO,
                "metadata_sha256": "sha", "license_metadata_sha256": "sha", "license_recognized_cc_by_nc_4_0": False,
                "payload_contract_sha256": "sha", "payload_artifact_count": "count", "payload_total_bytes": "count",
                "parquet_artifacts": "count", "json_artifacts": "count", "csv_artifacts": "count",
                "task_payload_fetched": False, "raw_private_payload_returned": False, "fetch_event_chain_sha256": "sha"}
        check = dict(value)
        check.pop("revision")
        if not PIN.fullmatch(revision) or type(recognized) is not bool:
            raise CustodyError()
        check["license_recognized_cc_by_nc_4_0"] = False
        _check(check, spec)
        _write_new(output, value)
        return value
    except BaseException as error:
        failure = {"schema": SCHEMA, "status": "failed", "stage": "metadata", **safe_error(error)}
        events.add("acquisition_failed", **failure)
        _write_new(output.with_suffix(".failure.json"), failure)
        raise CustodyError() from None


def acquire(*, private_store, output, overlap_baseline, transport=None, expected_revision=None, expected_contract=None):
    root, output = Path(private_store).resolve(), Path(output).resolve()
    if root.exists() or output.exists() or output.is_relative_to(root) or root.is_relative_to(output.parent):
        raise CustodyError()
    baseline, baseline_sha = _read_baseline(Path(overlap_baseline))
    root.mkdir(parents=True)
    events, stage = Events(root), "metadata"
    events.add("acquisition_intent", baseline_sha256=baseline_sha, public_schema_sha256=digest(SPEC))
    try:
        metadata, metadata_sha, _ = fetch(root, events, "metadata", API_URL, transport or OfficialTransport())
        revision, license_sha, recognized, artifacts = metadata_contract(metadata)
        if expected_revision is not None and revision != expected_revision:
            raise CustodyError()
        if expected_contract is not None and digest(artifacts) != expected_contract:
            raise CustodyError()
        events.revision = revision
        events.add("fixed_revision_bound_before_payload_fetch", metadata_sha256=metadata_sha)
        stage, rows, hashes, total = "payload", [], [], 0
        for index, item in enumerate(artifacts):
            path, sha, size = fetch(root, events, f"payload-{index:04d}", item["url"], transport or OfficialTransport())
            if size != item["size"]:
                raise CustodyError()
            actual = sha if item["kind"] == "sha256" else hashlib.sha1(f"blob {size}\0".encode() + path.read_bytes()).hexdigest()
            if actual != item["hash"]:
                raise CustodyError()
            stage = "parse"
            rows.extend(read_rows(path, item["suffix"]))
            hashes.append(sha)
            total += size
            stage = "payload"
        stage = "parse"
        factors = [factors_from_row(row) for row in rows]
        parent, first = list(range(len(rows))), {}
        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        for i, group in enumerate(factors):
            for factor in group:
                parent[find(i)] = find(first.setdefault(factor, i))
        groups = {}
        for i in range(len(rows)):
            groups.setdefault(find(i), []).append(i)
        family = sorted(set().union(*factors))
        artifact_factors = sorted({_opaque("artifact-fingerprint", {"sha256": sha}) for sha in hashes})
        events.add("private_inspection_completed")
        value = {key: spec for key, spec in SPEC.items() if not isinstance(spec, (dict, list)) and spec not in ("sha", "count", "token")}
        value.update(revision=revision, source_pin_sha256=digest(revision), metadata_sha256=metadata_sha,
                     license_metadata_sha256=license_sha, repository_license_recognized_cc_by_nc_4_0=recognized,
                     payload_artifact_count=len(hashes), payload_total_bytes=total, payload_artifact_sha256=hashes,
                     task_count=len(rows), metadata_shape_digest=digest([_shape(row) for row in rows]),
                     metadata_factor_count=len(family), opaque_family_fingerprints=family,
                     opaque_artifact_fingerprints=artifact_factors,
                     metadata_components=[{"token": _opaque("family", {"revision": revision, "members": members}), "member_count": len(members)} for members in groups.values()],
                     baseline_sha256=baseline_sha, baseline_family_count=len(baseline["family_fingerprints"]),
                     baseline_comparable_family_count=sum(x.startswith(("opaque-family-fingerprint-v1-", "opaque-factor-v1-")) for x in baseline["family_fingerprints"]),
                     baseline_artifact_count=len(baseline["artifact_fingerprints"]), baseline_publication_count=len(baseline["publication_fingerprints"]),
                     family_overlap_count=len(set(family) & set(baseline["family_fingerprints"])),
                     artifact_overlap_count=len(set(artifact_factors) & set(baseline["artifact_fingerprints"])),
                     fetch_event_count=events.count, fetch_event_chain_sha256=events.previous)
        stage = "output"
        validate_public(value)
        _write_new(root / "receipt.json", value)
        _write_new(output, value)
        return value
    except BaseException as error:
        failure = {"schema": SCHEMA, "status": "failed", "stage": stage, **safe_error(error)}
        events.add("acquisition_failed", **failure)
        _write_new(output.with_suffix(".failure.json"), failure)
        raise CustodyError() from None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Official AIRS HF controlled custody")
    parser.add_argument("--private-store", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--overlap-baseline", required=True, type=Path)
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--expected-revision")
    parser.add_argument("--expected-contract")
    args = parser.parse_args(argv)
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            if args.metadata_only:
                value = metadata_probe(private_store=args.private_store, output=args.output)
            else:
                if args.expected_revision is None or args.expected_contract is None:
                    raise CustodyError()
                value = acquire(private_store=args.private_store, output=args.output, overlap_baseline=args.overlap_baseline,
                                expected_revision=args.expected_revision, expected_contract=args.expected_contract)
                validate_public(value)
        print(canonical({"schema": SCHEMA, "status": "acquired", "receipt_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest()}))
        return 0
    except BaseException:
        print(canonical({"schema": SCHEMA, "status": "failed_details_suppressed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
