"""Provider-core integration uses real ports and synthetic peers, never models."""
import json
import sys
from pathlib import Path

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.grok_train_solver import GrokTrainModelPort
from research_loop.modular.model_port import CodexModelPort
from research_loop.modular.train_provider import (CodexTrainProvider, GrokTrainProvider,
    FrozenTrainProviderLedgerV2, wrap_train_provider)
from research_loop.modular import grok_acp_transport as transport
from research_loop.ontology import ContractError, canonical
from test_grok_train_solver import SCHEMA, REQUEST
from test_modular_train_controller import model_port


def native(root, monkeypatch, *, scenarios=('ok', 'ok', 'ok'), mutate=None, schema=None, input_cap=262144):
    root.mkdir(parents=True, exist_ok=True)
    exe=root/'synthetic-grok.exe';exe.write_bytes(b'fixture executable; never launched')
    home=root/'approved-login';home.mkdir();(home/'auth.json').write_text('{}')
    peer=(Path(__file__).parent/'fixtures/grok_acp_peer.py').resolve();logs=[]
    original=transport.ProcessTree
    def spawn(command,cwd,env,stderr):
        assert list(command)==[str(exe.resolve()),'--no-auto-update','--cwd',str(cwd),'agent','stdio']
        assert not any(Path(cwd).iterdir())
        assert all(p.is_dir() for p in Path(env['USERPROFILE']).rglob('*'))
        assert 'XAI_API_KEY' not in env and 'GROK_API_KEY' not in env
        call=Path(env['GROK_HOME']).parent
        assert (Path(env['GROK_HOME'])/'config.toml').read_text()==transport.diagnostic_config(2048)
        if mutate:mutate(len(logs)+1,call)
        log=call/'peer.jsonl';scenario=scenarios[len(logs)];logs.append(log)
        return original([sys.executable,str(peer),scenario,str(log)],cwd,env,stderr)
    monkeypatch.setattr(transport,'EXECUTABLE_SHA256',transport.digest(exe.read_bytes()))
    monkeypatch.setattr(transport,'ProcessTree',spawn)
    port=GrokTrainModelPort(executable=exe,work_root=root/'native-ledger',private_home=home,
        private_profile=root/'profiles',public_cwd=root/'public-contexts',
        frozen_files={str(peer):transport.digest(peer.read_bytes())},max_calls=len(scenarios),
        schemas={'m4_plan':schema or SCHEMA},slot_output_caps={'m4_plan':2048},
        slot_input_byte_caps={'m4_plan':input_cap},observed_main_token_cap=131072)
    return port,logs


def setup(kind,root,monkeypatch,*,failed=False):
    if kind=='grok':return native(root,monkeypatch,scenarios=('ok','rpc_error_usage' if failed else 'ok','ok'))
    count=[]
    def response(request):
        count.append(request.content_hash)
        return FrozenRecord.from_dict({} if failed and len(count)==2 else {'ok':True})
    return model_port(root,monkeypatch,schemas={'m4_plan':SCHEMA},response_factory=response),count


def events(request=REQUEST,response=None):
    return [{'stage':'model_request','data':{'request':request.data()}},
        {'stage':'model_response','data':{'request_digest':request.content_hash,'response':response or {'ok':True}}}]


@pytest.mark.parametrize('kind',['grok','codex'])
def test_real_port_config_originals_and_prefix_append(tmp_path,monkeypatch,kind):
    backend,logs=setup(kind,tmp_path,monkeypatch);provider=wrap_train_provider(backend)
    assert type(provider) is (GrokTrainProvider if kind=='grok' else CodexTrainProvider)
    assert not isinstance(provider,CodexModelPort)
    config=provider.configuration().data();assert not logs
    assert config['native_config']==backend.ledger['config']
    assert len(config['adapter_source_files'])==6
    assert config['limits']['schema_byte_caps'] is None
    assert config['limits']['request_envelope_byte_caps'] is None
    assert provider(REQUEST).data()=={'ok':True}
    prefix=provider.seal(tmp_path/'prefix.json')
    assert prefix.bind_events(events())==(1,)
    assert provider(REQUEST).data()=={'ok':True}
    verified=prefix.verify_originals().data()
    assert verified['originals_verified'] and verified['successful_prefix'] and verified['score_eligible']
    assert verified['later_calls']==1
    assert provider.seal(tmp_path/'two.json').bind_events(events()+events())==(1,2)
    assert len(provider.calls_since(1))==1
    usage=provider.usage().data()
    assert usage['known_reported_tokens']==(24 if kind=='grok' else 4)
    assert usage['main_opportunities']==2 and usage['unknown_main_opportunities']==0
    assert usage['title_tokens'] is usage['all_opportunity_tokens'] is usage['settled_additional_charge_usd'] is None
    assert not any(Path(p).name=='auth.json' for c in provider.state['calls'] for p in c['original_files'])
    if kind=='grok':
        assert config['limits']['lifetime_seconds']==60 and config['limits']['max_retries']==0
        assert usage['possible_initial_title_opportunities']==2
    else:
        assert config['limits']['prompt_byte_caps'] is None
        assert len(backend.ledger['context_probes'])==2  # Replays never run probes.


