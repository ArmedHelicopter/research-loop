"""Synthetic service integration: no benchmark reference payload is read here."""
from dataclasses import replace

import pytest

from evaluation.modular.scoring_service import AdaptedMetricReceiptVerifier, IndependentScoringService, ScorerConfig, ScoringAuthority
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.panel_receipts import FrozenPanel, PanelReceiptVerifier, ScientificScorerReceipt
from research_loop.ontology import ContractError


def _panel_with_config(tmp_path, benchmark):
    from test_modular_panel_receipts import panel
    config = ScorerConfig.create(benchmark=benchmark, evaluator_id="synthetic-authority", rubric_digest="a" * 64, version="v1")
    frozen, runtime = panel(tmp_path)
    cells = tuple(replace(cell, scorer_digest=config.digest) for cell in frozen.cells)
    return (FrozenPanel(frozen.stage, frozen.domain, frozen.split_digest, frozen.candidate_digest, frozen.scope_ids,
            frozen.legal_arm_grids, frozen.acceptance_criteria, cells, frozen.combinations), runtime, config)


@pytest.mark.parametrize("benchmark,expected", [("discoverybench", 0.125), ("blade", 0.5)])
def test_service_calculates_signed_adapted_scores_and_panel_verifies_them(tmp_path, benchmark, expected):
    frozen, runtime, config = _panel_with_config(tmp_path, benchmark)
    # This closure models protected evaluator state.  The service sees only the
    # controller's opaque task handle; the solver and receipt see neither key.
    dimensions = ({"context": 0.5, "variable_f1": 0.5, "relation": 0.5}
                  if benchmark == "discoverybench" else {"cvars": 1.0, "transform": 0.5, "model": 0.0})
    cells = [cell for cell in frozen.cells if cell.identity.benchmark == benchmark]
    handles = {FrozenRecord.from_dict(cell.identity.data()).content_hash: "private-task-handle-" + str(i) for i, cell in enumerate(cells)}
    service = IndependentScoringService(config=config, authority=ScoringAuthority("independent-test", b"s" * 32),
        evaluator=lambda handle, submission: dimensions, allowed_task_handles=handles)
    scores = []
    for cell, row in zip(cells, (r for r in runtime if r.cell_key in {c.key for c in cells})):
        scores.append(service.score(panel_digest=frozen.digest, cell=cell, runtime=row, submission=FrozenRecord.from_dict({"candidate": "synthetic-output"})))
    # The main assertion also drives the actual PanelReceiptVerifier contract.
    if benchmark == "discoverybench":
        assert scores[0].receipt.data()["body"]["metric"]["value"] == expected
    else:
        assert scores[0].receipt.data()["body"]["metric"]["value"] == expected
    verifier = AdaptedMetricReceiptVerifier(authority_keys={"independent-test": b"s" * 32}, config=config)
    for score, cell in zip(scores, cells):
        verifier(score, cell, frozen)

    # Individual service tests above cover each benchmark-specific aggregate.


def test_core_pair_service_drives_actual_panel_receipt_verifier(tmp_path):
    frozen, runtime, _ = _panel_with_config(tmp_path, "discoverybench")
    config = ScorerConfig.create(benchmark="core_pair", evaluator_id="synthetic-authority", rubric_digest="b" * 64, version="v1")
    frozen = FrozenPanel(frozen.stage, frozen.domain, frozen.split_digest, frozen.candidate_digest, frozen.scope_ids,
        frozen.legal_arm_grids, frozen.acceptance_criteria, tuple(replace(c, scorer_digest=config.digest) for c in frozen.cells), frozen.combinations)
    cells = {cell.key: cell for cell in frozen.cells}
    handles = {FrozenRecord.from_dict(cell.identity.data()).content_hash: cell.identity.benchmark for cell in frozen.cells}
    def evaluator(handle, submission):
        return ({"context": 1.0, "variable_f1": 0.5, "relation": 0.5}
                if handle == "discoverybench" else {"cvars": 1.0, "transform": 0.5, "model": 0.0})
    service = IndependentScoringService(config=config, authority=ScoringAuthority("independent-test", b"s" * 32), evaluator=evaluator, allowed_task_handles=handles)
    scores = tuple(service.score(panel_digest=frozen.digest, cell=cells[row.cell_key], runtime=row,
        submission=FrozenRecord.from_dict({"candidate": "synthetic-output"})) for row in runtime)
    verdict = PanelReceiptVerifier(scorer_verifier=AdaptedMetricReceiptVerifier(authority_keys={"independent-test": b"s" * 32}, config=config)).verify(frozen, runtime, scorer_receipts=scores)
    assert verdict.scientific_verified is True and verdict.decision == "evidence_verified"


def test_receipt_signature_aggregate_and_runtime_bindings_fail_closed(tmp_path):
    frozen, runtime, config = _panel_with_config(tmp_path, "blade")
    cell = next(c for c in frozen.cells if c.identity.benchmark == "blade")
    row = next(r for r in runtime if r.cell_key == cell.key)
    handle = FrozenRecord.from_dict(cell.identity.data()).content_hash
    service = IndependentScoringService(config=config, authority=ScoringAuthority("independent-test", b"s" * 32),
        evaluator=lambda *_: {"cvars": 1.0, "transform": 0.5, "model": 0.0}, allowed_task_handles={handle: "private-handle"})
    scored = service.score(panel_digest=frozen.digest, cell=cell, runtime=row, submission=FrozenRecord.from_dict({"candidate": "x"}))
    verifier = AdaptedMetricReceiptVerifier(authority_keys={"independent-test": b"s" * 32}, config=config)
    verifier(scored, cell, frozen)
    forged = scored.receipt.data(); forged["body"]["metric"]["value"] = 1.0
    with pytest.raises(ContractError, match="signature mismatch"):
        verifier(ScientificScorerReceipt(cell.key, FrozenRecord.from_dict(forged)), cell, frozen)
    with pytest.raises(ContractError, match="successful bound runtime"):
        service.score(panel_digest=frozen.digest, cell=cell, runtime=replace(row, status="unscored", failure_reason="evaluator unavailable"), submission=FrozenRecord.from_dict({"candidate": "x"}))
