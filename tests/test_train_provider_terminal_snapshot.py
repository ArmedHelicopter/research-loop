"""Terminal historical scalars cannot become current original provenance."""
import hashlib
import json

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.train_provider import GrokTrainProvider
from research_loop.ontology import ContractError
from helpers.native_ordinary_provider import native_ordinary_provider
from test_grok_train_solver import REQUEST, SCHEMA


def setup(root,patch,*,fault_at=None):
    return native_ordinary_provider(root/'provider',patch,schemas={'m4_plan':SCHEMA},max_calls=3,
        response=lambda request:{'ok':True},fault_at=fault_at)


@pytest.mark.parametrize('fault',['state','configuration','source','response'])
def test_terminal_snapshot_retains_history_after_original_drift_without_reinspection(tmp_path,monkeypatch,fault):
    provider, logs = setup(tmp_path,monkeypatch)
    provider(REQUEST)
    seal = provider.seal(tmp_path/'successful-prefix.json')
    backend=provider.backend
    if fault=='state':
        target=provider.state_path;target.write_bytes(b'{}')
    elif fault=='configuration':
        target=backend.ledger_path;body=json.loads(target.read_bytes());body['config']['model']='foreign'
        target.write_text(json.dumps(body),encoding='utf-8')
    elif fault=='source':
        target=tmp_path/'provider/synthetic-source-pin.py';target.write_bytes(b'changed')
    else:
        target=backend.calls_root/'0001-m4_plan/response.private.json';target.write_bytes(b'{"ok":false}')
    before=target.read_bytes()
    with pytest.raises(ContractError,match='provenance'):
        provider.inspect()
    if fault in {'source','response'}:
        with pytest.raises(ContractError):seal.verify_originals()
        with pytest.raises(ContractError):provider.seal(tmp_path/'invalid-seal.json')
    else:
        # Poison preserves the corrupt disk bytes before restoring the durable
        # stop marker from the in-memory record. Such originals can replay, but
        # terminal state permanently prevents their use for new scoring.
        assert seal.verify_originals().data()['score_eligible'] is False
        failed_seal=provider.seal(tmp_path/'terminal-audit-seal.json')
        assert failed_seal.verify_originals().data()['score_eligible'] is False
    with pytest.raises(ContractError):provider(REQUEST)
    def forbidden(*args,**kwargs):raise AssertionError('terminal snapshot retried inspection or native dispatch')
    monkeypatch.setattr(provider,'inspect',forbidden)
    monkeypatch.setattr(backend,'native_invoke',forbidden)
    snapshot=provider.failure_snapshot().data()
    assert snapshot['score_eligible'] is False and snapshot['current_originals_verified'] is False
    assert snapshot['known_reported_tokens_lower_bound']==12
    assert snapshot['observed_main_opportunities_lower_bound']==1
    assert snapshot['historical_observation']['known_usage_scope']=='native_main'
    assert snapshot['unknown_unobserved_opportunities'] is True
    assert snapshot['total_main_opportunities'] is None and snapshot['total_main_tokens'] is None
    assert snapshot['title_tokens'] is None and snapshot['settled_additional_charge_usd'] is None
    assert len(logs)==1 and not (tmp_path/'invalid-seal.json').exists()
    assert all('auth' not in p and 'memtrace' not in p for p in snapshot['preserved_fault_files'])
    assert 'calls' not in snapshot and 'response' not in snapshot
    if fault in {'state','configuration'}:
        preserved=provider.root/('fault-state.json' if fault=='state' else 'fault-native-ledger.json')
        assert preserved.read_bytes()==before
    else:
        assert target.read_bytes()==before


def test_no_fault_cannot_request_terminal_snapshot_and_corrupt_checkpoint_is_unknown(tmp_path,monkeypatch):
    provider, logs = setup(tmp_path,monkeypatch)
    with pytest.raises(ContractError,match='durable terminal'):
        provider.failure_snapshot()
    provider(REQUEST)
    path,_=provider._last_verified_accounting
    path.write_bytes(b'corrupt historical checkpoint')
    (provider.backend.calls_root/'0001-m4_plan/response.private.json').write_bytes(b'{}')
    with pytest.raises(ContractError):provider.inspect()
    snapshot=provider.failure_snapshot().data()
    assert snapshot['historical_observation'] is None
    assert snapshot['known_reported_tokens_lower_bound'] is None
    assert snapshot['observed_main_opportunities_lower_bound'] is None
    assert snapshot['score_eligible'] is False and len(logs)==1


def test_known_failed_main_is_retained_separately_from_unknown_settlement(tmp_path,monkeypatch):
    provider, logs = setup(tmp_path,monkeypatch,fault_at=2)
    provider(REQUEST)
    with pytest.raises(ContractError):provider(REQUEST)
    snapshot=provider.failure_snapshot().data()
    assert snapshot['known_reported_tokens_lower_bound']==24
    assert snapshot['observed_main_opportunities_lower_bound']==2
    assert snapshot['historical_observation']['observed_unknown_main_opportunities']==1
    assert snapshot['current_main_usage_complete'] is False
    assert snapshot['historical_observation']['possible_initial_title_opportunities']==2
    assert snapshot['all_opportunity_tokens'] is None and len(logs)==2