@pytest.mark.parametrize('kind',['grok','codex'])
def test_failed_later_target_preserves_prefix_and_known_main(tmp_path,monkeypatch,kind):
    backend,logs=setup(kind,tmp_path,monkeypatch,failed=True);provider=wrap_train_provider(backend)
    provider(REQUEST);prefix=provider.seal(tmp_path/'successful-prefix.json')
    with pytest.raises(ContractError):provider(REQUEST)
    assert provider.terminal() and len(logs)==2
    views=provider.inspect();assert len(views)==2 and not views[1].data()['successful']
    assert provider.usage().data()['known_reported_tokens']==(24 if kind=='grok' else 4)
    verification=prefix.verify_originals().data()
    assert verification['originals_verified'] and verification['successful_prefix']
    assert not verification['score_eligible'] and verification['later_calls']==1
    assert prefix.bind_events(events(),require_eligible=False)==(1,)
    with pytest.raises(ContractError):prefix.bind_events(events())
    assert not provider.seal(tmp_path/'failed-session.json').verify_originals().data()['score_eligible']
    resumed=wrap_train_provider(backend)
    with pytest.raises(ContractError):resumed(REQUEST)
    assert len(logs)==2 and backend.ledger['usage_incomplete']
    assert (provider.root/'ledger-0002.json').exists() and (provider.root/'fault-native-ledger.json').exists()


def test_failed_unverifiable_attempt_is_inspectable_without_response_eligibility(tmp_path,monkeypatch):
    def mutate(number,call):
        if number==2:(call/'prompt.private.txt').write_bytes(b'foreign prompt from synthetic peer')
    backend,logs=native(tmp_path,monkeypatch,mutate=mutate);provider=wrap_train_provider(backend)
    provider(REQUEST);prefix=provider.seal(tmp_path/'prefix.json')
    with pytest.raises(ContractError):provider(REQUEST)
    failed=provider.inspect()[1].data()
    assert not failed['successful'] and not failed['originals_verified'] and failed['response_digest'] is None
    assert failed['known_tokens']==12 and failed['main_usage_incomplete']
    assert provider.usage().data()['known_reported_tokens']==24
    assert prefix.verify_originals().data()['successful_prefix']
    assert not prefix.verify_originals().data()['score_eligible']
    with pytest.raises(ContractError):provider(REQUEST)
    assert len(logs)==2


@pytest.mark.parametrize('kind',['grok','codex'])
@pytest.mark.parametrize('fault',['prompt','response','ledger','source'])
def test_original_drift_durably_stops_before_later_io(tmp_path,monkeypatch,kind,fault):
    backend,logs=setup(kind,tmp_path,monkeypatch);provider=wrap_train_provider(backend)
    provider(REQUEST);seal=provider.seal(tmp_path/'prefix.json')
    call=(backend.calls_root if kind=='grok' else backend.call_root)/'0001-m4_plan'
    if fault=='prompt':(call/('prompt.private.txt' if kind=='grok' else 'prompt.txt')).write_bytes(b'foreign')
    elif fault=='response':(call/('response.private.json' if kind=='grok' else 'output.json')).write_bytes(b'{"ok":false}')
    elif fault=='source':Path(backend.executable).write_bytes(b'changed executable')
    else:
        ledger=json.loads(backend.ledger_path.read_bytes());ledger['calls'][0]['slot']='foreign'
        backend.ledger_path.write_bytes(canonical(ledger).encode())
        before=backend.ledger_path.read_bytes()
    with pytest.raises(ContractError):seal.verify_originals()
    with pytest.raises(ContractError):provider(REQUEST)
    assert len(logs)==1 and backend.ledger['usage_incomplete']
    assert json.loads(provider.state_path.read_bytes())['terminal_fault']
    if fault=='ledger':assert (provider.root/'fault-native-ledger.json').read_bytes()==before


