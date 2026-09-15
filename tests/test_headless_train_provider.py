"""Synthetic OS/HTTP evidence traverses the native port, adapter, phase and seal."""
from pathlib import Path

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.phase_provider import PhaseProviderSession, validate_configuration
from research_loop.modular.train_provider import GrokHeadlessTrainProvider, wrap_train_provider
from research_loop.modular import train_provider as provider_core
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


def test_phase_headless_binding_uses_two_fresh_passes_and_never_reuses_them(tmp_path, monkeypatch):
    backend=port(tmp_path,max_calls=2)
    dispatches,_=synthetic_native(tmp_path,monkeypatch,backend)
    provider=wrap_train_provider(backend);session=PhaseProviderSession(provider,tmp_path/'scopes.json')
    with session.scope('history') as scope: first=scope(REQUEST)
    with session.scope('target') as scope: second=scope(REQUEST)
    seal=session.seal(tmp_path/'seal.json')
    original=provider_core._verify_call;replayed=[]
    def observe(*args,**kwargs):
        replayed.append(args[1]['id']);return original(*args,**kwargs)
    monkeypatch.setattr(provider_core,'_verify_call',observe)
    target=events(REQUEST);target[-1]['data']['response']=second.data()
    ids,bound=seal.bind_events_with_calls(target,scope_id='target')
    assert ids==(2,) and [call.data()['id'] for call in bound]==[2]
    assert replayed==[1,2,1,2], 'one binding makes its two required fresh passes only'
    replayed.clear()
    assert seal.bind_events_with_calls(target,scope_id='target')[0]==(2,)
    assert replayed==[1,2,1,2], 'a separate consumer invocation must reread every original'
    replayed.clear()
    assert seal.original.bind_events(target,expected_call_ids=(2,))==(2,)
    assert replayed==[1,2], 'the public original-ledger entry remains independently fresh'
    replayed.clear()
    assert seal.original.bind_events(target,expected_call_ids=(2,))==(2,)
    assert replayed==[1,2], 'a second public entry must make another fresh pass'
    response=backend.calls_root/'0001-m4_plan'/'response.private.json'
    response.write_bytes(response.read_bytes()+b' ')
    with pytest.raises(ContractError):seal.bind_events_with_calls(target,scope_id='target')
    assert len(dispatches)==2
    with pytest.raises(ContractError):provider(REQUEST)
    assert len(dispatches)==2


def test_headless_binding_failure_poison_and_noneligible_history_remain_explicit(tmp_path, monkeypatch):
    backend=port(tmp_path,max_calls=2)
    dispatches,_=synthetic_native(tmp_path,monkeypatch,backend)
    provider=wrap_train_provider(backend);session=PhaseProviderSession(provider,tmp_path/'scopes.json')
    with session.scope('history') as scope: response=scope(REQUEST)
    history=session.seal(tmp_path/'history.json')
    with pytest.raises(ContractError):history.bind_events_with_calls([],scope_id='history')
    assert len(dispatches)==1
    with pytest.raises(ContractError):provider(REQUEST)
    assert len(dispatches)==1

    monkeypatch.undo()
    backend=port(tmp_path/'noneligible',max_calls=1)
    dispatches,_=synthetic_native(tmp_path/'noneligible',monkeypatch,backend)
    provider=wrap_train_provider(backend);session=PhaseProviderSession(provider,tmp_path/'noneligible-scopes.json')
    with session.scope('history') as scope: response=scope(REQUEST)
    history=session.seal(tmp_path/'noneligible-history.json')
    provider._poison('synthetic_terminal_after_history')
    retained=history.bind_events_with_calls(
        [{'stage':'model_request','data':{'request':REQUEST.data()}},
         {'stage':'model_response','data':{'request_digest':REQUEST.content_hash,'response':response.data()}}],
        scope_id='history',require_eligible=False)
    assert retained[0]==(1,) and retained[1][0].data()['known_tokens']==10
    with pytest.raises(ContractError):history.bind_events_with_calls(
        events(REQUEST),scope_id='history',require_eligible=True)


