"""First-acquisition custody command for the fixed CORE-Bench training source.

Raw bytes are streamed directly into a new private snapshot.  The only public
output is an immutable metadata receipt: source pin, hashes, event digests,
opaque family fingerprints, and a narrow statement about this acquisition
process.  It never exports task text, solutions, gold material, source code,
or record identifiers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Protocol

from research_loop.ontology import ContractError, canonical, digest


_SCHEMA = "controlled-source-acquisition-receipt-v1"
_OVERLAP_SCHEMA = "opaque-overlap-baseline-v1"


@dataclass(frozen=True)
class _Artifact:
    path: str
    size: int
    git_blob_sha1: str


_COREBENCH = {
    "source": "corebench",
    "repository": "siegelz/core-bench",
    "revision": "e32a2980e72fe6eb04ee04eb749458f570625663",
    "license": _Artifact("LICENSE", 1071, "04d237f5a4395c7d6d08bfda609ba374a2778c45"),
    "task": _Artifact("benchmark/dataset/core_train.json", 54907, "8ea09677fd4d98a4995144b959ba6f65bb2a85aa"),
}


class DownloadTransport(Protocol):
    def iter_bytes(self, url: str) -> Iterable[bytes]: ...


class OfficialGitHubTransport:
    def iter_bytes(self, url: str) -> Iterable[bytes]:
        with urllib.request.urlopen(url, timeout=60) as response:
            while chunk := response.read(64 * 1024):
                yield chunk


def _opaque(kind: str, value: object) -> str:
    return f"opaque-{kind}-v1-{digest(value)}"


def _url(artifact: _Artifact) -> str:
    return f"https://raw.githubusercontent.com/{_COREBENCH['repository']}/{_COREBENCH['revision']}/{artifact.path}"


def _safe_child(root: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if (not relative or path.is_absolute() or ".." in path.parts or "\\" in relative or ":" in relative):
        raise ContractError("unsafe controlled-source artifact path")
    candidate = root.joinpath(*path.parts)
    try:
        if not candidate.resolve().is_relative_to(root.resolve()):
            raise ContractError("controlled-source path escaped private store")
    except OSError as exc:
        raise ContractError("controlled-source private path is unavailable") from exc
    return candidate


def _git_hash(content_size: int, stream: Iterable[bytes], target: Path) -> tuple[str, str]:
    sha256 = hashlib.sha256()
    sha1 = hashlib.sha1(f"blob {content_size}\0".encode("ascii"))
    written = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as handle:
            for block in stream:
                if not isinstance(block, bytes) or not block:
                    raise ContractError("official transport returned an invalid block")
                written += len(block)
                if written > content_size:
                    raise ContractError("official artifact exceeded fixed size")
                sha256.update(block); sha1.update(block); handle.write(block)
            handle.flush(); os.fsync(handle.fileno())
    except Exception:
        target.unlink(missing_ok=True)
        raise
    if written != content_size:
        target.unlink(missing_ok=True)
        raise ContractError("official artifact size does not match fixed metadata")
    return sha256.hexdigest(), sha1.hexdigest()


def _schema_shape(value: object, path: str = "$") -> tuple[tuple[str, str], ...]:
    if isinstance(value, Mapping):
        result = [(path, "object")]
        for key in sorted(value):
            if not isinstance(key, str):
                raise ContractError("controlled source has a non-string schema key")
            result.extend(_schema_shape(value[key], f"{path}.{key}"))
        return tuple(result)
    if isinstance(value, list):
        result = [(path, "array")]
        for item in value:
            result.extend(_schema_shape(item, f"{path}[]"))
        return tuple(sorted(set(result)))
    return ((path, type(value).__name__),)


def _rows(value: object) -> list[Mapping[str, Any]]:
    if isinstance(value, list) and value and all(isinstance(row, Mapping) for row in value):
        return list(value)
    if isinstance(value, Mapping):
        for key in ("tasks", "data", "instances", "records"):
            rows = value.get(key)
            if isinstance(rows, list) and rows and all(isinstance(row, Mapping) for row in rows):
                return list(rows)
        if value and all(isinstance(row, Mapping) for row in value.values()):
            return list(value.values())
    raise ContractError("controlled source task schema cannot produce metadata records")


def _family_factors(row: Mapping[str, Any]) -> set[str]:
    """Hash only explicit lineage-like fields; never export values or IDs."""
    names = {"paper", "paper_id", "publication", "publication_id", "doi", "repository", "repo",
             "github", "github_name", "artifact", "artifact_id", "dataset", "dataset_id", "capsule",
             "capsule_id", "source", "source_id"}
    result: set[str] = set()
    def visit(value: object, path: tuple[str, ...] = ()) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if not isinstance(key, str):
                    raise ContractError("controlled source has a non-string metadata key")
                lowered = key.lower()
                if lowered in names and child not in (None, "", [], {}):
                    result.add(_opaque("family-fingerprint", {"field": lowered, "value": child}))
                visit(child, (*path, lowered))
        elif isinstance(value, list):
            for child in value:
                visit(child, path)
    visit(row)
    return result


def _family_receipt(task_bytes: bytes, overlap: Mapping[str, Any] | None) -> dict[str, Any]:
    try:
        parsed = json.loads(task_bytes)
    except ValueError as exc:
        raise ContractError("controlled source task artifact is not valid JSON") from exc
    rows = _rows(parsed)
    tokens = [_opaque("record", {"sha256": hashlib.sha256(canonical(row).encode("utf-8")).hexdigest()}) for row in rows]
    parent = {token: token for token in tokens}
    def find(token: str) -> str:
        while parent[token] != token:
            parent[token] = parent[parent[token]]; token = parent[token]
        return token
    def join(left: str, right: str) -> None:
        left, right = find(left), find(right)
        if left != right:
            parent[max(left, right)] = min(left, right)
    first: dict[str, str] = {}
    fingerprints: set[str] = set()
    for token, row in zip(tokens, rows, strict=True):
        for factor in _family_factors(row):
            fingerprints.add(factor)
            join(token, first.setdefault(factor, token))
    components: dict[str, list[str]] = {}
    for token in tokens:
        components.setdefault(find(token), []).append(token)
    known = set(overlap.get("family_fingerprints", [])) if overlap is not None else set()
    return {
        "record_count": len(rows),
        "schema_descriptor_digest": digest(sorted({item for row in rows for item in _schema_shape(row)})),
        "family_fingerprint_count": len(fingerprints),
        "opaque_family_tokens": [_opaque("family", sorted(members)) for _root, members in sorted(components.items())],
        "family_component_sizes": sorted(len(members) for members in components.values()),
        "family_overlap_with_available_baseline": sorted(fingerprints & known),
        "publication_lineage_status": "metadata_fingerprints_only_not_independent_provenance_proof",
    }


def _load_overlap(path: Path | None) -> Mapping[str, Any] | None:
    if path is None:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ContractError("invalid opaque overlap baseline") from exc
    expected = {"schema", "family_fingerprints", "artifact_fingerprints", "publication_fingerprints"}
    if (not isinstance(value, Mapping) or set(value) != expected or value.get("schema") != _OVERLAP_SCHEMA
            or any(not isinstance(value[key], list) or any(not isinstance(item, str) for item in value[key])
                   for key in expected - {"schema"})):
        raise ContractError("opaque overlap baseline schema is invalid")
    return value


def acquire_corebench(*, private_store: Path, output: Path, transport: DownloadTransport,
                      overlap_baseline: Path | None = None) -> dict[str, Any]:
    root = private_store.resolve(); output = output.resolve()
    if output.is_relative_to(root) or output.exists():
        raise ContractError("receipt must be a new file outside the private store")
    final = _safe_child(root, f"snapshots/corebench/{_COREBENCH['revision']}")
    if final.exists():
        raise ContractError("controlled CORE-Bench snapshot already exists")
    root.mkdir(parents=True, exist_ok=True)
    staging_parent = _safe_child(root, ".staging"); staging_parent.mkdir(exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="corebench-", dir=staging_parent))
    try:
        downloaded = []
        for kind, artifact in (("license", _COREBENCH["license"]), ("task", _COREBENCH["task"])):
            local_hash, git_hash = _git_hash(artifact.size, transport.iter_bytes(_url(artifact)), _safe_child(staging, artifact.path))
            if git_hash != artifact.git_blob_sha1:
                raise ContractError("official artifact does not match fixed Git blob")
            downloaded.append({"kind": kind, "source_path": artifact.path, "size_bytes": artifact.size,
                               "git_blob_sha1": artifact.git_blob_sha1, "local_sha256": local_hash})
        task_path = _safe_child(staging, _COREBENCH["task"].path)
        overlap = _load_overlap(overlap_baseline)
        family = _family_receipt(task_path.read_bytes(), overlap)
        artifact_fingerprints = [_opaque("artifact-fingerprint", {"sha256": row["local_sha256"]}) for row in downloaded]
        baseline_artifacts = set(overlap.get("artifact_fingerprints", [])) if overlap is not None else set()
        receipt = {
            "schema": _SCHEMA, "source": _COREBENCH["source"], "repository": _COREBENCH["repository"],
            "revision": _COREBENCH["revision"], "official_urls": [_url(_COREBENCH["license"]), _url(_COREBENCH["task"])],
            "fetch_events": [{"event": "streamed_fixed_official_artifact", "artifact_sha256": row["local_sha256"]}
                             for row in downloaded], "artifacts": downloaded,
            "license_sha256": downloaded[0]["local_sha256"], "family_metadata": family,
            "artifact_overlap_with_available_baseline": sorted(set(artifact_fingerprints) & baseline_artifacts),
            "overlap_limit": "available opaque fingerprints only; no equality is not provenance-independence proof",
            "raw_private_payload_returned": False, "optimizer_access": "none",
            "controlled_new_optimizer_process_payload_exported": False,
            "exposure_claim": "this acquisition exported no payload to this optimizer process; it does not establish pretraining or historical non-exposure",
            "mutated_existing_custody": False,
        }
        (staging / "acquisition-receipt.json").write_text(canonical(receipt) + "\n", encoding="utf-8", newline="\n")
        final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, final)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(canonical(receipt) + "\n", encoding="utf-8", newline="\n")
        return receipt
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Acquire fixed CORE-Bench bytes into private custody and emit metadata only.")
    parser.add_argument("--private-store", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--overlap-baseline", type=Path)
    args = parser.parse_args(argv)
    receipt = acquire_corebench(private_store=args.private_store, output=args.output,
                                transport=OfficialGitHubTransport(), overlap_baseline=args.overlap_baseline)
    print(canonical({"schema": _SCHEMA, "receipt_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
                     "raw_private_payload_returned": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
