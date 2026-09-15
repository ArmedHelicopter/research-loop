"""Archive the closed synthetic P0 custody-audit check without rerunning it.

The helper is intentionally unexecuted when prepared. It retains raw test-run
material privately, publishes only source/test receipts and metadata, and never
opens benchmark, VAL, or credential inputs.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

BASE = Path(r"E:\_ryanDev\AI\research-loop-modular")
WORK = BASE / "work"
PREFIX = "p0-custody-audit-check-r1"
COMMIT = "35be4696bbd11ae30e785d09d070c994a1ad2990"
SESSION = 97843
RUN_ROOT = WORK / PREFIX
DEST = BASE / "artifact-evidence-provenance" / "results" / "modular-engineering-20260915" / "p0-custody-audit-r1"
PRIVATE = BASE / "retained-private-evidence" / "p0-custody-audit-r1"
RETENTION_HELPER = WORK / "prepare_headless_lineage_full4_archive_r1.py"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def stamp(path: Path) -> dict[str, int | str]:
    raw = path.read_bytes()
    return {"sha256": sha(raw), "bytes": len(raw), "mtime_ns": path.stat().st_mtime_ns}


def load(path: Path) -> dict:
    return json.loads(path.read_bytes())


def write_new(path: Path, value: dict) -> None:
    with path.open("xb") as stream:
        stream.write((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _retention_module():
    spec = importlib.util.spec_from_file_location("p0_retention", RETENTION_HELPER)
    if spec is None or spec.loader is None:
        raise RuntimeError("retention helper is not loadable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    if DEST.exists() or PRIVATE.exists():
        raise SystemExit("refusing to overwrite an archive destination")
    if not RUN_ROOT.is_dir():
        raise SystemExit("closed P0 run root is missing")
    before = load(WORK / f"{PREFIX}-before.json")
    closed = load(WORK / f"{PREFIX}-closed.json")
    members = load(WORK / f"{PREFIX}-source-members.json")
    started = load(WORK / f"{PREFIX}-native-start.json")
    joined = load(WORK / f"{PREFIX}-native-join.json")
    junit_path = WORK / f"{PREFIX}.xml"
    log_path = WORK / f"{PREFIX}.log"
    source_zip = WORK / f"{PREFIX}-sources.zip"
    if (before.get("commit") != COMMIT or closed.get("commit") != COMMIT or members.get("commit") != COMMIT
            or joined.get("native_session_id") != SESSION or joined.get("source_commit") != COMMIT
            or joined.get("result", {}).get("exit_code") != 0 or closed.get("exit_code") != 0
            or before.get("source_before") != closed.get("source_after") or not closed.get("source_unchanged")
            or closed.get("new_paid_calls") != 0):
        raise SystemExit("closed P0 receipt binding differs")
    if started.get("result", started).get("session_id") != SESSION:
        raise SystemExit("native start does not bind joined P0 session")
    if sha(junit_path.read_bytes()) != closed.get("report_sha256"):
        raise SystemExit("JUnit hash differs from closed receipt")
    suites = list(ET.parse(junit_path).getroot().iter("testsuite"))
    junit = {name: sum(int(row.get(name, 0)) for row in suites) for name in ("tests", "failures", "errors", "skipped")}
    if junit != closed.get("junit") or junit != {"tests": 3, "failures": 0, "errors": 0, "skipped": 0}:
        raise SystemExit("JUnit counts differ from closed receipt")
    if sha(source_zip.read_bytes()) != members.get("archive_sha256"):
        raise SystemExit("source ZIP hash differs from source-member receipt")
    with zipfile.ZipFile(source_zip) as archive:
        if archive.testzip() is not None or archive.namelist() != [row["path"] for row in members["members"]]:
            raise SystemExit("source ZIP member order or CRC differs")
        for row in members["members"]:
            raw = archive.read(row["path"])
            if sha(raw) != row["sha256"] or len(raw) != row["bytes"]:
                raise SystemExit("source ZIP member bytes differ")
    if before["source_before"] != {row["path"]: row["sha256"] for row in members["members"]}:
        raise SystemExit("source-member receipt does not bind pre-run sources")

    retention = _retention_module()
    originals = sorted(retention.regular_files(RUN_ROOT))
    metadata = [WORK / f"{PREFIX}{suffix}" for suffix in ("-before.json", "-closed.json", "-source-members.json", "-sources.zip", ".xml", ".log", "-native-start.json", "-native-join.json")]
    inputs = sorted({*originals, *metadata, Path(__file__), RETENTION_HELPER})
    input_before = {str(path): stamp(path) for path in inputs}

    PRIVATE.mkdir(parents=True)
    private_zip = PRIVATE / "run-originals-without-credentials.zip"
    private_members = retention.add_zip(private_zip, ((f"run/{path.relative_to(RUN_ROOT).as_posix()}", path.read_bytes(), str(path)) for path in originals))
    with zipfile.ZipFile(private_zip) as archive:
        if archive.testzip() is not None or archive.namelist() != [row["path"] for row in private_members]:
            raise SystemExit("private ZIP member order or CRC differs")
        for row in private_members:
            raw = archive.read(row["path"])
            if sha(raw) != row["sha256"] or len(raw) != row["byte_count"] or sha(raw) != input_before[row["origin"]]["sha256"]:
                raise SystemExit("private ZIP member bytes differ")
    if input_before != {str(path): stamp(path) for path in inputs}:
        raise SystemExit("input bytes or mtimes changed during private retention")
    write_new(PRIVATE / "retention-manifest.json", {
        "schema": "p0-custody-audit-private-retention-v1", "run_root": str(RUN_ROOT),
        "archive": {"path": str(private_zip), "sha256": sha(private_zip.read_bytes()), "bytes": private_zip.stat().st_size},
        "members": private_members, "excluded_credentials": retention.EXCLUSIONS,
        "pruned_reparse_paths": sorted(retention.PRUNED_LINKS), "inputs_before": input_before, "inputs_after": input_before,
    })

    DEST.mkdir(parents=True)
    (DEST / ".gitattributes").write_bytes(b"* -text\n")
    public = {
        "before.json": WORK / f"{PREFIX}-before.json", "closed.json": WORK / f"{PREFIX}-closed.json",
        "source-members.json": WORK / f"{PREFIX}-source-members.json", "source-exact.zip": source_zip,
        "junit.xml": junit_path, "pytest.log": log_path, "native-start.json": WORK / f"{PREFIX}-native-start.json",
        "native-join.json": WORK / f"{PREFIX}-native-join.json", "archive-helper.py": Path(__file__),
        "retention-helper-source.py": RETENTION_HELPER, "private-retention-manifest.json": PRIVATE / "retention-manifest.json",
    }
    for name, source in public.items():
        shutil.copyfile(source, DEST / name)
        if (DEST / name).read_bytes() != source.read_bytes():
            raise SystemExit("public copy bytes differ")
    (DEST / "README.md").write_text("""# P0 custody audit check r1

