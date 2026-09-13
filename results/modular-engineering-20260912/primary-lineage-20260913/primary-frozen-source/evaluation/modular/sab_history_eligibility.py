"""A separate eligibility hold, preserving an existing SAB split verbatim.

Earlier instance IDs are not presumed equal to CSV ordinals. Until a shared,
revision-bound identity mapping exists, every existing SAB validation family is
held. A selection is potential exposure; a call receipt is observed I/O.
"""
from pathlib import Path

from evaluation.modular.fresh_airs_custodian import CustodyError, _check, _write_new
from evaluation.modular.primary_process_qualification import PinnedReads, literal_selection
from research_loop.ontology import digest


def supplement_sab_eligibility(destination, config):
    reads = PinnedReads(config["inputs"])
    seal = reads.json("sab_split")
    audit = reads.json("sab_audit")
    if (seal.get("schema") != "prospective-observed-family-split-v1"
            or seal.get("audit_sha256") != digest(audit)
            or seal.get("validation_lease_issued") is not False):
        raise CustodyError()
    groups = [row for row in seal["groups"] if row["source"] == "scienceagentbench" and row["split"] == "validation"]
    if not groups:
        raise CustodyError()
    for group in groups:
        _check(group["group_sha256"], "sha")
        _check(group["member_tokens"], ["sha"])
    held = sorted(token for row in groups for token in row["member_tokens"])
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    hold = {"schema": "observed-history-eligibility-hold-v1", "source": "scienceagentbench",
            "original_split_sha256": digest(seal), "original_audit_sha256": digest(audit),
            "config_sha256": digest(config), "status": "all_existing_validation_families_on_hold",
            "held_group_sha256": sorted(row["group_sha256"] for row in groups),
            "held_member_tokens": held, "held_record_count": len(held),
            "reason": "earlier_selection_scope_omitted_and_revision_bound_identity_mapping_unresolved",
            "original_split_mutated": False, "validation_lease_allowed": False,
            "validation_payload_read": False, "resampling_allowed": False}
    # The deny receipt survives a subsequent malformed historical file.
    _write_new(destination / "eligibility-hold.json", hold)
    try:
        manifest = reads.json("sab_initial_manifest")
        selected = literal_selection(reads.raw("sab_runner"), "TASK_IDS")
        if manifest.get("task_ids") != selected or any(type(value) is not int for value in selected):
            raise CustodyError()
        selected_set, called = set(selected), set()
        costs = {"call_count": 0, "succeeded_count": 0, "failed_count": 0,
                 "known_tokens": 0, "unknown_usage_count": 0}
        for entry in config["call_receipts"]:
            identity = entry["instance_id"]
            if identity not in selected_set:
                raise CustodyError()
            receipt = reads.json(entry["input"])
            if type(receipt.get("exit_code")) is not int or not isinstance(receipt.get("usage"), list):
                raise CustodyError()
            called.add(identity)
            costs["call_count"] += 1
            costs["succeeded_count" if receipt["exit_code"] == 0 else "failed_count"] += 1
            usage = receipt["usage"]
            if len(usage) == 1 and isinstance(usage[0], dict) and all(type(usage[0].get(k)) is int and usage[0][k] >= 0 for k in ("input_tokens", "output_tokens")):
                costs["known_tokens"] += usage[0]["input_tokens"] + usage[0]["output_tokens"]
            else:
                costs["unknown_usage_count"] += 1
        result = {"schema": "sab-earlier-history-eligibility-supplement-v1", "hold_sha256": digest(hold),
                  "selected_identity_count": len(selected_set), "call_observed_identity_count": len(called),
                  "potential_only_identity_count": len(selected_set - called),
                  "selected_identity_hashes": sorted(digest({"source": "legacy_sab_instance_id", "id": value}) for value in selected_set),
                  "called_identity_hashes": sorted(digest({"source": "legacy_sab_instance_id", "id": value}) for value in called),
                  "historical_call_cost": costs, "input_bindings": reads.finish(),
                  "mapping_status": "no_revision_bound_explicit_identity_bridge",
                  "same_ordinal_assumed": False, "specific_validation_overlap_established": False,
                  "validation_eligible_count": 0, "held_record_count": len(held),
                  "source_revision_relation": "not_established", "original_split_mutated": False,
                  "validation_payload_read": False, "new_model_calls": 0, "new_network_calls": 0}
        _write_new(destination / "history-supplement.json", result)
        return result
    except BaseException:
        _write_new(destination / "failure.json", {"schema": "sab-history-supplement-failure-v1",
                                                  "safe_error": "metadata_contract_failure_hold_retained",
                                                  "validation_eligible_count": 0})
        raise CustodyError() from None
