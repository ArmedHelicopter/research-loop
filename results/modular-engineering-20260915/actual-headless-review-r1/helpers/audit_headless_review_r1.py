"""Read-only independent readback for a closed headless subscription review run.

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
            # Secrets stay out of the metadata report.  Every other original
            # evidence file has a byte hash before and after readback.
            if item.name != "auth.json" and not item.name.startswith("key-"):
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
    parser.add_argument("--parent-result-sha256", required=True)
    parser.add_argument("--journal", required=True, type=Path)
    parser.add_argument("--headless-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists() or args.output.parent == args.headless_root or args.headless_root in args.output.parents:
        raise SystemExit("output must be a new file outside native evidence")
    if not args.result.is_file():
        raise SystemExit("run is not closed: result file is absent")
    if len(args.parent_result_sha256) != 64 or any(c not in "0123456789abcdef" for c in args.parent_result_sha256):
        raise SystemExit("invalid parent result sha256")

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

    config_descriptor = descriptor(args.config_descriptor)
    config = load_record(config_descriptor)
    before = metadata([args.result, args.journal, args.headless_root, args.config_descriptor])
    raw_result = args.result.read_bytes()
    if sha(raw_result) != args.parent_result_sha256:
        raise SystemExit("parent result sha256 differs")
    result = FrozenRecord.from_dict(json.loads(raw_result.decode("utf-8")))
    c, manifest, signed_materials, authorities, resolver, _guard = subscription.load_private(config_descriptor)
    report = verify(result, role="diagnostic", subject=manifest.content_hash,
                    authority_id=authorities["diagnostic"].authority_id, key=authorities["diagnostic"].key)
    if (report.get("schema") != subscription.OBSERVATION_SCHEMA_V3
            or report.get("postrun_sources_verified") is not True
            or report.get("worker_config_descriptor") != config_descriptor):
        raise SystemExit("final v3 report binding differs")
    materials = {sid: verify(receipt, role="material", subject=sid,
                             authority_id=authorities["material"].authority_id,
                             key=authorities["material"].key)
                 for sid, receipt in signed_materials.items()}
    inventory = load_record(c["request_inventory"])
    renderer = subscription.SubscriptionRenderer(manifest, resolver)
    if subscription.request_inventory(manifest, materials, renderer) != inventory:
        raise SystemExit("frozen inventory cannot be reconstructed from renderer")
    deployment = load_record(c["native_deployment"]).data()
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
        spec = manifest.data()["policy"]["ports"][entry["role"]] | {"native_context": native_context, "reasoning_effort": "low"}
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
            # A terminal native failure can retain a successful stream/known
            # usage while lacking a complete postflight account proof.  Preserve
            # it for the consumer replay, but do not present it as bound.
            if logged.get("headless_binding") is not None or response is not None:
                raise SystemExit("rejected native receipt exposed a binding or response")
            bound = json.loads((directory / "native-reservation.json").read_text(encoding="utf-8"))
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
            postflight = directory / "native" / "billing-after"
            requests = json.loads((postflight / "requests.json").read_text(encoding="utf-8"))
            if (not (postflight / "credits.private.json").is_file()
                    or not isinstance(requests, list) or len(requests) != 2
                    or requests[0].get("name") != "credits" or requests[0].get("status") != "received"
                    or requests[1].get("name") != "topup" or requests[1].get("status") != "reserved"
                    or (postflight / "observation.json").exists() or (postflight / "user.private.json").exists()):
                raise SystemExit("rejected native postflight partial-account evidence differs")
            verified_native[opportunity_id] = (receipt, None, None)
            readbacks.append({"opportunity_id": opportunity_id, "accepted": False,
                              "binding_digest": None, "receipt_digest": receipt.content_hash,
                              "verification": "rejected_receipt_preserved_unbound",
                              "known_usage": inspected.receipt.data()["usage"],
                              "partial_account": "credits received; topup reserved; no user/observation; full binding intentionally unavailable"})
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
            **{role: (lambda request, role=role: replay_port(role, request)) for role in subscription.ROLES})
        preliminary = replay.run()
        replay_report = verify(preliminary, role="diagnostic", subject=manifest.content_hash,
                               authority_id=authorities["diagnostic"].authority_id, key=authorities["diagnostic"].key)
        replay_report["postrun_sources_verified"] = True
        replay_report.update(schema=subscription.OBSERVATION_SCHEMA_V3, headless_transport="headless",
                             worker_config_descriptor=dict(config_descriptor))
        replay_result = authorities["diagnostic"].issue("diagnostic", manifest.content_hash, replay_report)
        replay.journal.append("subscription_result_finalized", {"receipt_digest": replay_result.content_hash})
    finally:
        calibration_pilot.PrivateJournal = original_journal
    if replay_result != result or replay.journal.rows != rows:
        raise SystemExit("memory-only consumer replay differs from original result or journal")
    if replay_used != set(verified_native):
        raise SystemExit("memory replay did not consume exactly the independently reread opportunities")
    full_source_guard()
    after = metadata([args.result, args.journal, args.headless_root, args.config_descriptor])
    if before != after:
        raise SystemExit("readback mutated or observed concurrent evidence changes")
    payload = {"schema": "independent-headless-review-readback-r1", "result_sha256": sha(raw_result),
               "config_descriptor": config_descriptor, "journal_final_digest": rows[-1]["digest"],
               "native_readbacks": readbacks, "source_metadata_before": before, "source_metadata_after": after,
               "full_memory_replay": "exact result and journal match using an append-only in-memory PrivateJournal and independently reread native results; no transport was called."}
    args.output.write_text(canonical(payload) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
