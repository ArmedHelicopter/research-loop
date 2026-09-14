"""One fresh original replay per phase verification, using both real port types."""
import pytest

from research_loop.modular import train_provider as core
from research_loop.modular.phase_provider import PhaseProviderSession
from research_loop.ontology import ContractError
from test_train_provider import setup, REQUEST


@pytest.mark.parametrize('kind', ['grok', 'codex'])
@pytest.mark.parametrize('fault', ['original', 'configuration'])
def test_phase_verification_reads_each_original_once_but_never_reuses_old_pass(tmp_path, monkeypatch, kind, fault):
    backend, calls = setup(kind, tmp_path/'provider', monkeypatch)
    provider = core.wrap_train_provider(backend)
    session = PhaseProviderSession(provider, tmp_path/'scopes.json')
    for scope_id in ('history', 'target'):
        with session.scope(scope_id) as model:
            model(REQUEST)
    assert len(calls) == 2
    original_verify = core._verify_call
    replayed = []
    def verify_each_original(*args, **kwargs):
        replayed.append(args[1]['id'])
        return original_verify(*args, **kwargs)
    monkeypatch.setattr(core, '_verify_call', verify_each_original)
    session.verify()
    assert replayed == [1, 2], 'one phase check should not replay the same native prefix twice'
    replayed.clear()
    session.verify()
    assert replayed == [1, 2], 'a later check must make a new original pass'
    if fault == 'original':
        first = backend.calls_root/'0001-m4_plan'/('response.private.json' if kind == 'grok' else 'output.json')
        first.write_bytes(first.read_bytes()+b' ')
    elif kind == 'grok':
        backend.slot_output_caps['m4_plan'] += 1
    else:
        backend.max_tokens += 1
    with pytest.raises(ContractError):
        session.verify()
    assert provider.state['terminal_fault'] is True and backend.ledger['usage_incomplete'] is True
    assert len(calls) == 2, 'a failed fresh audit must make no model or retry call'