@pytest.mark.parametrize(('expected_call_ids','require_eligible'),[
    ((2,1),True),
    (None,1),
])
def test_public_headless_binding_rejects_invalid_arguments_before_replay(tmp_path,monkeypatch,
                                                                          expected_call_ids,require_eligible):
    backend=port(tmp_path,max_calls=1)
    dispatches,_=synthetic_native(tmp_path,monkeypatch,backend)
    provider=wrap_train_provider(backend);response=provider(REQUEST)
    seal=provider.seal(tmp_path/'seal.json')
    original=provider_core._verify_call;replayed=[]
    def observe(*args,**kwargs):
        replayed.append(args[1]['id']);return original(*args,**kwargs)
    monkeypatch.setattr(provider_core,'_verify_call',observe)
    invalid=events(REQUEST);invalid[-1]['data']['response']=response.data()
    with pytest.raises(ContractError):seal.bind_events(
        invalid,expected_call_ids=expected_call_ids,require_eligible=require_eligible)
    assert replayed==[] and provider.state['terminal_fault'] is True
    assert len(dispatches)==1


def test_phase_headless_invalid_eligibility_replays_then_poisoned(tmp_path,monkeypatch):
    backend=port(tmp_path,max_calls=1)
    dispatches,_=synthetic_native(tmp_path,monkeypatch,backend)
    provider=wrap_train_provider(backend);session=PhaseProviderSession(provider,tmp_path/'scopes.json')
    with session.scope('history') as scope: response=scope(REQUEST)
    seal=session.seal(tmp_path/'seal.json')
    original=provider_core._verify_call;replayed=[]
    def observe(*args,**kwargs):
        replayed.append(args[1]['id']);return original(*args,**kwargs)
    monkeypatch.setattr(provider_core,'_verify_call',observe)
    event=events(REQUEST);event[-1]['data']['response']=response.data()
    with pytest.raises(ContractError):seal.bind_events_with_calls(
        event,scope_id='history',require_eligible=1)
    assert replayed==[1,1] and provider.state['terminal_fault'] is True
    assert len(dispatches)==1


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


@pytest.mark.parametrize('original',['process','reservation'])
def test_malformed_original_keeps_failed_provider_row(tmp_path,monkeypatch,original):
    backend=port(tmp_path,max_calls=2)
    calls,_=synthetic_native(tmp_path,monkeypatch,backend)
    provider=wrap_train_provider(backend)
    import research_loop.modular.grok_headless_transport as transport
    account=transport._account_recovered
    def corrupt_after(home,destination,recovery):
        result=account(home,destination,recovery)
        if Path(destination).name=='billing-after':
            native=Path(destination).parent
            path=native/'process.json' if original=='process' else native.parent/'native-reservation.json'
            path.write_bytes(b'[]')
        return result
    monkeypatch.setattr(transport,'_account_recovered',corrupt_after)
    with pytest.raises(ContractError):provider(REQUEST)
    views=provider.inspect()
    assert len(views)==1 and views[0].data()['known_tokens'] is None
    assert not views[0].data()['successful'] and views[0].data()['main_usage_incomplete']
    assert provider.usage().data()['main_opportunities']==1
    with pytest.raises(ContractError):provider(REQUEST)
    assert len(calls)==1


@pytest.mark.parametrize('change',['kind','effort','recovery','source','opportunity_contract'])
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
        if change=='opportunity_contract':
            config['native_config']['opportunity_contract']='foreign'
            config['native_config_digest']=FrozenRecord.from_dict(config['native_config']).content_hash
        if change=='recovery':
            config['native_config']['account_read_recovery']['max_attempts']=3
            config['native_config_digest']=FrozenRecord.from_dict(config['native_config']).content_hash
        with pytest.raises(ContractError):
            validate_configuration(FrozenRecord.from_dict(config),schemas={'m4_plan':SCHEMA},main_opportunities=1)
    assert not calls
