"""Durable, fail-closed deployment port for approved modular packages.

The deployment file is deliberately a complete snapshot.  It contains the
immutable package and the memory view consumed by the next task; its companion
hash file lets ``current`` detect a torn write or out-of-band modification.
"""

from __future__ import annotations

import hashlib
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.modules.improvement import CandidatePackage, DeploymentAck
from research_loop.ontology import ContractError, canonical, digest


class FileDeploymentPort:
    """A local, cross-process compare-and-swap deployment boundary."""

    def __init__(self, state_path: Path, initial: CandidatePackage) -> None:
        if not isinstance(initial, CandidatePackage):
            raise ContractError("file deployment requires an immutable initial package")
        self._path = Path(state_path)
        self._hash_path = self._path.with_name(self._path.name + ".sha256")
        self._previous_path = self._path.with_name(self._path.name + ".previous")
        self._previous_hash_path = self._previous_path.with_name(self._previous_path.name + ".sha256")
        self._lock_path = self._path.with_name(self._path.name + ".lock")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # The check and first write are one transaction.  A second process
        # waits for the first to publish a complete, hash-verified snapshot.
        with self._exclusive():
            if self._path.exists() or self._hash_path.exists():
                ack = self.current()
                if not ack.online:
                    raise ContractError("existing deployment state is corrupt or incomplete")
            else:
                self._persist(initial, archive_current=False)

    @staticmethod
    def _file_hash(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    def _snapshot(self, package: CandidatePackage) -> bytes:
        memory = package.record.data()["changes"].get("memory", {})
        return canonical({
            "schema": "modular-file-deployment-v1",
            "active_digest": package.digest,
            "package": package.record.data(),
            "memory_view": memory,
            "memory_digest": package.memory_digest,
        }).encode("utf-8")

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        """Acquire a directory lock without ever guessing that a stale lock is safe."""
        deadline = time.monotonic() + 2.0
        while True:
            try:
                self._lock_path.mkdir()
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise ContractError("deployment lock remains held; explicit operator recovery required")
                time.sleep(0.01)
        try:
            yield
        finally:
            try:
                self._lock_path.rmdir()
            except OSError as exc:
                raise ContractError("deployment lock release failed; explicit operator recovery required") from exc

    def _write_pair(self, path: Path, hash_path: Path, payload: bytes) -> None:
        file_hash = self._file_hash(payload)
        tmp_state = path.with_name(path.name + ".tmp")
        tmp_hash = hash_path.with_name(hash_path.name + ".tmp")
        try:
            with tmp_state.open("wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            with tmp_hash.open("w", encoding="ascii", newline="\n") as stream:
                stream.write(file_hash + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp_state, path)
            os.replace(tmp_hash, hash_path)
        finally:
            for temporary in (tmp_state, tmp_hash):
                if temporary.exists():
                    temporary.unlink()

    def _read_package(self, path: Path, hash_path: Path) -> CandidatePackage | None:
        try:
            payload = path.read_bytes()
            expected_hash = hash_path.read_text(encoding="ascii").strip()
            if len(expected_hash) != 64 or expected_hash != self._file_hash(payload):
                return None
            item = FrozenRecord(payload.decode("utf-8")).data()
            if set(item) != {"schema", "active_digest", "package", "memory_view", "memory_digest"} or item["schema"] != "modular-file-deployment-v1":
                return None
            package = CandidatePackage(FrozenRecord.from_dict(item["package"]))
            memory = package.record.data()["changes"].get("memory", {})
            if (item["active_digest"] != package.digest or item["memory_view"] != memory
                    or item["memory_digest"] != package.memory_digest or digest(memory) != package.memory_digest):
                return None
            return package
        except (OSError, UnicodeError, ValueError, ContractError):
            return None

    def _persist(self, package: CandidatePackage, *, archive_current: bool = True) -> None:
        if archive_current and self._path.exists():
            current = self._read_package(self._path, self._hash_path)
            if current is None:
                raise ContractError("deployment state drift blocks replacement")
            self._write_pair(self._previous_path, self._previous_hash_path, self._snapshot(current))
        self._write_pair(self._path, self._hash_path, self._snapshot(package))

    def current(self) -> DeploymentAck:
        package = self._read_package(self._path, self._hash_path)
        if package is None:
            return DeploymentAck("drift", "drift", False)
        return DeploymentAck(package.digest, package.memory_digest, True)

    def previous(self) -> CandidatePackage | None:
        """Read the last complete snapshot; it never repairs active state implicitly."""
        return self._read_package(self._previous_path, self._previous_hash_path)

    def activate(self, package: CandidatePackage, expected_active_digest: str) -> DeploymentAck:
        if not isinstance(package, CandidatePackage):
            raise ContractError("file deployment accepts immutable packages only")
        # The current read, expected-digest comparison, archival, and write
        # must share one inter-process critical section for CAS to mean CAS.
        with self._exclusive():
            current = self.current()
            if not current.online or current.active_digest != expected_active_digest:
                return DeploymentAck("drift", "drift", False)
            self._persist(package)
            return self.current()
