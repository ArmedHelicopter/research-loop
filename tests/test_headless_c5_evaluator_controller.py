"""Focused C5 headless-evaluator producer contracts; no C5 grid execution."""
from types import SimpleNamespace

import pytest

from evaluation.modular.scoring_service import ScorerConfig
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.joint_train_controller import _finalize_headless_c5_evaluator
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
    'evaluator_config_digest': 'a' * 64,
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
    assert not logs


def _score(cell_key, digest):
    return SimpleNamespace(cell_key=cell_key, receipt=SimpleNamespace(content_hash=digest * 64))


def _plan():
    scorer = ScorerConfig.create(benchmark='core_pair', evaluator_id='synthetic', version='v1', rubric_digest='c' * 64)
    protocol = SimpleNamespace(record=FrozenRecord.from_dict({'scorer': scorer.record.data()}))
    return SimpleNamespace(protocol=protocol, headless_evaluator_binding={'evaluator_usage': dict(_USAGE),
        'evaluator_provider': dict(_PROVIDER)})


def test_c5_finalizer_retains_verified_partial_closure_as_ineligible(monkeypatch):
    cells = (SimpleNamespace(key=('arm', 'blade')), SimpleNamespace(key=('arm', 'discoverybench')))
    panel = SimpleNamespace(cells=cells)
    scores = (_score(cells[0].key, '1'),)
    closure = FrozenRecord.from_dict({'body': {'nonce': 'n', 'known_main_tokens': 17,
        'scope': {'scored_cell_keys': [list(cells[0].key)], 'unscored_cell_count': 1}}})
    class Client:
        def finalize_headless_evaluator(self, *, receipts):
            assert receipts == scores
            return closure
    service = Client()
    monkeypatch.setattr('research_loop.modular.joint_train_controller.CombinationScorerProcessClient', Client)
    seen = {}
    def verify(value, **kwargs):
        seen.update(kwargs); assert value == closure
        return closure
    monkeypatch.setattr('research_loop.modular.joint_train_controller.verify_closure', verify)
    gate = _finalize_headless_c5_evaluator(plan=_plan(), panel=panel, service=service,
        scores=scores, scorer_authority_keys={'scorer': b'x' * 32})
    assert gate['status'] == 'inconclusive' and gate['score_eligible'] is False
    assert gate['failure_reason'] == 'incomplete_panel_closure'
    assert gate['closure'] == closure.data() and gate['known_headless_main_tokens'] == 17
    assert gate['ordered_receipt_digests'] == [scores[0].receipt.content_hash]
    assert seen['provider'] == _PROVIDER
