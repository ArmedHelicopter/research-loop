"""The production panel compiler and runner share one exact cell contract."""
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.panel_plan import compile_train_panel
from research_loop.modular.panel_receipts import PanelReceiptVerifier
from research_loop.modular.panel_runner import run_train_cell
from test_modular_panel_plan import inputs
from test_modular_panel_runner import audit, model


def test_compiled_q31_runs_every_paired_cell_through_real_runtime_journals(tmp_path):
    compiled = compile_train_panel(**inputs(("Q3.1",)))
    rows = []
    for index, cell in enumerate(compiled.panel.cells):
        result = run_train_cell(cell, task=compiled.tasks[cell.task_digest],
            scenario=compiled.scenarios[cell.key], package=compiled.packages[cell.runtime_arm.content_hash],
            objective=FrozenRecord.from_dict({"fixture_objective": "public prediction comparison"}),
            sidecar=tmp_path / str(index), model=model, audit_verifier=audit())
        rows.append(result.runtime)
    verdict = PanelReceiptVerifier().verify(compiled.panel, rows)
    assert len(rows) == 12
    assert verdict.decision == "engineering_verified" and verdict.scientific_verified is False
    assert verdict.failures == verdict.unscored == verdict.blocked == 0
