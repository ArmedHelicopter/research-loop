"""Focused C5 headless-evaluator producer contracts; no C5 grid execution."""
from types import SimpleNamespace

import pytest

from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from evaluation.modular.scoring_service import ScorerConfig
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.joint_train_controller import (
    _controller_attempt_body, _finalize_headless_c5_evaluator, _headless_c5_evaluator_gate,
)
from research_loop.modular.joint_train_protocol import (
    FrozenJointTrainProtocol, HEADLESS_OBLIGATION, OBLIGATION,
)
from research_loop.modular.joint_train_runtime import runtime_sources
from research_loop.ontology import ContractError
from test_joint_train_protocol import fixture


_USAGE = {
    'schema': 'c5-headless-evaluator-usage-declaration-v1',
    'provider_kind': 'grok-headless-frozen-evaluator-v1',
    'usage_contract': 'grok-headless-c5-usage-v1',
    'evaluator_config_digest': 'b' * 64,
}
_PROVIDER = {'kind': 'grok-headless-frozen-evaluator-v1', 'configuration_digest': 'b' * 64}


def test_c5_protocol_opt_in_freezes_declaration_without_altering_legacy(tmp_path, monkeypatch):
    args, _, logs = fixture(tmp_path, monkeypatch)
    legacy = FrozenJointTrainProtocol.freeze(**args)
    headless = FrozenJointTrainProtocol.freeze(**args, evaluator_usage=_USAGE, evaluator_provider=_PROVIDER)
    assert legacy.record.data()['schema'] == OBLIGATION
    assert 'evaluator_usage' not in legacy.record.data()
    body = headless.record.data()
    assert body['schema'] == HEADLESS_OBLIGATION
    assert body['evaluator_usage'] == _USAGE and body['evaluator_provider'] == _PROVIDER
    assert body['allocation'] == legacy.record.data()['allocation']
    assert len(body['issue_contracts']) == 48
    assert 'research_loop/modular/joint_train_evaluator_verification.py' in runtime_sources()
    assert len(body['catalogue']['recipes']) == 59 and body['allocation']['target_cells'] == 177
    for key, value in (('evaluator_usage', None), ('evaluator_provider', None)):
        altered = dict(body); altered[key] = value
        with pytest.raises(ContractError):
            FrozenJointTrainProtocol(FrozenRecord.from_dict(altered))
    mismatched = {**body, 'evaluator_usage': {**_USAGE, 'evaluator_config_digest': 'a' * 64}}
    with pytest.raises(ContractError, match='actual worker configuration'):
        FrozenJointTrainProtocol(FrozenRecord.from_dict(mismatched))
    assert not logs


def _score(cell_key, digest):
    return SimpleNamespace(cell_key=cell_key, receipt=SimpleNamespace(content_hash=digest * 64))


def _plan(config):
    protocol = SimpleNamespace(record=FrozenRecord.from_dict({'scorer': config.record.data(), 'allocation': {'target_cells': 2}}))
    return SimpleNamespace(record=FrozenRecord.from_dict({'run': 'c5'}), protocol=protocol,
        headless_evaluator_binding={'evaluator_usage': dict(_USAGE), 'evaluator_provider': dict(_PROVIDER)})


def _signed_closure(*, authority, panel, config, scores):
    calls = []
    for index, score in enumerate(scores, start=1):
        benchmark = score.cell_key[0]
        calls.append({'id': index, 'opportunity_id': f'headless-evaluator-{index:04d}-{benchmark}',
            'benchmark': benchmark, 'cell_key': list(score.cell_key), 'receipt_digest': score.receipt.content_hash,
            'request_digest': '1' * 64, 'output_digest': '2' * 64, 'prompt_digest': '3' * 64,
            'schema_digest': '4' * 64, 'native_receipt_sha256': '5' * 64,
            'reservation_sha256': '6' * 64, 'known_main_tokens': index + 2})
    expected = sorted(tuple(cell.key) for cell in panel.cells)
    return authority.issue({'schema': 'headless-evaluator-closure-v1', 'nonce': 'producer-nonce',
        'status': 'eligible', 'eligible': True, 'panel_digest': panel.digest,
        'scorer_config_digest': config.digest, 'evaluator_provider': _PROVIDER,
        'receipt_digests': [score.receipt.content_hash for score in scores], 'calls': calls,
        'scope': {'schema': 'headless-evaluator-closure-scope-v1',
            'expected_panel_cell_keys': [list(key) for key in expected],
            'scored_cell_keys': [list(score.cell_key) for score in scores],
            'unscored_cell_count': len(panel.cells) - len(scores)},
        'ledger_sha256': '7' * 64, 'known_main_tokens': sum(row['known_main_tokens'] for row in calls),
        'title_tokens': None, 'settled_additional_charge_usd': None, 'unknown_title_usage': True,
        'all_opportunity_tokens': None, 'frozen_files': {}})


