import hashlib
from pathlib import Path
import zipfile

import pytest

from research_loop.modular.artifact_catalogue import ArtifactCatalogue, source_snapshot
from research_loop.modular.artifact_source_archive import ArchivedSourceResolver
from research_loop.modular.contracts import DataIdentity
from research_loop.ontology import ContractError


def identity():
    return DataIdentity("synthetic", "archive-task", "group", "dataset-v1", "split-v1", "train")


def write_archive(path, members):
    with zipfile.ZipFile(path, "w") as archive:
        for name, raw in members:
            archive.writestr(name, raw)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recorded_catalogue(tmp_path):
    root = tmp_path / "original-source"
    producer = root / "pkg" / "producer.py"
    producer.parent.mkdir(parents=True)
    producer.write_bytes(b"ORIGINAL PRODUCER\n")
    snapshot = source_snapshot(producer)
    path = tmp_path / "catalogue.jsonl"
    catalogue = ArtifactCatalogue.external(path, identity=identity(), producer_source=snapshot)
    catalogue.append(kind="prediction", module="M4", payload={"n": 1})
    seal = catalogue.seal()
    archive = tmp_path / "frozen-sources.zip"
    digest = write_archive(archive, [("pkg/producer.py", producer.read_bytes())])
    return path, root, producer, snapshot, seal, archive, digest


def reader(path, snapshot, archive, digest, root):
    resolver = ArchivedSourceResolver(archive, digest, root)
    return ArtifactCatalogue.external(path, identity=identity(), producer_source=snapshot, source_resolver=resolver)


def test_archived_source_verifies_after_original_changes_or_disappears_without_extracting(tmp_path):
    path, root, producer, snapshot, seal, archive, digest = recorded_catalogue(tmp_path)
    producer.write_bytes(b"CHANGED\n")
    producer.unlink()
    before = sorted(item.relative_to(tmp_path).as_posix() for item in tmp_path.rglob("*"))
    reopened = reader(path, snapshot, archive, digest, root)
    reopened.verify(seal)
    assert len(reopened.records()) == 1
    after = sorted(item.relative_to(tmp_path).as_posix() for item in tmp_path.rglob("*"))
    assert after == before
    assert not producer.exists()


@pytest.mark.parametrize("mode", ["wrong", "missing", "tampered", "member", "root"])
def test_archive_reader_rejects_bad_archive_binding_without_writing(tmp_path, mode):
    path, root, producer, snapshot, _seal, archive, digest = recorded_catalogue(tmp_path)
    producer.unlink()
    archive_path, expected_digest, source_root = archive, digest, root
    if mode == "wrong":
        expected_digest = "0" * 64
    elif mode == "missing":
        archive_path = tmp_path / "missing.zip"
    elif mode == "tampered":
        archive.write_bytes(archive.read_bytes() + b"trailing tamper")
    elif mode == "member":
        expected_digest = write_archive(archive, [("pkg/other.py", b"ORIGINAL PRODUCER\n")])
    elif mode == "root":
        source_root = tmp_path / "different-original-root"
    before = sorted(item.relative_to(tmp_path).as_posix() for item in tmp_path.rglob("*"))
    with pytest.raises(ContractError):
        reader(path, snapshot, archive_path, expected_digest, source_root)
    after = sorted(item.relative_to(tmp_path).as_posix() for item in tmp_path.rglob("*"))
    assert after == before


@pytest.mark.parametrize("members", [
    [("../pkg/producer.py", b"ORIGINAL PRODUCER\n")],
    [("/pkg/producer.py", b"ORIGINAL PRODUCER\n")],
    [("C:/pkg/producer.py", b"ORIGINAL PRODUCER\n")],
    [("pkg/producer.py", b"ORIGINAL PRODUCER\n"), ("pkg/producer.py", b"ORIGINAL PRODUCER\n")],
])
def test_archive_reader_rejects_unsafe_duplicate_or_crossroot_members(tmp_path, members):
    path, root, producer, snapshot, _seal, archive, _digest = recorded_catalogue(tmp_path)
    producer.unlink()
    digest = write_archive(archive, members)
    before = sorted(item.relative_to(tmp_path).as_posix() for item in tmp_path.rglob("*"))
    with pytest.raises(ContractError):
        reader(path, snapshot, archive, digest, root)
    assert sorted(item.relative_to(tmp_path).as_posix() for item in tmp_path.rglob("*")) == before


def test_append_remains_live_source_bound_even_when_reader_has_an_archive(tmp_path):
    path, root, producer, snapshot, _seal, archive, digest = recorded_catalogue(tmp_path)
    path.with_name(path.name + ".seal.json").unlink()
    producer.unlink()
    reopened = reader(path, snapshot, archive, digest, root)
    with pytest.raises(ContractError, match="no longer resolvable"):
        reopened.append(kind="late", module="M5", payload={"n": 2})
