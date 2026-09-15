"""Prepare-only archive for the closed Grok initialize-stack diagnostic.

Run only after an independent reviewer chooses to archive the closed evidence.
It never launches Grok/CDB and never publishes raw stacks, logs, profile files,
or authentication material.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import zipfile
from pathlib import Path

BASE = Path(r"E:\_ryanDev\AI\research-loop-modular")
WORK = BASE / "work"
SOURCE = WORK / "grok130-initialize-stack-r1"
CDB_REPORT = WORK / "grok130-initialize-stack-r1-cdb-diagnosis-r1"
DEST = BASE / "artifact-evidence-provenance" / "results" / "modular-engineering-20260915" / "grok-initialize-stack-r1"
PRIVATE = BASE / "retained-private-evidence" / "grok-initialize-stack-r1"
HELPER = WORK / "prepare_headless_lineage_full4_archive_r1.py"
PREFIX = "grok130-initialize-stack-r1"
SESSION = 23777


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


def retention_module():
    spec = importlib.util.spec_from_file_location("initialize_stack_retention", HELPER)
    if spec is None or spec.loader is None:
        raise RuntimeError("retention helper is not loadable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    if DEST.exists() or PRIVATE.exists():
        raise SystemExit("refusing to overwrite archive destinations")
    if not SOURCE.is_dir() or not CDB_REPORT.is_dir():
        raise SystemExit("closed diagnostic roots are missing")
    start = load(WORK / f"{PREFIX}-native-start.json")
    join = load(WORK / f"{PREFIX}-native-join.json")
    closure = load(SOURCE / "closure.json")
    envelope = load(SOURCE / "envelope.json")
    result = closure.get("result", {})
    if (start.get("session_id") != SESSION or join.get("native_session_id") != SESSION
            or join.get("result", {}).get("exit_code") != 0 or result.get("faults") != ["timeout"]
            or result.get("elapsed_seconds") != 60.109000000025844 or result.get("response") is not None
            or result.get("initialize_writes_completed") != 1 or closure.get("model_prompt_writes") != 0
            or result.get("outbound_method_counts", {}).get("session/new") != 0
            or result.get("outbound_method_counts", {}).get("session/prompt") != 0
            or result.get("outbound_method_counts", {}).get("authenticate") != 0
            or result.get("outbound_method_counts", {}).get("_x.ai/billing") != 0
            or result.get("outbound_method_counts", {}).get("_x.ai/auto-topup-rule") != 0
            or closure.get("context_fault") is not None
            or not result.get("process_tree_closed") or not closure.get("source_unchanged")
            or not closure.get("global_auth_metadata_unchanged") or result.get("known_model_usage") is not None
            or result.get("settled_additional_charge_usd") is not None):
        raise SystemExit("closed initialize-only outcome differs from its retained receipt")
    cdb = closure.get("cdb_stack_capture", {})
    if (cdb.get("known_child_pid") != 66484 or cdb.get("debugger_exit_code") != 2147942487
            or cdb.get("actual_stack_frame_count") != 0 or cdb.get("status") != "capture_success_not_established"):
        raise SystemExit("CDB diagnosis receipt differs")
    if load(SOURCE / "parser-smoke-result.json") != {"exit_code": 0, "synthetic_input_only": True,
                                                        "schema": "grok130-cdb-parser-smoke-v1", "grok_or_cdb_started": False}:
        raise SystemExit("parser smoke receipt differs")
    if load(SOURCE / "preparation-manifest.json").get("schema") != "grok130-initialize-stack-preparation-v2":
        raise SystemExit("v2 preparation receipt differs")
    if load(SOURCE / "preparation-manifest.v1.json").get("schema") != "grok130-initialize-stack-preparation-v1":
        raise SystemExit("v1 preparation receipt differs")

    retention = retention_module()
    originals = sorted(retention.regular_files(SOURCE))
    cdb_public = sorted(path for path in retention.regular_files(CDB_REPORT) if path.suffix in {".json", ".md"})
    public_names = ("driver.py", "init_engine.py", "stack_capture.py", "parser_smoke.py", "README.md",
                    "launch-reservation.json", "envelope.json", "closure.json", "help-receipt.json",
                    "agent-help.stdout.txt", "agent-help.stderr.txt", "cdb-help-result.json", "cdb-help.txt",
                    "cdb-help.stderr.txt", "preparation-manifest.v1.json", "preparation-manifest.json", "parser-smoke-result.json")
    public_inputs = [SOURCE / name for name in public_names] + [WORK / f"{PREFIX}-native-start.json",
                     WORK / f"{PREFIX}-native-join.json", Path(__file__), HELPER]
    if any(not path.is_file() for path in public_inputs):
        raise SystemExit("declared public diagnostic receipt is missing")
    inputs = sorted({*originals, *cdb_public, *public_inputs})
    before = {str(path): stamp(path) for path in inputs}

    PRIVATE.mkdir(parents=True)
    private_zip = PRIVATE / "originals-without-credentials.zip"
    private_members = retention.add_zip(private_zip, ((f"stack-run/{path.relative_to(SOURCE).as_posix()}", path.read_bytes(), str(path)) for path in originals))
    with zipfile.ZipFile(private_zip) as archive:
        if archive.testzip() is not None or archive.namelist() != [row["path"] for row in private_members]:
            raise SystemExit("private archive CRC or member order differs")
        for row in private_members:
            raw = archive.read(row["path"])
            if sha(raw) != row["sha256"] or len(raw) != row["byte_count"] or sha(raw) != before[row["origin"]]["sha256"]:
                raise SystemExit("private archive bytes differ")
    if before != {str(path): stamp(path) for path in inputs}:
        raise SystemExit("original bytes or mtimes changed during private retention")
    write_new(PRIVATE / "retention-manifest.json", {"schema": "grok-initialize-stack-private-retention-v1",
        "archive": {"path": str(private_zip), "sha256": sha(private_zip.read_bytes()), "bytes": private_zip.stat().st_size},
        "members": private_members, "excluded_credentials": retention.EXCLUSIONS,
        "pruned_reparse_paths": sorted(retention.PRUNED_LINKS), "inputs_before": before, "inputs_after": before})

    DEST.mkdir(parents=True)
    (DEST / ".gitattributes").write_bytes(b"* -text\n")
    copies = {f"public/{path.name}": path for path in public_inputs}
    copies.update({f"cdb-source-only/{path.name}": path for path in cdb_public})
    for name, source in copies.items():
        target = DEST / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if target.read_bytes() != source.read_bytes():
            raise SystemExit("public evidence copy differs")
    frozen = envelope.get("frozen_files", {})
    source_rows = []
    with zipfile.ZipFile(DEST / "frozen-python-sources.zip", "x", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for origin, expected_hash in sorted(frozen.items()):
            path = Path(origin)
            if path.suffix != ".py":
                continue
            raw = path.read_bytes()
            if sha(raw) != expected_hash:
                raise SystemExit("frozen Python source hash differs")
            member = "source/" + path.name
            if any(row["member"] == member for row in source_rows):
                raise SystemExit("ambiguous frozen Python source basename")
            archive.writestr(member, raw)
            source_rows.append({"member": member, "origin": str(path), "sha256": expected_hash, "bytes": len(raw)})
    with zipfile.ZipFile(DEST / "frozen-python-sources.zip") as archive:
        if archive.testzip() is not None or archive.namelist() != [row["member"] for row in source_rows]:
            raise SystemExit("frozen source ZIP CRC or member order differs")
        for row in source_rows:
            raw = archive.read(row["member"])
            if sha(raw) != row["sha256"] or len(raw) != row["bytes"]:
                raise SystemExit("frozen source member bytes differ")
    write_new(DEST / "frozen-source-members.json", {"schema": "grok-initialize-stack-frozen-source-v1",
        "members": source_rows, "zip_sha256": sha((DEST / "frozen-python-sources.zip").read_bytes())})
    (DEST / "README.md").write_text("""# Grok initialize stack diagnostic r1

