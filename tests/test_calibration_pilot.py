"""Synthetic diagnostic calibration only; no real benchmark reference access."""
from evaluation.modular.calibration_pilot import PILOT_SCHEMA, OPPORTUNITIES


def test_contract_is_diagnostic_and_complete():
    assert PILOT_SCHEMA == 'four-train-diagnostic-calibration-v1'
    assert OPPORTUNITIES == 72
