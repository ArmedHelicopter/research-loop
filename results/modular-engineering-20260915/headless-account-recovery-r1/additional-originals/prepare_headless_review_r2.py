"""Prepare, but never dispatch, the bounded r2 headless review diagnostic.

This is intentionally a preparation-only helper.  It carries the closed r1
allocation forward, freezes the v4 recovery configuration, and writes no run
output.  Running the resulting worker is a separate, explicit operation.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


WORK = Path(__file__).parent
TREE = WORK.parent / "headless-review-recovery-runtime"
CHECK = WORK / "headless-account-recovery-root-r1-closed.json"
ROOT = WORK / "headless-review-preparation-r2"
RUN = WORK / "headless-review-run-r2"
OLD_RUN = WORK / "headless-authoring-indexed-run-r1"
R1_RUN = WORK / "headless-review-run-r1"
R1_READBACK = WORK / "headless-review-independent-readback-r1.json"
R1_CONFIG = WORK / "headless-review-preparation-r1" / "worker-config.private.json"
R1_PARENT_CLOSURE = R1_RUN / "public-parent-closure.json"
ASSESSMENT = WORK / "headless-review-r2-allocation-assessment.md"
PARENT_RESULT_SHA256 = "86003a6b1d654fc03646aaf24c60cd51ebdb53a1dd7fe1ff0779d137f3fcaa71"
R1_READBACK_SHA256 = "275fde0086447697b169c105cb549196748fefd2317d17f705100ffa789666b1"
R1_CONFIG_SHA256 = "ae394ced8833f0b750c485a2a474682ded1ea786dbe2307449ed1fed0b357799"
RECOVERY = {"schema": "headless-account-read-recovery-v1", "max_attempts": 2}
CAPS = {"reviewer1": 36, "reviewer2": 36, "arbitrator": 36, "evaluator": 72}
SPENT = {"reviewer1": 5, "reviewer2": 5, "arbitrator": 1, "evaluator": 0}
REMAINING = {role: CAPS[role] - SPENT[role] for role in CAPS}
AUTHORIZED_ACCOUNT_BINDING = "b13ba3f652654cf9907b60161d7cd397e5edd8da74646e642e4105768d511c2e"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engineering-check-sha256", required=True,
                        help="SHA-256 of the frozen recovery root check; never infer this value")
    args = parser.parse_args()
    if len(args.engineering_check_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in args.engineering_check_sha256):
        raise SystemExit("engineering check SHA-256 must be 64 lowercase hexadecimal characters")
    return args


def account_binding(auth_path: Path) -> str:
    rows = [value for value in json.loads(auth_path.read_bytes()).values()
            if type(value) is dict and value.get("auth_mode") == "oidc"
            and value.get("oidc_issuer") == "https://auth.x.ai"
            and value.get("oidc_client_id") == "b1a00492-073a-47ea-816f-4c329264a828"]
    assert len(rows) == 1
    return hashlib.sha256(rows[0]["user_id"].encode("utf-8")).hexdigest()


def apply_cumulative_caps(policy: dict) -> None:
    """Materialize the r1-spent remainder in the new frozen policy."""
    policy["max_main_opportunities"] = 169
    policy["max_title_opportunities"] = 169
    policy["max_total_opportunities"] = 338
    for role, port in policy["ports"].items():
        assert role in REMAINING and port["max_calls"] == CAPS[role]
        port["max_calls"] = REMAINING[role]
    assert {role: policy["ports"][role]["max_calls"] for role in REMAINING} == REMAINING
    assert (policy["max_main_opportunities"], policy["max_title_opportunities"],
            policy["max_total_opportunities"]) == (169, 169, 338)


def main() -> None:
    args = parse_args()
    sys.path.insert(0, str(TREE))
    from evaluation.modular.diagnostic_material_authoring import own_sources, write_record
    from evaluation.modular.diagnostic_subscription import CONFIG_SCHEMA_V4, compile_inventory, load_private, sha
    from evaluation.modular.calibration_pilot_process import load_record
    from research_loop.modular.grok_acp_transport import EXECUTABLE_SHA256, diagnostic_config

    def desc(path: Path) -> dict[str, str]:
        return {"path": str(path), "sha256": sha(path)}

    # The check is a required, closed source gate.  The hash comes from the
    # caller so this helper never substitutes a guessed future root record.
    assert CHECK.is_file() and sha(CHECK) == args.engineering_check_sha256
    check = json.loads(CHECK.read_bytes())
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=TREE, text=True).strip()
    assert head == check["commit"] and check["exit_code"] == 0 and check["source_unchanged"]
    assert check["junit"]["failures"] == check["junit"]["errors"] == check["junit"]["skipped"] == 0
    assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=TREE).strip()
    assert not (TREE / "data").exists()
    assert all(sha(TREE / name) == pin for name, pin in check["source_after"].items())

    # Parent result, independent readback, and r1 config are immutable input
    # evidence.  The spent rejected reservation is included, never reused.
    parent_result = R1_RUN / "diagnostic-result.private.json"
    assert sha(parent_result) == PARENT_RESULT_SHA256
    assert sha(R1_READBACK) == R1_READBACK_SHA256
    assert sha(R1_CONFIG) == R1_CONFIG_SHA256
    parent_closure = json.loads(R1_PARENT_CLOSURE.read_bytes())
    assert parent_closure["diagnostic_result"] == {"path": str(parent_result), "sha256": PARENT_RESULT_SHA256}
    assert parent_closure["worker_config"] == {"path": str(R1_CONFIG), "sha256": R1_CONFIG_SHA256}
    assert parent_closure["worker_exit"] == 0 and parent_closure["owned_tree_closed"] is True
    assert ASSESSMENT.is_file()
    assert sum(SPENT.values()) == 11 and sum(REMAINING.values()) == 169
    assert all(REMAINING[role] == CAPS[role] - SPENT[role] for role in CAPS)
    assert not ROOT.exists() and not RUN.exists()

    outcome_path = OLD_RUN / "private-output" / "public-outcome.json"
    outcome = json.loads(outcome_path.read_bytes())
    assert sha(outcome_path) == "7ce822b54e46a7fa2fe9c796b29b2560f68403813753cd97a9cec56128589240"
    assert outcome["material_availability"] == {"ready": 26, "unresolved_material": 7, "not_applicable": 3}
    assert not outcome["review_dispatch_blocked"] and not outcome["calibration_eligible"] and not outcome["validation_eligible"]
    old_config_path = OLD_RUN / "private-output" / "review-compiled-config.private.json"
    assert sha(old_config_path) == "b3c2860176e9dd1526b2ca5f5b160cb8e7bdab6435c443a71f7593c385f03da3"
    old = json.loads(old_config_path.read_bytes())
    old_manifest = load_record(outcome["review_manifest"]).data()
    old_inventory = load_record(outcome["ready_review_inventory"]).data()
    assert old["manifest"] == outcome["review_manifest"] and old["materials"] == outcome["materials"]
    assert old["request_inventory"] == outcome["ready_review_inventory"]
    assert sha(Path(outcome["materials"]["path"])) == outcome["materials"]["sha256"]
    assert sha(Path(outcome["supports"]["path"])) == outcome["supports"]["sha256"]
    load_record(outcome["materials"]); load_record(outcome["supports"])

    old_preparation = WORK / "headless-authoring-indexed-preparation-r1" / "public-preparation.json"
    old_prep = json.loads(old_preparation.read_bytes())
    old_envelope = load_record(old_prep["authoring_envelope"]).data()
    assert old_envelope["tasks"] == old_manifest["tasks"]
    assert old_envelope["reference_store"] == old["reference_store"]
    assert outcome["authoring_envelope_sha256"] == old_prep["authoring_envelope"]["sha256"]
    auth_path = Path("C:/Users/Administrator/.grok/auth.json")
    assert old_prep["authorized_account_binding"] == AUTHORIZED_ACCOUNT_BINDING
    assert account_binding(auth_path) == AUTHORIZED_ACCOUNT_BINDING

    ROOT.mkdir()
    envelope = {
        "schema": "headless-diagnostic-review-allocation-envelope-v1",
        "parent": {"diagnostic_result": desc(parent_result), "independent_readback": desc(R1_READBACK),
                   "worker_config": desc(R1_CONFIG), "public_parent_closure": desc(R1_PARENT_CLOSURE)},
        "cumulative_main_caps": {**CAPS, "total_main": 180},
        "spent_main": {**SPENT, "total_main": 11},
        "remaining_main": {**REMAINING, "total_main": 169},
        "new_inventory_upper_bound": {"reviewer1": 26, "reviewer2": 26, "arbitrator": 26,
                                        "evaluator": 52, "total_main": 130},
        "rejected_parent_reservation_is_spent": True,
        "scope": "correlated TRAIN-only diagnostic review and scoring; not independent samples, formal calibration, validation, or scientific-effect evidence",
    }
    allocation_desc = write_record(ROOT / "allocation-envelope.json", envelope)

    # Retain original signed material bytes, task identities, and logical slot
    # identities.  v4 source pins and port digests are intentionally fresh.
    input_files = {name: str(path.absolute()) for name, path in own_sources().items()}
    assert set(input_files) == set(old_manifest["input_pins"]) | {"native_headless_code"}
    manifest = copy.deepcopy(old_manifest)
    manifest["input_pins"] = {name: sha(path) for name, path in input_files.items()}
    apply_cumulative_caps(manifest["policy"])
    assert manifest["tasks"] == old_manifest["tasks"]
    assert {key: value for key, value in manifest.items() if key not in {"input_pins", "policy"}} == {
        key: value for key, value in old_manifest.items() if key not in {"input_pins", "policy"}}
    assert (manifest["policy"]["max_main_opportunities"] == manifest["policy"]["max_title_opportunities"] == 169
            and manifest["policy"]["max_total_opportunities"] == 338)
    assert {role: port["max_calls"] for role, port in manifest["policy"]["ports"].items()} == REMAINING
    assert all({key: value for key, value in manifest["policy"]["ports"][role].items() if key != "max_calls"}
               == {key: value for key, value in old_manifest["policy"]["ports"][role].items() if key != "max_calls"}
               for role in REMAINING)
    assert all(port["timeout_seconds"] == 60 and port["main_output_cap"] == 2048
               and port["max_input_bytes"] == 262144 and port["observed_main_token_cap"] == 131072
               and port["max_retries"] == 0 for port in manifest["policy"]["ports"].values())
    manifest_desc = write_record(ROOT / "review-manifest.json", manifest)
    config = copy.deepcopy(old)
    config.update(schema=CONFIG_SCHEMA_V4, transport="headless", account_read_recovery=RECOVERY,
                  manifest=manifest_desc, input_files=input_files,
                  journal_path=str(RUN / "review.private.jsonl"), request_inventory=None, native_deployment=None)
    uncompiled = write_record(ROOT / "uncompiled-config.private.json", config)
    inventory_desc = compile_inventory(uncompiled, ROOT / "request-inventory.json")
    inventory = load_record(inventory_desc).data()
    counts = {role: sum(entry["role"] == role for entry in inventory["entries"])
              for role in manifest["policy"]["ports"]}
    assert counts == {"reviewer1": 26, "reviewer2": 26, "arbitrator": 26, "evaluator": 52}
    assert sum(counts.values()) == 130
    assert all(counts[role] <= REMAINING[role] for role in counts) and sum(counts.values()) <= 169
    identity_keys = ("slot_id", "role", "repeat")
    assert [{key: entry[key] for key in identity_keys} for entry in inventory["entries"]] == [
        {key: entry[key] for key in identity_keys} for entry in old_inventory["entries"]]

    executable = Path("C:/Users/Administrator/.grok/bin/grok.exe")
    assert sha(executable) == EXECUTABLE_SHA256
    frozen = dict(old_envelope["frozen_files"])
    for path, expected in frozen.items():
        assert sha(path) == expected
    frozen.update({str(TREE / name): pin for name, pin in check["source_after"].items()})
    for item in (desc(outcome_path), desc(old_config_path), outcome["materials"], outcome["supports"],
                 outcome["review_manifest"], outcome["ready_review_inventory"], old_prep["authoring_envelope"],
                 desc(OLD_RUN / "independent-readback.json"), desc(CHECK), desc(parent_result), desc(R1_READBACK), desc(R1_PARENT_CLOSURE),
                 desc(R1_CONFIG), desc(ASSESSMENT), desc(Path(__file__)), allocation_desc, manifest_desc, inventory_desc):
        frozen[item["path"]] = item["sha256"]
    frozen[str(executable)] = EXECUTABLE_SHA256
    slots = {}
    for entry in inventory["entries"]:
        native = ROOT / "native-slots" / entry["opportunity_id"]
        slot = {key: str(native / key) for key in ("cwd", "private_home", "private_profile")}
        for path in slot.values():
            Path(path).mkdir(parents=True, exist_ok=False)
        home = Path(slot["private_home"])
        shutil.copyfile(auth_path, home / "auth.json")
        assert account_binding(home / "auth.json") == AUTHORIZED_ACCOUNT_BINDING
        config_path = home / "config.toml"
        config_path.write_bytes(diagnostic_config(manifest["policy"]["ports"][entry["role"]]["main_output_cap"]).encode())
        frozen[str(config_path)] = sha(config_path)
        slots[entry["opportunity_id"]] = slot
    deployment = write_record(ROOT / "native-deployment.private.json", {
        "schema": "frozen-native-subscription-headless-deployment-v2", "executable": str(executable),
        "slots": slots, "frozen_files": frozen, "account_read_recovery": RECOVERY})
    config.update(request_inventory=inventory_desc, native_deployment=deployment)
    config_desc = write_record(ROOT / "worker-config.private.json", config)
    load_private(config_desc)
    assert all(sha(path) == pin for path, pin in frozen.items())
    assert all(sha(TREE / name) == pin for name, pin in check["source_after"].items())
    receipt = {
        "schema": "headless-diagnostic-review-preparation-v2", "source_commit": head,
        "engineering_check": desc(CHECK), "preparer": desc(Path(__file__)), "allocation_envelope": allocation_desc,
        "parent_result": desc(parent_result), "parent_independent_readback": desc(R1_READBACK),
        "parent_public_closure": desc(R1_PARENT_CLOSURE),
        "parent_worker_config": desc(R1_CONFIG), "allocation_assessment": desc(ASSESSMENT),
        "producer_outcome": desc(outcome_path), "producer_independent_readback": desc(OLD_RUN / "independent-readback.json"),
        "producer_manifest": outcome["review_manifest"], "consumer_manifest": manifest_desc,
        "producer_inventory": outcome["ready_review_inventory"], "consumer_inventory": inventory_desc,
        "worker_config": config_desc, "native_deployment": deployment, "materials": outcome["materials"],
        "supports": outcome["supports"], "recovery": RECOVERY, "material_availability": outcome["material_availability"],
        "ready_request_count": 130, "ready_role_counts": counts, "cumulative_main_caps": envelope["cumulative_main_caps"],
        "spent_main": envelope["spent_main"], "remaining_main": envelope["remaining_main"],
        "main_timeout_seconds": 60, "reasoning_effort": "low", "max_retries": 0, "model_calls": 0,
        "validation_access": False, "calibration_eligible": False, "additional_paid_api_budget": 0,
        "settled_additional_charge_usd": None, "authorized_account_binding": AUTHORIZED_ACCOUNT_BINDING,
        "auth_handling": "opaque private copy; contents never logged, hashed or published",
        "lineage": "correlated TRAIN-only recovery diagnostic; original material bytes/signatures, tasks, and slot identities retained; policy and source pins changed",
        "source_unchanged_after_preparation": True,
    }
    write_record(ROOT / "public-preparation.json", receipt)
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
