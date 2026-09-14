"""Build a bounded evidence stage for the synthetic headless adapter review."""
from __future__ import annotations

import hashlib
import json
import shutil
import stat
import zipfile
from pathlib import Path


WORK = Path(r"E:\_ryanDev\AI\research-loop-modular\work")
STAGE = WORK / "headless-review-adapter-archive-stage-r1"
ROOT_STEM = "headless-review-adapter-root-r1"
ISOLATED = WORK / "headless-subscription-pilot-r6" / "pytest"
CASES = {
    "positive": ISOLATED / "test_headless_subscription_por0" / "source",
    "binding-rejection": ISOLATED / "test_headless_rejection_preser0" / "source",
    "private-request-mutation": ISOLATED / "test_headless_rejection_preser1" / "source",
    "target-rejection": ISOLATED / "test_headless_rejection_preser2" / "source",
}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def raw_copy(source: Path, target: Path) -> dict:
    if source.is_symlink() or not source.is_file():
        raise RuntimeError(f"expected a regular original file: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    if sha(source) != sha(target):
        raise RuntimeError(f"raw source bytes changed: {source}")
    return {"source": str(source), "bytes": target.stat().st_size, "sha256": sha(target)}


def selected_case_files(source: Path) -> list[Path]:
    journal = source / "private-journal.jsonl"
    headless = source / "private-journal.jsonl.headless"
    if not journal.is_file() or not headless.is_dir():
        raise RuntimeError(f"missing retained synthetic journal evidence: {source}")
    files = [journal]
    for item in sorted(headless.rglob("*")):
        if item.is_symlink():
            raise RuntimeError(f"refusing linked synthetic artifact: {item}")
        if item.is_file():
            files.append(item)
    if any(item.name.startswith("key-") or item.name == "auth.json" for item in files):
        raise RuntimeError("selected evidence unexpectedly includes authentication material")
    return files


def zip_case(label: str, source: Path) -> dict:
    members = []
    target = STAGE / f"isolated-{label}-synthetic-journals.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for item in selected_case_files(source):
            name = item.relative_to(source).as_posix()
            archive.write(item, name)
            members.append({"member": name, "bytes": item.stat().st_size, "sha256": sha(item)})
    inventory = STAGE / f"isolated-{label}-synthetic-journals-members.json"
    inventory.write_text(json.dumps({"source": str(source), "selection": "private journal and headless producer journal only; excludes auth/profile/key copies", "members": members}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"zip": target.name, "zip_bytes": target.stat().st_size, "zip_sha256": sha(target),
            "members": len(members), "member_bytes": sum(row["bytes"] for row in members),
            "member_inventory": inventory.name, "source": str(source)}


def main() -> None:
    if any(item.name != "archive-helper.py" for item in STAGE.iterdir()):
        raise RuntimeError("stage already contains data")
    originals = {}
    for suffix in ("-before.json", "-closed.json", "-source-members.json", "-sources.zip", ".xml"):
        source = WORK / f"{ROOT_STEM}{suffix}"
        originals[source.name] = raw_copy(source, STAGE / "root-frozen-originals" / source.name)
    cases = {label: zip_case(label, source) for label, source in CASES.items()}
    summary = {
        "stage": "headless-review-adapter-archive-stage-r1",
        "scope": "synthetic headless producer, PrivateSubscriptionPorts, and DiagnosticPilot adapter evidence",
        "commits": {"isolated_final": "afb118bad3a921ce8679852db2ab4e35e47287e8", "root_final": "a334cd63fbb61f767b34656bb10844ac0d73e692"},
        "integration_note": "The earlier e87d9a0a conflict was resolved to the exact afb118ba final test version.",
        "test_claim": "Synthetic only; no API calls and no VAL. Isolated focused pilot run retained five passing tests; no JUnit XML or standalone stdout record was retained.",
        "root_frozen_originals": originals,
        "isolated_synthetic_journal_archives": cases,
        "exclusions": "No real authoring/review private directories, auth copies, profile trees, or key files are archived.",
    }
    files = []
    for item in sorted(STAGE.rglob("*")):
        if item.is_dir() or item.name == "stage-manifest.json":
            continue
        if item.is_symlink() or not stat.S_ISREG(item.stat().st_mode):
            raise RuntimeError(f"refusing non-regular staged item: {item}")
        files.append({"path": item.relative_to(STAGE).as_posix(), "bytes": item.stat().st_size, "sha256": sha(item)})
    summary["stage_files_excluding_manifest"] = files
    summary["stage_file_count_excluding_manifest"] = len(files)
    summary["stage_bytes_excluding_manifest"] = sum(row["bytes"] for row in files)
    (STAGE / "stage-manifest.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
