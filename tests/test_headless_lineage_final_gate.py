"""Focused controller final-gate regressions; no worker or provider is started."""
from types import SimpleNamespace

import pytest

from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular import lineage_combination_controller as controller
from research_loop.ontology import ContractError
from test_lineage_combination_controller import _sources, _fixture


DECLARATION = {'schema': 'lineage-headless-evaluator-usage-declaration-v1',
    'provider_kind': 'grok-headless-frozen-evaluator-v1',
    'usage_contract': 'grok-headless-lineage-usage-v1', 'evaluator_config_digest': 'd' * 64}
PROVIDER = {'kind': 'grok-headless-frozen-evaluator-v1', 'configuration_digest': 'p' * 64}
LIMITS = {'model': 'grok-4.6', 'effort': 'low', 'tokens_per_cell': 20, 'timeout_seconds': 60}


class _Cell:
    def data(self):
        return {'schema': 'test-final-gate-cell-v1', 'id': 'one'}


class _Client:
    def __init__(self, authority, *, closure_error=True):
        self.authority = authority
        self.config = SimpleNamespace(digest='c' * 64)
        self.reference_binding = {'evaluator_usage': DECLARATION, 'limits': LIMITS}
        self.closure_error = closure_error
        self.receipt_digests = None

    def usage(self):
        return self.authority.issue({'schema': 'lineage-scorer-headless-usage-v1', 'nonce': 'usage',
            'panel_digest': 'a' * 64, 'scorer_digest': self.config.digest, 'ledger_sha256': 'l' * 64,
            'calls': [{'id': 1, 'status': 'unknown_or_failed', 'main_opportunity': 1,
                'known_headless_main_usage': {'input_tokens': 10, 'cache_read_input_tokens': 0,
                    'cache_creation_input_tokens': 0, 'output_tokens': 7, 'reasoning_tokens': 0, 'total_tokens': 17},
                'main_dispatch_state': 'possibly_dispatched', 'native_receipt_sha256': None,
                'reservation_sha256': None, 'accepted': None}], 'tokens': 17, 'usage_incomplete': True,
            'limits': LIMITS,
            'max_calls': 1, 'max_tokens': 20, 'provider_kind': PROVIDER['kind'],
            'usage_contract': DECLARATION['usage_contract'],
            'evaluator_config_digest': DECLARATION['evaluator_config_digest'],
            'accounting_scope': 'native_MAIN', 'title_and_all_opportunity_settlement': 'unknown'}).data()

    def finalize_lineage(self, *, nonce, receipt_digests):
        self.receipt_digests = receipt_digests
        raise ContractError('late closure replay failure')


def _pool(client):
    return SimpleNamespace(clients={'obligation': client},
        evaluator_usage_by_obligation={'obligation': DECLARATION},
        evaluator_providers_by_obligation={'obligation': PROVIDER})


def test_null_headless_binding_is_rejected_at_frozen_config_construction(tmp_path):
    _, _, _, config, _, _ = _fixture(tmp_path, _sources([]))
    body = dict(config.data()); body['lineage_evaluator_bindings'] = None
    with pytest.raises(ContractError, match='cannot be null'):
        controller.FrozenLineageTrainConfig(FrozenRecord.from_dict(body))


def test_pool_headless_contract_cannot_bypass_undeclared_final_gate():
    with pytest.raises(ContractError, match='pool and frozen final gate'):
        controller._assert_headless_lineage_gate_binding({}, _pool(object()), native=True)


def test_late_closure_failure_keeps_authenticated_main_lower_bound_and_failed_row_receipt():
    authority = LinkedExecutionAuthority('headless-scorer', b'k' * 32)
    client = _Client(authority)
    panel = SimpleNamespace(obligation_id='obligation', digest='a' * 64, cells=(_Cell(),))
    receipt = FrozenRecord.from_dict({'schema': 'test-scorer-receipt-v1', 'value': 1}).data()
    gate = controller._finalize_headless_lineage_gate(panels=(panel,), journal_cells=[{
        'cell': _Cell().data(), 'status': 'failed', 'scorer_receipt': receipt}], scoring_service=_pool(client),
        scorer_authority_keys={authority.authority_id: authority.key})
    entry = gate['panels'][0]
    assert gate['status'] == 'inconclusive'
    assert client.receipt_digests == [FrozenRecord.from_dict(receipt).content_hash]
    assert entry['native_MAIN_known_tokens_lower_bound'] == 17
    assert entry['native_MAIN_completeness'] == 'unknown'
    assert entry['authenticated_usage_digest']


def test_controller_rejects_a_client_closure_that_only_client_code_claims_to_have_verified(monkeypatch):
    authority = LinkedExecutionAuthority('headless-scorer', b'k' * 32)
    client = _Client(authority)
    panel = SimpleNamespace(obligation_id='obligation', digest='a' * 64, cells=(_Cell(),))
    client.closure_error = False
    client.finalize_lineage = lambda **_: FrozenRecord.from_dict({'schema': 'forged-closure-v1'})
    seen = []
    def reject(*args, **kwargs):
        seen.append(kwargs)
        raise ContractError('outer verifier rejected forged closure')
    monkeypatch.setattr(controller, 'verify_lineage_closure', reject)
    gate = controller._finalize_headless_lineage_gate(panels=(panel,), journal_cells=[], scoring_service=_pool(client),
        scorer_authority_keys={authority.authority_id: authority.key})
    assert seen and seen[0]['config'] is client.config and seen[0]['provider'] == PROVIDER
    assert seen[0]['reference_binding'] is client.reference_binding
    assert gate['panels'][0]['status'] == 'inconclusive'