@pytest.mark.parametrize('fault',['duplicate','foreign','missing','changed'])
def test_runtime_binding_rejects_unmatched_or_changed_responses(tmp_path,monkeypatch,fault):
    backend,logs=native(tmp_path,monkeypatch);provider=wrap_train_provider(backend)
    provider(REQUEST);seal=provider.seal(tmp_path/'prefix.json');trace=events()
    if fault=='duplicate':trace.append(trace[-1])
    elif fault=='foreign':trace[-1]['data']['request_digest']='b'*64
    elif fault=='missing':trace.pop()
    else:trace[-1]['data']['response']={'ok':False}
    with pytest.raises(ContractError):seal.bind_events(trace)
    with pytest.raises(ContractError):provider(REQUEST)
    assert provider.terminal()
    assert len(logs)==1


def test_closed_types_reject_callable_subclasses_mock_and_custom_native(tmp_path,monkeypatch):
    class Masquerade(CodexModelPort):pass
    for candidate in (lambda request:request, object(), object.__new__(Masquerade)):
        with pytest.raises(ContractError):wrap_train_provider(candidate)
    mocked=CodexModelPort(sys.executable,tmp_path/'mock',max_calls=1,max_tokens=10,
        schema_by_slot={'m4_plan':SCHEMA},allow_mock_context=True,
        process_runner=lambda *a,**k:None,context_probe_runner=lambda *a,**k:None)
    with pytest.raises(ContractError):CodexTrainProvider(mocked)
    backend,logs=native(tmp_path/'native',monkeypatch)
    backend.native_invoke=lambda **kwargs:None
    with pytest.raises(ContractError):GrokTrainProvider(backend)
    assert not logs


def test_prompt_cap_does_not_claim_schema_or_envelope_bound(tmp_path,monkeypatch):
    schema={**SCHEMA,'properties':{**SCHEMA['properties'],
        **{f'optional_public_field_{i}':{'type':'string'} for i in range(100)}}}
    backend,logs=native(tmp_path,monkeypatch,schema=schema,input_cap=1024)
    provider=wrap_train_provider(backend);provider(REQUEST)
    row=provider.inspect()[0].data();limits=provider.configuration().data()['limits']
    assert row['prompt_bytes']<=limits['prompt_byte_caps']['m4_plan']
    assert row['schema_bytes']>1024 and row['request_stream_bytes']>1024
    assert limits['schema_byte_caps'] is limits['request_envelope_byte_caps'] is None
    assert len(logs)==1


def test_pre_dispatch_failure_has_zero_new_opportunities_and_blocks_retry(tmp_path,monkeypatch):
    backend,logs=native(tmp_path,monkeypatch,input_cap=1);provider=wrap_train_provider(backend)
    with pytest.raises(ContractError):provider(REQUEST)
    assert provider.terminal() and provider.usage().data()['main_opportunities']==0
    assert not provider.seal(tmp_path/'empty.json').verify_originals().data()['score_eligible']
    with pytest.raises(ContractError):provider(REQUEST)
    assert not logs


def test_seal_bytes_are_original_evidence_and_close_future_dispatch(tmp_path,monkeypatch):
    backend,logs=native(tmp_path,monkeypatch);provider=wrap_train_provider(backend)
    provider(REQUEST);seal=provider.seal(tmp_path/'prefix.json')
    seal.path.write_bytes(seal.path.read_bytes()+b' ')
    with pytest.raises(ContractError):seal.verify_originals()
    with pytest.raises(ContractError):provider(REQUEST)
    assert provider.terminal() and len(logs)==1


def test_original_audit_never_opens_login_file_bodies(tmp_path,monkeypatch):
    backend,logs=native(tmp_path,monkeypatch);provider=wrap_train_provider(backend)
    original=Path.read_bytes
    def guarded(path):
        assert path.name not in ('auth.json','login-backup.json'), 'opaque login read forbidden'
        return original(path)
    monkeypatch.setattr(Path,'read_bytes',guarded)
    provider(REQUEST)
    (backend.calls_root/'0001-m4_plan/native-home/login-backup.json').write_text('{}')
    assert provider.seal(tmp_path/'prefix.json').verify_originals().data()['score_eligible']
    assert len(logs)==1
