"""Synthetic loopback checks for the distinct local Ollama TRAIN seam."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.ollama_train_provider import OPTIONS, PREFIX, OllamaChatTrainModelPort
from research_loop.modular.phase_provider import PhaseProviderSession
from research_loop.modular.train_provider import OllamaTrainProvider
from research_loop.ontology import ContractError

SCHEMA={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}
DIGEST='405af0433597057d18d68ef22b3f1a1ae7d67f2329aeb85f4d468bc07e83f182'

@contextmanager
def server(*, malformed=False):
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            raw=self.rfile.read(int(self.headers['Content-Length']));body=json.loads(raw);calls.append(body)
            assert self.path=='/api/chat' and set(body)=={'model','messages','format','stream','options'}
            assert body['stream'] is False and body['options']==OPTIONS and body['format']==SCHEMA
            assert body['messages'][0]['content'].startswith(PREFIX)
            response={'model':'research-loop-qwen25-7b-q4-r1:latest','message':{'role':'assistant','content':'not-json' if malformed else '{"ok":true}'},'done':True,'done_reason':'stop','prompt_eval_count':11,'eval_count':7,'total_duration':100,'load_duration':0,'prompt_eval_duration':10,'eval_duration':20}
            data=json.dumps(response).encode();self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    http=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    try: yield f'http://127.0.0.1:{http.server_port}/api/chat',calls
    finally: http.shutdown();http.server_close();thread.join()

def request():
    return FrozenRecord.from_dict({'schema':'public-model-request-v1','task':{'identity':{'domain':'train','benchmark':'discoverybench','task_id':'synthetic','group_id':'g','dataset_version':'v1','split_id':'s'}},'lock_digest':'a'*64,'objective':'synthetic','slot':'plan','instruction':'synthetic','context':{},'module_context':{},'execution_feedback':{}})

def provider(root,endpoint):
    return OllamaTrainProvider(OllamaChatTrainModelPort(work_root=root/'port',endpoint=endpoint,model='research-loop-qwen25-7b-q4-r1:latest',model_digest=DIGEST,schemas={'plan':SCHEMA},max_calls=1,slot_output_caps={'plan':1024},slot_input_byte_caps={'plan':16384},observed_main_token_cap=2048,timeout_seconds=10))

def test_loopback_train_phase_replays_originals(tmp_path):
    with server() as (endpoint,calls):
        p=provider(tmp_path,endpoint);session=PhaseProviderSession(p,tmp_path/'scopes.json')
        with session.scope('synthetic') as scope: assert scope(request()).data()=={'ok':True}
        seal=session.seal(tmp_path/'seal.json');assert seal.verify().data()['score_eligible'] is True
        assert len(calls)==1 and p.usage().data()['known_reported_tokens']==18
        raw=p.backend.calls_root/'0001-plan/http-response.bin';raw.write_bytes(raw.read_bytes()+b' ')
        with pytest.raises(ContractError): seal.verify()

def test_malformed_response_is_retained_and_closes_denominator(tmp_path):
    with server(malformed=True) as (endpoint,calls):
        p=provider(tmp_path,endpoint)
        with pytest.raises(ContractError): p(request())
        with pytest.raises(ContractError): p(request())
        assert len(calls)==1 and p.backend.ledger['calls'][0]['status']=='unknown_or_failed'
        assert (p.backend.calls_root/'0001-plan/http-response.bin').is_file()
