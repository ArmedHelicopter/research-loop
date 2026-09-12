"""Synthetic calibration-gate integration checks; no labels or real custody state."""
from pathlib import Path

import pytest

from evaluation.modular.calibration import CalibrationAuthority
from evaluation.modular.custody import CustodyStore, InventoryItem
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError, digest


PANEL, SCORER, PROTOCOL = "a" * 64, "b" * 64, "c" * 64


CRITERIA = {"minimum_cases_per_benchmark": 9,
            "minimum_coverage": {"valid_positive": 1, "valid_negative": 1, "invalid_measurement": 1,
                                 "uncertain": 1, "negation_or_quoted_completion": 1, "correct_rejection": 1,
                                 "over_rejection": 1, "reasonable_alternative": 1, "empty_output": 1},
            "minimum_precision": 0.8, "minimum_recall": 0.8, "maximum_abstention_rate": 0.2,
            "maximum_uncertainty": 0.2}


def receipt(*, panel=PANEL, scorer=SCORER, protocol=PROTOCOL, criteria=CRITERIA, coverage=None, matrix=None, uncertainty=None, benchmarks=None) -> FrozenRecord:
    coverage = coverage or {name: 1 for name in CRITERIA["minimum_coverage"]}
    matrix = matrix or {"tp": 4, "tn": 4, "fp": 0, "fn": 0, "abstained": 1}
    uncertainty = uncertainty if uncertainty is not None else 0.1
    return CalibrationAuthority("calibration-service", b"k" * 32).issue({
        "schema": "scorer-calibration-v1", "panel_digest": panel, "scorer_digest": scorer,
        "protocol_digest": protocol, "scorer_code_digest": "d" * 64, "judge_identity": "independent-judge",
        "judge_parameters": {"temperature": 0}, "rubric_digest": "e" * 64,
        "calibration_manifest_digest": "f" * 64, "blind_review_protocol_digest": "1" * 64,
        "arbitration_protocol_digest": "2" * 64, "applicable_benchmarks": benchmarks or ["blade", "discoverybench"],
        "criteria": criteria, "criteria_digest": digest(criteria),
        "coverage": {"blade": coverage, "discoverybench": coverage},
        "confusion_matrix": {"blade": matrix, "discoverybench": matrix},
        "uncertainty": {"blade": uncertainty, "discoverybench": uncertainty},
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
    assert lease["qualification"] == "calibration_eligible" and lease["status"] == "active"
    assert lease["calibration_receipt_digest"] == receipt().content_hash


def test_untrusted_or_caller_shaped_calibration_is_rejected(tmp_path: Path) -> None:
    custody, group = store(tmp_path)
    unsigned = FrozenRecord.from_dict({"body": receipt().data()["body"], "mac": "0" * 64})
    with pytest.raises(ContractError, match="signature"):
        custody.lease_validation(stage="C1", panel_digest=PANEL, group_ids=[group], arm_schedule=["arm"],
                                 scorer_digest=SCORER, protocol_digest=PROTOCOL, calibration_receipt=unsigned)


@pytest.mark.parametrize(("matrix", "coverage"), [
    ({"tp": 0, "tn": 0, "fp": 4, "fn": 4, "abstained": 1}, None),
    ({"tp": 0, "tn": 0, "fp": 0, "fn": 0, "abstained": 0}, {name: 0 for name in CRITERIA["minimum_coverage"]}),
    ({"tp": 4, "tn": 4, "fp": 0, "fn": 0, "abstained": 1}, {**{name: 1 for name in CRITERIA["minimum_coverage"]}, "reasonable_alternative": 0}),
])
def test_signed_metadata_does_not_imply_calibration_eligibility(tmp_path: Path, matrix, coverage) -> None:
    custody, group = store(tmp_path)
    with pytest.raises(ContractError, match="does not meet frozen criteria"):
        custody.lease_validation(stage="C1", panel_digest=PANEL, group_ids=[group], arm_schedule=["arm"],
                                 scorer_digest=SCORER, protocol_digest=PROTOCOL,
                                 calibration_receipt=receipt(matrix=matrix, coverage=coverage))


@pytest.mark.parametrize("uncertainty", [float("nan"), float("inf")])
def test_nonfinite_uncertainty_is_rejected_before_qualification(tmp_path: Path, uncertainty: float) -> None:
    custody, group = store(tmp_path)
    with pytest.raises(ContractError, match="finite"):
        custody.lease_validation(stage="C1", panel_digest=PANEL, group_ids=[group], arm_schedule=["arm"],
                                 scorer_digest=SCORER, protocol_digest=PROTOCOL, calibration_receipt=receipt(uncertainty=uncertainty))


def test_signed_criteria_digest_cannot_drift(tmp_path: Path) -> None:
    custody, group = store(tmp_path)
    body = receipt().data()["body"]
    body["criteria_digest"] = "0" * 64
    forged = CalibrationAuthority("calibration-service", b"k" * 32).issue({**body, "criteria_digest": digest(body["criteria"])})
    bad = FrozenRecord.from_dict({"body": {**forged.data()["body"], "criteria_digest": "0" * 64}, "mac": forged.data()["mac"]})
    with pytest.raises(ContractError, match="criteria digest"):
        custody.lease_validation(stage="C1", panel_digest=PANEL, group_ids=[group], arm_schedule=["arm"], scorer_digest=SCORER, protocol_digest=PROTOCOL, calibration_receipt=bad)


def test_missing_benchmark_coverage_never_creates_an_eligible_receipt() -> None:
    with pytest.raises(ContractError, match="both required benchmarks"):
        receipt(benchmarks=["blade"])
