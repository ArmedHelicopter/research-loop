"""Synthetic train-reference integration tests; no benchmark reference is read."""
from dataclasses import replace

import pytest

from evaluation.modular.scoring_service import (
    AdaptedMetricReceiptVerifier, FrozenBenchmarkRubricEndpoint,
    FrozenRubricTransport, IndependentScoringService, ScorerConfig, ScoringAuthority,
)
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.panel_receipts import FrozenPanel, PanelReceiptVerifier
from research_loop.ontology import ContractError


@pytest.mark.parametrize("field", ["runtime_output_digest", "submission_digest", "scientific_validity", "calibration"])
def test_authenticated_but_inconsistent_receipt_cannot_change_the_executed_submission_or_claim_science(tmp_path, field):
    from research_loop.modular.panel_receipts import ScientificScorerReceipt
    frozen, runtime, config = _panel_with_config(tmp_path, "core_pair")
    cells = {cell.key: cell for cell in frozen.cells}
    output = {"discoverybench": {"context": 1, "variable_f1": 1, "relation": 1, "reason": "synthetic"},
              "blade": {"cvars": 2, "transform": 2, "model": 2, "reason": "synthetic"}}
    service, _, _ = _service(frozen, config, output)
    scores = [service.score(panel=frozen, cell=cells[row.cell_key], runtime=row) for row in runtime]
    body = scores[0].receipt.data()["body"]
    body[field] = "f" * 64 if field.endswith("digest") else "validated"
    # Authentication does not bypass comparison with the actual runtime.
    scores[0] = ScientificScorerReceipt(scores[0].cell_key, ScoringAuthority("independent-test", b"s" * 32).issue(body))
    with pytest.raises(ContractError, match="verified runtime output|cannot assert scientific"):
        PanelReceiptVerifier(scorer_verifier=AdaptedMetricReceiptVerifier(authority_keys={"independent-test": b"s" * 32}, config=config)).verify(frozen, runtime, scorer_receipts=scores)


class SyntheticTrainResolver:
    def __call__(self, handle, benchmark):
        if handle != "synthetic-train" or benchmark not in {"discoverybench", "blade"}:
            raise ContractError("synthetic reference is unavailable")
        return FrozenRecord.from_dict({"schema": "train-only-rubric-reference-v1", "split": "train",
            "benchmark": benchmark, "task_context": {"question": "synthetic"},
            "references": [{"spec_id": "synthetic-reference", "answer": "X relates to Y"}]})


class CannedIndependentEvaluator:
    def __init__(self, output): self.output = output; self.calls = []
    def __call__(self, request):
        body = request.data(); self.calls.append(body)
        assert body["schema"] == "frozen-independent-evaluator-call-v1"
        assert "ANONYMOUS_CANDIDATE=" in body["prompt"]
        output = self.output.get(body["benchmark"], self.output) if isinstance(self.output, dict) and "reason" not in self.output else self.output
        return FrozenRecord.from_dict(output)


def _panel_with_config(tmp_path, benchmark):
    from test_modular_panel_receipts import panel
    config = ScorerConfig.create(benchmark=benchmark, evaluator_id="frozen-rubric-v1", rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest(), version="v1")
    frozen, runtime = panel(tmp_path)
    cells = tuple(replace(cell, scorer_digest=config.digest) for cell in frozen.cells)
    return (FrozenPanel(frozen.stage, frozen.domain, frozen.split_digest, frozen.candidate_digest, frozen.scope_ids,
            frozen.legal_arm_grids, frozen.acceptance_criteria, cells, frozen.combinations), runtime, config)


def _service(panel, config, output):
    identities = {FrozenRecord.from_dict(cell.identity.data()).content_hash: "synthetic-train" for cell in panel.cells}
    model = CannedIndependentEvaluator(output)
    endpoint = FrozenBenchmarkRubricEndpoint(resolver=SyntheticTrainResolver(), evaluator=model,
        evaluator_id="frozen-rubric-v1", evaluator_version="v1")
    service = IndependentScoringService(config=config, authority=ScoringAuthority("independent-test", b"s" * 32),
        evaluator=FrozenRubricTransport(endpoint), allowed_task_handles=identities)
    return service, endpoint, model


