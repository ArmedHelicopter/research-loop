import json
from pathlib import Path

import pytest

from evaluation.modular.extended_qualification import validate_extended_qualification
from research_loop.ontology import ContractError


def _live():
    return {"schema": "extended-source-inventory-metadata-v1", "inventory_digest": "9a25e086a55a1ebd73837a549c332a7cfd103910d0b086042b89ab1e5cbef7c7",
            "custody_state_sha256": "6959fe024f6468b0fc0bae79ab3d39ff73c0492c6f15659079d178e4b0a212d3",
            "access_isolation": "not_verified", "split_assigned": False,
            "qualification": "unassigned_pending_source_family_and_exposure_review",
            "source_pins": {"scicode": "4510f6a6aa27c43fad7b43da2c59602a86e88480", "scienceagentbench": "9c6e96c9e74572e979b0930ee735041cef528cb7"}}


def test_metadata_only_manifest_blocks_unknown_extended_sources():
    path = Path("docs/data-source-metadata/extended-source-qualification.json")
    verdict = validate_extended_qualification(json.loads(path.read_text(encoding="utf-8")), _live())
    assert verdict["decision"] == "blocked_pending_independent_exposure_attestation_and_partition"
    assert verdict["sources"] == ["scicode", "scienceagentbench"]


def test_manifest_cannot_upgrade_unknown_exposure_to_a_training_or_validation_claim():
    manifest = json.loads(Path("docs/data-source-metadata/extended-source-qualification.json").read_text(encoding="utf-8"))
    manifest["sources"]["scicode"]["runtime_status"] = "train_eligible"
    with pytest.raises(ContractError, match="unknown exposure"):
        validate_extended_qualification(manifest, _live())


def test_manifest_rejects_a_changed_received_pin_before_any_qualification():
    manifest = json.loads(Path("docs/data-source-metadata/extended-source-qualification.json").read_text(encoding="utf-8"))
    live = _live()
    live["source_pins"] = {**live["source_pins"], "scicode": "different-received-pin"}
    with pytest.raises(ContractError, match="not bound"):
        validate_extended_qualification(manifest, live)


def test_manifest_cannot_replace_the_core_benchmark_pair():
    manifest = json.loads(Path("docs/data-source-metadata/extended-source-qualification.json").read_text(encoding="utf-8"))
    manifest["core_benchmarks_retained"] = ["scicode", "scienceagentbench"]
    with pytest.raises(ContractError, match="cannot replace core benchmarks"):
        validate_extended_qualification(manifest, _live())


def test_received_dataset_pins_are_archived_separately_from_repository_metadata_pins():
    public = json.loads(Path("docs/data-source-metadata/received-snapshot-public-metadata.json").read_text(encoding="utf-8"))
    live = _live()
    assert {name: row["received_snapshot_revision"] for name, row in public["sources"].items()} == live["source_pins"]
    assert {name: row["dataset_card_license_declaration"] for name, row in public["sources"].items()} == {
        "scicode": "apache-2.0", "scienceagentbench": "cc-by-4.0"}
    for name in live["source_pins"]:
        historical = json.loads(Path(f"docs/data-source-metadata/{name}.json").read_text(encoding="utf-8"))
        assert historical["received_dataset_snapshot"]["revision"] == live["source_pins"][name]
        assert historical["received_dataset_snapshot"]["revision"] != historical["pinned_commit"]
