from types import SimpleNamespace
import pytest

from research_loop.modular.contracts import FrozenRecord
from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from research_loop.modular import joint_train_evaluator_verification as verifier
from research_loop.ontology import ContractError


DIGESTS = ('a'*64, 'b'*64)
USAGE = {'schema':'c5-headless-evaluator-usage-declaration-v1', 'provider_kind':'grok-headless-frozen-evaluator-v1',
         'usage_contract':'grok-headless-c5-usage-v1', 'evaluator_config_digest':'c'*64}
PROVIDER = {'kind':'grok-headless-frozen-evaluator-v1', 'configuration_digest':'d'*64}
PANEL = SimpleNamespace(digest='e'*64, cells=(SimpleNamespace(key=('blade','z')), SimpleNamespace(key=('discoverybench','a'))))


def _gate():
    return {'schema':'c5-common-final-headless-evaluator-v1', 'status':'eligible', 'score_eligible':True,
            'evaluator_usage':USAGE, 'evaluator_provider':PROVIDER, 'ordered_receipt_digests':list(DIGESTS),
            'closure':{'body':{'nonce':'n'}, 'mac':'x'}, 'known_headless_main_tokens':7,
            'title_and_all_opportunity_settlement':'unknown', 'failure_reason':None, 'error_type':None}


def test_consumer_requires_complete_signed_closure_before_selector(monkeypatch):
    seen = {}
    def signed(*args, **kwargs):
        seen.update(kwargs)
        return FrozenRecord.from_dict({'known_main_tokens':7,
            'scope':{'unscored_cell_count':0, 'scored_cell_keys':[['blade','z'],['discoverybench','a']]}})
    monkeypatch.setattr(verifier, 'verify_closure', signed)
    verifier.verify_joint_headless_evaluator_gate(_gate(), authority_keys={'s':b's'*32}, panel=PANEL,
        scorer_config=object(), evaluator_provider=PROVIDER, evaluator_usage=USAGE, ordered_receipt_digests=DIGESTS)
    assert seen['provider'] == PROVIDER and seen['receipt_digests'] == list(DIGESTS)


@pytest.mark.parametrize('change', [lambda gate: gate.update(closure=None),
                                      lambda gate: gate.update(status='inconclusive', score_eligible=False)])
def test_consumer_rejects_missing_or_unknown_headless_gate(change):
    gate = _gate(); change(gate)
    with pytest.raises(ContractError):
        verifier.verify_joint_headless_evaluator_gate(gate, authority_keys={}, panel=PANEL, scorer_config=object(),
            evaluator_provider=PROVIDER, evaluator_usage=USAGE, ordered_receipt_digests=DIGESTS)


def test_consumer_rejects_partial_or_tampered_closure(monkeypatch):
    monkeypatch.setattr(verifier, 'verify_closure', lambda *args, **kwargs: FrozenRecord.from_dict({
        'known_main_tokens':7, 'scope':{'unscored_cell_count':1, 'scored_cell_keys':[['blade','z']]}}))
    with pytest.raises(ContractError, match='partial'):
        verifier.verify_joint_headless_evaluator_gate(_gate(), authority_keys={'s':b's'*32}, panel=PANEL,
            scorer_config=object(), evaluator_provider=PROVIDER, evaluator_usage=USAGE, ordered_receipt_digests=DIGESTS)


def _signed_reverse_order_gate():
    authority = LinkedExecutionAuthority('scorer', b's'*32)
    calls = []
    for index, (key, receipt, tokens) in enumerate(((('discoverybench','a'), DIGESTS[0], 3),
                                                     (('blade','z'), DIGESTS[1], 4)), start=1):
        benchmark = key[0]
        calls.append({'id':index, 'opportunity_id':f'headless-evaluator-{index:04d}-{benchmark}',
            'benchmark':benchmark, 'cell_key':list(key), 'receipt_digest':receipt,
            'request_digest':'1'*64, 'output_digest':'2'*64, 'prompt_digest':'3'*64,
            'schema_digest':'4'*64, 'native_receipt_sha256':'5'*64, 'reservation_sha256':'6'*64,
            'known_main_tokens':tokens})
    closure = authority.issue({'schema':'headless-evaluator-closure-v1', 'nonce':'nonce', 'status':'eligible',
        'eligible':True, 'panel_digest':PANEL.digest, 'scorer_config_digest':'f'*64,
        'evaluator_provider':PROVIDER, 'receipt_digests':list(DIGESTS), 'calls':calls,
        'scope':{'schema':'headless-evaluator-closure-scope-v1',
            'expected_panel_cell_keys':[['blade','z'],['discoverybench','a']],
            'scored_cell_keys':[['discoverybench','a'],['blade','z']], 'unscored_cell_count':0},
        'ledger_sha256':'7'*64, 'known_main_tokens':7, 'title_tokens':None,
        'settled_additional_charge_usd':None, 'unknown_title_usage':True,
        'all_opportunity_tokens':None, 'frozen_files':{}})
    gate = _gate(); gate.update(closure=closure.data(), known_headless_main_tokens=7)
    return authority, gate


def test_real_signed_complete_reverse_submission_order_passes_and_tampering_rejects():
    authority, gate = _signed_reverse_order_gate()
    config = SimpleNamespace(digest='f'*64)
    verifier.verify_joint_headless_evaluator_gate(gate, authority_keys={authority.authority_id:authority.key},
        panel=PANEL, scorer_config=config, evaluator_provider=PROVIDER, evaluator_usage=USAGE,
        ordered_receipt_digests=DIGESTS)
    tampered = dict(gate); tampered['closure'] = dict(gate['closure']); tampered['closure']['mac'] = '0'*64
    with pytest.raises(ContractError):
        verifier.verify_joint_headless_evaluator_gate(tampered, authority_keys={authority.authority_id:authority.key},
            panel=PANEL, scorer_config=config, evaluator_provider=PROVIDER, evaluator_usage=USAGE,
            ordered_receipt_digests=DIGESTS)
    with pytest.raises(ContractError):
        verifier.verify_joint_headless_evaluator_gate(gate, authority_keys={authority.authority_id:authority.key},
            panel=PANEL, scorer_config=config, evaluator_provider=PROVIDER, evaluator_usage=USAGE,
            ordered_receipt_digests=(DIGESTS[0],))
