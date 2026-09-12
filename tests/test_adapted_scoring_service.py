"""Synthetic service integration: no benchmark reference payload is read here."""
from dataclasses import replace

import pytest

from evaluation.modular.scoring_service import (AdaptedMetricReceiptVerifier, ExactFieldReferenceEvaluator,
    IndependentScoringService, ScorerConfig, ScoringAuthority)
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


@pytest.mark.parametrize("benchmark,expected", [("discoverybench", 0.0), ("blade", 2 / 3)])
def test_service_calculates_signed_adapted_scores_and_panel_verifies_them(tmp_path, benchmark, expected):
    frozen, runtime, config = _panel_with_config(tmp_path, benchmark)
    cells = [cell for cell in frozen.cells if cell.identity.benchmark == benchmark]
    handles = {FrozenRecord.from_dict(cell.identity.data()).content_hash: "private-task-handle-" + str(i) for i, cell in enumerate(cells)}
    # The evaluator parses each executed candidate and compares it with the
    # service-only synthetic reference.  No expected dimensions enter it.
    references = {handle: {"benchmark": benchmark, "expected": {"outcome": "unknown", "conclusion": "different", "programme_complete": False}}
                  for handle in handles.values()}
    service = IndependentScoringService(config=config, authority=ScoringAuthority("independent-test", b"s" * 32),
        evaluator=ExactFieldReferenceEvaluator(references), allowed_task_handles=handles)
    scores = []
    for cell, row in zip(cells, (r for r in runtime if r.cell_key in {c.key for c in cells})):
        scores.append(service.score(panel_digest=frozen.digest, cell=cell, runtime=row))
    # The main assertion also drives the actual PanelReceiptVerifier contract.
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
    handles = {FrozenRecord.from_dict(cell.identity.data()).content_hash: "private-" + str(i) for i, cell in enumerate(frozen.cells)}
    benchmarks = {FrozenRecord.from_dict(cell.identity.data()).content_hash: cell.identity.benchmark for cell in frozen.cells}
    references = {handle: {"benchmark": benchmarks[identity_digest], "expected": {"outcome": "unknown", "conclusion": "engineering fixture", "programme_complete": False}}
                  for identity_digest, handle in handles.items()}
    service = IndependentScoringService(config=config, authority=ScoringAuthority("independent-test", b"s" * 32),
        evaluator=ExactFieldReferenceEvaluator(references), allowed_task_handles=handles)
    scores = tuple(service.score(panel_digest=frozen.digest, cell=cells[row.cell_key], runtime=row,
        ) for row in runtime)
    verdict = PanelReceiptVerifier(scorer_verifier=AdaptedMetricReceiptVerifier(authority_keys={"independent-test": b"s" * 32}, config=config)).verify(frozen, runtime, scorer_receipts=scores)
    assert verdict.adapted_score_verified is True and verdict.scientific_verified is False and verdict.decision == "adapted_score_verified"


def test_receipt_signature_aggregate_and_runtime_bindings_fail_closed(tmp_path):
    frozen, runtime, config = _panel_with_config(tmp_path, "blade")
    cell = next(c for c in frozen.cells if c.identity.benchmark == "blade")
    row = next(r for r in runtime if r.cell_key == cell.key)
    handle = FrozenRecord.from_dict(cell.identity.data()).content_hash
    service = IndependentScoringService(config=config, authority=ScoringAuthority("independent-test", b"s" * 32),
        evaluator=ExactFieldReferenceEvaluator({"private-handle": {"benchmark": "blade", "expected": {"outcome": "unknown", "conclusion": "engineering fixture", "programme_complete": False}}}), allowed_task_handles={handle: "private-handle"})
    scored = service.score(panel_digest=frozen.digest, cell=cell, runtime=row)
    verifier = AdaptedMetricReceiptVerifier(authority_keys={"independent-test": b"s" * 32}, config=config)
    verifier(scored, cell, frozen)
    forged = scored.receipt.data(); forged["body"]["metric"]["value"] = 0.0
    with pytest.raises(ContractError, match="signature mismatch"):
        verifier(ScientificScorerReceipt(cell.key, FrozenRecord.from_dict(forged)), cell, frozen)
    other_cell = next(c for c in frozen.cells if c.identity.benchmark == "blade" and c.key != cell.key)
    with pytest.raises(ContractError, match="cell does not match"):
        service.score(panel_digest=frozen.digest, cell=other_cell, runtime=row)
    with pytest.raises(ContractError, match="output does not bind"):
        service.score(panel_digest=frozen.digest, cell=cell, runtime=replace(row, output_digest="b" * 64))
