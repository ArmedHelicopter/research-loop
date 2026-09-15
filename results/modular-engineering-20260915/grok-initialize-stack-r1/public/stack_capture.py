"""Private bounded CDB stack capture for the known initialize-only child PID."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Mapping

CDB = Path(r"C:/Program Files (x86)/Windows Kits/10/Debuggers/x64/cdb.exe")
CDB_TIMEOUT_SECONDS = 20


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_module_labels(raw: bytes) -> list[str]:
    """Return only DLL basenames; raw stacks never leave the private directory."""
    return sorted({match.decode("ascii", "ignore").lower()
                   for match in re.findall(rb"(?i)\b[a-z0-9_.-]+\.dll\b", raw)})


def _stack_frame_count(raw: bytes) -> int:
    # CDB `k` prints one frame per line beginning with a thread-frame ordinal.
    return len(re.findall(rb"(?mi)^\s*[0-9a-f]+\s+[0-9a-f`]+", raw))


def capture_known_child_stacks(*, pid: int, private_root: Path,
                               expected_cdb_sha256: str) -> dict[str, Any]:
    """Attach only to the live child PID supplied by the initialize engine.

    `-pvr` is noninvasive/nonsuspending and `-pd` requests automatic detach.
    The command is fixed to stacks without arguments; it cannot issue a dump,
    execute a debugger shell, inspect memory, or target a name/pattern.
    """
    if type(pid) is not int or pid <= 0:
        raise ValueError("known child PID is malformed")
    if not CDB.is_file() or _sha(CDB) != expected_cdb_sha256:
        raise RuntimeError("CDB source pin differs")
    private_root.mkdir(parents=True, exist_ok=False)
    stack_log = private_root / "cdb.private.stack.log"
    stdout_path = private_root / "cdb.private.stdout.bin"
    stderr_path = private_root / "cdb.private.stderr.bin"
    command = [str(CDB), "-pvr", "-pd", "-p", str(pid), "-netsym:no", "-sins",
               "-noshell", "-logo", str(stack_log), "-c", "~* k; q"]
    environment = {"SystemRoot": os.environ["SystemRoot"], "WINDIR": os.environ["WINDIR"],
                   "COMSPEC": os.environ["COMSPEC"], "PATH": os.environ["PATH"],
                   "_NT_SYMBOL_PATH": "", "_NT_ALT_SYMBOL_PATH": "",
                   "_NT_DEBUGGER_EXTENSION_PATH": ""}
    started = time.monotonic()
    timed_out = False
    with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
            cwd=str(private_root), env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            exit_code = process.wait(timeout=CDB_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            # The 20-second limit is the point at which termination is signaled.
            # A following reap is recorded separately; it is not stack collection.
            timed_out = True
            process.kill()
            try:
                exit_code = process.wait(timeout=1)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("CDB did not exit after the 20-second capture limit") from exc
    raw_files = (stack_log, stdout_path, stderr_path)
    # Public data deliberately contains only labels/counts/status, never stack text,
    # pointers, addresses, arguments, process paths, or received data.
    labels = []
    line_count = 0
    frame_count = 0
    if stack_log.exists():
        raw = stack_log.read_bytes()
        line_count = raw.count(b"\n")
        labels = extract_module_labels(raw)
        frame_count = _stack_frame_count(raw)
    return {"schema": "grok130-cdb-stack-capture-v1", "known_child_pid": pid,
            "cdb_sha256": expected_cdb_sha256, "command_fixed": True,
            "noninvasive_nonsuspending_requested": True, "automatic_detach_requested": True,
            "remote_symbols_disabled": True, "arguments_or_memory_printed": False,
            "dump_created": False, "timeout_seconds": CDB_TIMEOUT_SECONDS,
            "timed_out": timed_out, "debugger_exit_code": exit_code,
            "debugger_elapsed_seconds": time.monotonic() - started,
            "capture_timeout_termination_signaled": timed_out,
            "private_raw_files": {path.name: {"exists": path.exists(),
                "sha256": _sha(path) if path.exists() else None,
                "bytes": path.stat().st_size if path.exists() else None} for path in raw_files},
            "public_module_labels": labels, "public_stack_line_count": line_count,
            "actual_stack_frame_count": frame_count,
            "detach_independently_observed": False}
