"""Read-only resolution of a producer-source snapshot from a frozen ZIP."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
from pathlib import Path, PurePosixPath
import re
import zipfile

from research_loop.ontology import ContractError


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class ArchivedSourceResolver:
    """Resolve historical source bytes without extracting a source archive.

    ``source_root`` is the root used when producer snapshots were recorded.
    The expected archive digest is deliberately supplied by the caller rather
    than accepted from the archive itself.
    """

    archive_path: Path
    archive_sha256: str
    source_root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "archive_path", Path(self.archive_path))
        source_root = Path(self.source_root)
        if not source_root.is_absolute() or '..' in source_root.parts:
            raise ContractError("original source root must be absolute and canonical")
        object.__setattr__(self, "source_root", source_root)
        if type(self.archive_sha256) is not str or not _SHA256.fullmatch(self.archive_sha256):
            raise ContractError("expected source archive SHA-256 is invalid")
        if not self.source_root.is_absolute():
            raise ContractError("original source root must be absolute")

    def verify_snapshot(self, snapshot: dict[str, object]) -> None:
        """Confirm one recorded source snapshot against the frozen archive."""
        try:
            if type(snapshot['path']) is not str:
                raise ContractError('producer source path must be an absolute recorded path')
            source_path = Path(snapshot["path"])
            expected_hash = snapshot["sha256"]
            expected_bytes = snapshot["bytes"]
        except (KeyError, TypeError) as exc:
            raise ContractError("producer source requires an actual file snapshot") from exc
        if (not source_path.is_absolute() or '..' in source_path.parts or type(expected_hash) is not str
                or not _SHA256.fullmatch(expected_hash) or type(expected_bytes) is not int
                or expected_bytes < 0):
            raise ContractError("producer source requires an actual file snapshot")
        try:
            member = source_path.relative_to(self.source_root).as_posix()
        except ValueError as exc:
            raise ContractError("producer source is outside the archived source root") from exc
        if not member or member == ".":
            raise ContractError("producer source is outside the archived source root")
        archive = self._open_verified_archive()
        with archive:
            infos = self._validated_members(archive)
            info = infos.get(member)
            if info is None:
                raise ContractError("producer source is missing from the frozen archive")
            with archive.open(info, "r") as stream:
                raw = stream.read()
        if len(raw) != expected_bytes or hashlib.sha256(raw).hexdigest() != expected_hash:
            raise ContractError("frozen producer source bytes differ from the recorded snapshot")

    def _open_verified_archive(self) -> zipfile.ZipFile:
        try:
            raw = self.archive_path.read_bytes()
        except OSError as exc:
            raise ContractError("frozen producer source archive is unavailable") from exc
        if hashlib.sha256(raw).hexdigest() != self.archive_sha256:
            raise ContractError("frozen producer source archive digest differs")
        try:
            # Read the bytes whose digest was checked. Reopening the pathname
            # would allow a replacement between hashing and ZIP member reads.
            return zipfile.ZipFile(io.BytesIO(raw), "r")
        except (OSError, zipfile.BadZipFile) as exc:
            raise ContractError("frozen producer source archive is invalid") from exc

    @staticmethod
    def _validated_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
        members: dict[str, zipfile.ZipInfo] = {}
        for info in archive.infolist():
            name = info.filename
            path = PurePosixPath(name)
            if (not name or "\\" in name or "\x00" in name or path.is_absolute()
                    or any(part in {"", ".", ".."} or ':' in part for part in name.split('/'))
                    or info.is_dir()):
                raise ContractError("frozen producer source archive contains an unsafe member")
            if name in members:
                raise ContractError("frozen producer source archive contains a duplicate member")
            members[name] = info
        return members
