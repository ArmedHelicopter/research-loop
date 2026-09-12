"""Synthetic calibration-gate integration checks; no labels or real custody state."""
from pathlib import Path

import pytest

from evaluation.modular.calibration import CalibrationAuthority
from evaluation.modular.custody import CustodyStore, InventoryItem
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError


PANEL, SCORER, PROTOCOL = "a" * 64, "b" * 64, "c" * 64


def receipt(*, panel=PANEL, scorer=SCORER, protocol=PROTOCOL) -> FrozenRecord:
    return CalibrationAuthority("calibration-service", b"k" * 32).issue({
        "schema": "scorer-calibration-v1", "panel_digest": panel, "scorer_digest": scorer,
        "protocol_digest": protocol, "scorer_code_digest": "d" * 64, "judge_identity": "independent-judge",
        "judge_parameters": {"temperature": 0}, "rubric_digest": "e" * 64,
        "calibration_manifest_digest": "f" * 64, "blind_review_protocol_digest": "1" * 64,
        "arbitration_protocol_digest": "2" * 64, "applicable_benchmarks": ["blade", "discoverybench"],
        "confusion_matrix": {"positive": {"positive": 2, "negative": 0}, "negative": {"positive": 0, "negative": 2}},
        "uncertainty": {"wilson_half_width": 0.1},
    })


def store(tmp_path: Path, *, keys=True) -> tuple[CustodyStore, str]:
    result = CustodyStore(tmp_path / "synthetic.json", calibration_keys={"calibration-service": b"k" * 32} if keys else None)
    result.inventory([InventoryItem("blade", "synthetic", "group", "synthetic", "synthetic", ("0" * 64,))])
    result.attest_independent_clean(item_ids=["blade:synthetic"], custodian_id="custodian",
                                    source_qualification_digest="3" * 64, exposure_qualification_digest="4" * 64,
                                    tested_arm_ids=["tested-arm"])
    return result, result.split(seed="synthetic", validation_percent=100)["rows"][0]["group"]


def test_qualification_is_metadata_only_without_receipt_and_lease_fails_closed(tmp_path: Path) -> None:
    custody, group = store(tmp_path, keys=False)
    metadata = custody.qualify_stage(stage="C1", panel_digest=PANEL, group_ids=[group], arm_schedule=["arm"])
    assert metadata["qualification"] == "metadata_only" and metadata["qualified"] is False
    with pytest.raises(ContractError, match="signed scorer calibration"):
        custody.lease_validation(stage="C1", panel_digest=PANEL, group_ids=[group], arm_schedule=["arm"])


def test_lease_requires_configured_authority_and_exact_panel_scorer_protocol(tmp_path: Path) -> None:
    custody, group = store(tmp_path)
    with pytest.raises(ContractError, match="exact panel, scorer, and protocol"):
        custody.lease_validation(stage="C1", panel_digest=PANEL, group_ids=[group], arm_schedule=["arm"],
                                 scorer_digest=SCORER, protocol_digest=PROTOCOL, calibration_receipt=receipt(panel="9" * 64))
    lease = custody.lease_validation(stage="C1", panel_digest=PANEL, group_ids=[group], arm_schedule=["arm"],
                                     scorer_digest=SCORER, protocol_digest=PROTOCOL, calibration_receipt=receipt())
    assert lease["qualification"] == "calibrated" and lease["status"] == "active"
    assert lease["calibration_receipt_digest"] == receipt().content_hash


def test_untrusted_or_caller_shaped_calibration_is_rejected(tmp_path: Path) -> None:
    custody, group = store(tmp_path)
    unsigned = FrozenRecord.from_dict({"body": receipt().data()["body"], "mac": "0" * 64})
    with pytest.raises(ContractError, match="signature"):
        custody.lease_validation(stage="C1", panel_digest=PANEL, group_ids=[group], arm_schedule=["arm"],
                                 scorer_digest=SCORER, protocol_digest=PROTOCOL, calibration_receipt=unsigned)
