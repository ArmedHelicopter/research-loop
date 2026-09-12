"""Fixture-only transport tests; no benchmark reference payload is read."""
from dataclasses import replace
import hashlib

import pytest

from evaluation.modular.scoring_service import (AdaptedMetricReceiptVerifier, FrozenRubricTransport,
    IndependentScoringService, ScorerConfig, ScoringAuthority)
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.panel_receipts import FrozenPanel, PanelReceiptVerifier, ScientificScorerReceipt
from research_loop.ontology import ContractError


class FixtureOnlyRubricEndpoint:
    """Synthetic parser/comparator, deliberately unavailable to production code."""
    _fields = {
        "discoverybench": {"context": "outcome", "variable_f1": "conclusion", "relation": "programme_complete"},
        "blade": {"cvars": "outcome", "transform": "conclusion", "model": "programme_complete"},
    }

    def __init__(self, references):
        self.references = references

    def __call__(self, request):
        body = request.data(); benchmark, candidate = body["benchmark"], body["candidate"]
        expected = self.references[body["task_handle"]]
        fields = self._fields[benchmark]
        if set(expected) != set(fields.values()) or any(field not in candidate for field in fields.values()):
            raise ContractError("fixture reference/candidate lacks a required compared field")
        dimensions = {dimension: float(candidate[field] == expected[field]) for dimension, field in fields.items()}
        return FrozenRecord.from_dict({"schema": "adapted-rubric-evaluation-response-v1", "panel_digest": body["panel_digest"],
            "scorer_config_digest": body["scorer_config_digest"], "benchmark": benchmark,
            "task_handle_digest": hashlib.sha256(body["task_handle"].encode()).hexdigest(),
            "candidate_digest": body["candidate_digest"], "dimensions": dimensions})


def _panel_with_config(tmp_path, benchmark):
    from test_modular_panel_receipts import panel
    config = ScorerConfig.create(benchmark=benchmark, evaluator_id="frozen-rubric-transport", rubric_digest="a" * 64, version="v1")
    frozen, runtime = panel(tmp_path)
    cells = tuple(replace(cell, scorer_digest=config.digest) for cell in frozen.cells)
    return (FrozenPanel(frozen.stage, frozen.domain, frozen.split_digest, frozen.candidate_digest, frozen.scope_ids,
            frozen.legal_arm_grids, frozen.acceptance_criteria, cells, frozen.combinations), runtime, config)


def _service(panel, config, *, mismatch_conclusion=False):
    identities = {FrozenRecord.from_dict(cell.identity.data()).content_hash: "fixture-private-" + str(i)
                  for i, cell in enumerate(panel.cells)}
    references = {handle: {"outcome": "unknown", "conclusion": "different" if mismatch_conclusion else "engineering fixture", "programme_complete": False}
                  for handle in identities.values()}
    return IndependentScoringService(config=config, authority=ScoringAuthority("independent-test", b"s" * 32),
        evaluator=FrozenRubricTransport(FixtureOnlyRubricEndpoint(references)), allowed_task_handles=identities)


@pytest.mark.parametrize("benchmark,expected", [("discoverybench", 0.0), ("blade", 2 / 3)])
def test_fixture_transport_parses_executed_candidate_and_calculates_adapted_metric(tmp_path, benchmark, expected):
    frozen, runtime, config = _panel_with_config(tmp_path, benchmark)
    service = _service(frozen, config, mismatch_conclusion=True)
    cell = next(cell for cell in frozen.cells if cell.identity.benchmark == benchmark)
    row = next(row for row in runtime if row.cell_key == cell.key)
    score = service.score(panel=frozen, cell=cell, runtime=row)
    assert score.receipt.data()["body"]["metric"]["value"] == expected
    AdaptedMetricReceiptVerifier(authority_keys={"independent-test": b"s" * 32}, config=config)(score, cell, frozen)


