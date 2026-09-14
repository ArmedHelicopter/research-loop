"""A sealed-prefix audit derives eligibility from one fresh original pass."""
import pytest
from research_loop.modular import train_provider as core
from research_loop.ontology import ContractError
from test_train_provider import setup, REQUEST


@pytest.mark.parametrize('kind', ['grok','codex'])
@pytest.mark.parametrize('fault', ['seal','response'])
def test_seal_audit_reads_once_and_remains_fresh_after_append_or_original_drift(tmp_path,monkeypatch,kind,fault):
    backend,calls=setup(kind,tmp_path/'provider',monkeypatch)
    provider=core.wrap_train_provider(backend)
    provider.call(REQUEST);provider.call(REQUEST)
    prefix=provider.seal(tmp_path/'sealed-prefix.json')
    original=core._verify_call;replayed=[]
    def observe(*args,**kwargs):
        replayed.append(args[1]['id'])
        return original(*args,**kwargs)
    monkeypatch.setattr(core,'_verify_call',observe)
    assert prefix.verify_originals().data()['score_eligible'] is True
    assert replayed==[1,2], 'eligibility must use the same freshly checked originals'
    provider.call(REQUEST);replayed.clear()
    verified=prefix.verify_originals().data()
    assert replayed==[1,2,3], 'a later audit must read the entire current prefix once'
    assert verified['score_eligible'] is True and verified['later_calls']==1
    assert len(calls)==3
    path=prefix.path
    if fault=='response':
        path=(backend.calls_root if kind=='grok' else backend.call_root)/'0001-m4_plan'/(
            'response.private.json' if kind=='grok' else 'output.json')
    path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ContractError):prefix.verify_originals()
    assert provider.state['terminal_fault'] is True
    with pytest.raises(ContractError):provider.call(REQUEST)
    assert len(calls)==3
