"""Fail-closed AIRS first acquisition; never execute or print upstream contents.

Only this process reads the newly fetched private archive.  A strict recursive
allowlist validates every public receipt before its first write.  Exceptions,
archive paths, metadata keys, and YAML diagnostics cannot leave through the CLI.
This is an output boundary, not authenticated OS isolation or historical purity.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from research_loop.ontology import canonical, digest

REVISION = "72a629ce14309ed5bcfb42ebbc944028dd4b9542"
REPOSITORY = "facebookresearch/airs-bench"
TREE_URL = f"https://api.github.com/repos/{REPOSITORY}/git/trees/{REVISION}?recursive=1"
ARCHIVE_URL = f"https://codeload.github.com/{REPOSITORY}/zip/{REVISION}"
SCHEMA = "fresh-airs-controlled-acquisition-v1"
LIMIT = 64 * 1024 * 1024
SHA = re.compile(r"[0-9a-f]{64}\Z")
TOKEN = re.compile(r"opaque-(?:family|factor|family-fingerprint|artifact-fingerprint|publication)-v1-[0-9a-f]{64}\Z")
BASELINE_TOKEN = re.compile(r"opaque-(?:source-family|family|factor|family-fingerprint|artifact-fingerprint|publication)-v1-[0-9a-f]{64}\Z")


class CustodyError(Exception):
    """Only a fixed error code may be emitted by the CLI."""


def _opaque(kind, value):
    return f"opaque-{kind}-v1-{digest(value)}"


def _check(value, spec):
    # No arbitrary object, string, mapping key, exception text, or type name is
    # accepted. Error messages deliberately do not identify rejected fields.
    if isinstance(spec, dict):
        if type(value) is not dict or set(value) != set(spec):
            raise CustodyError()
        for key, child in spec.items():
            _check(value[key], child)
    elif isinstance(spec, list):
        if type(value) is not list:
            raise CustodyError()
        for item in value:
            _check(item, spec[0])
    elif spec == "count":
        if type(value) is not int or not 0 <= value <= 10**9:
            raise CustodyError()
    elif spec == "sha":
        if type(value) is not str or not SHA.fullmatch(value):
            raise CustodyError()
    elif spec == "token":
        if type(value) is not str or not TOKEN.fullmatch(value):
            raise CustodyError()
    elif type(value) is not type(spec) or value != spec:
        raise CustodyError()


PUBLIC_SPEC = {
    "schema": SCHEMA, "source": "airsbench", "repository": REPOSITORY,
    "revision": REVISION, "acquisition_scope": "official_repository_task_definitions",
    "tree_sha256": "sha", "archive_sha256": "sha", "license_sha256": "sha",
    "fetch_event_chain_sha256": "sha", "fetch_event_count": "count",
    "archive_blob_count_verified": "count", "task_count": "count",
    "task_bundle_complete_count": "count", "task_blob_count": "count",
    "task_content_sha256": ["sha"], "metadata_shape_digest": "sha",
    "metadata_components": [{"token": "token", "member_count": "count"}],
    "opaque_family_fingerprints": ["token"],
    "opaque_artifact_fingerprints": ["token"],
    "baseline_sha256": "sha", "baseline_family_count": "count",
    "baseline_artifact_count": "count", "baseline_publication_count": "count",
    "baseline_comparable_family_count": "count",
    "family_comparison_status": "exact_equalities_only_schema_domain_coverage_incomplete",
    "primary_benchmark_lineage_baseline_status": "unavailable",
    "family_overlap_count": "count", "artifact_overlap_count": "count",
    "publication_overlap_status": "unknown_no_comparable_publication_mapping",
    "lineage_status": "metadata_components_not_independence_proof",
    "upstream_dataset_payload_status": "not_acquired",
    "upstream_dataset_license_status": "unknown_requires_per_dataset_review",
    "repository_license_status": "source_declared_cc_by_nc_4_0",
    "runtime_adapter_status": "not_implemented_not_executed",
    "historical_exposure_status": "unknown",
    "current_process_payload_exported": False,
    "os_access_isolation_verified": False,
    "validation_eligible_count": 0, "split_created": False,
    "validation_lease_issued": False, "existing_custody_mutated": False,
}


def validate_public(value):
    _check(value, PUBLIC_SPEC)
    if sum(x["member_count"] for x in value["metadata_components"]) != value["task_count"]:
        raise CustodyError()
    return value


def _write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


class OfficialTransport:
    def iter_bytes(self, url):
        if url not in (TREE_URL, ARCHIVE_URL):
            raise CustodyError()
        request = urllib.request.Request(url, headers={"User-Agent": "research-loop-custodian"})
        with urllib.request.urlopen(request, timeout=45) as response:
            while block := response.read(65536):
                yield block


class _Events:
    def __init__(self, root):
        self.root, self.previous, self.count = root, "0" * 64, 0

    def add(self, event, **fields):
        value = {"event": event, "revision": REVISION,
                 "utc": datetime.now(timezone.utc).isoformat(),
                 "previous_sha256": self.previous, **fields}
        self.count += 1
        path = self.root / f"event-{self.count:04d}.json"
        _write_new(path, value)
        self.previous = hashlib.sha256(path.read_bytes()).hexdigest()


def _fetch(root, events, kind, url, transport):
    events.add("fetch_started", kind=kind, official_url=url)
    path = root / f"{kind}.bin"
    sha, size = hashlib.sha256(), 0
    with path.open("xb") as stream:
        for chunk in transport.iter_bytes(url):
            if type(chunk) is not bytes or not chunk:
                raise CustodyError()
            size += len(chunk)
            if size > LIMIT:
                raise CustodyError()
            stream.write(chunk)
            sha.update(chunk)
        stream.flush()
        os.fsync(stream.fileno())
    events.add("fetch_completed", kind=kind, bytes=size, sha256=sha.hexdigest())
    return path, sha.hexdigest()


def _read_baseline(path):
    raw = path.read_bytes()
    value = json.loads(raw)
    expected = {"schema", "family_fingerprints", "artifact_fingerprints", "publication_fingerprints"}
    if type(value) is not dict or set(value) != expected or value["schema"] != "opaque-overlap-baseline-v1":
        raise CustodyError()
    for key in expected - {"schema"}:
        if type(value[key]) is not list or any(type(x) is not str or not BASELINE_TOKEN.fullmatch(x) for x in value[key]):
            raise CustodyError()
    return value, hashlib.sha256(raw).hexdigest()


def _metadata_factors(value):
    names = {"paper", "paper_id", "publication", "publication_id", "doi", "repository", "repo",
             "github", "github_name", "artifact", "artifact_id", "dataset", "dataset_id", "capsule",
             "capsule_id", "source", "source_id", "src_file_or_path", "dataset_folder_tree",
             "huggingface_repo", "hf_repo", "dataset_name"}
    result = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and key.lower() in names and child not in (None, "", [], {}):
                field = key.lower()
                result.add(_opaque("family-fingerprint", {"field": field, "value": child}))
                # Retain compatibility with the earlier custodian's exact-value
                # scheme; non-equality cannot rule out semantic overlap.
                if isinstance(child, str):
                    result.add(_opaque("factor", {"field": field, "value": child.strip()}))
            result.update(_metadata_factors(child))
    elif isinstance(value, list):
        for child in value:
            result.update(_metadata_factors(child))
    return result


def _shape(value):
    # Even the private shape descriptor discards dynamic keys and scalar text.
    if isinstance(value, dict):
        return ["object", sorted((_shape(v) for v in value.values()), key=canonical)]
    if isinstance(value, list):
        return ["array", sorted((_shape(v) for v in value), key=canonical)]
    return "scalar"


def _inspect(tree_path, archive_path):
    import yaml  # Safe parsing only; upstream Python is never imported.
    tree = json.loads(tree_path.read_bytes())
    if tree.get("sha") != REVISION or tree.get("truncated") is not False:
        raise CustodyError()
    expected = {e["path"]: (e["size"], e["sha"]) for e in tree["tree"] if e["type"] == "blob"}
    contents = {}
    with zipfile.ZipFile(archive_path) as archive:
        if sum(info.file_size for info in archive.infolist()) > 4 * LIMIT:
            raise CustodyError()
        for info in archive.infolist():
            if info.is_dir():
                continue
            parts = PurePosixPath(info.filename).parts
            if len(parts) < 2 or ".." in parts or info.file_size > LIMIT:
                raise CustodyError()
            relative = "/".join(parts[1:])
            if relative not in expected or relative in contents:
                raise CustodyError()
            data = archive.read(info)
            size, blob = expected[relative]
            actual = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
            if len(data) != size or actual != blob:
                raise CustodyError()
            contents[relative] = data
    if set(contents) != set(expected) or "LICENSE" not in contents:
        raise CustodyError()
    bundles = {}
    for relative, data in contents.items():
        parts = PurePosixPath(relative).parts
        if len(parts) == 5 and parts[:3] == ("airsbench", "tasks", "rad"):
            bundles.setdefault(parts[3], {})[parts[4]] = data
    if not bundles:
        raise CustodyError()
    factors, shapes, hashes, complete = [], [], [], 0
    required = {"metadata.yaml", "project_description.md", "prepare.py", "evaluate.py", "evaluate_prepare.py"}
    for bundle in bundles.values():
        complete += required <= set(bundle)
        metadata = yaml.safe_load(bundle["metadata.yaml"])
        if not isinstance(metadata, dict):
            raise CustodyError()
        factors.append(_metadata_factors(metadata))
        shapes.append(_shape(metadata))
        hashes.extend(hashlib.sha256(data).hexdigest() for data in bundle.values())
    parents = list(range(len(factors)))
    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    first = {}
    for i, values in enumerate(factors):
        for factor in values:
            j = first.setdefault(factor, i)
            parents[find(i)] = find(j)
    groups = {}
    for i in range(len(factors)):
        groups.setdefault(find(i), []).append(i)
    return {"archive_blob_count_verified": len(contents), "task_count": len(bundles),
            "task_bundle_complete_count": int(complete), "task_blob_count": len(hashes),
            "task_content_sha256": sorted(hashes), "metadata_shape_digest": digest(shapes),
            "license_sha256": hashlib.sha256(contents["LICENSE"]).hexdigest(),
            "metadata_components": [{"token": _opaque("family", {"revision": REVISION, "members": members}),
                                     "member_count": len(members)} for members in groups.values()],
            "opaque_family_fingerprints": sorted(set().union(*factors)),
            "opaque_artifact_fingerprints": sorted({_opaque("artifact-fingerprint", {"sha256": h}) for h in hashes})}


def acquire(*, private_store, output, overlap_baseline, transport=None):
    root, output = Path(private_store).resolve(), Path(output).resolve()
    if root.exists() or output.exists() or output.is_relative_to(root) or root.is_relative_to(output.parent):
        raise CustodyError()
    baseline, baseline_sha = _read_baseline(Path(overlap_baseline))
    root.mkdir(parents=True)
    events = _Events(root)
    # Preserve the intent before the FIRST network request; failures never erase
    # the private bytes or event chain and cannot be retried in this directory.
    events.add("acquisition_intent", baseline_sha256=baseline_sha,
               public_schema_sha256=digest(PUBLIC_SPEC))
    try:
        tree, tree_sha = _fetch(root, events, "tree", TREE_URL, transport or OfficialTransport())
        archive, archive_sha = _fetch(root, events, "archive", ARCHIVE_URL, transport or OfficialTransport())
        metadata = _inspect(tree, archive)
        events.add("private_inspection_completed", archive_sha256=archive_sha)
        value = {key: spec for key, spec in PUBLIC_SPEC.items() if not isinstance(spec, (dict, list))
                 and spec not in ("sha", "count", "token")}
        value.update(metadata)
        value.update(tree_sha256=tree_sha, archive_sha256=archive_sha,
                     fetch_event_chain_sha256=events.previous, fetch_event_count=events.count,
                     baseline_sha256=baseline_sha,
                     baseline_family_count=len(baseline["family_fingerprints"]),
                     baseline_artifact_count=len(baseline["artifact_fingerprints"]),
                     baseline_publication_count=len(baseline["publication_fingerprints"]),
                     baseline_comparable_family_count=sum(x.startswith(("opaque-family-fingerprint-v1-", "opaque-factor-v1-")) for x in baseline["family_fingerprints"]),
                     family_overlap_count=len(set(metadata["opaque_family_fingerprints"]) & set(baseline["family_fingerprints"])),
                     artifact_overlap_count=len(set(metadata["opaque_artifact_fingerprints"]) & set(baseline["artifact_fingerprints"])))
        validate_public(value)
        _write_new(root / "receipt.json", value)
        _write_new(output, value)
        return value
    except BaseException:
        events.add("acquisition_failed_details_suppressed")
        raise CustodyError() from None


def main(argv=None):
    parser = argparse.ArgumentParser(description="AIRS metadata-only controlled custody")
    parser.add_argument("--private-store", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--overlap-baseline", required=True, type=Path)
    args = parser.parse_args(argv)
    # Suppress library warnings/diagnostics as well as exception strings.
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            value = acquire(private_store=args.private_store, output=args.output,
                            overlap_baseline=args.overlap_baseline)
        validate_public(value)
        print(canonical({"schema": SCHEMA, "status": "acquired",
                         "receipt_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest()}))
        return 0
    except BaseException:
        print(canonical({"schema": SCHEMA, "status": "failed_details_suppressed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
