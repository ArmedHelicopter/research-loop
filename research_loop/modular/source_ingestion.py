"""Controller-only acquisition of pinned external benchmark snapshots.

This module stores opaque source bytes in a private directory.  Its public
result is an immutable inventory receipt; it intentionally has no data-reader,
task-projection, split, or qualification API.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Final, Iterable, Mapping, Protocol

from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError


@dataclass(frozen=True)
class ArtifactSpec:
    source_path: str
    size_bytes: int
    git_blob_sha1: str | None = None
    lfs_sha256: str | None = None

    def __post_init__(self) -> None:
        path = PurePosixPath(self.source_path)
        if (not self.source_path or path.is_absolute() or ".." in path.parts
                or "\\" in self.source_path or len(path.parts) == 0):
            raise ContractError("source artifact path must be a safe relative POSIX path")
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise ContractError("source artifact size must be a nonnegative integer")
        for field, value, length in (("git blob SHA-1", self.git_blob_sha1, 40), ("LFS SHA-256", self.lfs_sha256, 64)):
            if value is not None and (not isinstance(value, str) or len(value) != length or any(c not in "0123456789abcdef" for c in value)):
                raise ContractError(f"invalid {field}")
        if self.git_blob_sha1 is None and self.lfs_sha256 is None:
            raise ContractError("source artifact requires a Git blob SHA-1 or LFS SHA-256")


@dataclass(frozen=True)
class SourceSnapshot:
    canonical_id: str
    repository: str
    revision: str
    artifacts: tuple[ArtifactSpec, ...]

    def __post_init__(self) -> None:
        if self.canonical_id not in {"scienceagentbench", "scicode"}:
            raise ContractError("only registered pinned extended sources may be acquired")
        if (not isinstance(self.repository, str) or not self.repository or not isinstance(self.revision, str)
                or len(self.revision) != 40 or any(c not in "0123456789abcdef" for c in self.revision)):
            raise ContractError("pinned repository and revision required")
        if not self.artifacts or len({item.source_path for item in self.artifacts}) != len(self.artifacts):
            raise ContractError("source snapshot requires unique artifacts")


SOURCE_SNAPSHOTS: Final[Mapping[str, SourceSnapshot]] = MappingProxyType({
    "scienceagentbench": SourceSnapshot(
        "scienceagentbench", "osunlp/ScienceAgentBench", "9c6e96c9e74572e979b0930ee735041cef528cb7", (
            ArtifactSpec("ScienceAgentBench.csv", 278626, git_blob_sha1="65c148f52416af4a00437072108c6c1b03dce7dc"),
            ArtifactSpec("data/verified-00000-of-00001.parquet", 129086,
                         git_blob_sha1="3ab66131e23fe3e924c5de9af528440de99679ae",
                         lfs_sha256="c6f937863a220bd1762a00c20a0f79cc8dfca900b819bdb552150310731ae147"),
        ),
    ),
    "scicode": SourceSnapshot(
        "scicode", "SciCode1/SciCode", "4510f6a6aa27c43fad7b43da2c59602a86e88480", (
            ArtifactSpec("problems_dev.jsonl", 279558, git_blob_sha1="ce8984e15447ef0876e696906d100f3eadf941d0"),
            ArtifactSpec("problems_test.jsonl", 933500, git_blob_sha1="b72b96897f0b72ee560b588b7b80106e00a93d29"),
        ),
    ),
})


class DownloadTransport(Protocol):
    def iter_bytes(self, url: str) -> Iterable[bytes]: ...


class HttpDownloadTransport:
    """Small streaming HTTP transport used only by the controller CLI."""

    def iter_bytes(self, url: str) -> Iterable[bytes]:
        with urllib.request.urlopen(url, timeout=60) as response:
            while chunk := response.read(64 * 1024):
                yield chunk


def source_url(snapshot: SourceSnapshot, artifact: ArtifactSpec) -> str:
    return (f"https://huggingface.co/datasets/{snapshot.repository}/resolve/"
            f"{snapshot.revision}/{artifact.source_path}?download=true")


def _git_blob_digest(size_bytes: int) -> "hashlib._Hash":
    digest = hashlib.sha1()
    digest.update(f"blob {size_bytes}\0".encode("ascii"))
    return digest


def _private_child(root: Path, relative: str) -> Path:
    candidate = root / Path(*PurePosixPath(relative).parts)
    if os.path.commonpath((str(root.resolve()), str(candidate.resolve()))) != str(root.resolve()):
        raise ContractError("private-store path escaped root")
    return candidate


class SourceAcquirer:
    """Writes verified snapshots, returning metadata-only receipts."""

    def __init__(self, transport: DownloadTransport):
        self._transport = transport

    def acquire(self, source_id: str, private_store: Path) -> FrozenRecord:
        snapshot = SOURCE_SNAPSHOTS.get(source_id)
        if snapshot is None:
            raise ContractError("unsupported or moving source reference")
        if not isinstance(private_store, Path):
            raise ContractError("private_store must be a Path")
        private_store.mkdir(parents=True, exist_ok=True)
        root = private_store.resolve()
        final = _private_child(root, f"snapshots/{snapshot.canonical_id}/{snapshot.revision}")
        if final.exists():
            raise ContractError("immutable source snapshot already exists; inspect its receipt")
        staging_parent = _private_child(root, ".staging")
        staging_parent.mkdir(exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f"{snapshot.canonical_id}-", dir=staging_parent))
        try:
            inventory = [self._download(snapshot, artifact, staging) for artifact in snapshot.artifacts]
            receipt = FrozenRecord.from_dict({
                "schema": "pinned-source-snapshot-receipt-v1",
                "source": snapshot.canonical_id,
                "repository": snapshot.repository,
                "revision": snapshot.revision,
                "artifacts": inventory,
                "content_exposed": False,
                "split_qualified": False,
                "task_projection_created": False,
            })
            receipt_path = staging / "snapshot-receipt.json"
            receipt_path.write_text(receipt.encoded + "\n", encoding="utf-8", newline="\n")
            with receipt_path.open("r+b") as stream:
                os.fsync(stream.fileno())
            final.parent.mkdir(parents=True, exist_ok=True)
            if final.exists():
                raise ContractError("immutable source snapshot already exists; inspect its receipt")
            os.replace(staging, final)
            return receipt
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise

    def _download(self, snapshot: SourceSnapshot, artifact: ArtifactSpec, staging: Path) -> dict[str, object]:
        target = _private_child(staging, artifact.source_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        local_sha256 = hashlib.sha256()
        git_sha1 = _git_blob_digest(artifact.size_bytes) if artifact.git_blob_sha1 else None
        written = 0
        try:
            with target.open("xb") as stream:
                for chunk in self._transport.iter_bytes(source_url(snapshot, artifact)):
                    if not isinstance(chunk, bytes) or not chunk:
                        raise ContractError("download transport yielded an invalid chunk")
                    written += len(chunk)
                    if written > artifact.size_bytes:
                        raise ContractError("download exceeded pinned source size")
                    local_sha256.update(chunk)
                    if git_sha1 is not None:
                        git_sha1.update(chunk)
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            target.unlink(missing_ok=True)
            raise
        if written != artifact.size_bytes:
            target.unlink(missing_ok=True)
            raise ContractError("download size does not match pinned source metadata")
        local_hash = local_sha256.hexdigest()
        if artifact.lfs_sha256 is not None and local_hash != artifact.lfs_sha256:
            target.unlink(missing_ok=True)
            raise ContractError("download LFS SHA-256 does not match pinned source metadata")
        if git_sha1 is not None and git_sha1.hexdigest() != artifact.git_blob_sha1:
            target.unlink(missing_ok=True)
            raise ContractError("download Git blob SHA-1 does not match pinned source metadata")
        return {
            "source_path": artifact.source_path,
            "size_bytes": written,
            "git_blob_sha1": artifact.git_blob_sha1,
            "lfs_sha256": artifact.lfs_sha256,
            "local_sha256": local_hash,
            "local_hash_kind": "SHA-256 of private downloaded bytes",
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Acquire one fixed external source snapshot into a private store.")
    parser.add_argument("--source", required=True, choices=tuple(SOURCE_SNAPSHOTS))
    parser.add_argument("--private-store", required=True, type=Path)
    args = parser.parse_args(argv)
    receipt = SourceAcquirer(HttpDownloadTransport()).acquire(args.source, args.private_store)
    print(receipt.encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
