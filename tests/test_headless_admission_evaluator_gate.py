"""Focused admission headless-evaluator final-gate contracts; no provider or worker starts."""
from types import SimpleNamespace

import pytest

from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from evaluation.modular.scoring_service import ScorerConfig
from research_loop.modular.ordinary_provider import (
    finalize_headless_evaluator_gate, headless_evaluator_binding,
)
from research_loop.modular.train_provider_preflight import native_envelope
from research_loop.ontology import ContractError


FAMILY = 'admission-prediction-exploration'
USAGE = {'schema': f'{FAMILY}-headless-evaluator-usage-declaration-v1',
    'provider_kind': 'grok-headless-frozen-evaluator-v1',
    'usage_contract': f'grok-headless-{FAMILY}-usage-v1', 'evaluator_config_digest': 'b' * 64}
PROVIDER = {'kind': 'grok-headless-frozen-evaluator-v1', 'configuration_digest': 'b' * 64}


def _score(key, digest):
    return SimpleNamespace(cell_key=key, receipt=SimpleNamespace(content_hash=digest * 64))


def _signed_closure(*, authority, panel, config, scores, provider=PROVIDER):
    calls = []
    for index, score in enumerate(scores, start=1):
        benchmark = score.cell_key[0]
        calls.append({'id': index, 'opportunity_id': f'headless-evaluator-{index:04d}-{benchmark}',
            'benchmark': benchmark, 'cell_key': list(score.cell_key), 'receipt_digest': score.receipt.content_hash,
            'request_digest': '1' * 64, 'output_digest': '2' * 64, 'prompt_digest': '3' * 64,
            'schema_digest': '4' * 64, 'native_receipt_sha256': '5' * 64,
            'reservation_sha256': '6' * 64, 'known_main_tokens': index + 2})
    expected = sorted(tuple(cell.key) for cell in panel.cells)
    return authority.issue({'schema': 'headless-evaluator-closure-v1', 'nonce': 'admission-nonce',
        'status': 'eligible', 'eligible': True, 'panel_digest': panel.digest,
        'scorer_config_digest': config.digest, 'evaluator_provider': provider,
        'receipt_digests': [score.receipt.content_hash for score in scores], 'calls': calls,
        'scope': {'schema': 'headless-evaluator-closure-scope-v1',
            'expected_panel_cell_keys': [list(key) for key in expected],
            'scored_cell_keys': [list(score.cell_key) for score in scores],
            'unscored_cell_count': len(panel.cells) - len(scores)},
        'ledger_sha256': '7' * 64, 'known_main_tokens': sum(row['known_main_tokens'] for row in calls),
        'title_tokens': None, 'settled_additional_charge_usd': None, 'unknown_title_usage': True,
        'all_opportunity_tokens': None, 'frozen_files': {}})


def _case(*, partial=False, authority_key=b's' * 32, closure_provider=PROVIDER):
    cells = (SimpleNamespace(key=('blade', 'z')), SimpleNamespace(key=('discoverybench', 'a')))
    panel = SimpleNamespace(digest='e' * 64, cells=cells)
    scores = (_score(cells[1].key, '1'),) if partial else (_score(cells[1].key, '1'), _score(cells[0].key, '2'))
    config = ScorerConfig.create(benchmark='core_pair', evaluator_id='synthetic', version='v1', rubric_digest='c' * 64)
    authority = LinkedExecutionAuthority('scorer', authority_key)
    closure = _signed_closure(authority=authority, panel=panel, config=config, scores=scores, provider=closure_provider)
    class Client:
        def __init__(self): self.config=config; self.calls=0
        def finalize_headless_evaluator(self, *, receipts):
            self.calls += 1
            assert receipts == scores
            return closure
    return panel, scores, config, authority, closure, Client()


def _finish(*, panel, scores, authority, service, capture):
    frozen = ScorerConfig.create(benchmark='core_pair', evaluator_id='synthetic', version='v1', rubric_digest='c' * 64)
    return finalize_headless_evaluator_gate(binding={'evaluator_usage': dict(USAGE), 'evaluator_provider': dict(PROVIDER)},
        family=FAMILY, service=service, panel=panel, scores=scores,
        scorer_authority_keys={authority.authority_id: authority.key}, scorer_config=frozen, capture=capture)


def test_final_gate_reverifies_real_signed_complete_closure_and_preserves_submission_order():
    panel, scores, _, authority, closure, service = _case()
    captured = []
    gate = _finish(panel=panel, scores=scores, authority=authority, service=service, capture=lambda value: captured.append(dict(value)))
    assert service.calls == 1 and gate['status'] == 'eligible' and gate['score_eligible'] is True
    assert gate['closure'] == closure.data()
    assert gate['ordered_receipt_digests'] == [score.receipt.content_hash for score in scores]
    assert gate['known_headless_main_tokens'] == 7
    assert gate['title_and_all_opportunity_settlement'] == 'unknown'
    assert captured[0]['closure'] == closure.data() and captured[-1]['status'] == 'eligible'


