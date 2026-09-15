"""Read-only, neutral custody-state audit snapshots.

This auditor does not read task or reference payloads, issue/consume leases, or
provide operating-system isolation. HMAC verifier keys are caller-held secrets;
the CLI intentionally audits state only, while receipt verification is an
explicit programmatic API.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from evaluation.modular import custody as custody_module
from evaluation.modular.custody import InventoryItem, SCHEMA, _merged_groups
from research_loop.modular import panel_receipts as receipt_module
from research_loop.modular.artifact_catalogue import source_snapshot
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.panel_receipts import verify_signed
from research_loop.ontology import ContractError, canonical, digest

R = FrozenRecord.from_dict
_ANCHOR_SCHEMA = "custody-state-byte-anchor-v1"
_AUDIT_SCHEMA = "custody-audit-snapshot-v1"
_HEX = frozenset("0123456789abcdef")


def custody_state_anchor(raw: bytes) -> FrozenRecord:
    """Make a caller-retainable byte anchor; auditing never derives one implicitly."""
    if not isinstance(raw, bytes):
        raise ContractError("custody state anchor needs raw bytes")
    return R({"schema": _ANCHOR_SCHEMA, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})


def _digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX


def _anchor(value: FrozenRecord) -> dict[str, Any]:
    if type(value) is not FrozenRecord:
        raise ContractError("exact caller-supplied custody state anchor required")
    body = value.data()
    if (set(body) != {"schema", "sha256", "bytes"} or body["schema"] != _ANCHOR_SCHEMA
            or type(body["bytes"]) is not int or body["bytes"] < 1 or not _digest(body["sha256"])):
        raise ContractError("invalid custody state byte anchor")
    return body


def _same_anchor(raw: bytes, expected: Mapping[str, Any]) -> None:
    if len(raw) != expected["bytes"] or hashlib.sha256(raw).hexdigest() != expected["sha256"]:
        raise ContractError("custody state differs from caller-supplied byte anchor")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("duplicate custody JSON key")
        result[key] = value
    return result


def _parse_pinned_state(raw: bytes) -> dict[str, Any]:
    try:
        state = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("invalid custody state JSON") from exc
    required = {"schema", "inventory", "inventory_digest", "attestations", "split", "leases"}
    if not isinstance(state, dict) or set(state) != required or state["schema"] != SCHEMA:
        raise ContractError("unsupported custody state")
    return state


def _safe_text(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise ContractError("custody " + field + " differs")


def _verify_attestations(state: Mapping[str, Any], inventory_ids: set[str]) -> str:
    attestations = state["attestations"]
    if not isinstance(attestations, dict) or any(not isinstance(item, str) or item not in inventory_ids for item in attestations):
        raise ContractError("custody attestations differ")
    rows = []
    required = {"items", "custodian_id", "source_qualification_digest", "exposure_qualification_digest", "tested_arm_ids", "digest"}
    for item, record in attestations.items():
        if (not isinstance(record, dict) or set(record) != required or not isinstance(record["items"], list)
                or not record["items"] or any(not isinstance(value, str) for value in record["items"])
                or item not in record["items"] or sorted(set(record["items"])) != record["items"]
                or not set(record["items"]) <= inventory_ids or not isinstance(record["tested_arm_ids"], list)
                or not record["tested_arm_ids"] or any(not isinstance(value, str) for value in record["tested_arm_ids"])
                or sorted(set(record["tested_arm_ids"])) != record["tested_arm_ids"]
                or record["custodian_id"] in record["tested_arm_ids"]
                or not _digest(record["source_qualification_digest"])
                or not _digest(record["exposure_qualification_digest"]) or not _digest(record["digest"])):
            raise ContractError("custody attestation differs")
        _safe_text(record["custodian_id"], "attestation custodian")
        if record["digest"] != digest({key: record[key] for key in required - {"digest"}}):
            raise ContractError("custody attestation digest differs")
        rows.append(record["digest"])
    return digest(sorted(rows))


def _verify_split(state: Mapping[str, Any], inventory: list[InventoryItem], attestations: Mapping[str, Any]) -> None:
    split = state["split"]
    if split is None:
        if state["leases"]:
            raise ContractError("custody lease exists without split")
        return
    required = {"digest", "seed", "validation_percent", "inventory_digest", "rows"}
    optional = required | {"train_only_declaration"}
    fields = set(split) if isinstance(split, dict) else set()
    if (fields != required and fields != optional) or split["inventory_digest"] != state["inventory_digest"]:
        raise ContractError("custody split differs")
    if (not isinstance(split["seed"], str) or type(split["validation_percent"]) is not int
            or not 1 <= split["validation_percent"] <= 100 or not isinstance(split["rows"], list)
            or not _digest(split["digest"])):
        raise ContractError("custody split fields differ")
    groups = _merged_groups(inventory)
    known = set(groups)
    declaration = split.get("train_only_declaration")
    if declaration is None:
        train_only_groups: set[str] = set()
    else:
        if (not isinstance(declaration, dict) or set(declaration) != {"item_ids", "group_ids", "reason_commitment"}
                or not isinstance(declaration["item_ids"], list) or not declaration["item_ids"]
                or declaration["item_ids"] != sorted(set(declaration["item_ids"])) or not set(declaration["item_ids"]) <= known
                or not isinstance(declaration["group_ids"], list) or declaration["group_ids"] != sorted(set(declaration["group_ids"]))
                or not _digest(declaration["reason_commitment"])):
            raise ContractError("custody train-only declaration differs")
        train_only_groups = {groups[item_id] for item_id in declaration["item_ids"]}
        if declaration["group_ids"] != sorted(train_only_groups):
            raise ContractError("custody train-only group declaration differs")
    allocation: dict[str, str] = {}
    for group in set(groups.values()):
        members = [item for item in inventory if groups[f"{item.benchmark}:{item.task_id}"] == group]
        if group in train_only_groups or any(item.exposure == "exposed" for item in members):
            allocation[group] = "train"
        elif not all(f"{item.benchmark}:{item.task_id}" in attestations for item in members):
            allocation[group] = "quarantine"
        else:
            bucket = int(hashlib.sha256(f"{split['seed']}:{group}".encode()).hexdigest(), 16) % 100
            allocation[group] = "validation" if bucket < split["validation_percent"] else "train"
    rows = []
    for item in inventory:
        item_id = f"{item.benchmark}:{item.task_id}"
        rows.append({"item": item_id, "group": groups[item_id], "domain": allocation[groups[item_id]],
                     "official_split": item.official_split, "exposure": item.exposure,
                     "custodian_qualified": item_id in attestations})
    payload = {"seed": split["seed"], "validation_percent": split["validation_percent"],
               "inventory_digest": state["inventory_digest"], "rows": sorted(rows, key=lambda row: row["item"])}
    if declaration is not None:
        payload["train_only_declaration"] = declaration
    if split != {"digest": digest(payload), **payload}:
        raise ContractError("custody split allocation replay differs")


def _lease_body(lease: Mapping[str, Any]) -> dict[str, Any]:
    common = {"id", "stage", "panel_digest", "candidate_digest", "groups", "arm_schedule", "arm_schedule_digest",
              "split_digest", "qualified", "qualification", "metadata_authenticated", "calibration_eligible",
              "scorer_digest", "protocol_digest", "calibration_receipt_digest", "criteria_digest", "calibration_authority",
              "required_benchmarks", "panel_validated", "status"}
    with_panel = common | {"task_identities_digest"}
    fields = set(lease) if isinstance(lease, Mapping) else set()
    if fields != common and fields != with_panel:
        raise ContractError("custody lease has unsupported fields")
    if (not all(_digest(lease[key]) for key in ("id", "panel_digest", "candidate_digest", "arm_schedule_digest", "split_digest", "scorer_digest", "protocol_digest", "calibration_receipt_digest", "criteria_digest"))
            or not isinstance(lease["groups"], list) or not lease["groups"] or any(not isinstance(value, str) for value in lease["groups"])
            or lease["groups"] != sorted(set(lease["groups"]))
            or not isinstance(lease["arm_schedule"], list) or not lease["arm_schedule"] or any(not isinstance(value, str) for value in lease["arm_schedule"])
            or len(set(lease["arm_schedule"])) != len(lease["arm_schedule"])
            or not isinstance(lease["required_benchmarks"], list) or not lease["required_benchmarks"] or any(not isinstance(value, str) for value in lease["required_benchmarks"])
            or lease["arm_schedule_digest"] != digest(lease["arm_schedule"])
            or lease["status"] not in {"active", "consumed"}
            or lease["qualification"] != "calibration_eligible"
            or lease["qualified"] is not True or lease["metadata_authenticated"] is not True or lease["calibration_eligible"] is not True
            or type(lease["panel_validated"]) is not bool):
        raise ContractError("custody lease binding differs")
    for value in (lease["stage"], lease["calibration_authority"], *lease["groups"], *lease["arm_schedule"]):
        _safe_text(value, "lease field")
    if lease["panel_validated"] != ("task_identities_digest" in lease):
        raise ContractError("custody lease panel validation differs")
    if lease["panel_validated"] and not _digest(lease["task_identities_digest"]):
        raise ContractError("custody lease task identity binding differs")
    lease_id = digest({"stage": lease["stage"], "panel": lease["panel_digest"], "candidate": lease["candidate_digest"],
                       "groups": lease["groups"], "arms": lease["arm_schedule"], "split": lease["split_digest"],
                       "scorer": lease["scorer_digest"], "protocol": lease["protocol_digest"],
                       "calibration": lease["calibration_receipt_digest"]})
    if lease["id"] != lease_id:
        raise ContractError("custody lease identity differs")
    return dict(lease)


def _verify_leases(state: Mapping[str, Any], split_digest: str | None) -> dict[str, dict[str, Any]]:
    leases = state["leases"]
    if not isinstance(leases, dict):
        raise ContractError("custody leases differ")
    result = {}
    for lease_id, raw in leases.items():
        if not _digest(lease_id) or not isinstance(raw, dict):
            raise ContractError("custody lease record differs")
        lease = _lease_body(raw)
        if lease_id != lease["id"] or (split_digest is not None and lease["split_digest"] != split_digest):
            raise ContractError("custody lease state binding differs")
        result[lease_id] = lease
    return result


def _receipt_binding(receipt: FrozenRecord, keys: Mapping[str, bytes], leases: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    if not isinstance(receipt, FrozenRecord):
        raise ContractError("persisted custody receipt must be frozen")
    if not isinstance(keys, Mapping) or not keys or any(not isinstance(name, str) or not isinstance(key, bytes) for name, key in keys.items()):
        raise ContractError("custody receipt verification needs caller-held HMAC authority keys")
    body = verify_signed(receipt, keys, schema="custody-panel-lease-v2")
    required = {"schema", "lease_id", "stage", "panel_digest", "candidate_digest", "groups", "arm_schedule", "split_digest",
                "scorer_digest", "protocol_digest", "calibration_receipt_digest", "criteria_digest", "required_benchmarks",
                "task_identities_digest", "status", "authority"}
    if set(body) != required or body["lease_id"] not in leases:
        raise ContractError("custody receipt does not bind a retained lease")
    lease = leases[body["lease_id"]]
    fields = ("stage", "panel_digest", "candidate_digest", "groups", "arm_schedule", "split_digest", "scorer_digest",
              "protocol_digest", "calibration_receipt_digest", "criteria_digest", "required_benchmarks", "task_identities_digest", "status")
    if (not lease["panel_validated"] or lease["status"] != "consumed" or any(body[name] != lease[name] for name in fields)):
        raise ContractError("custody receipt does not exactly replay the consumed lease")
    return {"status": "verified", "receipt_digest": receipt.content_hash, "lease_id": body["lease_id"], "authority": body["authority"]}


def verify_custody_snapshot(state_path: Path, *, anchor: FrozenRecord, receipt: FrozenRecord | None = None,
                            receipt_keys: Mapping[str, bytes] | None = None) -> FrozenRecord:
    """Verify pinned state bytes, metadata allocation replay, and an optional retained receipt."""
    expected = _anchor(anchor)
    path = Path(state_path).resolve(strict=True)
    raw_before = path.read_bytes()
    _same_anchor(raw_before, expected)
    state = _parse_pinned_state(raw_before)
    if not isinstance(state["inventory"], list):
        raise ContractError("custody inventory differs")
    inventory = [InventoryItem.parse(row) for row in state["inventory"]]
    expected_inventory = sorted((item.data() for item in inventory), key=lambda row: (row["benchmark"], row["task_id"]))
    inventory_ids = {f"{item.benchmark}:{item.task_id}" for item in inventory}
    if len(inventory_ids) != len(inventory) or state["inventory"] != expected_inventory or state["inventory_digest"] != digest(expected_inventory):
        raise ContractError("custody inventory differs")
    attestation_digest = _verify_attestations(state, inventory_ids)
    _verify_split(state, inventory, state["attestations"])
    leases = _verify_leases(state, state["split"]["digest"] if state["split"] is not None else None)
    if receipt is None:
        if receipt_keys is not None:
            raise ContractError("custody receipt keys require an explicit persisted receipt")
        receipt_observation = {"status": "absent"}
    else:
        receipt_observation = _receipt_binding(receipt, receipt_keys, leases)
    raw_after = path.read_bytes()
    _same_anchor(raw_after, expected)
    if raw_after != raw_before:
        raise ContractError("custody state changed during audit read")
    lease_rows = [{"lease_id": key, "status": value["status"], "panel_validated": value["panel_validated"],
                   "binding_digest": digest({name: value[name] for name in value if name != "id"})}
                  for key, value in sorted(leases.items())]
    return R({"schema": _AUDIT_SCHEMA, "anchor": expected, "custody_schema": SCHEMA,
              "inventory_digest": state["inventory_digest"], "split_digest": state["split"]["digest"] if state["split"] else None,
              "attestation_count": len(state["attestations"]), "attestation_digest": attestation_digest,
              "lease_count": len(lease_rows), "leases": lease_rows, "receipt_observation": receipt_observation,
              "verification_scope": {"state_bytes_anchored": True, "split_allocation_replayed": state["split"] is not None,
                                     "attestation_record_digests_verified": True, "independent_custodian_authority_verified": False,
                                     "calibration_authority_verified": False},
              "producer_sources": {"auditor": source_snapshot(Path(__file__)),
                                   "custody_semantics": source_snapshot(Path(custody_module.__file__)),
                                   "receipt_semantics": source_snapshot(Path(receipt_module.__file__))},
              "optimizer_visible": False, "scientific_validated": False})


def _main() -> None:
    parser = argparse.ArgumentParser(description="Read-only auditor for a caller-pinned modular custody state.")
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--state-sha256", required=True)
    parser.add_argument("--state-bytes", required=True, type=int)
    parser.add_argument("--output", type=Path, help="new auditor-owned output file; default writes canonical JSON to stdout")
    args = parser.parse_args()
    anchor = R({"schema": _ANCHOR_SCHEMA, "sha256": args.state_sha256, "bytes": args.state_bytes})
    result = verify_custody_snapshot(args.state, anchor=anchor)
    if args.output is None:
        print(result.encoded)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(result.encoded + "\n")


if __name__ == "__main__":
    _main()
