"""Synthetic estimator checks; no benchmark source or score is read."""
import runpy
from pathlib import Path

import pytest

from research_loop.modular.combination_contrasts import estimate_grouped_contrast
from research_loop.modular.combination_panels import CombinationPanelVerifier
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.panel_receipts import ScientificScorerReceipt
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError


def test_pair_interaction_is_group_weighted_and_requires_complete_bound_metrics(tmp_path: Path):
    helper = runpy.run_path("tests/test_modular_combination_panels.py")
    catalogue = helper["_catalogue"](); panel = catalogue.panels["pair:M1+M4"]
    verifier = AuditVerifier({"audit-a": b"a" * 32, "audit-b": b"b" * 32})
    def model(request):
        objective = FrozenRecord.from_dict(request.data()["objective"])
        return FrozenRecord.from_dict({"objective_digest": objective.content_hash, "outcome": "unknown", "evidence_ids": [], "conclusion": "synthetic", "programme_complete": False})
    rows = [helper["run_combination_cell"](panel, cell, task=catalogue.tasks[cell.task_digest], scenario=catalogue.scenarios[cell.key],
            package=catalogue.packages[cell.runtime_arm.content_hash], objective=FrozenRecord.from_dict({"p": panel.digest}),
            sidecar=tmp_path / str(i), model=model, audit_verifier=verifier) for i, cell in enumerate(panel.cells)]
    scored = tuple(ScientificScorerReceipt(row.cell_key, FrozenRecord.from_dict({"schema": "independent-scored-cell-v1", "runtime_trace_digest": row.trace_digest,
        "scorer_digest": next(cell.scorer_digest for cell in panel.cells if cell.key == row.cell_key)})) for row in rows)
    metrics = tuple(FrozenRecord.from_dict({"schema": "combination-cell-metric-v1", "cell_key": list(row.cell_key), "runtime_trace_digest": row.trace_digest,
        "scorer_receipt_digest": score.receipt.content_hash, "value": 1.0 if row.cell_key[-1] == "11" else 0.0,
        "direction": "higher_better", "value_range": [0.0, 1.0], "scale": "unit"}) for row, score in zip(rows, scored, strict=True))
    result = estimate_grouped_contrast(panel, runtime=rows, scorer_receipts=scored, metrics=metrics,
        verifier=CombinationPanelVerifier(scorer_verifier=lambda *_: None), direction="higher_better", value_range=(0.0, 1.0), scale="unit")
    assert all(value["mean"] == 1.0 for value in result.data()["benchmark_estimates"].values())
    with pytest.raises(ContractError, match="missing metric"):
        estimate_grouped_contrast(panel, runtime=rows, scorer_receipts=scored, metrics=metrics[:-1],
            verifier=CombinationPanelVerifier(scorer_verifier=lambda *_: None), direction="higher_better", value_range=(0.0, 1.0), scale="unit")