def test_verified_partial_closure_is_retained_with_known_lower_bound_but_ineligible():
    panel, scores, _, authority, closure, service = _case(partial=True)
    captured = []
    gate = _finish(panel=panel, scores=scores, authority=authority, service=service, capture=lambda value: captured.append(dict(value)))
    assert gate['status'] == 'inconclusive' and gate['failure_reason'] == 'incomplete_panel_closure'
    assert gate['closure'] == closure.data() and gate['known_headless_main_tokens'] == 3
    assert captured[0]['closure'] == closure.data() and captured[-1]['known_headless_main_tokens'] == 3


@pytest.mark.parametrize('fault', ['provider', 'authority', 'config', 'digest'])
def test_tampered_or_wrongly_bound_closure_is_ineligible_but_raw_envelope_is_retained(fault):
    panel, scores, config, authority, closure, service = _case()
    captured = []
    if fault == 'provider':
        closure = _signed_closure(authority=authority, panel=panel, config=config, scores=scores,
            provider={'kind': PROVIDER['kind'], 'configuration_digest': 'a' * 64})
        service.finalize_headless_evaluator = lambda **_: closure
    elif fault == 'authority':
        verifier_authority = LinkedExecutionAuthority('scorer', b'x' * 32)
        gate = finalize_headless_evaluator_gate(binding={'evaluator_usage': dict(USAGE), 'evaluator_provider': dict(PROVIDER)},
            family=FAMILY, service=service, panel=panel, scores=scores,
            scorer_authority_keys={verifier_authority.authority_id: verifier_authority.key},
            scorer_config=config, capture=lambda value: captured.append(dict(value)))
        assert gate['score_eligible'] is False and gate['closure'] == closure.data() and gate['known_headless_main_tokens'] is None
        return
    elif fault == 'config':
        service.config = ScorerConfig.create(benchmark='core_pair', evaluator_id='other', version='v1', rubric_digest='c' * 64)
        closure = _signed_closure(authority=authority, panel=panel, config=service.config, scores=scores)
        service.finalize_headless_evaluator = lambda **_: closure
    else:
        bad = list(scores); bad[0] = _score(scores[0].cell_key, 'f')
        scores = tuple(bad)
        service.finalize_headless_evaluator = lambda **_: closure
    gate = _finish(panel=panel, scores=scores, authority=authority, service=service, capture=lambda value: captured.append(dict(value)))
    assert gate['score_eligible'] is False and gate['closure'] == closure.data()
    assert gate['known_headless_main_tokens'] is None and captured[0]['closure'] == closure.data()


def test_declaration_requires_digest_equality_and_legacy_cannot_smuggle_a_pool():
    body = {'evaluator_usage': dict(USAGE), 'evaluator_provider': dict(PROVIDER)}
    assert headless_evaluator_binding(body, family=FAMILY, enabled=True)['evaluator_provider'] == PROVIDER
    with pytest.raises(ContractError):
        headless_evaluator_binding({**body, 'evaluator_provider': {**PROVIDER, 'configuration_digest': 'a' * 64}},
            family=FAMILY, enabled=True)
    with pytest.raises(ContractError):
        headless_evaluator_binding(body, family=FAMILY, enabled=False)


def test_missing_schema_is_not_a_native_envelope():
    assert native_envelope({}, 'admission_prediction_exploration') is False
    assert native_envelope({'schema': None}, 'admission_prediction_exploration') is False


def test_last_capture_failure_cannot_return_an_eligible_gate():
    panel, scores, _, authority, _, service = _case()
    captures = []
    def capture(gate):
        captures.append(dict(gate))
        if gate['score_eligible']:
            raise OSError('journal unavailable')
    gate = _finish(panel=panel, scores=scores, authority=authority, service=service, capture=capture)
    assert len(captures) == 3
    assert gate['status'] == 'inconclusive' and gate['score_eligible'] is False
    assert gate['failure_reason'] == 'closure_capture_failed'


def test_finalize_cannot_swap_service_config_for_the_frozen_scorer_binding():
    panel, scores, config, authority, _, service = _case()
    changed = ScorerConfig.create(benchmark='core_pair', evaluator_id='other', version='v1', rubric_digest='c' * 64)
    changed_closure = _signed_closure(authority=authority, panel=panel, config=changed, scores=scores)
    def finalize(**_):
        service.config = changed
        return changed_closure
    service.finalize_headless_evaluator = finalize
    gate = _finish(panel=panel, scores=scores, authority=authority, service=service, capture=lambda _: None)
    assert config != changed and gate['score_eligible'] is False
    assert gate['closure'] == changed_closure.data() and gate['known_headless_main_tokens'] is None