The original native session 23777 joined with exit code 0, but the diagnostic itself did not initialize successfully:
one initialize write received no response by the 60.109-second deadline. The driver exited 0 after closing its owned process tree.
There were zero session/new, session/prompt, authenticate, and billing RPC writes; no prompt was sent. Known model usage and settlement
remain unknown. The result is therefore a closed no-response diagnostic, not a successful startup or a zero-usage claim.

The retained CDB attempt observed known child PID 66484 and exited 2147942487 because Netsym treated `n` as an invalid switch.
It captured no stack frames; this is explicitly `capture_success_not_established`, not a debugger-derived localization. The separate
CDB source-only diagnosis files preserve that correction without publishing raw debugger streams.

Public material contains helpers, frozen Python sources, help/preparation/closure/parser receipts, native start/join receipts, and
metadata-only CDB diagnosis. Raw native logs, stdout/stderr, stacks, profile/home material, and auth.json are not public. Private
retention excludes credential-shaped files and records exclusions. Both preparation v1/v2 and the parser-smoke receipt are retained.

This used no actual private/VAL benchmark input, no model prompt, and no paid API. It does not establish source/binary equivalence,
OS isolation, authentication health, a root cause, scientific validity, or a repair. No C5 or M4/M5 experiment was retried.
""", encoding="utf-8", newline="\n")
    manifest = {"schema": "grok-initialize-stack-published-files-v1", "files": [
        {"path": path.relative_to(DEST).as_posix(), "sha256": sha(path.read_bytes()), "bytes": path.stat().st_size}
        for path in sorted(DEST.rglob("*")) if path.is_file() and path.name != "published-manifest.json"
    ]}
    write_new(DEST / "published-manifest.json", manifest)
    for row in manifest["files"]:
        raw = (DEST / row["path"]).read_bytes()
        if sha(raw) != row["sha256"] or len(raw) != row["bytes"]:
            raise SystemExit("published manifest bytes differ")
    if before != {str(path): stamp(path) for path in inputs}:
        raise SystemExit("original bytes or mtimes changed during public archival")
    print(json.dumps({"public_archive": str(DEST), "private_archive": str(PRIVATE),
        "private_noncredential_members": len(private_members), "public_files": len(manifest["files"]) + 1}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
