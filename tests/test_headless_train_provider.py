"""Synthetic OS/HTTP evidence traverses the native port, adapter, phase and seal."""
from pathlib import Path

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.phase_provider import PhaseProviderSession, validate_configuration
from research_loop.modular.train_provider import GrokHeadlessTrainProvider, wrap_train_provider
from research_loop.ontology import ContractError
from test_grok_headless_train_solver import port, synthetic_native, REQUEST, SCHEMA


def events(request=REQUEST):
    return [{'stage':'model_request','data':{'request':request.data()}},
        {'stage':'model_response','data':{'request_digest':request.content_hash,'response':{'ok':True}}}]


def test_headless_provider_phase_and_consumption_seal(tmp_path, monkeypatch):
    backend=port(tmp_path,max_calls=2)
    calls,gets=synthetic_native(tmp_path,monkeypatch,backend)
    provider=wrap_train_provider(backend)
    assert type(provider) is GrokHeadlessTrainProvider
    config=provider.configuration()
    validate_configuration(config,schemas={'m4_plan':SCHEMA},main_opportunities=2)
    assert config.data()['provider_kind']=='grok-headless-public-train-v1'
    session=PhaseProviderSession(provider,tmp_path/'scopes.json')
    with session.scope('module:M4:train:1') as scope:
        assert scope(REQUEST).data()=={'ok':True}
    first=session.seal(tmp_path/'first-seal.json')
    assert first.bind_events(events(),scope_id='module:M4:train:1')==(1,)
    with session.scope('combination:M4+M5:train:1') as scope:
        assert scope(REQUEST).data()=={'ok':True}
    final=session.finish(tmp_path/'final-seal.json')
    assert first.verify().data()['later_calls']==1
    assert final.bind_events(events(),scope_id='combination:M4+M5:train:1')==(2,)
    usage=provider.usage().data()
    assert len(calls)==2 and len(gets)==12 and usage['main_opportunities']==2
    assert usage['known_reported_tokens']==20 and usage['unknown_main_opportunities']==0
    assert usage['title_tokens'] is None and usage['all_opportunity_tokens'] is None
    native=provider.state['calls'][0]['original_files']
    assert any(Path(name).as_posix().endswith('billing-after/attempts.json') for name in native)
    assert not any(name.endswith('auth.json') for name in native)


def test_postflight_rejection_is_retained_in_provider_denominator(tmp_path, monkeypatch):
    backend=port(tmp_path,max_calls=2)
    calls,_=synthetic_native(tmp_path,monkeypatch,backend)
    provider=wrap_train_provider(backend)
    import research_loop.modular.grok_headless_transport as transport
    original=transport._account_recovered
    reads=[]
    def fail_after(*args,**kwargs):
        reads.append(1)
        if len(reads)==2: raise ContractError('synthetic postflight failure')
        return original(*args,**kwargs)
    monkeypatch.setattr(transport,'_account_recovered',fail_after)
    with pytest.raises(ContractError): provider(REQUEST)
    row=provider.inspect()[0].data()
    assert not row['successful'] and not row['known_usage_binding_verified']
    assert row['known_tokens']==10 and row['main_usage_incomplete']
    assert row['response_digest'] is None
    retained=provider.state['calls'][0]['original_files']
    assert any(Path(name).as_posix().endswith('native/response.private.json') for name in retained)
    snapshot=provider.failure_snapshot().data()
    assert snapshot['observed_main_opportunities_lower_bound']==1
    assert snapshot['known_reported_tokens_lower_bound']==10
    assert snapshot['score_eligible'] is False
    with pytest.raises(ContractError): provider(REQUEST)
    assert len(calls)==1


def test_seal_refuses_forged_consumption_and_closes_future_dispatch(tmp_path, monkeypatch):
    backend=port(tmp_path,max_calls=2)
    calls,_=synthetic_native(tmp_path,monkeypatch,backend)
    provider=wrap_train_provider(backend);provider(REQUEST)
    seal=provider.seal(tmp_path/'seal.json')
    forged=events();forged[-1]['data']['response']={'ok':False}
    with pytest.raises(ContractError):seal.bind_events(forged,expected_call_ids=(1,))
    with pytest.raises(ContractError):provider(REQUEST)
    assert len(calls)==1


def test_unknown_main_usage_keeps_the_spent_opportunity(tmp_path,monkeypatch):
    backend=port(tmp_path,max_calls=2)
    calls,_=synthetic_native(tmp_path,monkeypatch,backend)
    peer=tmp_path/'headless-peer.py'
    raw=peer.read_text(encoding='utf-8')
    assert 'usage={"input_tokens":8' in raw
    peer.write_text(raw.replace('usage={"input_tokens":8','usage={"input_tokens":"unavailable"'),encoding='utf-8')
    provider=wrap_train_provider(backend)
    with pytest.raises(ContractError):provider(REQUEST)
    observed=provider.usage().data()
    assert observed['main_opportunities']==1 and observed['unknown_main_opportunities']==1
    assert observed['known_reported_tokens']==0 and observed['all_opportunity_tokens'] is None
    assert provider.inspect()[0].data()['known_tokens'] is None
    with pytest.raises(ContractError):provider(REQUEST)
    assert len(calls)==1


@pytest.mark.parametrize('change',['kind','effort','recovery','source'])
def test_headless_configuration_cannot_be_relabelled_or_relaxed(tmp_path,monkeypatch,change):
    backend=port(tmp_path)
    calls,_=synthetic_native(tmp_path,monkeypatch,backend)
    provider=wrap_train_provider(backend)
    config=provider.configuration().data()
    if change=='source':
        backend.private_home=tmp_path/'foreign-home'
        with pytest.raises(ContractError):provider(REQUEST)
    else:
        if change=='kind':config['provider_kind']='grok-acp-public-train-v1'
        if change=='effort':config['execution_mode']='high'
        if change=='recovery':
            config['native_config']['account_read_recovery']['max_attempts']=3
            config['native_config_digest']=FrozenRecord.from_dict(config['native_config']).content_hash
        with pytest.raises(ContractError):
            validate_configuration(FrozenRecord.from_dict(config),schemas={'m4_plan':SCHEMA},main_opportunities=1)
    assert not calls
