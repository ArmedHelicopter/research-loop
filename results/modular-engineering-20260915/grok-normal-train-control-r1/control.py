"""Prepare or execute one isolated normal headless TRAIN opportunity.

`prepare` is side-effect free outside WORK and copies one already-exported
public TRAIN request.  `execute` is deliberately separate and terminal: it
reserves the control before normal transport/account reads, dispatches at most
one prompt, and never retries a model opportunity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from datetime import datetime, timezone


SCRIPT = Path(__file__).resolve()
if SCRIPT.name == "control.py":
    ROOT = SCRIPT.parent
    WORK = ROOT.parent
else:
    WORK = SCRIPT.parent
    ROOT = WORK / "grok-normal-train-control-r1"
RUNTIME = WORK.parent / "actual-m4m5-headless-runtime-r1"
M4_PREP = WORK / "actual-m4m5-headless-preparation-r1"
ORIGINAL_REQUEST = (WORK / "actual-m4m5-headless-run-r1" / "solver-model" / "calls"
                    / "0001-m4_plan" / "request.private.json")
EXECUTABLE = Path("C:/Users/Administrator/.grok/bin/grok.exe")
AUTH = Path("C:/Users/Administrator/.grok/auth.json")
EXECUTABLE_SHA256 = "bf43dc75f5478a106eab1e86d422c963e4dbe9666cf14dab363733d27bf1e672"
EXPECTED_ROOT = {"control.py", "manifest.json", "request.public.json"}


def sha(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def metadata(path: Path | str) -> dict:
    stat = Path(path).stat()
    return {"bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def write_new(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def read(path: Path) -> dict:
    return json.loads(path.read_bytes())


def prepare() -> None:
    if ROOT.exists():
        raise RuntimeError("control root already exists; never overwrite or retry it")
    prep = read(M4_PREP / "preparation.json")
    controller = M4_PREP / "controller.json"
    if (prep.get("source_commit") != "2113371268b30411712273623371cbcf49e0ccc8"
            or not ORIGINAL_REQUEST.is_file()
            or sha(EXECUTABLE) != EXECUTABLE_SHA256):
        raise RuntimeError("frozen M4/M5 source/request or production executable differs")
    request = read(ORIGINAL_REQUEST)
    if (set(request) != {"schema", "task", "lock_digest", "objective", "slot", "instruction",
                         "context", "module_context", "execution_feedback"}
            or request.get("schema") != "public-model-request-v1"
            or request.get("slot") != "m4_plan"
            or request.get("execution_feedback") != []):
        raise RuntimeError("selected original is not an unmodified public TRAIN m4_plan request")
    schemas = read(controller).get("schemas")
    if not isinstance(schemas, dict) or not isinstance(schemas.get("m4_plan"), dict):
        raise RuntimeError("frozen M4/M5 m4_plan schema unavailable")
    runtime_pins = prep.get("source_pins")
    if not isinstance(runtime_pins, dict) or runtime_pins.get(str(EXECUTABLE.resolve())) != EXECUTABLE_SHA256:
        raise RuntimeError("frozen M4/M5 source manifest lacks production executable binding")
    if any(sha(path) != digest for path, digest in runtime_pins.items()):
        raise RuntimeError("frozen M4/M5 source input drift")
    ROOT.mkdir()
    control = ROOT / "control.py"
    request_copy = ROOT / "request.public.json"
    shutil.copyfile(Path(__file__), control)
    shutil.copyfile(ORIGINAL_REQUEST, request_copy)
    if control.read_bytes() != Path(__file__).read_bytes() or request_copy.read_bytes() != ORIGINAL_REQUEST.read_bytes():
        raise RuntimeError("control copy binding differs")
    inputs = {
        str(control.resolve()): sha(control),
        str(request_copy.resolve()): sha(request_copy),
        str(ORIGINAL_REQUEST.resolve()): sha(ORIGINAL_REQUEST),
        str((M4_PREP / "preparation.json").resolve()): sha(M4_PREP / "preparation.json"),
        str(controller.resolve()): sha(controller),
        str(EXECUTABLE.resolve()): EXECUTABLE_SHA256,
    }
    write_new(ROOT / "manifest.json", {
        "schema": "grok-normal-train-control-preparation-v1",
        "execution_performed": False,
        "source_commit": prep["source_commit"],
        "runtime_root": str(RUNTIME.resolve()),
        "production_executable": {"path": str(EXECUTABLE.resolve()), "sha256": EXECUTABLE_SHA256},
        "input_pins": inputs,
        "runtime_source_pins": runtime_pins,
        "request": {"original_path": str(ORIGINAL_REQUEST.resolve()), "sha256": sha(ORIGINAL_REQUEST),
                    "copied_path": str(request_copy.resolve()), "slot": "m4_plan", "domain": "train"},
        "schema_digest": sha(controller),
        "limits": {"model_opportunities": 1, "model_retries": 0, "prompt_timeout_seconds": 60,
                   "main_output_cap": 2048, "observed_main_token_cap": 131072,
                   "input_byte_cap": 262144, "validation_opened": False,
                   "api_key_route_permitted": False, "billing_or_login_change_permitted": False},
        "known_limits": {"title_and_all_opportunity_settlement": "unknown",
                           "scientific_effectiveness_proven": False,
                           "formal_calibration": "not_performed"},
    })
    print(json.dumps({"prepared": str(ROOT), "model_opportunities": 1, "native_dispatches": 0,
                      "validation_opened": False}), flush=True)


def execute() -> None:
    if {p.name for p in ROOT.iterdir()} != EXPECTED_ROOT:
        raise RuntimeError("control root is not fresh; never launch a modified or previously attempted root")
    manifest = read(ROOT / "manifest.json")
    if manifest.get("schema") != "grok-normal-train-control-preparation-v1" or manifest.get("execution_performed") is not False:
        raise RuntimeError("unexpected execution manifest")
    if any(sha(path) != digest for path, digest in manifest["input_pins"].items()):
        raise RuntimeError("control input pin differs")
    if any(sha(path) != digest for path, digest in manifest["runtime_source_pins"].items()):
        raise RuntimeError("runtime source pin differs")
    if sha(EXECUTABLE) != EXECUTABLE_SHA256:
        raise RuntimeError("production executable drift")
    request_path = ROOT / "request.public.json"
    request = read(request_path)
    if sha(request_path) != manifest["request"]["sha256"] or request.get("slot") != "m4_plan":
        raise RuntimeError("public TRAIN request binding differs")
    write_new(ROOT / "launch-reservation.json", {
        "schema": "grok-normal-train-control-reservation-v1", "created_at": datetime.now(timezone.utc).isoformat(),
        "model_opportunities": 1, "model_retries": 0, "prompt_timeout_seconds": 60,
        "validation_opened": False, "api_key_route_permitted": False,
        "billing_or_login_change_permitted": False,
        "note": "Normal transport performs its existing read-only account pre/postflight; this control makes no billing or login change.",
    })
    auth_before = metadata(AUTH)
    private_home, private_profile, public_cwd = ROOT / "private-home", ROOT / "private-profile", ROOT / "public-cwd"
    private_home.mkdir(); private_profile.mkdir(); public_cwd.mkdir()
    shutil.copyfile(AUTH, private_home / "auth.json")
    if metadata(AUTH) != auth_before:
        raise RuntimeError("global auth metadata changed during opaque copy")
    sys.path.insert(0, str(RUNTIME))
    from research_loop.modular.contracts import FrozenRecord
    from research_loop.modular.grok_headless_train_solver import GrokHeadlessTrainModelPort
    controller = read(M4_PREP / "controller.json")
    schemas = {"m4_plan": controller["schemas"]["m4_plan"]}
    port = GrokHeadlessTrainModelPort(
        executable=EXECUTABLE, work_root=ROOT / "control-model", private_home=private_home,
        private_profile=private_profile, public_cwd=public_cwd, frozen_files=manifest["runtime_source_pins"],
        max_calls=1, schemas=schemas, slot_output_caps={"m4_plan": 2048},
        slot_input_byte_caps={"m4_plan": 262144}, observed_main_token_cap=131072,
        account_read_recovery={"schema": "headless-account-read-recovery-v1", "max_attempts": 2},
    )
    response = None
    error_type = None
    try:
        response = port(FrozenRecord.from_dict(request))
    except Exception as error:
        error_type = type(error).__name__
    ledger = ROOT / "control-model" / "ledger.json"
    closure = {
        "schema": "grok-normal-train-control-closure-v1",
        "status": "succeeded" if response is not None else "terminal_unknown_or_failed",
        "request_sha256": sha(request_path), "response_sha256": response.content_hash if response else None,
        "error_type": error_type, "ledger": {"path": str(ledger), "sha256": sha(ledger)} if ledger.exists() else None,
        "auth_metadata_before": auth_before, "auth_metadata_after": metadata(AUTH),
        "global_auth_metadata_unchanged": metadata(AUTH) == auth_before,
        "source_unchanged": all(sha(path) == digest for path, digest in manifest["runtime_source_pins"].items()),
        "validation_opened": False, "scientific_effectiveness_proven": False,
        "title_and_all_opportunity_settlement": "unknown",
    }
    write_new(ROOT / "closure.json", closure)
    print(json.dumps({"closure": str(ROOT / "closure.json"), "status": closure["status"],
                      "response_observed": response is not None, "source_unchanged": closure["source_unchanged"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "execute"))
    action = parser.parse_args().action
    if action == "prepare":
        prepare()
    else:
        execute()
