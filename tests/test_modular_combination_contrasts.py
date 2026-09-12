"""Synthetic estimator checks; no benchmark source or score is read."""
import runpy
from dataclasses import replace
from pathlib import Path

import pytest

from research_loop.modular.combination_contrasts import estimate_grouped_contrast
from research_loop.modular.combination_panels import CombinationPanelVerifier
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.panel_receipts import ScientificScorerReceipt
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.combination_panels import compile_combination_catalogue
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


def test_group_equal_weighting_does_not_promote_two_tasks_to_two_independent_groups(tmp_path: Path):
    helper = runpy.run_path("tests/test_modular_combination_panels.py")
    base_tasks, arm_map, scorer, criteria = helper["_inputs"]()
    tasks = []
    for base in base_tasks:
        # group A has two tasks, group B one task, for each benchmark.
        for task_id, group in (("a1", base.identity.group_id + "-a"), ("a2", base.identity.group_id + "-a"), ("b", base.identity.group_id + "-b")):
            tasks.append(replace(base, identity=replace(base.identity, task_id=base.identity.benchmark + "-" + task_id, group_id=group)))
    manifest = TrainingManifest.freeze([task.identity for task in tasks])
    packages = {key: CandidatePackage.create(parent_digest=None, manifest=manifest,
        changes={"prompt": {"instructions": "grouped synthetic arm" + key}}, search_cost=0) for key in arm_map}
    panel = compile_combination_catalogue(stage="groups", tasks=tasks, baseline_digest="a" * 64,
        packages_by_arm=packages, scorer=scorer, acceptance_criteria=criteria).panels["pair:M1+M4"]
    audit = AuditVerifier({"a": b"a" * 32, "b": b"b" * 32})
    def model(request): return FrozenRecord.from_dict({"objective_digest": FrozenRecord.from_dict(request.data()["objective"]).content_hash, "outcome": "unknown", "evidence_ids": [], "conclusion": "synthetic", "programme_complete": False})
    task_map = {task.content_hash: task for task in tasks}
    scenarios = {cell.key: FrozenRecord.from_dict({"schema": "combination-public-scenario-v1", "obligation_id": panel.obligation_id, "design_digest": panel.design.content_hash, "task_digest": cell.task_digest, "replicate": cell.replicate, "status": "predeclared"}) for cell in panel.cells}
    from research_loop.modular.combination_panels import run_combination_cell
    rows = [run_combination_cell(panel, cell, task=task_map[cell.task_digest], scenario=scenarios[cell.key], package=packages[cell.runtime_arm.content_hash], objective=FrozenRecord.from_dict({"p": panel.digest}), sidecar=tmp_path / str(i), model=model, audit_verifier=audit) for i, cell in enumerate(panel.cells)]
    scored = []
    for row in rows:
        # Only the B-group full interaction is 2; A's two tasks are 0.
        group_b = row.cell_key[3].endswith("-b")
        value = 2.0 if group_b and row.cell_key[-1] == "11" else 0.0
        cell = next(c for c in panel.cells if c.key == row.cell_key)
        scored.append(ScientificScorerReceipt(row.cell_key, FrozenRecord.from_dict({"schema": "independent-scored-cell-v1", "runtime_trace_digest": row.trace_digest, "scorer_digest": cell.scorer_digest, "metric": {"value": value, "direction": "higher_better", "value_range": [0.0, 2.0], "scale": "unit"}})))
    report = estimate_grouped_contrast(panel, runtime=rows, scorer_receipts=scored, verifier=CombinationPanelVerifier(scorer_verifier=lambda *_: None), direction="higher_better", value_range=(0.0, 2.0), scale="unit").data()
    assert all(value["independent_groups"] == 2 and value["mean"] == 1.0 for value in report["benchmark_estimates"].values())


def test_metric_mutation_and_trace_drift_fail_authenticated_scorer_verifier(tmp_path: Path):
    helper = runpy.run_path("tests/test_modular_combination_panels.py")
    catalogue = helper["_catalogue"](); panel = catalogue.panels["pair:M1+M4"]
    audit = AuditVerifier({"a": b"a" * 32, "b": b"b" * 32})
    def model(request): return FrozenRecord.from_dict({"objective_digest": FrozenRecord.from_dict(request.data()["objective"]).content_hash, "outcome": "unknown", "evidence_ids": [], "conclusion": "synthetic", "programme_complete": False})
    rows = [helper["run_combination_cell"](panel, cell, task=catalogue.tasks[cell.task_digest], scenario=catalogue.scenarios[cell.key], package=catalogue.packages[cell.runtime_arm.content_hash], objective=FrozenRecord.from_dict({"p": panel.digest}), sidecar=tmp_path / str(i), model=model, audit_verifier=audit) for i, cell in enumerate(panel.cells)]
    scored = tuple(ScientificScorerReceipt(row.cell_key, FrozenRecord.from_dict({"schema": "independent-scored-cell-v1", "runtime_trace_digest": row.trace_digest, "scorer_digest": next(c.scorer_digest for c in panel.cells if c.key == row.cell_key), "metric": {"value": 0.0, "direction": "higher_better", "value_range": [0.0, 1.0], "scale": "unit"}})) for row in rows)
    allowed = {item.receipt.content_hash for item in scored}
    trusted = CombinationPanelVerifier(scorer_verifier=lambda receipt, *_: (_ for _ in ()).throw(ContractError("signature drift")) if receipt.receipt.content_hash not in allowed else None)
    changed = list(scored); body = changed[0].receipt.data(); body["metric"]["value"] = 1.0; changed[0] = ScientificScorerReceipt(changed[0].cell_key, FrozenRecord.from_dict(body))
    with pytest.raises(ContractError, match="signature drift"):
        estimate_grouped_contrast(panel, runtime=rows, scorer_receipts=changed, verifier=trusted, direction="higher_better", value_range=(0.0, 1.0), scale="unit")
    body = scored[0].receipt.data(); body["runtime_trace_digest"] = "0" * 64; drift = list(scored); drift[0] = ScientificScorerReceipt(drift[0].cell_key, FrozenRecord.from_dict(body))
    with pytest.raises(ContractError):
        estimate_grouped_contrast(panel, runtime=rows, scorer_receipts=drift, verifier=CombinationPanelVerifier(scorer_verifier=lambda *_: None), direction="higher_better", value_range=(0.0, 1.0), scale="unit")
