from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from research_loop.modular import source_ingestion
from research_loop.modular.contracts import ContractError
from research_loop.modular.source_ingestion import ArtifactSpec, SourceAcquirer, SourceSnapshot


def git_blob_sha1(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode("ascii") + payload).hexdigest()


class MemoryTransport:
    def __init__(self, payloads: dict[str, list[bytes] | Exception]):
        self.payloads = payloads
        self.urls: list[str] = []

    def iter_bytes(self, url: str):
        self.urls.append(url)
        item = next(value for key, value in self.payloads.items() if url.endswith(key + "?download=true"))
        if isinstance(item, Exception):
            raise item
        yield from item


def fixture_snapshot(payload: bytes, *, path: str = "public.jsonl") -> SourceSnapshot:
    return SourceSnapshot("scicode", "SciCode1/SciCode", "a" * 40,
                          (ArtifactSpec(path, len(payload), git_blob_sha1=git_blob_sha1(payload)),))


def install(monkeypatch, snapshot: SourceSnapshot) -> None:
    monkeypatch.setattr(source_ingestion, "SOURCE_SNAPSHOTS", {snapshot.canonical_id: snapshot})


def test_acquires_verified_private_snapshot_and_returns_no_reader(tmp_path: Path, monkeypatch) -> None:
    payload = b'{"synthetic":true}\n'
    snapshot = fixture_snapshot(payload)
    install(monkeypatch, snapshot)
    receipt = SourceAcquirer(MemoryTransport({"public.jsonl": [payload[:4], payload[4:]]})).acquire("scicode", tmp_path / "private")
    row = receipt.data()
    assert row["payload_returned"] is False and row["access_isolation"] == "not_verified"
    assert row["split_qualified"] is False
    assert row["artifacts"][0]["local_sha256"] == hashlib.sha256(payload).hexdigest()
    assert not hasattr(SourceAcquirer, "read") and not hasattr(SourceAcquirer, "open")
    stored = tmp_path / "private" / "snapshots" / "scicode" / ("a" * 40) / "public.jsonl"
    assert stored.read_bytes() == payload


def test_hash_failure_removes_partial_staging_and_has_no_completion_receipt(tmp_path: Path, monkeypatch) -> None:
    snapshot = fixture_snapshot(b"expected")
    install(monkeypatch, snapshot)
    with pytest.raises(ContractError, match="Git blob"):
        SourceAcquirer(MemoryTransport({"public.jsonl": [b"wrong!!!"]})).acquire("scicode", tmp_path / "private")
    assert not list((tmp_path / "private").rglob("snapshot-receipt.json"))
    assert not list((tmp_path / "private" / "snapshots").glob("**/*")) if (tmp_path / "private" / "snapshots").exists() else True


def test_interrupted_download_never_becomes_a_snapshot(tmp_path: Path, monkeypatch) -> None:
    snapshot = fixture_snapshot(b"expected")
    install(monkeypatch, snapshot)
    with pytest.raises(OSError, match="offline"):
        SourceAcquirer(MemoryTransport({"public.jsonl": OSError("offline")})).acquire("scicode", tmp_path / "private")
    assert not list((tmp_path / "private").rglob("snapshot-receipt.json"))


@pytest.mark.parametrize("path", ["../escape", "/absolute", "nested\\escape", "C:/drive", "file:stream", " leading", "trailing "])
def test_source_paths_reject_escape(path: str) -> None:
    with pytest.raises(ContractError):
        ArtifactSpec(path, 1, git_blob_sha1="a" * 40)


def test_existing_snapshot_is_an_immutable_conflict(tmp_path: Path, monkeypatch) -> None:
    payload = b"expected"
    snapshot = fixture_snapshot(payload)
    install(monkeypatch, snapshot)
    acquirer = SourceAcquirer(MemoryTransport({"public.jsonl": [payload]}))
    acquirer.acquire("scicode", tmp_path / "private")
    with pytest.raises(ContractError, match="immutable"):
        acquirer.acquire("scicode", tmp_path / "private")


def test_lfs_payload_uses_lfs_sha256_not_pointer_blob_sha1(tmp_path: Path, monkeypatch) -> None:
    payload = b"lfs-payload"
    pointer_sha1 = "b" * 40
    snapshot = SourceSnapshot("scienceagentbench", "osunlp/ScienceAgentBench", "c" * 40, (
        ArtifactSpec("data/public.parquet", len(payload), git_blob_sha1=pointer_sha1,
                     lfs_sha256=hashlib.sha256(payload).hexdigest()),
    ))
    install(monkeypatch, snapshot)
    receipt = SourceAcquirer(MemoryTransport({"data/public.parquet": [payload]})).acquire("scienceagentbench", tmp_path / "private")
    artifact = receipt.data()["artifacts"][0]
    assert artifact["git_blob_sha1"] == pointer_sha1
    assert artifact["git_blob_sha1_kind"].startswith("Git LFS pointer")


def test_lfs_sha256_mismatch_fails_closed_even_when_pointer_metadata_exists(tmp_path: Path, monkeypatch) -> None:
    payload = b"lfs-payload"
    snapshot = SourceSnapshot("scienceagentbench", "osunlp/ScienceAgentBench", "d" * 40, (
        ArtifactSpec("data/public.parquet", len(payload), git_blob_sha1="b" * 40, lfs_sha256="a" * 64),
    ))
    install(monkeypatch, snapshot)
    with pytest.raises(ContractError, match="LFS SHA-256"):
        SourceAcquirer(MemoryTransport({"data/public.parquet": [payload]})).acquire("scienceagentbench", tmp_path / "private")


def test_rejects_unregistered_source_and_never_accepts_moving_ref(tmp_path: Path) -> None:
    with pytest.raises(ContractError, match="unsupported or moving"):
        SourceAcquirer(MemoryTransport({})).acquire("scienceagentbench@main", tmp_path / "private")
