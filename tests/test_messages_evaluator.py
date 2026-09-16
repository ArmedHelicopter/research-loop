"""Private scoring through the production child process and actual loopback HTTP."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import sys
import threading

import pytest

from evaluation.modular.messages_evaluator import KIND, PREFIX, MessagesEvaluatorModelPort
from evaluation.modular.messages_evaluator_closure import finalize, verify_closure
from evaluation.modular.scorer_process import (LinkedScorerProcessClient, build_service,
    messages_evaluator_descriptor, parse_server_config)
from evaluation.modular.linked_scoring import verify_linked_adapted_receipt
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError, canonical
from test_scorer_process import _material, _config
from test_train_adapted_selection import EXEC, SCORER


@pytest.fixture(scope='module')
def inputs(tmp_path_factory):
    # Existing producer fixture uses synthetic execution receipts; we are testing
    # only the new scorer seam. Prior 12-cell real Docker evidence stays separate.
    return _material(tmp_path_factory.mktemp('messages-inputs'))[0]


@contextmanager
def http_evaluator(fault=None):
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*args): pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert self.headers['Authorization']=='Bearer synthetic-evaluator-secret'
            assert self.headers['anthropic-version']=='2023-06-01'
            assert body['thinking']=={'type':'disabled'} and body['max_tokens']==4096
            text=body['messages'][0]['content'];assert text.startswith(PREFIX)
            private=json.loads(text[len(PREFIX):]);assert set(private)=={'prompt','output_schema'}
            assert 'PRIVATE-REFERENCE-SENTINEL' in private['prompt']
            assert 'public-model-request-v1' not in text
            schema=private['output_schema'];calls.append(body)
            answer=({'cvars':2,'transform':2,'model':2} if 'cvars' in schema['properties'] else
                {'context':1,'variable_f1':1,'relation':1})|{'reason':'synthetic independent scorer'}
            b={'type':'message','role':'assistant','model':'fixture-evaluator','stop_reason':'end_turn',
                'content':[{'type':'thinking','thinking':'PRIVATE-THINKING-SENTINEL'},{'type':'text','text':canonical(answer)}],
                'usage':{'input_tokens':17,'output_tokens':13,'cache_creation_input_tokens':0,'cache_read_input_tokens':2}}
            if fault=='unknown_usage': b.pop('usage')
            if fault=='truncated': b['stop_reason']='max_tokens'
            raw=json.dumps(b).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try: yield 'http://127.0.0.1:'+str(server.server_port)+'/v1/messages',calls
    finally: server.shutdown();server.server_close();thread.join()


def prepare(root,args,endpoint):
    value=_config(root,args);credential=root/'synthetic-credential.json'
    credential.write_text(canonical({'base_url':endpoint,'token':'synthetic-evaluator-secret'}))
    rubric=args['config'].record.data()
    value['evaluator']={'provider_kind':KIND,'endpoint':endpoint,'model':'fixture-evaluator',
        'response_models':['fixture-evaluator'],'credential_file':str(credential.resolve()),'work_root':str((root/'http-evaluator').resolve()),
        'evaluator_id':rubric['evaluator_id'],'evaluator_version':rubric['version'],'max_calls':2,'max_tokens':262144,
        'output_cap':4096,'input_byte_cap':262144,'observed_token_cap':131072,'timeout_seconds':30,'max_response_bytes':2097152}
    path=root/'server.json';path.write_text(canonical(value));return value,path


def client(root,args,value,path,*,binding=None):
    return LinkedScorerProcessClient(panel=args['panel'],config=args['config'],
        command=[sys.executable,'-c','from evaluation.modular.scorer_process import main; raise SystemExit(main())',
            '--config',str(path.resolve()),'--config-sha256',hashlib.sha256(path.read_bytes()).hexdigest(),'--journal',str((root/'worker.jsonl').resolve())],
        journal_path=root/'client.jsonl',task_handle_bindings={k:hashlib.sha256(v.encode()).hexdigest() for k,v in value['task_handles'].items()},
        execution_authority_keys={EXEC.authority_id:EXEC.key},scorer_authority_keys={SCORER.authority_id:SCORER.key},
        evaluator_provider=binding or messages_evaluator_descriptor(value['evaluator']),response_timeout_seconds=60)


def test_independent_http_worker_two_benchmarks_signed_closure_and_raw_replay(tmp_path,inputs):
    with http_evaluator() as (endpoint,calls):
        value,path=prepare(tmp_path,inputs,endpoint);peer=client(tmp_path,inputs,value,path)
        chosen=[next(c for c in inputs['panel'].cells if c.identity.benchmark==b) for b in ('discoverybench','blade')]
        try:
            scores=[peer.submit(cell_key=c.key,linked_input=inputs['linked_inputs'][c.key]) for c in chosen]
            for cell,score in zip(chosen,scores,strict=True):
                verify_linked_adapted_receipt(score,authority_keys={SCORER.authority_id:SCORER.key},config=inputs['config'],
                    panel=inputs['panel'],cell=cell,linked_input=inputs['linked_inputs'][cell.key],execution_authority_keys={EXEC.authority_id:EXEC.key})
            closure=peer.finalize_messages_evaluator(receipts=scores)
            body=closure.data()['body'];assert body['evaluator_provider']['kind']==KIND
            assert body['known_reported_tokens']==64 and body['scope']['unscored_cell_count']==10
            assert peer.finalize_messages_evaluator(receipts=scores)==closure
        finally: peer.close()
        assert len(calls)==2
        service=build_service(parse_server_config(value))
        again=finalize(service=service,panel=inputs['panel'],journal_path=tmp_path/'worker.jsonl',nonce=body['nonce'],
            receipt_digests=[s.receipt.content_hash for s in scores])
        assert again==closure and len(calls)==2
        verify_closure(again,authority_keys={SCORER.authority_id:SCORER.key},panel=inputs['panel'],config=inputs['config'],
            provider=body['evaluator_provider'],nonce=body['nonce'],receipt_digests=body['receipt_digests'])
        for f in ('client.jsonl','worker.jsonl','client.jsonl.headless-evaluator-observations.jsonl'):
            p=tmp_path/f
            if p.exists():
                assert not any(s in p.read_text() for s in ('PRIVATE-REFERENCE-SENTINEL','PRIVATE-THINKING-SENTINEL','synthetic-evaluator-secret'))
        port=service.messages_evaluator_port;raw=port.calls_root/'0001/http-response.private.bin';before=raw.read_bytes();raw.write_bytes(before+b' ')
        for p in port.root.rglob('*'):
            if p.is_file(): assert b'synthetic-evaluator-secret' not in p.read_bytes()
        with pytest.raises(ContractError): finalize(service=service,panel=inputs['panel'],journal_path=tmp_path/'worker.jsonl',
            nonce=body['nonce'],receipt_digests=body['receipt_digests'])
        assert (port.root/'replay-fault-ledger.json').is_file() and raw.read_bytes()==before+b' '


@pytest.mark.parametrize('fault',['unknown_usage','truncated'])
def test_worker_failure_retains_one_attempt_and_refuses_score_or_retry(tmp_path,inputs,fault):
    with http_evaluator(fault) as (endpoint,calls):
        value,path=prepare(tmp_path,inputs,endpoint);peer=client(tmp_path,inputs,value,path);cell=inputs['panel'].cells[0]
        try:
            for _ in range(2):
                with pytest.raises(ContractError): peer.submit(cell_key=cell.key,linked_input=inputs['linked_inputs'][cell.key])
            with pytest.raises(ContractError): peer.finalize_messages_evaluator(receipts=[])
        finally: peer.close()
        assert len(calls)==1
        root=Path(value['evaluator']['work_root']);ledger=json.loads((root/'ledger.json').read_bytes())
        assert len(ledger['calls'])==1 and ledger['usage_incomplete'] and ledger['calls'][0]['status']=='unknown_or_failed'
        assert ledger['calls'][0]['usage'] is None if fault=='unknown_usage' else ledger['calls'][0]['usage']['total_tokens']==32
        assert (root/'calls/0001/http-response.private.bin').is_file()
        before=(root/'events.jsonl').read_bytes();port=MessagesEvaluatorModelPort(value['evaluator']);port.replay()
        assert (root/'events.jsonl').read_bytes()==before
        assert [json.loads(v)['status'] for v in (tmp_path/'worker.jsonl').read_text().splitlines()]==['reserved','unknown']


def test_descriptor_mismatch_and_public_request_rejected_before_http(tmp_path,inputs):
    with http_evaluator() as (endpoint,calls):
        value,path=prepare(tmp_path,inputs,endpoint)
        with pytest.raises(ContractError): client(tmp_path,inputs,value,path,binding={'kind':KIND,'configuration_digest':'0'*64})
        port=MessagesEvaluatorModelPort(value['evaluator'])
        with pytest.raises(ContractError): port(FrozenRecord.from_dict({'schema':'public-model-request-v1'}))
        assert not calls and not port.ledger['calls']
