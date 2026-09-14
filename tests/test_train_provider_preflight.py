"""New envelope admission is distinct from original native call eligibility."""
import hashlib
import os
from pathlib import Path
import sys

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.phase_provider import PhaseProviderSession, call_accounting
from research_loop.modular.train_provider_preflight import (
    NATIVE_SCHEMAS, native_fields, validate_native_declaration,
    native_provider_preflight, scorer_process_preflight)
from research_loop.ontology import ContractError, canonical
from helpers.native_ordinary_provider import native_ordinary_provider
from test_grok_train_solver import REQUEST as BASE_REQUEST


SCHEMAS = {'final': {'type':'object','properties':{'answer':{'type':'string'}},
    'required':['answer'],'additionalProperties':False}}
REQUEST = FrozenRecord.from_dict({**BASE_REQUEST.data(),'slot':'final'})


def setup(root, patch):
    provider, logs = native_ordinary_provider(root/'provider',patch,schemas=SCHEMAS,
        max_calls=2,response=lambda request:{'answer':'public synthetic answer'})
    body = {'schema':NATIVE_SCHEMAS['singleton'],'provider':provider.configuration().data()}
    return provider, logs, body


@pytest.mark.parametrize('family', tuple(NATIVE_SCHEMAS))
def test_each_explicit_native_envelope_preserves_true_configuration(tmp_path,monkeypatch,family):
    provider, logs, body = setup(tmp_path,monkeypatch)
    body['schema'] = NATIVE_SCHEMAS[family]
    assert native_fields(body, {'schema','model','effort','max_calls','max_tokens','schemas'},family=family)
    assert native_provider_preflight(body,provider,family=family,schemas=SCHEMAS,
        main_opportunities=2) == provider.configuration()
    assert logs == []
    body['schema'] += '-unreviewed'
    with pytest.raises(ContractError):
        native_provider_preflight(body,provider,family=family,schemas=SCHEMAS,main_opportunities=2)


def test_preflight_default_native_call_original_seal_and_scoped_binding(tmp_path,monkeypatch):
    provider, logs, body = setup(tmp_path,monkeypatch)
    native_provider_preflight(body,provider,family='singleton',schemas=SCHEMAS,main_opportunities=2)
    session = PhaseProviderSession(provider,tmp_path/'scopes.json')
    with session.scope('first-cell') as model:
        response = model(REQUEST)
    seal = session.seal(tmp_path/'provider-seal.json')
    events = [{'stage':'model_request','data':{'request':REQUEST.data()}},
        {'stage':'model_response','data':{'request_digest':REQUEST.content_hash,'response':response.data()}}]
    assert seal.bind_events(events,scope_id='first-cell') == (1,)
    usage = call_accounting(provider.inspect())
    assert usage['provider_calls'] == 1 and usage['known_reported_tokens'] == 12
    assert usage['possible_initial_title_opportunities'] == 1 and usage['all_opportunity_tokens'] is None
    assert len(logs) == 1
    with pytest.raises(ContractError,match='fresh'):
        native_provider_preflight(body,provider,family='singleton',schemas=SCHEMAS,main_opportunities=2)


@pytest.mark.parametrize('field,value', [
    ('prompt_byte_caps',{'final':1048576}),('requested_output_token_caps',{'final':8192}),
    ('observed_main_token_cap',262144),('schema_byte_caps',{'final':262144}),
    ('request_envelope_byte_caps',{'final':262144}),('lifetime_seconds',180),
    ('possible_initial_title_opportunities',0)])
def test_declared_byte_token_lifetime_and_title_bounds_are_not_interchangeable(tmp_path,monkeypatch,field,value):
    provider, logs, body = setup(tmp_path,monkeypatch)
    body['provider']['limits'][field] = value
    with pytest.raises(ContractError):
        validate_native_declaration(body,family='singleton',schemas=SCHEMAS,main_opportunities=2)
    assert logs == []


def test_no_callable_or_codex_field_assertion_can_replace_original_provider(tmp_path,monkeypatch):
    provider, logs, body = setup(tmp_path,monkeypatch)
    with pytest.raises(ContractError,match='closed'):
        native_provider_preflight(body,lambda request:request,family='singleton',schemas=SCHEMAS,main_opportunities=2)
    body['max_tokens'] = 100
    with pytest.raises(ContractError,match='legacy'):
        native_provider_preflight(body,provider,family='singleton',schemas=SCHEMAS,main_opportunities=2)
    assert logs == []


def test_separate_scorer_preflight_replays_actual_process_binding(tmp_path):
    from evaluation.modular.scorer_process import CombinationScorerProcessClient
    from test_state_prediction_scorer_process import _server, _panel, EXECUTION, SCORER
    panel, packets, *_ = _panel(tmp_path/'panel','pair:M2+M4')
    server, config, handles = _server(tmp_path/'server',panel,packets)
    path = tmp_path/'server.json'; path.write_text(canonical(server),encoding='utf-8')
    helper = Path(__file__).parent/'helpers/state_prediction_scorer_process_helper.py'
    bindings = {k:hashlib.sha256(v.encode()).hexdigest() for k,v in handles.items()}
    client = CombinationScorerProcessClient(panel=panel,config=config,state_prediction=True,
        command=[sys.executable,str(helper.resolve()),'--config',str(path.resolve()),
            '--config-sha256',hashlib.sha256(path.read_bytes()).hexdigest(),
            '--journal',str((tmp_path/'worker.jsonl').resolve())],
        journal_path=tmp_path/'client.jsonl',task_handle_bindings=bindings,
        execution_authority_keys={EXECUTION.authority_id:EXECUTION.key},
        scorer_authority_keys={SCORER.authority_id:SCORER.key},environment={**os.environ,'PYTHONIOENCODING':'utf-8'})
    body = {'scorer':config.record.data(),'scorer_handle_bindings':bindings}
    try:
        scorer_process_preflight(body,client,EXECUTION,{SCORER.authority_id:SCORER.key},family='state_prediction')
        with pytest.raises(ContractError):
            scorer_process_preflight(body,client,EXECUTION,{SCORER.authority_id:SCORER.key},family='state_retrieval')
        body['scorer_handle_bindings'] = {k:'f'*64 for k in bindings}
        with pytest.raises(ContractError):
            scorer_process_preflight(body,client,EXECUTION,{SCORER.authority_id:SCORER.key},family='state_prediction')
        assert not (tmp_path/'worker.jsonl').exists()
    finally:
        client.close()
