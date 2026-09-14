"""Build the bounded, read-only C5 checkpoint-cache evidence stage."""

from __future__ import annotations

import hashlib
import json
import shutil
import stat
import sys
import zipfile
from pathlib import Path


BASE = Path(r"E:\_ryanDev\AI\research-loop-modular")
WORK = BASE / "work"
STAGE = WORK / "c5-checkpoint-cache-archive-stage-r1"

PROFILE = WORK / "c5-verifier-profile-r1" / "actual-history-target.pstats"

RUNS = {
    "isolated-405e": {
        "prefix": WORK / "c5-checkpoint-plan-cache",
        "stem": "frozen-check",
        "commit": "405e7b0d8554598a2176749ba51b56bac6939607",
        "runtime_test_root": None,
    },
    "isolated-ab77": {
        "prefix": WORK / "c5-checkpoint-plan-cache",
        "stem": "history-target-frozen",
        "commit": "ab77a0ca1f6f0d7d86b9749c7ff3567cac9c40ae",
        "runtime_test_root": WORK / "c5-checkpoint-plan-cache" / "history-target-frozen" / "test_actual_history_target_pip0",
    },
    "root-a1db": {
        "prefix": WORK,
        "stem": "c5-checkpoint-cache-root-r1",
        "commit": "a1db763ad1119d058e3c285f1dab6d8237d71eac",
        "runtime_test_root": WORK / "c5-checkpoint-cache-root-r1" / "test_actual_history_target_pip0",
    },
}

