from __future__ import annotations

import pytest

from evaluation.modular.custody import CustodyStore, InventoryItem, _merged_groups
from evaluation.modular.calibration import CalibrationAuthority
from research_loop.ontology import ContractError, digest


def _item(benchmark: str, task: str, group: str, content_hash: str) -> InventoryItem:
    return InventoryItem(benchmark, task, group, "official-dev", f"fixture/{task}", (content_hash,))


def _calibration(panel: str):
    criteria = {"minimum_cases_per_benchmark": 1, "minimum_coverage": {"valid_positive": 1, "valid_negative": 1,
        "invalid_measurement": 1, "uncertain": 1, "negation_or_quoted_completion": 1, "correct_rejection": 1,
        "over_rejection": 1, "reasonable_alternative": 1, "empty_output": 1}, "minimum_precision": 0.5,
        "minimum_recall": 0.5, "maximum_abstention_rate": 0.5, "maximum_uncertainty": 0.5}
    coverage = {key: 1 for key in criteria["minimum_coverage"]}
    matrix = {"tp": 1, "tn": 1, "fp": 0, "fn": 0, "abstained": 0}
    return CalibrationAuthority("fixture-calibration", b"k" * 32).issue({"schema": "scorer-calibration-v1", "panel_digest": panel,
        "scorer_digest": "e" * 64, "protocol_digest": "f" * 64, "scorer_code_digest": "1" * 64,
        "judge_identity": "independent", "judge_parameters": {"temperature": 0}, "rubric_digest": "2" * 64,
        "calibration_manifest_digest": "3" * 64, "blind_review_protocol_digest": "4" * 64,
        "arbitration_protocol_digest": "5" * 64, "applicable_benchmarks": ["blade", "discoverybench"],
        "criteria": criteria, "criteria_digest": digest(criteria), "coverage": {"blade": coverage, "discoverybench": coverage},
        "confusion_matrix": {"blade": matrix, "discoverybench": matrix}, "uncertainty": {"blade": 0.1, "discoverybench": 0.1}})


def test_default_split_payload_and_digest_remain_legacy_compatible(tmp_path) -> None:
    items = [_item("scicode", "one", "one", "a" * 64)]
    store = CustodyStore(tmp_path / "state.json")
    inventory_digest = store.inventory(items)
    split = store.split(seed="legacy", validation_percent=50)
    groups = _merged_groups(items)
    expected_payload = {"seed": "legacy", "validation_percent": 50, "inventory_digest": inventory_digest,
        "rows": [{"item": "scicode:one", "group": groups["scicode:one"], "domain": "quarantine",
                  "official_split": "official-dev", "exposure": "unknown", "custodian_qualified": False}]}
    assert split["digest"] == digest(expected_payload)
    assert "train_only_declaration" not in split
    assert CustodyStore(tmp_path / "state.json").split(seed="legacy", validation_percent=50)["digest"] == split["digest"]


def test_predeclared_member_forces_its_entire_cross_benchmark_hash_closure_train_only(tmp_path) -> None:
    shared = "a" * 64
    store = CustodyStore(tmp_path / "state.json")
    store.inventory([_item("scicode", "official-dev", "scicode-dev", shared),
                     _item("scienceagentbench", "connected", "sab-root", shared)])
    reason = "b" * 64
    split = store.split(seed="frozen", validation_percent=100,
                        train_only_item_ids=["scicode:official-dev"], train_only_reason_commitment=reason)
    rows = {row["item"]: row for row in split["rows"]}
    assert rows["scicode:official-dev"]["group"] == rows["scienceagentbench:connected"]["group"]
    assert {row["domain"] for row in rows.values()} == {"train"}
    assert split["train_only_declaration"] == {"item_ids": ["scicode:official-dev"],
        "group_ids": [rows["scicode:official-dev"]["group"]], "reason_commitment": reason}
    with pytest.raises(ContractError, match="non-validation"):
        store.qualify_stage(stage="future", panel_digest="c" * 64,
                            group_ids=[rows["scicode:official-dev"]["group"]], arm_schedule=["arm-a"])
    with pytest.raises(ContractError, match="non-validation"):
        store.lease_validation(stage="future", panel_digest="c" * 64, candidate_digest="d" * 64,
            group_ids=[rows["scicode:official-dev"]["group"]], arm_schedule=["arm-a"], scorer_digest="e" * 64,
            protocol_digest="f" * 64, calibration_receipt=_calibration("c" * 64))
    assert CustodyStore(tmp_path / "state.json").split(seed="frozen", validation_percent=100,
        train_only_item_ids=["scicode:official-dev"], train_only_reason_commitment=reason)["digest"] == split["digest"]
    with pytest.raises(ContractError, match="reallocation"):
        store.split(seed="frozen", validation_percent=100)
    with pytest.raises(ContractError, match="reallocation"):
        store.split(seed="frozen", validation_percent=100,
                    train_only_item_ids=["scicode:official-dev"], train_only_reason_commitment="d" * 64)


def test_train_only_declaration_rejects_unknown_or_uncommitted_items(tmp_path) -> None:
    store = CustodyStore(tmp_path / "state.json")
    store.inventory([_item("scicode", "known", "known", "a" * 64)])
    with pytest.raises(ContractError, match="invalid train-only"):
        store.split(seed="frozen", train_only_item_ids=["scicode:unknown"], train_only_reason_commitment="b" * 64)
    with pytest.raises(ContractError, match="invalid train-only"):
        store.split(seed="frozen", train_only_item_ids=["scicode:known"], train_only_reason_commitment=None)
    with pytest.raises(ContractError, match="reason requires"):
        store.split(seed="frozen", train_only_reason_commitment="b" * 64)
