"""Read-only independent readback for a closed v4 headless review run.

This utility intentionally does not construct PrivateSubscriptionPorts or launch
any model/account process.  It writes one metadata-only report outside the run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def retained_rejected_response(path: Path, receipt: dict) -> dict:
    """A postflight rejection may retain output bytes without exposing output."""
    from research_loop.modular.contracts import FrozenRecord
    if not path.is_file():
        if receipt.get('response_sha256') is not None:
            raise ValueError('rejected receipt names absent retained response')
        return {'present': False, 'sha256': None, 'consumed': False}
    raw = path.read_bytes()
    record = FrozenRecord.from_dict(json.loads(raw))
    if raw != record.encoded.encode('utf-8') or sha(raw) != receipt.get('response_sha256'):
        raise ValueError('rejected retained response bytes differ from receipt')
    return {'present': True, 'sha256': sha(raw), 'consumed': False}


def descriptor(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if set(value) == {"path", "sha256"}:
        return value
    for key in ("worker_config_descriptor", "worker_config", "config_descriptor"):
        if isinstance(value.get(key), dict) and set(value[key]) == {"path", "sha256"}:
            return value[key]
    raise ValueError("descriptor file does not contain a path/sha256 descriptor")


def metadata(paths: list[Path]) -> dict[str, dict[str, int | str]]:
    result = {}
    for root in paths:
        if root.is_file():
            items = [root]
        elif root.is_dir():
            items = [item for item in root.rglob("*") if item.is_file()]
        else:
            raise ValueError(f"missing input: {root}")
        for item in items:
            stat = item.stat()
            row = {"bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}
            # The r2 run root contains no auth/key material.  Hash every raw
            # run artifact before and after the readback.
            row["sha256"] = sha(item.read_bytes())
            result[str(item)] = row
    return result


def journal_rows(path: Path, digest):
    previous = "0" * 64
    rows = []
    for sequence, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        row = json.loads(line)
        if row.get("sequence") != sequence or row.get("previous") != previous or row.get("digest") != digest({k: row[k] for k in ("sequence", "previous", "event", "data")}):
            raise ValueError("private journal chain mismatch")
        previous = row["digest"]
        rows.append(row)
    if not rows:
        raise ValueError("empty private journal")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-descriptor", required=True, type=Path,
                        help="JSON descriptor or public preparation record containing it")
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--parent-closure", required=True, type=Path)
    parser.add_argument("--preparation", required=True, type=Path)
    parser.add_argument("--journal", required=True, type=Path)
    parser.add_argument("--headless-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists() or args.output.parent == args.headless_root or args.headless_root in args.output.parents:
        raise SystemExit("output must be a new file outside native evidence")
    if not args.parent_closure.is_file():
        raise SystemExit("run is not closed: parent closure is absent")
    if not args.result.is_file():
        raise SystemExit("run is not closed: result file is absent")

    # Import only after all paths are fixed.  No transport entrypoint is called.
    import evaluation.modular.calibration_pilot as calibration_pilot
    import evaluation.modular.diagnostic_subscription as subscription
    import research_loop.modular.grok_headless_transport as headless
    from evaluation.modular.calibration_pilot_process import load_record
    from research_loop.modular.contracts import FrozenRecord
    from evaluation.modular.calibration_pilot import verify
    from research_loop.ontology import canonical, digest

    def forbidden(*_args, **_kwargs):
        raise RuntimeError("readback helper forbids transport/model execution")
    subscription.run_headless_diagnostic = forbidden
    headless.run_headless_diagnostic = forbidden

    closure = json.loads(args.parent_closure.read_text(encoding="utf-8"))
    if (closure.get("schema") != "headless-diagnostic-review-parent-closure-v2"
            or closure.get("worker_exit") != 0 or closure.get("parent_timeout") is not False
            or closure.get("owned_tree_closed") is not True or closure.get("source_unchanged") is not True):
        raise SystemExit("r2 parent closure does not establish a closed successful worker")
    config_descriptor = descriptor(args.config_descriptor)
    prepared = json.loads(args.preparation.read_text(encoding="utf-8"))
    if (prepared.get("schema") != "headless-diagnostic-review-preparation-v2"
            or prepared.get("worker_config") != config_descriptor):
        raise SystemExit("r2 preparation/config descriptor differs")
    config = load_record(config_descriptor)
    before = metadata([args.result, args.journal, args.headless_root, args.config_descriptor, args.parent_closure, args.preparation])
    raw_result = args.result.read_bytes()
    if closure.get("diagnostic_result") != {"path": str(args.result), "sha256": sha(raw_result)}:
        raise SystemExit("parent closure result descriptor differs")
    result = FrozenRecord.from_dict(json.loads(raw_result.decode("utf-8")))
    c, manifest, signed_materials, authorities, resolver, _guard = subscription.load_private(config_descriptor)
    report = verify(result, role="diagnostic", subject=manifest.content_hash,
                    authority_id=authorities["diagnostic"].authority_id, key=authorities["diagnostic"].key)
    recovery = {"schema": "headless-account-read-recovery-v1", "max_attempts": 2}
    if (report.get("schema") != subscription.OBSERVATION_SCHEMA_V4
            or report.get("postrun_sources_verified") is not True
            or report.get("worker_config_descriptor") != config_descriptor
            or report.get("account_read_recovery") != recovery
            or report.get("native_deployment_descriptor") != config.data().get("native_deployment")):
        raise SystemExit("final v4 report binding differs")
    materials = {sid: verify(receipt, role="material", subject=sid,
                             authority_id=authorities["material"].authority_id,
                             key=authorities["material"].key)
                 for sid, receipt in signed_materials.items()}
    inventory = load_record(c["request_inventory"])
    renderer = subscription.SubscriptionRenderer(manifest, resolver)
    if subscription.request_inventory(manifest, materials, renderer) != inventory:
        raise SystemExit("frozen inventory cannot be reconstructed from renderer")
    deployment = load_record(c["native_deployment"]).data()
    if (c.get("schema") != subscription.CONFIG_SCHEMA_V4 or c.get("transport") != "headless"
            or c.get("account_read_recovery") != recovery
            or deployment.get("schema") != "frozen-native-subscription-headless-deployment-v2"
            or deployment.get("account_read_recovery") != recovery):
        raise SystemExit("frozen v4 recovery deployment differs")
    allocation_desc = prepared.get("allocation_envelope")
    if not isinstance(allocation_desc, dict) or set(allocation_desc) != {"path", "sha256"}:
        raise SystemExit("preparation allocation descriptor differs")
    allocation_raw = Path(allocation_desc["path"]).read_bytes()
    if sha(allocation_raw) != allocation_desc["sha256"]:
        raise SystemExit("allocation envelope hash differs")
    allocation = json.loads(allocation_raw)
    caps = {"reviewer1": 36, "reviewer2": 36, "arbitrator": 36, "evaluator": 72}
    spent = {"reviewer1": 5, "reviewer2": 5, "arbitrator": 1, "evaluator": 0}
    remaining = {"reviewer1": 31, "reviewer2": 31, "arbitrator": 35, "evaluator": 72}
    if (allocation.get("cumulative_main_caps") != caps | {"total_main": 180}
            or allocation.get("spent_main") != spent | {"total_main": 11}
            or allocation.get("remaining_main") != remaining | {"total_main": 169}
            or allocation.get("parent") != {"diagnostic_result": prepared.get("parent_result"),
                "independent_readback": prepared.get("parent_independent_readback"),
                "worker_config": prepared.get("parent_worker_config"),
                "public_parent_closure": prepared.get("parent_public_closure")}):
        raise SystemExit("cumulative allocation envelope differs")
    budget_report = report.get("budget") if isinstance(report.get("budget"), dict) else None
    if (not isinstance(budget_report, dict)
            or {role: budget_report.get("allocated_role_opportunities", {}).get(role, {}).get("cap")
                for role in remaining} != remaining
            or any((not isinstance((allocation_row := budget_report["allocated_role_opportunities"][role]).get("reserved"), int)
                   or allocation_row["reserved"] < 0 or allocation_row["reserved"] > remaining[role]
                   or allocation_row.get("unused") != remaining[role] - allocation_row["reserved"])
                   for role in remaining)
            or budget_report.get("reserved_main_opportunities", 0) > 169):
        raise SystemExit("v4 allocated role opportunities differ")
    frozen = dict(deployment["frozen_files"])
    frozen[c["native_deployment"]["path"]] = c["native_deployment"]["sha256"]
    frozen[config_descriptor["path"]] = config_descriptor["sha256"]
    def full_source_guard():
        _guard()
        headless._sources(frozen)
    full_source_guard()
    entries = {entry["opportunity_id"]: entry for entry in inventory.data()["entries"]}
    rows = journal_rows(args.journal, digest)
    readbacks, verified_native = [], {}
    for row in rows:
        if row["event"] != "subscription_headless_receipt":
            continue
        logged = row["data"]
        entry = logged["binding"]
        opportunity_id = entry["opportunity_id"]
        if entries.get(opportunity_id) != entry:
            raise SystemExit("journal receipt entry differs from reconstructed frozen inventory")
        if opportunity_id in verified_native:
            raise SystemExit("duplicate headless native opportunity")
        directory = args.headless_root / opportunity_id
        request_path = directory / "headless-request.private.json"
        request_raw = request_path.read_bytes()
        request = json.loads(request_raw.decode("utf-8"))
        if set(request) != {"prompt", "output_schema"} or request_raw != canonical(request).encode("utf-8"):
            raise SystemExit("dynamic private request shape differs")
        rebuilt = {"prompt_sha256": sha(request["prompt"].encode("utf-8")),
                   "schema_digest": digest(request["output_schema"]),
                   "input_bytes": len(request["prompt"].encode("utf-8"))}
        if any(rebuilt[key] != entry[key] for key in rebuilt):
            raise SystemExit("dynamic private request differs from renderer-reconstructed inventory")
        dynamic_frozen = frozen | {str(request_path): sha(request_raw)}
        raw_receipt = json.loads((directory / "native" / "observer-receipt.json").read_text(encoding="utf-8"))
        if raw_receipt != logged.get("receipt"):
            raise SystemExit("raw native observer receipt differs from journal")
        receipt = FrozenRecord.from_dict(raw_receipt)
        response_path = directory / "native" / "response.private.json"
        response = FrozenRecord.from_dict(json.loads(response_path.read_text(encoding="utf-8"))) if receipt.data().get("accepted") else None
        native_context = dict(deployment["slots"][opportunity_id]) | {"executable": deployment["executable"], "reasoning_effort": "low"}
        native_context["account_read_recovery"] = recovery
        spec = manifest.data()["policy"]["ports"][entry["role"]] | {
            "native_context": native_context, "reasoning_effort": "low", "account_read_recovery": recovery}
        bound_entry = dict(entry) | {"private_request": {"path": str(request_path), "sha256": sha(request_raw)}}
        if receipt.data().get("accepted") is True:
            verified = headless.verify_headless_request_binding(headless.HeadlessResult(receipt, response), bound_entry,
                                                                directory, spec, dynamic_frozen)
            if logged.get("headless_binding") != verified.data():
                raise SystemExit("journal headless binding differs from independently reread binding")
            verified_native[opportunity_id] = (receipt, response, verified)
            readbacks.append({"opportunity_id": opportunity_id, "accepted": True,
                              "binding_digest": verified.content_hash, "receipt_digest": receipt.content_hash,
                              "verification": "independently_bound"})
        else:
            # Preserve independently reread stream usage and recovery-attempt
            # evidence, while never presenting a rejected receipt as bound.
            if (logged.get("headless_binding") is not None or response is not None
                    or receipt.data().get("schema") != headless.RECOVERY_RECEIPT_SCHEMA
                    or receipt.data().get("account_read_recovery") != recovery):
                raise SystemExit("rejected native receipt exposed a binding or response")
            retained_response = retained_rejected_response(response_path, receipt.data())
            bound = json.loads((directory / "native-reservation.json").read_text(encoding="utf-8"))
            if (bound.get("schema") != headless.RECOVERY_RESERVATION_SCHEMA
                    or bound.get("account_read_recovery") != recovery):
                raise SystemExit("rejected native recovery reservation differs")
            attempts = {}
            for phase, field in (("billing-before", "account_preflight_attempts_sha256"),
                                 ("billing-after", "account_postflight_attempts_sha256")):
                path = directory / "native" / phase / "attempts.json"
                if path.exists():
                    raw_attempts = path.read_bytes(); value = json.loads(raw_attempts)
                    if (receipt.data().get(field) != sha(raw_attempts) or value.get("recovery") != recovery
                            or not isinstance(value.get("attempts"), list)):
                        raise SystemExit("rejected native recovery attempt evidence differs")
                    attempts[phase] = {"sha256": sha(raw_attempts), "attempt_count": len(value["attempts"]),
                                       "winning_attempt": value.get("winning_attempt")}
                elif receipt.data().get(field) is not None:
                    raise SystemExit("receipt names a missing recovery attempt record")
            inspected = None
            if receipt.data().get("prompt_process_launched") is True:
                stream_raw, process = headless._reread_process(directory / "native", bound["command"], bound,
                                                                spec["timeout_seconds"])
                inspected = headless.inspect_grok_stream(stream_raw, schema=request["output_schema"],
                                                         session_id=bound["session_id"],
                                                         max_output_tokens=spec["main_output_cap"],
                                                         max_total_tokens=spec["observed_main_token_cap"],
                                                         process_exit_code=process["process_exit_code"])
                if (process != receipt.data().get("native_process")
                        or inspected.receipt.data() != receipt.data().get("stream_inspection")):
                    raise SystemExit("rejected native stream/process evidence differs from observer")
            verified_native[opportunity_id] = (receipt, None, None)
            readbacks.append({"opportunity_id": opportunity_id, "accepted": False,
                              "binding_digest": None, "receipt_digest": receipt.content_hash,
                              "verification": "rejected_receipt_preserved_unbound",
                              "known_usage": None if inspected is None else inspected.receipt.data()["usage"],
                              "retained_response": retained_response,
                              "recovery_attempts": attempts,
                              "limit": "full account binding unavailable for rejected receipt"})
    budget = report.get("budget") if isinstance(report.get("budget"), dict) else {}
    if len(verified_native) != budget.get("reserved_main_opportunities"):
        raise SystemExit("native receipt count differs from finalized budget reservations")
    reserved = {row["data"]["binding"]["opportunity_id"] for row in rows if row["event"] == "subscription_reserved"}
    if reserved != set(verified_native):
        raise SystemExit("journal reservations and independently reread native opportunities differ")
    rejected_indexes = [index for index, row in enumerate(rows) if row["event"] == "subscription_headless_receipt"
                        and row["data"]["receipt"].get("accepted") is not True]
    if rejected_indexes and any(row["event"] == "subscription_reserved" for row in rows[rejected_indexes[0] + 1:]):
        raise SystemExit("new reservation appears after terminal rejected native receipt")
    final = [row for row in rows if row["event"] == "subscription_result_finalized"]
    if len(final) != 1 or final[0]["data"].get("receipt_digest") != result.content_hash:
        raise SystemExit("journal final result binding differs")
    if rows[-1] is not final[0]:
        raise SystemExit("finalized receipt is not journal tail")

    # Recreate the consumer exclusively in memory.  The ports return the
    # independently reread native result; they cannot create a directory or
    # reach a model/account process.
    class MemoryJournal:
        def __init__(self, _path):
            self.rows = []
            self.sequence = 0
            self.previous = "0" * 64
        def append(self, event, data):
            row = {"sequence": self.sequence, "previous": self.previous, "event": event, "data": data}
            row["digest"] = digest(row)
            self.rows.append(row)
            self.sequence += 1
            self.previous = row["digest"]

    replay_used, replay_pending = set(), {}
    def replay_plan(role, request):
        wire = subscription.request_wire(renderer, role, request)
        schema = subscription.response_schema(role, request)
        matches = [entry for entry in inventory.data()["entries"] if entry["role"] == role
                   and entry["request_digest"] == request.content_hash and entry["opportunity_id"] not in replay_used]
        if not matches:
            raise RuntimeError("replay capacity cannot select an unused frozen entry")
        entry = matches[0]  # exact production plan order; evaluator repeats share request_digest.
        expected = {"prompt_sha256": sha(wire.encode("utf-8")), "schema_digest": digest(schema),
                    "input_bytes": len(wire.encode("utf-8")), "port_digest": digest(manifest.data()["policy"]["ports"][role])}
        if any(entry[key] != value for key, value in expected.items()):
            raise RuntimeError("replay capacity request differs from frozen inventory")
        replay_used.add(entry["opportunity_id"])
        replay_pending[(role, request.content_hash)] = entry
        return subscription.record(entry)

    def replay_port(role, request):
        entry = replay_pending.pop((role, request.content_hash))
        receipt, response, binding = verified_native[entry["opportunity_id"]]
        output = response
        if output is not None and role != "evaluator":
            try:
                target = calibration_pilot.target(output.data(), request.data()["benchmark"])
                output = authorities[role].issue(role, request.content_hash, target)
            except Exception:
                output = None
        return subscription.SubscriptionResult(output, receipt, subscription.record(entry), None, "headless", binding)

    original_journal = calibration_pilot.PrivateJournal
    calibration_pilot.PrivateJournal = MemoryJournal
    try:
        replay = subscription.SubscriptionPilot(manifest=manifest, resolver=resolver, materials=signed_materials,
            keys={role: authority.key for role, authority in authorities.items()}, authority=authorities["diagnostic"],
            journal_path=Path("memory-only-journal"), source_guard=full_source_guard, capacity_port=replay_plan,
            account_read_recovery=recovery,
            **{role: (lambda request, role=role: replay_port(role, request)) for role in subscription.ROLES})
        preliminary = replay.run()
        replay_report = verify(preliminary, role="diagnostic", subject=manifest.content_hash,
                               authority_id=authorities["diagnostic"].authority_id, key=authorities["diagnostic"].key)
        replay_report["postrun_sources_verified"] = True
        replay_report.update(schema=subscription.OBSERVATION_SCHEMA_V4, headless_transport="headless",
                             worker_config_descriptor=dict(config_descriptor), account_read_recovery=dict(recovery),
                             native_deployment_descriptor=dict(c["native_deployment"]))
        replay_result = authorities["diagnostic"].issue("diagnostic", manifest.content_hash, replay_report)
        replay.journal.append("subscription_result_finalized", {"receipt_digest": replay_result.content_hash})
    finally:
        calibration_pilot.PrivateJournal = original_journal
    if replay_result != result or replay.journal.rows != rows:
        raise SystemExit("memory-only consumer replay differs from original result or journal")
    if replay_used != set(verified_native):
        raise SystemExit("memory replay did not consume exactly the independently reread opportunities")
    full_source_guard()
    after = metadata([args.result, args.journal, args.headless_root, args.config_descriptor, args.parent_closure, args.preparation])
    if before != after:
        raise SystemExit("readback mutated or observed concurrent evidence changes")
    payload = {"schema": "independent-headless-review-readback-r2", "result_sha256": sha(raw_result),
               "config_descriptor": config_descriptor, "parent_closure": {"path": str(args.parent_closure),
               "sha256": sha(args.parent_closure.read_bytes())}, "preparation": {"path": str(args.preparation),
               "sha256": sha(args.preparation.read_bytes())}, "allocation_envelope": allocation_desc,
               "cumulative_main_caps": allocation["cumulative_main_caps"], "spent_main": allocation["spent_main"],
               "remaining_main": allocation["remaining_main"], "journal_final_digest": rows[-1]["digest"],
               "native_readbacks": readbacks, "source_metadata_before": before, "source_metadata_after": after,
               "full_memory_replay": "exact result and journal match using an append-only in-memory PrivateJournal and independently reread native results; no transport was called."}
    args.output.write_text(canonical(payload) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