def _real_finalizer(monkeypatch, *, partial):
    cells = (SimpleNamespace(key=('blade', 'z')), SimpleNamespace(key=('discoverybench', 'a')))
    panel = SimpleNamespace(digest='e' * 64, cells=cells)
    # Actual submission order is deliberately reverse lexical/panel order.
    scores = (_score(cells[1].key, '1'),) if partial else (_score(cells[1].key, '1'), _score(cells[0].key, '2'))
    config = ScorerConfig.create(benchmark='core_pair', evaluator_id='synthetic', version='v1', rubric_digest='c' * 64)
    authority = LinkedExecutionAuthority('scorer', b's' * 32)
    closure = _signed_closure(authority=authority, panel=panel, config=config, scores=scores)
    class Client:
        def __init__(self): self.calls = 0
        def finalize_headless_evaluator(self, *, receipts):
            self.calls += 1
            assert receipts == scores
            return closure
    service = Client()
    monkeypatch.setattr('research_loop.modular.joint_train_controller.CombinationScorerProcessClient', Client)
    gate = _finalize_headless_c5_evaluator(plan=_plan(config), panel=panel, service=service,
        scores=scores, scorer_authority_keys={authority.authority_id: authority.key})
    return gate, closure, service, scores


def test_c5_finalizer_reverifies_real_signed_complete_closure_once(monkeypatch):
    gate, closure, service, scores = _real_finalizer(monkeypatch, partial=False)
    assert service.calls == 1
    assert gate['status'] == 'eligible' and gate['score_eligible'] is True
    assert gate['closure'] == closure.data()
    assert gate['known_headless_main_tokens'] == 7
    assert gate['ordered_receipt_digests'] == [score.receipt.content_hash for score in scores]


def test_c5_finalizer_retains_real_signed_partial_closure_as_ineligible(monkeypatch):
    gate, closure, service, scores = _real_finalizer(monkeypatch, partial=True)
    assert service.calls == 1
    assert gate['status'] == 'inconclusive' and gate['score_eligible'] is False
    assert gate['failure_reason'] == 'incomplete_panel_closure'
    assert gate['closure'] == closure.data() and gate['known_headless_main_tokens'] == 3
    assert gate['ordered_receipt_digests'] == [scores[0].receipt.content_hash]


def test_c5_attempt_persists_initial_and_verified_partial_evaluator_gate(monkeypatch):
    gate, closure, _, _ = _real_finalizer(monkeypatch, partial=True)
    plan = _plan(ScorerConfig.create(benchmark='core_pair', evaluator_id='synthetic', version='v1', rubric_digest='c' * 64))
    initial = _headless_c5_evaluator_gate(plan.headless_evaluator_binding, failure_reason='not_finalized')
    before = _controller_attempt_body(plan=plan, build_rows=[], rows=[], accounting={'provider_calls': 0}, evaluator_gate=initial)
    after = _controller_attempt_body(plan=plan, build_rows=[], rows=[], accounting={'provider_calls': 0}, evaluator_gate=gate)
    assert before['evaluator_final_verification']['closure'] is None
    assert after['evaluator_final_verification']['closure'] == closure.data()
    assert after['evaluator_final_verification']['known_headless_main_tokens'] == 3
    assert after['evaluator_final_verification']['score_eligible'] is False
