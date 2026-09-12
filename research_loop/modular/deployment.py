"""Durable, fail-closed deployment port for approved modular packages.

The deployment file is deliberately a complete snapshot.  It contains the
immutable package and the memory view consumed by the next task; its companion
hash file lets ``current`` detect a torn write or out-of-band modification.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.modules.improvement import CandidatePackage, DeploymentAck
from research_loop.ontology import ContractError, canonical, digest


class FileDeploymentPort:
    """A local single-file deployment boundary with compare-and-swap activation."""

    def __init__(self, state_path: Path, initial: CandidatePackage) -> None:
        if not isinstance(initial, CandidatePackage):
            raise ContractError("file deployment requires an immutable initial package")
        self._path = Path(state_path)
        self._hash_path = self._path.with_name(self._path.name + ".sha256")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists() or self._hash_path.exists():
            ack = self.current()
            if not ack.online:
                raise ContractError("existing deployment state is corrupt or incomplete")
        else:
            self._persist(initial)

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

    def _persist(self, package: CandidatePackage) -> None:
        payload = self._snapshot(package)
        file_hash = self._file_hash(payload)
        tmp_state = self._path.with_name(self._path.name + ".tmp")
        tmp_hash = self._hash_path.with_name(self._hash_path.name + ".tmp")
        try:
            with tmp_state.open("wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            with tmp_hash.open("w", encoding="ascii", newline="\n") as stream:
                stream.write(file_hash + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp_state, self._path)
            os.replace(tmp_hash, self._hash_path)
        finally:
            for temporary in (tmp_state, tmp_hash):
                if temporary.exists():
                    temporary.unlink()

    def current(self) -> DeploymentAck:
        try:
            payload = self._path.read_bytes()
            expected_hash = self._hash_path.read_text(encoding="ascii").strip()
            if len(expected_hash) != 64 or expected_hash != self._file_hash(payload):
                return DeploymentAck("drift", "drift", False)
            item = FrozenRecord(payload.decode("utf-8")).data()
            if set(item) != {"schema", "active_digest", "package", "memory_view", "memory_digest"} or item["schema"] != "modular-file-deployment-v1":
                return DeploymentAck("drift", "drift", False)
            package = CandidatePackage(FrozenRecord.from_dict(item["package"]))
            memory = package.record.data()["changes"].get("memory", {})
            if (item["active_digest"] != package.digest or item["memory_view"] != memory
                    or item["memory_digest"] != package.memory_digest or digest(memory) != package.memory_digest):
                return DeploymentAck("drift", "drift", False)
            return DeploymentAck(package.digest, package.memory_digest, True)
        except (OSError, UnicodeError, ValueError, ContractError):
            return DeploymentAck("drift", "drift", False)

    def activate(self, package: CandidatePackage, expected_active_digest: str) -> DeploymentAck:
        if not isinstance(package, CandidatePackage):
            raise ContractError("file deployment accepts immutable packages only")
        current = self.current()
        if not current.online or current.active_digest != expected_active_digest:
            return DeploymentAck("drift", "drift", False)
        self._persist(package)
        return self.current()
