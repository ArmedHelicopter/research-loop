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
        "scorer_digest": next(cell.scorer_digest for cell in panel.cells if cell.key == row.cell_key), "metric": {"value": 1.0 if row.cell_key[-1] == "11" else 0.0,
        "direction": "higher_better", "value_range": [0.0, 1.0], "scale": "unit"}})) for row in rows)
    result = estimate_grouped_contrast(panel, runtime=rows, scorer_receipts=scored,
        verifier=CombinationPanelVerifier(scorer_verifier=lambda *_: None), direction="higher_better", value_range=(0.0, 1.0), scale="unit")
    assert all(value["mean"] == 1.0 for value in result.data()["benchmark_estimates"].values())
    with pytest.raises(ContractError, match="scorer receipts"):
        estimate_grouped_contrast(panel, runtime=rows, scorer_receipts=scored[:-1],
            verifier=CombinationPanelVerifier(scorer_verifier=lambda *_: None), direction="higher_better", value_range=(0.0, 1.0), scale="unit")


@pytest.mark.parametrize("obligation,positive_arm", [("triple:M4+M5+M6", "111"), ("full-loo", "full")])
def test_triple_and_loo_use_frozen_arms_and_keep_benchmarks_separate(tmp_path: Path, obligation: str, positive_arm: str):
    helper = runpy.run_path("tests/test_modular_combination_panels.py")
    catalogue = helper["_catalogue"](); panel = catalogue.panels[obligation]
    audit = AuditVerifier({"audit-a": b"a" * 32, "audit-b": b"b" * 32})
    def model(request):
        return FrozenRecord.from_dict({"objective_digest": FrozenRecord.from_dict(request.data()["objective"]).content_hash, "outcome": "unknown", "evidence_ids": [], "conclusion": "synthetic", "programme_complete": False})
    rows = [helper["run_combination_cell"](panel, cell, task=catalogue.tasks[cell.task_digest], scenario=catalogue.scenarios[cell.key], package=catalogue.packages[cell.runtime_arm.content_hash], objective=FrozenRecord.from_dict({"p": panel.digest}), sidecar=tmp_path / str(i), model=model, audit_verifier=audit) for i, cell in enumerate(panel.cells)]
    scored = tuple(ScientificScorerReceipt(row.cell_key, FrozenRecord.from_dict({"schema": "independent-scored-cell-v1", "runtime_trace_digest": row.trace_digest, "scorer_digest": next(cell.scorer_digest for cell in panel.cells if cell.key == row.cell_key), "metric": {"value": 1.0 if row.cell_key[-1] == positive_arm else 0.0, "direction": "higher_better", "value_range": [0.0, 1.0], "scale": "unit"}})) for row in rows)
    report = estimate_grouped_contrast(panel, runtime=rows, scorer_receipts=scored, verifier=CombinationPanelVerifier(scorer_verifier=lambda *_: None), direction="higher_better", value_range=(0.0, 1.0), scale="unit").data()
    if obligation == "full-loo":
        assert report["status"] == "not_identifiable" and report["benchmark_estimates"] == {}
        return
    assert set(report["benchmark_estimates"]) == {"blade", "discoverybench"}
    assert all(row["mean"] == 1.0 for row in report["benchmark_estimates"].values())


def test_dependency_unavailable_returns_not_identifiable_without_filling_metrics(tmp_path: Path):
    helper = runpy.run_path("tests/test_modular_combination_panels.py")
    catalogue = helper["_catalogue"](); panel = catalogue.panels["pair:M2+M3"]
    assert panel.interaction_status == "not_identifiable"
