"""One bounded ACP initialize-only diagnostic.  No session or prompt is sent."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
SOURCE_HOME = pathlib.Path(
    r"E:\_ryanDev\AI\research-loop-modular\work\actual-m4m5-headless-run-r1"
    r"\solver-model\calls\0001-m4_plan\native-home"
)
EXE = pathlib.Path(r"C:\Users\Administrator\.grok\bin\grok.exe")
SAVED_SOURCE = pathlib.Path(
    r"E:\_ryanDev\AI\research-loop-modular\work\grok-supported-route-source-r1\headless.rs"
)
INPUT_HOME = ROOT / "private-input-home-opaque"
RUNTIME_HOME = ROOT / "private-runtime-home"
PRIVATE = ROOT / "private"
PUBLIC_CWD = ROOT / "public-cwd"
TIMEOUT_SECONDS = 20


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def manifest(root: pathlib.Path) -> tuple[list[dict], list[dict]]:
    files: list[dict] = []
    excluded: list[dict] = []
    for p in sorted(root.rglob("*"), key=lambda x: x.as_posix()):
        rel = p.relative_to(root).as_posix()
        if p.is_symlink():
            raise RuntimeError(f"refusing symlink/reparse source: {rel}")
        if not p.is_file():
            continue
        s = p.stat()
        entry = {"path": rel, "bytes": s.st_size, "mtime_ns": s.st_mtime_ns}
        if p.name.lower() == "auth.json" or p.suffix.lower() == ".key":
            # Credential contents are deliberately neither parsed nor hashed.
            excluded.append(entry)
        else:
            entry["sha256"] = sha256(p)
            files.append(entry)
    return files, excluded


def ensure_empty(path: pathlib.Path) -> None:
    if path.exists():
        raise RuntimeError(f"refusing to reuse diagnostic path: {path}")


def main() -> int:
    for p in (INPUT_HOME, RUNTIME_HOME, PRIVATE, PUBLIC_CWD):
        ensure_empty(p)
    if not SOURCE_HOME.is_dir() or not EXE.is_file() or not SAVED_SOURCE.is_file():
        raise RuntimeError("required frozen input missing")

    source_files_before, credential_exclusions = manifest(SOURCE_HOME)
    INPUT_HOME.parent.mkdir(parents=True, exist_ok=True)
    # Opaque file copy: no credential value is parsed or emitted.
    shutil.copytree(SOURCE_HOME, INPUT_HOME, copy_function=shutil.copy2)
    input_files, input_exclusions = manifest(INPUT_HOME)
    if source_files_before != input_files or credential_exclusions != input_exclusions:
        raise RuntimeError("opaque input copy manifest mismatch")

    preflight = {
        "kind": "acp_initialize_only",
        "source_home": str(SOURCE_HOME),
        "opaque_input_home": str(INPUT_HOME),
        "credential_content_read_or_emitted": False,
        "credential_named_exclusions": credential_exclusions,
        "noncredential_file_manifest": input_files,
        "pinned_executable": {"path": str(EXE), "sha256": sha256(EXE)},
        "saved_headless_source": {"path": str(SAVED_SOURCE), "sha256": sha256(SAVED_SOURCE)},
        "documented_entrypoint": [str(EXE), "agent", "stdio"],
        "deadline_seconds": TIMEOUT_SECONDS,
        "prohibited_after_initialize": ["session/new", "prompt", "model", "evaluator", "VAL", "Docker"],
        "created_at_epoch": time.time(),
    }
    (ROOT / "frozen-prelaunch.json").write_text(json.dumps(preflight, indent=2, sort_keys=True), encoding="utf-8")

    # Copy from the frozen opaque input so the process cannot modify that input.
    shutil.copytree(INPUT_HOME, RUNTIME_HOME, copy_function=shutil.copy2)
    PRIVATE.mkdir()
    PUBLIC_CWD.mkdir()
    private_home = ROOT / "private-home"
    appdata = ROOT / "private-appdata"
    localappdata = ROOT / "private-localappdata"
    temp = ROOT / "private-temp"
    for p in (private_home, appdata, localappdata, temp):
        p.mkdir()
    env = os.environ.copy()
    env.update({
        "GROK_HOME": str(RUNTIME_HOME),
        "HOME": str(private_home),
        "USERPROFILE": str(private_home),
        "HOMEPATH": "\\private-home",
        "APPDATA": str(appdata),
        "LOCALAPPDATA": str(localappdata),
        "TEMP": str(temp),
        "TMP": str(temp),
        "GROK_DISABLE_API_KEY_AUTH": "1",
        "GROK_DISABLE_AUTOUPDATER": "1",
        "GROK_MEMORY": "false",
        "GROK_SUBAGENTS": "false",
        "GROK_TITLE_REFRESH": "false",
        "GROK_TURN_SUMMARY": "false",
        "GROK_WORKFLOWS": "false",
    })
    safe_env = {k: env[k] for k in sorted(env) if k.startswith("GROK_")}
    # This is the one request.  No subsequent ACP message is constructed.
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": 1,
            "clientCapabilities": {"fs": {}, "terminal": False},
            "meta": {
                "clientType": "headless",
                "clientVersion": "acp-initialize-diagnostic-r1",
                "startupHints": {"nonInteractive": True, "skipGitStatus": True, "skipProjectLayout": True},
            },
        },
    }
    command = [str(EXE), "agent", "--no-leader", "stdio"]
    command_safe = {"command": command, "cwd": str(PUBLIC_CWD), "grok_env": safe_env}
    (ROOT / "command.safe.json").write_text(json.dumps(command_safe, indent=2, sort_keys=True), encoding="utf-8")
    started = time.time()
    p = subprocess.Popen(
        command, cwd=str(PUBLIC_CWD), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    timed_out = False
    close_method = None
    try:
        stdout, stderr = p.communicate((json.dumps(request, separators=(",", ":")) + "\n").encode("utf-8"), timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        timed_out = True
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        close_method = "taskkill_owned_tree"
        stdout, stderr = p.communicate(timeout=10)
    finished = time.time()
    out = PRIVATE / "stdio.stdout.bin"
    err = PRIVATE / "stdio.stderr.bin"
    out.write_bytes(stdout)
    err.write_bytes(stderr)
    receipt = {
        "kind": "acp_initialize_only",
        "pid": p.pid,
        "started_at_epoch": started,
        "finished_at_epoch": finished,
        "elapsed_seconds": finished - started,
        "deadline_seconds": TIMEOUT_SECONDS,
        "timed_out": timed_out,
        "owned_tree_close_method": close_method,
        "exit_code": p.returncode,
        "request_count": 1,
        "sent_methods": ["initialize"],
        "session_new_sent": False,
        "prompt_sent": False,
        "model_selected": False,
        "evaluator_called": False,
        "settlement": "unknown",
        "usage": "unknown",
        "stdout": {"bytes": len(stdout), "sha256": sha256(out)},
        "stderr": {"bytes": len(stderr), "sha256": sha256(err)},
    }
    (ROOT / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    source_files_after, _ = manifest(SOURCE_HOME)
    (ROOT / "source-home-before-after.json").write_text(json.dumps({
        "unchanged_noncredential_files": source_files_before == source_files_after,
        "before": source_files_before,
        "after": source_files_after,
    }, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