@pytest.mark.parametrize("benchmark,output,expected", [
    ("discoverybench", {"context": 1, "variable_f1": 0.5, "relation": 1, "reason": "synthetic"}, 0.5),
    ("blade", {"cvars": 2, "transform": 1, "model": 1, "reason": "synthetic"}, 2 / 3),
])
def test_endpoint_to_signed_receipt_to_panel_verifier(tmp_path, benchmark, output, expected):
    frozen, runtime, config = _panel_with_config(tmp_path, benchmark)
    service, _, model = _service(frozen, config, output)
    cell = next(c for c in frozen.cells if c.identity.benchmark == benchmark)
    row = next(r for r in runtime if r.cell_key == cell.key)
    score = service.score(panel=frozen, cell=cell, runtime=row)
    body = score.receipt.data()["body"]
    assert body["metric"]["value"] == expected
    assert body["evaluator_evidence"]["mode"] == "single_candidate_train_only"
    assert model.calls[0]["evaluator_id"] == "frozen-rubric-v1"
    AdaptedMetricReceiptVerifier(authority_keys={"independent-test": b"s" * 32}, config=config)(score, cell, frozen)


def test_core_pair_validation_remains_unaccepted(tmp_path):
    frozen, runtime, _ = _panel_with_config(tmp_path, "discoverybench")
    config = ScorerConfig.create(benchmark="core_pair", evaluator_id="frozen-rubric-v1", rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest(), version="v1")
    frozen = FrozenPanel(frozen.stage, frozen.domain, frozen.split_digest, frozen.candidate_digest, frozen.scope_ids,
        frozen.legal_arm_grids, frozen.acceptance_criteria, tuple(replace(c, scorer_digest=config.digest) for c in frozen.cells), frozen.combinations)
    service, _, _ = _service(frozen, config, {"discoverybench": {"context": 1, "variable_f1": 1, "relation": 1, "reason": "synthetic"}, "blade": {"cvars": 2, "transform": 2, "model": 2, "reason": "synthetic"}})
    cells = {c.key: c for c in frozen.cells}
    scores = tuple(service.score(panel=frozen, cell=cells[r.cell_key], runtime=r) for r in runtime)
    verdict = PanelReceiptVerifier(scorer_verifier=AdaptedMetricReceiptVerifier(authority_keys={"independent-test": b"s" * 32}, config=config)).verify(frozen, runtime, scorer_receipts=scores)
    assert verdict.adapted_score_verified and not verdict.scientific_verified and not verdict.acceptance_verified


def test_endpoint_rejects_range_missing_reference_and_wrong_candidate(tmp_path):
    frozen, _, config = _panel_with_config(tmp_path, "blade")
    service, endpoint, _ = _service(frozen, config, {"cvars": 3, "transform": 1, "model": 1, "reason": "bad"})
    candidate = {"outcome": "unknown", "conclusion": "engineering fixture", "programme_complete": False}
    request = FrozenRecord.from_dict({"schema": "adapted-rubric-evaluation-request-v1", "panel_digest": frozen.digest,
        "scorer_config_digest": config.digest, "benchmark": "blade", "task_handle": "synthetic-train",
        "candidate": candidate, "candidate_digest": FrozenRecord.from_dict(candidate).content_hash})
    with pytest.raises(ContractError, match="outside the frozen rubric"):
        endpoint(request)
    missing = FrozenRecord.from_dict({**request.data(), "task_handle": "missing"})
    with pytest.raises(ContractError, match="unavailable"):
        endpoint(missing)
    wrong = FrozenRecord.from_dict({**request.data(), "candidate_digest": "a" * 64})
    with pytest.raises(ContractError, match="candidate digest mismatch"):
        endpoint(wrong)
    assert service.config is config


def test_signed_receipt_rejects_duplicate_and_validation_rejects_adapted_only(tmp_path):
    frozen, runtime, _ = _panel_with_config(tmp_path, "discoverybench")
    config = ScorerConfig.create(benchmark="core_pair", evaluator_id="frozen-rubric-v1", rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest(), version="v1")
    frozen = FrozenPanel(frozen.stage, frozen.domain, frozen.split_digest, frozen.candidate_digest, frozen.scope_ids,
        frozen.legal_arm_grids, frozen.acceptance_criteria, tuple(replace(c, scorer_digest=config.digest) for c in frozen.cells), frozen.combinations)
    service, _, _ = _service(frozen, config, {"discoverybench": {"context": 1, "variable_f1": 1, "relation": 1, "reason": "synthetic"}, "blade": {"cvars": 2, "transform": 2, "model": 2, "reason": "synthetic"}})
    cells = {c.key: c for c in frozen.cells}
    scores = tuple(service.score(panel=frozen, cell=cells[r.cell_key], runtime=r) for r in runtime)
    verifier = PanelReceiptVerifier(scorer_verifier=AdaptedMetricReceiptVerifier(authority_keys={"independent-test": b"s" * 32}, config=config))
    with pytest.raises(ContractError, match="duplicate"):
        verifier.verify(frozen, runtime, scorer_receipts=scores + (scores[0],))
    verdict = verifier.verify(frozen, runtime, scorer_receipts=scores)
    assert not verdict.acceptance_verified
