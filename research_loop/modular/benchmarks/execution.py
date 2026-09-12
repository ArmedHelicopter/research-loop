"""Fail-closed Docker broker for a single public task execution."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.ontology import ContractError, digest


_IMAGE = re.compile(r"^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$")
_INPUT = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_DOCKER_INFRASTRUCTURE_ERRORS = (
    "cannot connect to the docker daemon", "docker daemon", "error during connect",
    "failed to connect to the docker api", "unable to find image", "no such image",
    "pull access denied", "is the docker daemon running",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class ArtifactReceipt:
    identity: DataIdentity
    artifact_id: str
    path: str
    sha256: str
    byte_count: int
    record: FrozenRecord

    @property
    def content_hash(self) -> str:
        return digest({"identity": self.identity.data(), "artifact_id": self.artifact_id,
                       "sha256": self.sha256, "byte_count": self.byte_count, "record": self.record.data()})


def validate_artifact(identity: DataIdentity, artifact_id: str, path: Path) -> ArtifactReceipt:
    if not isinstance(artifact_id, str) or not _INPUT.fullmatch(artifact_id):
        raise ContractError("artifact id is invalid")
    if not isinstance(path, Path) or path.is_symlink() or not path.is_file():
        raise ContractError("artifact must be a regular file")
    resolved = path.resolve(strict=True)
    data = {"artifact_id": artifact_id, "sha256": _sha256(resolved), "byte_count": resolved.stat().st_size}
    return ArtifactReceipt(identity, artifact_id, str(resolved), data["sha256"], data["byte_count"], FrozenRecord.from_dict(data))


@dataclass(frozen=True)
class ExecutionRequest:
    identity: DataIdentity
    image: str
    program: Path
    inputs: Mapping[str, Path]
    timeout_seconds: int = 20

    def __post_init__(self) -> None:
        if not isinstance(self.image, str) or not _IMAGE.fullmatch(self.image):
            raise ContractError("execution image must be pinned by sha256 digest")
        if not isinstance(self.timeout_seconds, int) or not 1 <= self.timeout_seconds <= 120:
            raise ContractError("execution timeout must be between 1 and 120 seconds")
        if not isinstance(self.inputs, Mapping) or not self.inputs:
            raise ContractError("execution needs one or more public input files")
        if not all(isinstance(key, str) and _INPUT.fullmatch(key) for key in self.inputs):
            raise ContractError("invalid input mount name")


@dataclass(frozen=True)
class ExecutionReceipt:
    identity: DataIdentity
    status: str
    artifact: ArtifactReceipt | None
    record: FrozenRecord

    @property
    def content_hash(self) -> str:
        return digest({"identity": self.identity.data(), "status": self.status,
                       "artifact": self.artifact.content_hash if self.artifact else None,
                       "record": self.record.data()})


class DockerExecutionBroker:
    """Execute Python only in Docker; every unavailable state is a typed receipt."""

    def __init__(self, allowed_roots: Sequence[Path], *, runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run) -> None:
        if not allowed_roots:
            raise ContractError("broker requires explicit public file roots")
        self._roots = tuple(self._checked_root(path) for path in allowed_roots)
        self._runner = runner

    @staticmethod
    def _is_reparse_path(path: Path) -> bool:
        """Treat Windows junctions and all symlinks as link traversal."""
        try:
            info = path.stat(follow_symlinks=False)
        except OSError:
            return False
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & reparse)

    @classmethod
    def _has_link_component(cls, path: Path) -> bool:
        cursor = path.absolute()
        while cursor != cursor.parent:
            if cls._is_reparse_path(cursor):
                return True
            cursor = cursor.parent
        return False

    @classmethod
    def _checked_root(cls, path: Path) -> Path:
        if not isinstance(path, Path) or ".." in path.parts or cls._is_reparse_path(path) or not path.is_dir():
            raise ContractError("allowed root must be a real directory")
        if cls._has_link_component(path):
            raise ContractError("allowed root cannot have a link or reparse parent")
        return path.resolve(strict=True)

    def _safe_file(self, path: Path) -> Path:
        if not isinstance(path, Path) or ".." in path.parts or self._is_reparse_path(path) or not path.is_file():
            raise ContractError("only regular files may be mounted")
        if self._has_link_component(path):
            raise ContractError("symlinked or reparse paths cannot be mounted")
        resolved = path.resolve(strict=True)
        if not any(resolved.is_relative_to(root) for root in self._roots):
            raise ContractError("mount path is outside the broker allowlist")
        return resolved

    @staticmethod
    def _mount_source(path: Path) -> str:
        value = str(path)
        # Docker's -v grammar is colon-delimited. On Windows the drive separator
        # is the sole permitted colon; commas are disallowed so no volume option
        # can be smuggled through a filename.
        if os.name == "nt":
            if not re.fullmatch(r"[A-Za-z]:[\\/][^,:]*", value):
                raise ContractError("unsafe Windows mount source")
        elif ":" in value or "," in value:
            raise ContractError("unsafe mount source")
        return value

    @staticmethod
    def _clip(value: bytes | str | None, limit: int) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        return value[-limit:]

    def execute(self, request: ExecutionRequest) -> ExecutionReceipt:
        try:
            program = self._safe_file(request.program)
            inputs = {key: self._safe_file(path) for key, path in request.inputs.items()}
            mounts = {key: self._mount_source(path) for key, path in inputs.items()}
            program_mount = self._mount_source(program)
        except ContractError as exc:
            return self._receipt(request.identity, "rejected", None, {"reason": str(exc)})
        try:
            artifact = validate_artifact(request.identity, "program", program)
        except (ContractError, OSError) as exc:
            return self._receipt(request.identity, "rejected", None, {"reason": f"program validation failed: {exc}"})
        name = "research-loop-" + digest({"task": request.identity.data(), "program": artifact.sha256, "time": time.time_ns()})[:20]
        argv = ["docker", "run", "--pull", "never", "--name", name, "--rm", "--network", "none", "--read-only",
                "--user", "1000:1000", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m", "--pids-limit", "128",
                "--memory", "1g", "--cpus", "1.0", "--cap-drop", "ALL", "--security-opt", "no-new-privileges"]
        for key in sorted(inputs):
            argv.extend(["-v", f"{mounts[key]}:/input/{key}:ro"])
        argv.extend(["-v", f"{program_mount}:/task/analysis.py:ro", request.image, "python3", "/task/analysis.py"])
        started = time.monotonic()
        try:
            completed = self._runner(argv, capture_output=True, timeout=request.timeout_seconds)
        except FileNotFoundError:
            return self._receipt(request.identity, "unavailable", artifact, {"reason": "docker executable unavailable", "argv": argv})
        except subprocess.TimeoutExpired as exc:
            cleanup = self._cleanup_container(name)
            return self._receipt(request.identity, "timed_out", artifact, {"argv": argv, "stdout": self._clip(exc.stdout, 12000), "stderr": self._clip(exc.stderr, 4000), "wall_seconds": round(time.monotonic() - started, 3), "cleanup": cleanup})
        except OSError as exc:
            return self._receipt(request.identity, "unavailable", artifact, {"reason": f"docker invocation failed: {exc}", "argv": argv})
        stderr = self._clip(completed.stderr, 4000)
        if completed.returncode and any(marker in stderr.lower() for marker in _DOCKER_INFRASTRUCTURE_ERRORS):
            status = "unavailable"
        else:
            status = "succeeded" if completed.returncode == 0 else "failed"
        return self._receipt(request.identity, status, artifact, {"argv": argv, "exit_code": completed.returncode,
                "stdout": self._clip(completed.stdout, 12000), "stderr": stderr,
                "wall_seconds": round(time.monotonic() - started, 3)})

    def _cleanup_container(self, name: str) -> dict[str, object]:
        """Only remove the digest-derived container name owned by this invocation."""
        argv = ["docker", "rm", "-f", name]
        try:
            result = self._runner(argv, capture_output=True, timeout=15)
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
            return {"attempted": True, "removed": False, "reason": str(exc)}
        return {"attempted": True, "removed": result.returncode == 0,
                "exit_code": result.returncode, "stderr": self._clip(result.stderr, 4000)}

    @staticmethod
    def _receipt(identity: DataIdentity, status: str, artifact: ArtifactReceipt | None, data: dict[str, object]) -> ExecutionReceipt:
        if status not in {"succeeded", "failed", "unavailable", "timed_out", "rejected"}:
            raise ContractError("unknown execution status")
        return ExecutionReceipt(identity, status, artifact, FrozenRecord.from_dict({"status": status, **data}))