FULL_CASES = {
    "isolated-ab77-history-target": WORK / "c5-checkpoint-plan-cache" / "history-target-frozen" / "test_actual_history_target_pip0",
    "root-a1db-history-target": WORK / "c5-checkpoint-cache-root-r1" / "test_actual_history_target_pip0",
    "root-a1db-cached-status": WORK / "c5-checkpoint-cache-root-r1" / "test_checkpoint_rows_are_froze0",
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_raw(source: Path, destination: Path) -> dict[str, object]:
    if not source.is_file() or source.is_symlink():
        raise RuntimeError(f"expected regular source file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if digest(source) != digest(destination):
        raise RuntimeError(f"raw copy changed bytes: {source}")
    return {"source": str(source), "bytes": destination.stat().st_size, "sha256": digest(destination)}


def runtime_directories(test_root: Path) -> list[Path]:
    stages = test_root / "common-run" / "stages"
    if not stages.is_dir():
        raise RuntimeError(f"missing exact common-run stages root: {stages}")
    directories = sorted(path / "runtime" for path in stages.iterdir() if path.is_dir() and (path / "runtime").is_dir())
    if len(directories) != 2:
        raise RuntimeError(f"expected exactly two selected common-run runtime directories, found {len(directories)} under {stages}")
    return directories


def write_runtime_zip(label: str, test_root: Path) -> dict[str, object]:
    directories = runtime_directories(test_root)
    records: list[dict[str, object]] = []
    zip_path = STAGE / f"{label}-actual-runtime.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for runtime in directories:
            for item in sorted(runtime.rglob("*")):
                if item.is_symlink():
                    raise RuntimeError(f"refusing symlink in selected runtime: {item}")
                if item.is_dir():
                    continue
                if not item.is_file():
                    raise RuntimeError(f"refusing non-regular runtime entry: {item}")
                arcname = item.relative_to(test_root).as_posix()
                archive.write(item, arcname)
                records.append({"member": arcname, "bytes": item.stat().st_size, "sha256": digest(item)})
    records.sort(key=lambda row: str(row["member"]))
    members_path = STAGE / f"{label}-actual-runtime-members.json"
    members_path.write_text(json.dumps({"test_root": str(test_root), "selected_runtime_directories": [str(p) for p in directories], "members": records}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "zip": zip_path.name,
        "zip_bytes": zip_path.stat().st_size,
        "zip_sha256": digest(zip_path),
        "members": len(records),
        "member_bytes": sum(int(row["bytes"]) for row in records),
        "member_inventory": members_path.name,
        "selected_runtime_directories": [str(p) for p in directories],
    }


def write_case_zip(label: str, test_root: Path) -> dict[str, object]:
    if not test_root.is_dir() or test_root.is_symlink():
        raise RuntimeError(f"expected regular selected synthetic test root: {test_root}")
    records: list[dict[str, object]] = []
    zip_path = STAGE / f"{label}-full-case.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for item in sorted(test_root.rglob("*")):
            if item.is_symlink():
                raise RuntimeError(f"refusing symlink in selected case: {item}")
            if item.is_dir():
                continue
            if not item.is_file():
                raise RuntimeError(f"refusing non-regular case entry: {item}")
            arcname = item.relative_to(test_root).as_posix()
            archive.write(item, arcname)
            records.append({"member": arcname, "bytes": item.stat().st_size, "sha256": digest(item)})
    records.sort(key=lambda row: str(row["member"]))
    members_path = STAGE / f"{label}-full-case-members.json"
    members_path.write_text(json.dumps({"test_root": str(test_root), "fixture_classification": "synthetic retained test case", "members": records}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "zip": zip_path.name,
        "zip_bytes": zip_path.stat().st_size,
        "zip_sha256": digest(zip_path),
        "members": len(records),
        "member_bytes": sum(int(row["bytes"]) for row in records),
        "member_inventory": members_path.name,
        "test_root": str(test_root),
    }


def closed_source_unchanged(path: Path) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("source_unchanged") is True


def stage_inventory() -> list[dict[str, object]]:
    files = []
    for item in sorted(STAGE.rglob("*")):
        if item.is_dir() or item.name == "stage-manifest.json":
            continue
        if item.is_symlink() or not stat.S_ISREG(item.stat().st_mode):
            raise RuntimeError(f"refusing non-regular stage entry: {item}")
        files.append({"path": item.relative_to(STAGE).as_posix(), "bytes": item.stat().st_size, "sha256": digest(item)})
    return files


def main() -> None:
    augment = sys.argv[1:] == ["--augment-full-cases"]
    if (STAGE / "stage-manifest.json").exists() and not augment:
        raise RuntimeError(f"refusing to overwrite completed stage: {STAGE}")

    originals: dict[str, object] = {}
    for label, run in RUNS.items():
        destination = STAGE / "originals" / label
        copied: dict[str, object] = {}
        for suffix in ("before.json", "closed.json", "source-members.json", "sources.zip", "xml"):
            filename = f"{run['stem']}.{suffix}" if suffix == "xml" else f"{run['stem']}-{suffix}"
            source = Path(run["prefix"]) / filename
            copied[suffix] = copy_raw(source, destination / source.name)
        if not closed_source_unchanged(Path(run["prefix"]) / f"{run['stem']}-closed.json"):
            raise RuntimeError(f"source was not unchanged for {label}")
        originals[label] = {"commit": run["commit"], "source_unchanged": True, "files": copied}

    profile = copy_raw(PROFILE, STAGE / "originals" / "profile" / PROFILE.name)
    profile_command = {
        "status": "partial_profile_incomplete",
        "pstats": PROFILE.name,
        "command_reconstructed_from_recorded_execution": [
            str(WORK / "custody-root-venv" / "Scripts" / "python.exe"), "-m", "cProfile", "-o", str(PROFILE), "-m", "pytest",
            "tests/test_joint_train_runtime.py::test_actual_history_target_pipeline_with_full_catalogue",
            "--basetemp", str(WORK / "c5-verifier-profile-r1" / "pytest"), "-q",
        ],
        "note": "No original standalone helper was retained. This command record is reconstructed, and is not represented as an original helper.",
        "measurement": "106873119 calls in 107.661 seconds before deliberate bounded stop; not a completed test result.",
    }
    (STAGE / "originals" / "profile" / "profile-command-reconstructed.json").write_text(json.dumps(profile_command, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    runtimes = {}
    for label in ("isolated-ab77", "root-a1db"):
        runtimes[label] = write_runtime_zip(label, RUNS[label]["runtime_test_root"])

    full_cases = {label: write_case_zip(label, test_root) for label, test_root in FULL_CASES.items()}

    summary = """# C5 checkpoint-plan cache evidence stage\n\nThe cache precomputes only immutable planned checkpoint rows at executor construction. It does not cache filesystem, frozen-protocol, dependency, provider, allocation, or status observations. This stage contains synthetic retained test evidence only.\n\nThe `actual-history-target.pstats` profile is incomplete: it was deliberately stopped after 107.661 seconds, so it is a bounded cost observation and not a passing test result. No original profile helper exists; its separately labeled command record is reconstructed.\n\nThe full-case ZIPs preserve each selected synthetic test directory, including checkpoint, plan/protocol, stage/provider-ledger, trace, input-binding, and cached-status evidence. Fixture-private filenames are retained because these cases use synthetic providers and no actual credentials/API authentication were present. The narrower runtime ZIPs are derivative extracts of the full cases and are not independent samples. The stage does not make a full-grid performance claim and did not change live immutable-record-runtime source.\n"""
    (STAGE / "SUMMARY.md").write_text(summary, encoding="utf-8")

    files = stage_inventory()
    manifest = {
        "stage": "c5-checkpoint-cache-archive-stage-r1",
        "scope": "bounded synthetic checkpoint-cache evidence archive",
        "source_change_claim": "pure immutable planned-row derivation only; no live immutable-record-runtime changes; no full-grid effect claim",
        "profile": profile,
        "originals": originals,
        "actual_runtime_archives": runtimes,
        "full_case_archives": full_cases,
        "archive_relationship": "runtime archives are derivative extracts of the full selected case archives and are not independent samples",
        "stage_files_excluding_manifest": files,
        "stage_file_count_excluding_manifest": len(files),
        "stage_bytes_excluding_manifest": sum(int(row["bytes"]) for row in files),
    }
    (STAGE / "stage-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
