"""Real loopback HTTP plus existing Q3.1 Docker/private-worker consumer; no APIs."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time

import pytest

from research_loop.modular.anthropic_train_provider import AnthropicMessagesTrainModelPort, PREFIX
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.phase_provider import PhaseProviderSession
from research_loop.modular.train_provider import AnthropicTrainProvider
from research_loop.modular.train_provider_preflight import validate_native_declaration
from research_loop.ontology import ContractError
from test_grok_train_solver import SCHEMA, REQUEST


@contextmanager
def server(answer, *, fault=None):
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self, *args): pass
        def do_POST(self):
            raw=self.rfile.read(int(self.headers['Content-Length'])); body=json.loads(raw)
            assert self.path=='/v1/messages' and self.headers['Authorization']=='Bearer synthetic-secret'
            assert self.headers['anthropic-version']=='2023-06-01'
            assert set(body)=={'model','max_tokens','temperature','thinking','messages'}
            assert body['thinking']=={'type':'disabled'} and body['temperature']==0
            prompt=body['messages'][0]['content']; assert prompt.startswith(PREFIX)
            request=FrozenRecord.from_dict(json.loads(prompt[len(PREFIX):])['request'])
            calls.append(body)
            response={'id':'synthetic-'+str(len(calls)),'type':'message','role':'assistant','model':'fixture-model',
                'stop_reason':'max_tokens' if fault=='truncated' else 'end_turn',
                'content':[{'type':'thinking','thinking':'PRIVATE-THINKING-SENTINEL'},
                    {'type':'text','text':json.dumps(answer(request))}],
                'usage':{'input_tokens':11,'output_tokens':7,'cache_creation_input_tokens':2,'cache_read_input_tokens':3}}
            if fault=='unknown_usage': response.pop('usage')
            if fault=='model': response['model']='unfrozen-alias'
            if fault=='extra_json': response['content'][-1]['text']='{"ok":true,"unexpected":1}'
            if fault=='schema': response['content'][-1]['text']='{"ok":"not boolean"}'
            if fault=='timeout': time.sleep(1.2)
            raw=json.dumps(response).encode()
            self.send_response(int(fault) if fault in ('401','429','503') else 200)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
            try: self.end_headers();self.wfile.write(raw)
            except (ConnectionError,OSError): pass
    service=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=service.serve_forever,daemon=True);thread.start()
    try: yield 'http://127.0.0.1:'+str(service.server_port)+'/v1/messages',calls
    finally: service.shutdown();service.server_close();thread.join()


def provider(root, endpoint, *, schemas=None, max_calls=2, timeout_seconds=30):
    root.mkdir(parents=True,exist_ok=True)
    auth=root/'synthetic-auth.json';auth.write_text(json.dumps({'base_url':endpoint,'token':'synthetic-secret'}))
    schemas=schemas or {'m4_plan':SCHEMA}
    return AnthropicTrainProvider(AnthropicMessagesTrainModelPort(work_root=root/'port',endpoint=endpoint,
        credential_file=auth,model='fixture-model',response_models=['fixture-model'],schemas=schemas,max_calls=max_calls,
        slot_output_caps={s:4096 for s in schemas},slot_input_byte_caps={s:262144 for s in schemas},
        observed_main_token_cap=131072,timeout_seconds=timeout_seconds))


def request(split='TRAIN'):
    b=REQUEST.data();b['task']={'identity':{'domain':'train' if split=='TRAIN' else 'validation',
        'benchmark':'discoverybench','task_id':'synthetic','group_id':'group','dataset_version':'v1','split_id':'s1'}}
    return FrozenRecord.from_dict(b)


def test_phase_consumes_original_http_and_rejects_tamper(tmp_path):
    with server(lambda _: {'ok':True}) as (endpoint,calls):
        p=provider(tmp_path,endpoint);session=PhaseProviderSession(p,tmp_path/'scopes.json')
        for n in range(2):
            with session.scope(str(n)) as scope: assert scope(request()).data()=={'ok':True}
        seal=session.seal(tmp_path/'seal.json');seal.verify()
        assert len(calls)==2 and p.usage().data()['known_reported_tokens']==46
        assert p.usage().data()['known_usage_scope']=='anthropic_messages_reported'
        assert 'synthetic-secret' not in p.configuration().encoded
        for path in p.backend.root.rglob('*'):
            if path.is_file(): assert b'synthetic-secret' not in path.read_bytes()
        first=p.backend.calls_root/'0001-m4_plan/http-response.bin'
        first.write_bytes(first.read_bytes().replace(b'11',b'99'))
        with pytest.raises(ContractError): seal.verify()
        assert (p.root/'fault-native-ledger.json').is_file()


@pytest.mark.parametrize('fault',['truncated','unknown_usage','model','401','429','503','timeout','extra_json','schema'])
def test_rejected_attempt_closes_without_retry_and_retains_originals(tmp_path,fault):
    with server(lambda _: {'ok':True},fault=fault) as (endpoint,calls):
        p=provider(tmp_path,endpoint,timeout_seconds=1 if fault=='timeout' else 30)
        with pytest.raises(ContractError): p(request())
        before=(p.backend.events_path).read_bytes()
        with pytest.raises(ContractError): p(request())
        assert len(calls)==1 and p.backend.events_path.read_bytes()==before
        assert p.inspect()[0].data()['successful'] is False
        assert p.backend.ledger['calls'][0]['status']=='unknown_or_failed'
        directory=p.backend.calls_root/'0001-m4_plan'
        assert (directory/'http-request.json').is_file()
        if fault!='timeout': assert (directory/'http-response.bin').is_file()


def test_val_and_old_envelope_rejected_before_http(tmp_path):
    with server(lambda _: {'ok':True}) as (endpoint,calls):
        p=provider(tmp_path,endpoint)
        for schema in ('train-panel-controller-v1','train-panel-controller-v2'):
            with pytest.raises(ContractError): validate_native_declaration({'schema':schema,'provider':p.configuration().data()},
                family='singleton',schemas=p.backend.schemas,main_opportunities=2)
        with pytest.raises(ContractError): p.backend(request('VAL'))
        assert calls==[] and p.backend.ledger['calls']==[]


def test_q31_http_native_docker_independent_scorer_complete_consumer(tmp_path,monkeypatch):
    # Reuse the full public controller/scorer test, changing only its producer
    # constructor. The independent scorer remains a synthetic OS stdio worker.
    import test_ordinary_headless_scoring as integration
    from contextlib import ExitStack
    with ExitStack() as stack:
        def messages(root, patch, *, schemas,max_calls,response,**unused):
            endpoint,calls=stack.enter_context(server(response))
            return provider(root,endpoint,schemas=schemas,max_calls=max_calls),calls,[]
        old_body=integration._native_body
        def envelope(old,p):
            body=old_body(old,p);body['schema']='train-panel-controller-v3';return body
        monkeypatch.setattr(integration,'headless_train_provider',messages)
        monkeypatch.setattr(integration,'_native_body',envelope)
        integration.test_all_twelve_cells_reach_native_solve_live_docker_private_score_and_signed_closure(tmp_path,monkeypatch)
