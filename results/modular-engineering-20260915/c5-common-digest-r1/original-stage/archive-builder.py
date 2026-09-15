"""Archive the closed C5 common-digest r1 deadline-interrupted engineering run.

Writes only a new public WORK stage and a new retained-private-evidence copy.
It never resumes the test, changes the immutable source worktree, or follows
runtime links/junctions.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

BASE = Path(r"E:/_ryanDev/AI/research-loop-modular")
WORK = BASE / "work"
SOURCE = BASE / "immutable-record-runtime"
PREFIX = WORK / "c5-common-digest-r1"
STAGE = WORK / "c5-common-digest-r1-archive-stage-r1"
PRIVATE = BASE / "retained-private-evidence" / "c5-common-digest-r1-runtime-r1"
CONFIG = WORK / "c5-common-digest-r1-watchdog-config.json"
JOURNAL = WORK / "c5-common-digest-r1-watchdog.jsonl"
BEFORE = WORK / "c5-common-digest-r1-before.json"
SOURCE_MEMBERS = WORK / "c5-common-digest-r1-source-members.json"
SOURCE_ZIP = WORK / "c5-common-digest-r1-sources.zip"
WATCHER = WORK / "watch_native_phase_deadline_r1.ps1"
CHUNK_BYTES = 24 * 1024 * 1024


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)


def json_new(path: Path, body: object) -> None:
    write_new(path, (json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def copy_original(path: Path, destination: Path) -> dict[str, object]:
    before = path.stat()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with path.open("rb") as source, destination.open("xb") as target:
        while raw := source.read(1024 * 1024):
            target.write(raw)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError(f"original changed while copying: {path}")
    os.utime(destination, ns=(before.st_atime_ns, before.st_mtime_ns))
    source_hash, dest_hash = sha_file(path), sha_file(destination)
    if source_hash != dest_hash:
        raise RuntimeError(f"copied bytes differ: {path}")
    return {"file": path.name, "bytes": before.st_size, "mtime_ns": before.st_mtime_ns, "sha256": source_hash}


def is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def listing() -> tuple[dict[str, tuple[int, int]], dict[str, str], list[str]]:
    files: dict[str, tuple[int, int]] = {}
    links: dict[str, str] = {}
    directories: list[str] = []
    for root, dirnames, names in os.walk(PREFIX, followlinks=False):
        current = Path(root)
        directories.append(current.relative_to(PREFIX).as_posix())
        for name in list(dirnames):
            path = current / name
            if is_link(path):
                links[path.relative_to(PREFIX).as_posix()] = os.readlink(path)
                dirnames.remove(name)
        for name in names:
            path = current / name
            if is_link(path):
                links[path.relative_to(PREFIX).as_posix()] = os.readlink(path)
                continue
            stat = path.stat()
            files[path.relative_to(PREFIX).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return dict(sorted(files.items())), dict(sorted(links.items())), sorted(directories)


def no_process_with_identity(rows: list[dict[str, object]]) -> bool:
    # Query only PIDs captured by the watchdog. A fresh recycled PID cannot pass
    # because creation ticks must also agree.
    clauses = " OR ".join(f"ProcessId = {int(row['pid'])}" for row in rows)
    command = ("Get-CimInstance Win32_Process -Filter '" + clauses + "' | "
               "Select-Object ProcessId,@{Name='creation_utc_ticks';Expression={$_.CreationDate.ToUniversalTime().Ticks}} | "
               "ConvertTo-Json -Compress")
    observed = subprocess.check_output(["powershell.exe", "-NoProfile", "-Command", command], text=True).strip()
    current = json.loads(observed) if observed else []
    if isinstance(current, dict):
        current = [current]
    return not any(now["ProcessId"] == old["pid"] and now["creation_utc_ticks"] == old["creation_utc_ticks"]
                   for now in current for old in rows)


def main() -> None:
    if STAGE.exists() or PRIVATE.exists():
        raise RuntimeError("new archive destinations must not already exist")
    config = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    events = [json.loads(line) for line in JOURNAL.read_text(encoding="utf-8-sig").splitlines()]
    inventory = next((row for row in events if row.get("event") == "deadline_inventory"), None)
    closed = events[-1] if events else None
    if (not inventory or not closed or closed.get("event") != "deadline_cleanup_recorded"
            or closed.get("remaining_observed_owned_processes") != []
            or inventory.get("observed_owned_docker_names") != []
            or any(row.get("absent_after_cleanup") is not True for row in closed.get("observed_owned_docker_cleanup", []))
            or not no_process_with_identity(inventory["processes"])):
        raise RuntimeError("watchdog closure is not proven")
    before = json.loads(BEFORE.read_bytes())
    members = json.loads(SOURCE_MEMBERS.read_bytes())
    if (before["commit"] != config["source"] or members["commit"] != before["commit"]
            or before["source_before"] != {row["path"]: row["sha256"] for row in members["members"]}
            or sha_file(SOURCE_ZIP) != members["archive_sha256"]):
        raise RuntimeError("frozen source descriptor mismatch")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=SOURCE).strip():
        raise RuntimeError("immutable source worktree is no longer clean")
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SOURCE, text=True).strip() != before["commit"]:
        raise RuntimeError("immutable source worktree commit differs")
    for path, expected in before["source_before"].items():
        if sha_file(SOURCE / path) != expected:
            raise RuntimeError(f"frozen source drift: {path}")
    with zipfile.ZipFile(SOURCE_ZIP) as archive:
        if archive.testzip() is not None or set(archive.namelist()) != set(before["source_before"]):
            raise RuntimeError("frozen source ZIP is not complete")
        for row in members["members"]:
            raw = archive.read(row["path"])
            if len(raw) != row["bytes"] or sha_bytes(raw) != row["sha256"]:
                raise RuntimeError(f"frozen source ZIP member differs: {row['path']}")
    # The watchdog killed pytest before its normal result wrapper could write a
    # closure or JUnit result. Preserve that absence rather than fabricating one.
    if Path(str(PREFIX) + "-closed.json").exists() or Path(str(PREFIX) + ".xml").exists():
        raise RuntimeError("interrupted run unexpectedly has a normal closure/JUnit artifact")
    files, links, directories = listing()
    checkpoint_path = PREFIX / "test_complete_common_train_con0" / "common-run" / "checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_bytes())
    counts: dict[str, int] = {}
    for row in checkpoint["rows"]:
        key = str(row["stage"]) + ":" + str(row["status"])
        counts[key] = counts.get(key, 0) + 1
    if counts != {"history_build:succeeded": 46, "target:succeeded": 57, "target:not_executed": 61}:
        raise RuntimeError("unexpected final checkpoint counts")
    # Public stage deliberately contains only closure metadata and the frozen
    # source bundle. All runtime originals, including synthetic key fixtures,
    # remain inside the retained private archive.
    STAGE.mkdir(parents=True, exist_ok=False)
    write_new(STAGE / ".gitattributes", b"** -text\n")
    originals = []
    for source in (CONFIG, JOURNAL, BEFORE, SOURCE_MEMBERS, SOURCE_ZIP, WATCHER, Path(__file__)):
        originals.append(copy_original(source, STAGE / ("archive-builder.py" if source == Path(__file__) else source.name)))
    readme = """# C5 common digest r1：截止归档暂存\n\n这是提交 `105dfcd321faa3245b9a1605515e1eb147d04c5f` 的隔离 C5 工程检查。watchdog 在冻结截止 `2026-09-15T08:56:20.622818+08:00` 后终止已观察的进程树；`deadline_cleanup_recorded` 记录没有残留已观察进程，也没有已观察 Docker 名称。\n\n最终 checkpoint 只有 46 个 history_build 成功、57 个 target 成功与 61 个 target 未执行（共 164 行）。正常的 JUnit 和 closed 回执没有形成；本归档不会伪造它们。该记录是 deadline-interrupted、未完成的工程证据，不是完整 C5 通过、模型效果、科学有效性、calibration 或 VAL 结论。\n\n公开暂存仅包含 watchdog/冻结源/元数据。`runtime-private-inventory.json` 与 `closure.json` 绑定私有原件副本；完整 runtime bytes（含测试私钥夹具）仅保留在 `retained-private-evidence`，且链接/junction 不会被跟随。\n"""
    write_new(STAGE / "README.md", readme.encode("utf-8"))
    runtime_members: list[dict[str, object]] = []
    groups: list[list[str]] = []
    group: list[str] = []; size = 0
    for name, (bytes_count, _) in files.items():
        if group and size + bytes_count > CHUNK_BYTES:
            groups.append(group); group = []; size = 0
        group.append(name); size += bytes_count
    if group:
        groups.append(group)
    PRIVATE.mkdir(parents=True, exist_ok=False)
    for index, names in enumerate(groups):
        zip_path = PRIVATE / f"runtime-{index:03d}.zip"
        with zipfile.ZipFile(zip_path, "x", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
            for name in names:
                source = PREFIX / name
                raw = source.read_bytes()
                stat = source.stat()
                if (len(raw), stat.st_mtime_ns) != files[name]:
                    raise RuntimeError(f"runtime original changed while copying: {name}")
                archive.writestr(name, raw)
                runtime_members.append({"path": name, "bytes": len(raw), "mtime_ns": stat.st_mtime_ns,
                                        "sha256": sha_bytes(raw), "archive": zip_path.name})
    if listing() != (files, links, directories):
        raise RuntimeError("runtime tree changed during private archive")
    for zip_path in PRIVATE.glob("runtime-*.zip"):
        expected = [row for row in runtime_members if row["archive"] == zip_path.name]
        with zipfile.ZipFile(zip_path) as archive:
            if archive.testzip() is not None or set(archive.namelist()) != {row["path"] for row in expected}:
                raise RuntimeError(f"runtime ZIP member set differs: {zip_path.name}")
            for row in expected:
                raw = archive.read(row["path"])
                if len(raw) != row["bytes"] or sha_bytes(raw) != row["sha256"]:
                    raise RuntimeError(f"runtime ZIP bytes differ: {row['path']}")
    json_new(PRIVATE / "runtime-members.json", runtime_members)
    json_new(PRIVATE / "runtime-links-not-followed.json", {"links": links, "directories": directories})
    private_manifest = {path.name: {"bytes": path.stat().st_size, "sha256": sha_file(path)}
                        for path in sorted(PRIVATE.iterdir()) if path.is_file()}
    json_new(PRIVATE / "private-manifest.json", private_manifest)
    closure = {"schema": "c5-common-digest-r1-deadline-closure-v1", "status": "deadline_interrupted_incomplete",
               "source_commit": before["commit"], "deadline": config["deadline"], "watchdog_events": [row["event"] for row in events],
               "watchdog_owned_tree_termination_exit": next(row for row in events if row["event"] == "owned_tree_termination")["exit_code"],
               "observed_owned_processes_absent": True, "observed_owned_docker_names": [],
               "unobserved_resource_absence_proven": False, "checkpoint_counts": counts,
               "expected_history_builds": config["expected_history_builds"], "expected_target_cells": config["expected_target_cells"],
               "actual_synthetic_main_calls": None, "actual_docker_attempts": None, "actual_scorer_invocations": None,
               "new_paid_calls": 0, "normal_junit_or_closed_receipt_present": False,
               "scientific_validated": False, "calibration_eligible": False, "validation_eligible": False}
    json_new(STAGE / "closure.json", closure)
    inventory = {"schema": "c5-common-digest-r1-private-runtime-inventory-v1", "private_root": str(PRIVATE),
                 "runtime_regular_files": len(runtime_members), "runtime_bytes": sum(row["bytes"] for row in runtime_members),
                 "runtime_archives": len(groups), "links_not_followed": links,
                 "private_manifest_sha256": sha_file(PRIVATE / "private-manifest.json")}
    json_new(STAGE / "runtime-private-inventory.json", inventory)
    public_files = sorted(path.name for path in STAGE.iterdir() if path.is_file())
    manifest = {"schema": "c5-common-digest-r1-public-stage-v1", "public_file_names": public_files + ["manifest.json"],
                "manifest_self_excluded_from_hashes": True,
                "files": [{"path": path.name, "bytes": path.stat().st_size, "sha256": sha_file(path)}
                          for path in sorted(STAGE.iterdir()) if path.is_file()],
                "closure": closure, "private_inventory": inventory}
    json_new(STAGE / "manifest.json", manifest)
    # Reopen every destination file and every source member after all writes.
    if listing() != (files, links, directories):
        raise RuntimeError("runtime tree changed before final verification")
    for row in runtime_members:
        with zipfile.ZipFile(PRIVATE / row["archive"]) as archive:
            raw = archive.read(row["path"])
        source = PREFIX / row["path"]
        if (sha_bytes(raw) != row["sha256"] or source.stat().st_mtime_ns != row["mtime_ns"]
                or sha_file(source) != row["sha256"]):
            raise RuntimeError(f"final original verification failed: {row['path']}")
    report = {"stage": str(STAGE), "private": str(PRIVATE), "stage_files": len(list(STAGE.iterdir())),
              "runtime_files": len(runtime_members), "runtime_bytes": sum(row["bytes"] for row in runtime_members),
              "runtime_archives": len(groups), "checkpoint_counts": counts,
              "stage_manifest_sha256": sha_file(STAGE / "manifest.json"),
              "private_manifest_sha256": sha_file(PRIVATE / "private-manifest.json"),
              "source_zip_sha256": sha_file(SOURCE_ZIP), "all_runtime_original_bytes_and_mtime_verified": True}
    print(json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