This directory retains the closed synthetic check of the auditor-only P0 custody-state snapshot reader.
The run joined native session 97843 with exit code 0; the JUnit receipt records 3 passing tests and no new paid calls.
The check used synthetic validation identities and synthetic signed receipts only. It did not read actual private custody state,
benchmark payloads, VAL inputs, or credentials, and it made no model or paid API call.

The reader checks caller-pinned state bytes, deterministic custody metadata allocation replay, and an optional independently retained
signed lease receipt. It records receipt absence without inventing issuance. It is a snapshot check, not a complete custody history,
external-custodian or calibration-authority proof, operating-system isolation proof, scientific validation, or a real private/VAL audit.

The full noncredential test-root originals are retained privately. Public files contain the frozen source ZIP, start/join receipts,
JUnit, test log, and archive manifests; no raw runtime sidecars or private test-state records are published.
""", encoding="utf-8", newline="\n")
    published = {"schema": "p0-custody-audit-published-files-v1", "files": [
        {"path": path.name, "sha256": sha(path.read_bytes()), "bytes": path.stat().st_size}
        for path in sorted(DEST.iterdir()) if path.name != "published-manifest.json"
    ]}
    write_new(DEST / "published-manifest.json", published)
    for row in published["files"]:
        raw = (DEST / row["path"]).read_bytes()
        if sha(raw) != row["sha256"] or len(raw) != row["bytes"]:
            raise SystemExit("published manifest byte verification failed")
    if input_before != {str(path): stamp(path) for path in inputs}:
        raise SystemExit("input bytes or mtimes changed during public archival")
    print(json.dumps({"public_archive": str(DEST), "private_archive": str(PRIVATE),
                      "retained_noncredential_originals": len(private_members),
                      "published_files": len(published["files"]) + 1}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
