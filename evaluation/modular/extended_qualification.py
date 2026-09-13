"""Metadata-only gate for extended-source qualification manifests.

It reads no source payload and never changes custody.  A caller may use this
to check that a proposed manifest still blocks unknown-exposure imports before
asking a separately authorised custodian for content-derived evidence.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from research_loop.ontology import ContractError


_SOURCES = {"scicode", "scienceagentbench"}
_FAMILY_COMPONENT_COUNTS = {"scicode": 2, "scienceagentbench": 28}
_MANIFEST_KEYS = {
    "schema",
    "core_benchmarks_retained",
    "live_metadata_binding",
    "sources",
    "decision",
    "required_independent_custody",
}
_BINDING_KEYS = {
    "inventory_digest",
    "custody_state_sha256",
    "source_pins_observed_in_live_import",
    "access_isolation",
    "split_assigned",
}


def validate_extended_qualification(manifest: Mapping[str, Any], live_metadata: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, Mapping) or set(manifest) != _MANIFEST_KEYS:
        raise ContractError("extended qualification manifest schema is invalid")
    if manifest["schema"] != "extended-source-qualification-v1" or manifest["core_benchmarks_retained"] != ["discoverybench", "blade"]:
        raise ContractError("extended qualification cannot replace core benchmarks")
    if not isinstance(live_metadata, Mapping) or live_metadata.get("schema") != "extended-source-inventory-metadata-v1":
        raise ContractError("live extended metadata schema is invalid")
    binding = manifest["live_metadata_binding"]
    if not isinstance(binding, Mapping) or set(binding) != _BINDING_KEYS:
        raise ContractError("qualification manifest binding schema is invalid")
    if (
        binding.get("inventory_digest") != live_metadata.get("inventory_digest")
        or binding.get("custody_state_sha256") != live_metadata.get("custody_state_sha256")
        or binding.get("source_pins_observed_in_live_import") != live_metadata.get("source_pins")
        or binding.get("access_isolation") != live_metadata.get("access_isolation")
        or binding.get("split_assigned") is not live_metadata.get("split_assigned")
    ):
        raise ContractError("qualification manifest is not bound to live inventory metadata")
    if live_metadata.get("access_isolation") != "not_verified" or live_metadata.get("split_assigned") is not False or live_metadata.get("qualification") != "unassigned_pending_source_family_and_exposure_review":
        raise ContractError("metadata-only qualification cannot override live custody state")
    sources = manifest["sources"]
    if not isinstance(sources, Mapping) or set(sources) != _SOURCES:
        raise ContractError("qualification manifest must cover both extended sources")
    for name, row in sources.items():
        if not isinstance(row, Mapping) or row.get("runtime_status") != "quarantine_until_review" or row.get("exposure") != "unknown":
            raise ContractError("unknown exposure source cannot be qualified")
        expected_evidence = ("received_artifact_and_atomic_substeps_closure_recorded" if name == "scicode"
                             else "dataset_tree_repository_and_source_path_closure_recorded")
        if (row.get("source_family_evidence") != expected_evidence
                or row.get("dataset_license_status") != "official_card_declaration_recorded_pending_received_terms_review"
                or row.get("family_component_count") != _FAMILY_COMPONENT_COUNTS[name]
                or not isinstance(row.get("custodian_receipt_sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", row["custodian_receipt_sha256"]) is None):
            raise ContractError("source-family and license evidence is incomplete")
        if not isinstance(row.get("required_evidence"), list) or not row["required_evidence"]:
            raise ContractError("qualification manifest requires a concrete custody evidence list")
    if (manifest["decision"] != "blocked_pending_independent_exposure_attestation_and_partition"
            or manifest["required_independent_custody"] is not True):
        raise ContractError("metadata-only manifest must remain blocked pending independent custody")
    return {"schema": "extended-source-qualification-verdict-v1",
            "decision": "blocked_pending_independent_exposure_attestation_and_partition",
            "inventory_digest": live_metadata["inventory_digest"], "sources": sorted(_SOURCES)}
