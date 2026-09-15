"""Archive the closed r4 M4/M5 public-TRAIN attempt without rerunning it.

This script is intentionally inert on import.  It preserves the original run,
preparation, and private evidence byte-for-byte except for the pre-existing
credential exclusions supplied by the retention helper.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from collections import Counter
from pathlib import Path
import zipfile


BASE = Path("E:/_ryanDev/AI/research-loop-modular")
WORK = BASE / "work"
WORK_RECORDS = BASE / "WORK"
RUN = WORK / "actual-m4m5-headless-grok130-run-r4"
PREP = WORK / "actual-m4m5-headless-grok130-preparation-r4"
RAW_PRIVATE = BASE / "custody-private/actual-m4m5-headless-grok130-r4"
PUBLIC_ROOT = BASE / "artifact-evidence-provenance/results/modular-engineering-20260915"
DEST = PUBLIC_ROOT / "actual-m4m5-headless-grok130-r4-recovery-r1"
RETAINED = BASE / "retained-private-evidence/actual-m4m5-headless-grok130-r4-recovery-r1"
RETENTION_HELPER = WORK_RECORDS / "prepare_headless_lineage_full4_archive_r1.py"
RUNTIME_ARCHIVE = PUBLIC_ROOT / "headless-capture-timeout-repaired-checks-r2"
ACTOR = BASE / "headless-train-timeout-r1"
SOURCE_COMMIT = "d672c274ccb4da45605e2013ec5fcd4b3fcfa9c9"
NATIVE_SESSION_ID = 35109


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_bytes())


def write(path: Path, value: dict) -> None:
    with path.open("xb") as stream:
        stream.write((json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def stamp(path: Path) -> dict:
    raw = path.read_bytes()
    return {"sha256": sha(raw), "bytes": len(raw), "mtime_ns": path.stat().st_mtime_ns}


def process_metadata(path: Path) -> dict:
    body = read(path)
    required = {"pid", "started_at", "finished_at", "timeout_seconds", "timed_out", "failure",
                "process_exit_code", "owned_tree_closed"}
    assert required <= set(body)
    return {key: body[key] for key in required} | {"original_sha256": sha(path.read_bytes())}


def diagnostics(role: str, ledger_path: Path) -> dict:
    ledger = read(ledger_path)
    rows = []
    for index, call in enumerate(ledger["calls"], 1):
        native = Path(call["private_directory"])
        stem = f"{index:04d}-{call.get('slot', call.get('benchmark'))}"
        assert native == ledger_path.parent / "calls" / stem / "native" and native.is_relative_to(BASE)
        observer_path = native / "observer-receipt.json"
        process_path = native / "process.json"
        assert observer_path.is_file() and process_path.is_file()
        observer, process = read(observer_path), read(process_path)
        stream = observer["stream_inspection"]
        assert observer["prompt_process_launched"] is True
        assert process["owned_tree_closed"] is True and process["failure"] is None and process["process_exit_code"] == 0
        if call["status"] == "succeeded":
            assert observer["accepted"] is True and process["timed_out"] is False
            assert stream["accepted"] is True and isinstance(stream["usage"], dict)
            assert stream["cost_status"] == "server_reported" and isinstance(call.get("known_headless_main_usage"), dict)
        elif call["status"] == "unknown_or_failed":
            assert observer["accepted"] is False and process["timed_out"] is True
            assert stream["accepted"] is False and stream["usage"] is None and stream["cost_status"] == "unknown"
            assert call.get("known_headless_main_usage") is None
        else:
            raise AssertionError("r4 ledger contains an unsupported reservation status")
        rows.append({
            "role": role,
            "reservation_index": index,
            "slot_or_benchmark": call.get("slot", call.get("benchmark")),
            "ledger_status": call["status"],
            "main_dispatch_state": call["main_dispatch_state"],
            "prompt_process_launched": observer["prompt_process_launched"],
            "accepted": observer["accepted"],
            "known_main_usage": call.get("known_headless_main_usage"),
            "stream_usage_observed": stream["usage"] is not None,
            "stream_cost_status": stream["cost_status"],
            "stream_fault_count": len(stream["faults"]),
            "observer_sha256": sha(observer_path.read_bytes()),
            "process": process_metadata(process_path),
        })
    return {
        "role": role,
        "ledger_sha256": sha(ledger_path.read_bytes()),
        "reservations": len(rows),
        "statuses": dict(Counter(row["ledger_status"] for row in rows)),
        "known_main_tokens": ledger["known_main_tokens"],
        "usage_incomplete": ledger["usage_incomplete"],
        "calls": rows,
    }


def load_retention_helper():
    spec = importlib.util.spec_from_file_location("m4m5_retention_r4", RETENTION_HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    assert not DEST.exists() and not RETAINED.exists()
    assert ACTOR.is_dir() and RUNTIME_ARCHIVE.is_dir()
    start = WORK_RECORDS / "actual-m4m5-headless-grok130-r4-native-start.json"
    join = WORK_RECORDS / "actual-m4m5-headless-grok130-r4-native-join.json"
    driver_log = WORK_RECORDS / "actual-m4m5-headless-grok130-r4-driver.log"
    assert read(start)["session_id"] == read(join)["native_session_id"] == NATIVE_SESSION_ID
    joined = read(join)
    assert joined["source_commit"] == SOURCE_COMMIT
    assert joined["result"] == {"chunk_id": "4adbd5", "wall_time_seconds": 8e-7,
                                "exit_code": 0, "original_token_count": 0, "output": ""}
    assert read(driver_log) == {"stage": "closed", "exit_code": 0, "timed_out": False,
                                "source_and_inputs_unchanged": True, "summary_present": True}

    closure = read(RUN / "parent-closure.json")
    assert closure["source_and_inputs_unchanged"] is True
    assert closure["process"]["process_exit_code"] == 0 and closure["process"]["timed_out"] is False
    assert closure["process"]["owned_tree_closed"] is True and closure["process"]["timeout_seconds"] == 18000
    summary = read(RUN / "summary.json")
    receipt = read(RUN / "controller/controller-receipt.json")
    attempts = read(RUN / "controller/controller-attempt.json")
    prep = read(PREP / "preparation.json")
    assert prep["source_commit"] == summary["source_commit"] == SOURCE_COMMIT
    assert prep["labels_source_commit"] == SOURCE_COMMIT
    assert summary["status"] == receipt["status"] == "inconclusive"
    assert summary["cells"] == receipt["expected_cells"] == len(attempts["cells"]) == 8
    assert (summary["scored_cells"], summary["eligible_scored_cells"]) == (4, 0)
    assert (receipt["successful_cells"], receipt["failed_cells"], receipt["blocked_cells"]) == (4, 3, 1)
    assert Counter(row["status"] for row in attempts["cells"]) == {"succeeded": 4, "failed": 3, "blocked": 1}
    assert summary["validation_opened"] is False and receipt["pruned_cells"] == []
    assert prep["additional_paid_api_budget"] == 0
    assert prep["solver_timeout_seconds"] == prep["evaluator_timeout_seconds"] == 240
    assert prep["parent_timeout_seconds"] == 18000
    assert all(sha(Path(path).read_bytes()) == digest for path, digest in
               {**prep["source_pins"], **prep["input_pins"]}.items())

    roles = [diagnostics("solver", RUN / "solver-model/ledger.json"),
             diagnostics("evaluator", RAW_PRIVATE / "evaluator-model/ledger.json")]
    assert [row["reservations"] for row in roles] == [31, 5]
    assert [row["known_main_tokens"] for row in roles] == [220901, 26750]
    assert all(row["usage_incomplete"] is True for row in roles)
    assert roles[0]["statuses"] == {"succeeded": 30, "unknown_or_failed": 1}
    assert roles[1]["statuses"] == {"succeeded": 4, "unknown_or_failed": 1}
    failed = [call for role in roles for call in role["calls"] if call["ledger_status"] == "unknown_or_failed"]
    assert len(failed) == 2 and all(call["main_dispatch_state"] == "possibly_dispatched" for call in failed)
    assert all(call["stream_usage_observed"] is False and call["stream_cost_status"] == "unknown" for call in failed)
    finalization = RAW_PRIVATE / "scorer-worker.jsonl.headless-evaluator-finalization.jsonl"
    final_rows = [json.loads(line) for line in finalization.read_text(encoding="utf-8").splitlines()]
    assert [(row["status"], row.get("reason")) for row in final_rows] == [
        ("attempted", None), ("rejected", "provenance_replay_failed")]
    assert receipt["native_final_verification"]["reason"] == "native_original_replay_failed"
    assert receipt["evaluator_final_verification"]["score_eligible"] is False

    retention = load_retention_helper()
    originals = []
    for root, label in ((RUN, "run"), (PREP, "preparation"), (RAW_PRIVATE, "private")):
        originals.extend((label + "/" + path.relative_to(root).as_posix(), path)
                         for path in sorted(retention.regular_files(root)))
    public = {
        "summary.json": RUN / "summary.json",
        "controller-receipt.json": RUN / "controller/controller-receipt.json",
        "parent-closure.json": RUN / "parent-closure.json",
        "preparation.json": PREP / "preparation.json",
        "native-start.json": start,
        "native-join.json": join,
        "driver.log": driver_log,
        "runner-source.py": WORK / "run_actual_m4m5_headless_grok130_r4.py",
        "archive-helper.py": Path(__file__),
        "retention-helper-source.py": RETENTION_HELPER,
    }
    inputs = sorted(set([path for _, path in originals] + list(public.values())))
    before = {str(path): stamp(path) for path in inputs}
    RETAINED.mkdir(parents=True)
    zip_path = RETAINED / "original-run-preparation-private-without-credentials.zip"
    members = retention.add_zip(zip_path, ((name, path.read_bytes(), str(path)) for name, path in originals))
    with zipfile.ZipFile(zip_path) as archive:
        assert archive.testzip() is None and archive.namelist() == [row["path"] for row in members]
        for row in members:
            raw = archive.read(row["path"])
            assert sha(raw) == row["sha256"] == before[row["origin"]]["sha256"]
            assert len(raw) == row["byte_count"]
    assert before == {str(path): stamp(path) for path in inputs}
    retained = {
        "schema": "actual-m4m5-grok130-r4-retention-v1",
        "archive_path": str(zip_path), "archive_sha256": sha(zip_path.read_bytes()), "members": members,
        "excluded_credentials": retention.EXCLUSIONS, "pruned_reparse_paths": sorted(retention.PRUNED_LINKS),
        "inputs_before": before, "inputs_after": before,
    }
    write(RETAINED / "retention-manifest.json", retained)
    public["private-retention-manifest.json"] = RETAINED / "retention-manifest.json"

    assessment = {
        "schema": "closed-m4m5-train-r4-diagnostic-v1", "source_commit": SOURCE_COMMIT,
        "panel_digest": receipt["panel_digest"], "cells": {"expected": 8, "succeeded": 4, "failed": 3,
            "blocked": 1, "scored": 4, "eligible_scored": 0}, "roles": roles,
        "parent_process": process_metadata(RUN / "parent-process/process.json"),
        "finalization": {"path": str(finalization), "sha256": sha(finalization.read_bytes()),
            "status": "rejected", "reason": "provenance_replay_failed"},
        "cause": "Two independent native MAIN captures timed out after dispatch. Each is terminal with unknown usage; the subsequent provenance replay and evaluator-finalization rejections are conservative cascades, not evidence of a separate replay defect.",
        "source_archive_reference": {"path": str(RUNTIME_ARCHIVE),
            "status": "pre-existing headless-capture-timeout-repaired-checks-r2 archive; this archiver does not generate or replace it"},
        "evidence_limits": [
            "This is execution and retention evidence, not module-effect estimation.",
            "Prompt dispatch with absent settled usage cannot establish zero consumption or a zero charge.",
            "The two unknown reservations remain in the denominator and make score eligibility zero.",
            "No retry, regrade, data change, credential inclusion, or validation access is performed by this archive.",
            "Scientific effectiveness, calibration, and validation acceptance remain unproven.",
            "Title and all-opportunity settlement remains unknown; additional paid API budget is zero, not a settlement observation.",
        ],
        "scientific_effectiveness_proven": False, "validation_opened": False,
    }
    DEST.mkdir(parents=True)
    (DEST / ".gitattributes").write_bytes(b"* -text\n")
    for name, path in public.items():
        (DEST / name).write_bytes(path.read_bytes())
        assert (DEST / name).read_bytes() == path.read_bytes()
    write(DEST / "execution-diagnosis.json", assessment)
    (DEST / "README.md").write_text(
        "# M4/M5 Grok 1.0.30 public-TRAIN attempt r4\n\n"
        "The owned parent process closed with exit zero, but this eight-cell run is inconclusive: "
        "four cells succeeded, three failed, one was blocked, four were scored, and none were score-eligible. "
        "The solver retained 31 reservations and the evaluator retained five; each ledger has one timed-out, "
        "possibly-dispatched reservation with unknown usage. The final provenance and evaluator closure therefore "
        "reject eligibility. VAL was not opened.\n\n"
        "Raw prompts, responses, account observations, dataset content, intermediate artifacts, and source/input "
        "pins are retained privately with existing credentials excluded. The exact runtime source is referenced by "
        "the pre-existing [capture-timeout repaired archive](../headless-capture-timeout-repaired-checks-r2/README.md); "
        "this archive does not generate that source archive.\n\n"
        "This is execution evidence only. It does not establish scientific effectiveness, a score comparison, "
        "calibration, validation acceptance, or complete charge settlement.\n", encoding="utf-8")
    assert before == {str(path): stamp(path) for path in inputs}
    files = [{"path": path.name, "sha256": sha(path.read_bytes()), "bytes": path.stat().st_size}
             for path in sorted(DEST.iterdir())]
    write(DEST / "published-manifest.json", {"schema": "actual-m4m5-grok130-r4-public-v1", "files": files})
    print(json.dumps({"archive": str(DEST), "public_files": len(files) + 1, "private_originals": len(members),
                      "manifest_sha256": sha((DEST / "published-manifest.json").read_bytes())}))


if __name__ == "__main__":
    main()