def test_core_pair_is_adapted_only_not_scientific_or_validation_evidence(tmp_path):
    frozen, runtime, _ = _panel_with_config(tmp_path, "discoverybench")
    config = ScorerConfig.create(benchmark="core_pair", evaluator_id="frozen-rubric-transport", rubric_digest="b" * 64, version="v1")
    frozen = FrozenPanel(frozen.stage, frozen.domain, frozen.split_digest, frozen.candidate_digest, frozen.scope_ids,
        frozen.legal_arm_grids, frozen.acceptance_criteria, tuple(replace(cell, scorer_digest=config.digest) for cell in frozen.cells), frozen.combinations)
    cells = {cell.key: cell for cell in frozen.cells}; service = _service(frozen, config)
    scores = tuple(service.score(panel=frozen, cell=cells[row.cell_key], runtime=row) for row in runtime)
    verdict = PanelReceiptVerifier(scorer_verifier=AdaptedMetricReceiptVerifier(authority_keys={"independent-test": b"s" * 32}, config=config)).verify(frozen, runtime, scorer_receipts=scores)
    assert verdict.adapted_score_verified and not verdict.scientific_verified and not verdict.acceptance_verified
    assert verdict.decision == "adapted_score_verified"


def test_signature_and_full_runtime_binding_fail_closed(tmp_path):
    frozen, runtime, config = _panel_with_config(tmp_path, "blade")
    service = _service(frozen, config)
    cell = next(cell for cell in frozen.cells if cell.identity.benchmark == "blade")
    row = next(row for row in runtime if row.cell_key == cell.key)
    scored = service.score(panel=frozen, cell=cell, runtime=row)
    verifier = AdaptedMetricReceiptVerifier(authority_keys={"independent-test": b"s" * 32}, config=config)
    forged = scored.receipt.data(); forged["body"]["metric"]["value"] = 0.0
    with pytest.raises(ContractError, match="signature mismatch"):
        verifier(ScientificScorerReceipt(cell.key, FrozenRecord.from_dict(forged)), cell, frozen)
    other = next(item for item in frozen.cells if item.identity.benchmark == "blade" and item.key != cell.key)
    with pytest.raises(ContractError, match="cell does not match"):
        service.score(panel=frozen, cell=other, runtime=row)
    with pytest.raises(ContractError, match="terminal runtime output evidence"):
        service.score(panel=frozen, cell=cell, runtime=replace(row, output_digest="b" * 64))
    with pytest.raises(ContractError, match="cell does not match"):
        service.score(panel=frozen, cell=replace(cell, variant="forged-variant"), runtime=row)
    changed = tuple(replace(item, package_digest="b" * 64) if item.arm_id == cell.arm_id else item for item in frozen.cells)
    altered = FrozenPanel(frozen.stage, frozen.domain, frozen.split_digest, frozen.candidate_digest, frozen.scope_ids,
        frozen.legal_arm_grids, frozen.acceptance_criteria, changed, frozen.combinations)
    altered_cell = next(item for item in altered.cells if item.key == cell.key)
    with pytest.raises(ContractError, match="package or legal-arm binding"):
        _service(altered, config).score(panel=altered, cell=altered_cell, runtime=row)


def test_fixture_endpoint_rejects_missing_values_instead_of_none_equals_none(tmp_path):
    frozen, runtime, config = _panel_with_config(tmp_path, "blade")
    service = _service(frozen, config)
    cell = next(cell for cell in frozen.cells if cell.identity.benchmark == "blade")
    row = next(row for row in runtime if row.cell_key == cell.key)
    endpoint = FixtureOnlyRubricEndpoint({"fixture": {"outcome": "unknown", "conclusion": "x", "programme_complete": False}})
    request = FrozenRecord.from_dict({"schema": "adapted-rubric-evaluation-request-v1", "panel_digest": frozen.digest,
        "scorer_config_digest": config.digest, "benchmark": "blade", "task_handle": "fixture",
        "candidate": {"outcome": "unknown", "conclusion": "x"}, "candidate_digest": "a" * 64})
    with pytest.raises(ContractError, match="lacks a required"):
        endpoint(request)
    assert service.score(panel=frozen, cell=cell, runtime=row).cell_key == cell.key
