"""Independent, private Messages evaluator; never a public TRAIN model port."""
import http.client
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit

from research_loop.modular.anthropic_train_provider import (
    allocation_lock, original, parse_response, parse_usage, read, record, require, sha, write)
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError, canonical
from evaluation.modular.scoring_service import FrozenBenchmarkRubricEndpoint

KIND = 'anthropic-messages-independent-evaluator-v1'
REQUEST = 'frozen-independent-evaluator-call-v1'
PREFIX = 'Return only JSON conforming to the supplied schema.\n'


def material(spec, *, rubric_mode='primary_v1'):
    fields = {'provider_kind','endpoint','model','response_models','credential_file','work_root',
        'evaluator_id','evaluator_version','max_calls','max_tokens','output_cap','input_byte_cap',
        'observed_token_cap','timeout_seconds','max_response_bytes'}
    require(type(spec) is dict and set(spec) == fields and spec['provider_kind'] == KIND
        and rubric_mode == 'primary_v1', 'exact Messages primary evaluator declaration required')
    for key in ('model','evaluator_id','evaluator_version'):
        require(type(spec[key]) is str and spec[key], 'nonempty evaluator identity required')
    require(type(spec['response_models']) is list and spec['response_models']
        and all(type(v) is str and v for v in spec['response_models']), 'exact response aliases required')
    url = urlsplit(spec['endpoint'])
    require((url.scheme == 'https' or (url.scheme == 'http' and url.hostname == '127.0.0.1'))
        and url.hostname and not url.username and not url.password and not url.query and not url.fragment
        and url.path.endswith('/v1/messages'), 'exact evaluator Messages endpoint required')
    for key in ('max_calls','max_tokens','output_cap','input_byte_cap','observed_token_cap','timeout_seconds','max_response_bytes'):
        require(type(spec[key]) is int and spec[key] > 0, 'bounded evaluator allocation required')
    require(spec['output_cap'] < spec['observed_token_cap'] <= spec['max_tokens']
        and spec['timeout_seconds'] <= 600 and 1024 <= spec['max_response_bytes'] <= 16777216,
        'evaluator token/time/response bound differs')
    require(Path(spec['credential_file']).is_absolute() and Path(spec['work_root']).is_absolute(), 'absolute private paths required')
    import evaluation.modular.scorer_process as factory
    import evaluation.modular.messages_evaluator_closure as closure
    import evaluation.modular.headless_evaluator_closure as dispatch
    import evaluation.modular.scoring_service as rubric
    import research_loop.modular.anthropic_train_provider as common
    import research_loop.modular.model_port as schema
    import research_loop.modular.contracts as contracts
    import research_loop.ontology as ontology
    pins = {str(Path(m.__file__).resolve()):sha(Path(m.__file__).read_bytes())
        for m in (factory,closure,dispatch,rubric,common,schema,contracts,ontology)}
    pins[str(Path(__file__).resolve())] = sha(Path(__file__).read_bytes())
    c = {k:v for k,v in spec.items() if k not in ('credential_file','work_root')}
    c.update(schema='messages-independent-evaluator-port-v1',request_contract=REQUEST,domain='train',
        rubric_mode=rubric_mode,rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest(),
        max_retries=0,thinking={'type':'disabled'},thinking_policy='requested_only',temperature=0,stream=False,
        auth_scheme='bearer',anthropic_version='2023-06-01',source_files=pins,
        schemas={b:FrozenBenchmarkRubricEndpoint._output_schema(b) for b in ('discoverybench','blade')})
    return record(c)


def descriptor(spec, *, rubric_mode='primary_v1'):
    return {'kind':KIND,'configuration_digest':material(spec,rubric_mode=rubric_mode).content_hash}


class MessagesEvaluatorModelPort:
    provider_kind = KIND

    def __init__(self, spec, *, rubric_mode='primary_v1'):
        self._config_record = material(spec,rubric_mode=rubric_mode)
        c = self._config_record.data()
        self.root = Path(spec['work_root']).resolve(); self.credential_file = Path(spec['credential_file']).resolve()
        self.evaluator_id, self.evaluator_version = c['evaluator_id'], c['evaluator_version']
        self.rubric_digest, self.frozen_files = c['rubric_digest'], c['source_files']
        self.root.mkdir(parents=True,exist_ok=True); self.calls_root=self.root/'calls'; self.calls_root.mkdir(exist_ok=True)
        self.ledger_path=self.root/'ledger.json'; self.events_path=self.root/'events.jsonl'
        with allocation_lock(self.root/'allocator.lock'):
            if self.ledger_path.exists(): self.ledger=read(self.ledger_path); self.replay()
            else:
                require(not self.events_path.exists(), 'orphan evaluator originals require investigation')
                self.ledger={'config':c,'calls':[],'tokens':0,'usage_incomplete':False}
                original(self.events_path,b'');write(self.ledger_path,self.ledger)

    def _event(self, body):
        with self.events_path.open('ab') as stream:
            stream.write(canonical(body).encode()+b'\n');stream.flush();os.fsync(stream.fileno())

    def verify_request(self, request):
        c=self._config_record.data(); b=request.data() if type(request) is FrozenRecord else {}
        fields={'schema','evaluator_id','evaluator_version','benchmark','prompt','output_schema',
            'prompt_digest','schema_digest','reference_digest','rubric_digest'}
        require(set(b)==fields and b['schema']==REQUEST and b['evaluator_id']==c['evaluator_id']
            and b['evaluator_version']==c['evaluator_version'] and b['benchmark'] in c['schemas'], 'private evaluator subject differs')
        require(b['output_schema']==c['schemas'][b['benchmark']] and b['schema_digest']==sha(canonical(b['output_schema']).encode())
            and type(b['prompt']) is str and b['prompt_digest']==sha(canonical(b['prompt']).encode())
            and b['rubric_digest']==c['rubric_digest'] and type(b['reference_digest']) is str
            and len(b['reference_digest'])==64 and all(v in '0123456789abcdef' for v in b['reference_digest']),
            'private evaluator rubric binding differs')
        try:
            prefix,tail=b['prompt'].split('\nTASK=');task,tail=tail.split('\nREFERENCE=');ref,candidate=tail.split('\nANONYMOUS_CANDIDATE=')
            values=[json.loads(v) for v in (task,ref,candidate)]
            rubric=FrozenBenchmarkRubricEndpoint._DISCOVERY_RUBRIC if b['benchmark']=='discoverybench' else FrozenBenchmarkRubricEndpoint._BLADE_RUBRIC
            require(b['prompt']==FrozenBenchmarkRubricEndpoint._prompt(b['benchmark'],rubric,*values), 'private rubric template differs')
        except (ValueError,TypeError) as exc: raise ContractError('private rubric template invalid') from exc
        return b

    def _body(self, request):
        b=self.verify_request(request); c=self._config_record.data()
        prompt=PREFIX+canonical({'output_schema':b['output_schema'],'prompt':b['prompt']})
        require(len(prompt.encode())<=c['input_byte_cap'], 'evaluator prompt over bound')
        return {'model':c['model'],'max_tokens':c['output_cap'],'temperature':0,'thinking':{'type':'disabled'},
            'messages':[{'role':'user','content':prompt}]}

    def _parse(self, raw, benchmark):
        c=self._config_record.data()
        return parse_response(raw,{**c,'slot_output_caps':{benchmark:c['output_cap']},
            'observed_main_token_cap':c['observed_token_cap']},benchmark)

    def __call__(self, request):
        with allocation_lock(self.root/'allocator.lock'):
            self.replay();c=self._config_record.data();b=self.verify_request(request);body=self._body(request)
            require(not self.ledger['usage_incomplete'] and len(self.ledger['calls'])<c['max_calls']
                and self.ledger['tokens']+c['observed_token_cap']<=c['max_tokens'], 'evaluator allocation closed')
            number=len(self.ledger['calls'])+1;directory=self.calls_root/f'{number:04d}';directory.mkdir()
            original(directory/'request.private.json',request.encoded.encode());original(directory/'http-request.private.json',canonical(body).encode())
            row={'id':number,'benchmark':b['benchmark'],'request_digest':request.content_hash,'response_digest':None,
                'status':'reserved','usage':None,'files':{}}
            self.ledger['calls'].append(row);self._event({'kind':'reserved','id':number,'request_digest':request.content_hash});write(self.ledger_path,self.ledger)
            connection=None;failure=None
            try:
                auth=read(self.credential_file);base=auth.get('base_url','').rstrip('/')
                require(c['endpoint'] in (base,base+'/v1/messages') and type(auth.get('token')) is str and auth['token']
                    and '\r' not in auth['token'] and '\n' not in auth['token'], 'evaluator credential route differs')
                url=urlsplit(c['endpoint']);connection=(http.client.HTTPSConnection if url.scheme=='https' else http.client.HTTPConnection)(url.hostname,url.port,timeout=c['timeout_seconds'])
                start=time.monotonic();connection.request('POST',url.path,body=canonical(body).encode(),headers={
                    'Authorization':'Bearer '+auth['token'],'anthropic-version':'2023-06-01','Content-Type':'application/json'})
                sock=connection.sock;response=connection.getresponse();original(directory/'http-status.json',canonical({'status':response.status}).encode());size=0
                with (directory/'http-response.private.bin').open('xb') as stream:
                    while True:
                        remaining=c['timeout_seconds']-(time.monotonic()-start);require(remaining>0,'evaluator deadline exceeded');sock.settimeout(remaining)
                        chunk=response.read1(min(65536,c['max_response_bytes']+1-size))
                        if not chunk: break
                        stream.write(chunk);stream.flush();size+=len(chunk);require(size<=c['max_response_bytes'],'evaluator response over bound')
                require(response.status==200,'evaluator HTTP rejected')
                answer,usage=self._parse((directory/'http-response.private.bin').read_bytes(),b['benchmark'])
                original(directory/'response.private.json',answer.encoded.encode());row.update(status='succeeded',usage=usage,response_digest=answer.content_hash)
            except Exception as exc:
                failure=exc;path=directory/'http-response.private.bin';usage=parse_usage(path.read_bytes()) if path.exists() else None
                row.update(status='unknown_or_failed',usage=usage,error_type=type(exc).__name__);self.ledger['usage_incomplete']=True
            finally:
                if connection is not None: connection.close()
                row['files']={p.name:sha(p.read_bytes()) for p in sorted(directory.iterdir())}
                self.ledger['tokens']+=(row['usage'] or {}).get('total_tokens',0)
                self._event({'kind':'completed','row':row});write(self.ledger_path,self.ledger)
            if failure: raise ContractError('evaluator attempt terminal; originals retained') from failure
            self.replay();return answer

    def replay(self):
        try:
            c=self._config_record.data()
            require(read(self.ledger_path)==self.ledger and self.ledger['config']==c, 'evaluator ledger/config drift')
            require(all(sha(Path(p).read_bytes())==h for p,h in self.frozen_files.items()), 'evaluator source drift')
            events=[json.loads(v) for v in self.events_path.read_bytes().splitlines()];rows=self.ledger['calls'];total=0
            require(len(events)==2*len(rows),'evaluator attempt denominator differs')
            for number,row in enumerate(rows,1):
                directory=self.calls_root/f'{number:04d}'
                require(row['id']==number and row['files']=={p.name:sha(p.read_bytes()) for p in sorted(directory.iterdir())},'evaluator original bytes drift')
                request=record(read(directory/'request.private.json'));self.verify_request(request)
                require(request.content_hash==row['request_digest'] and read(directory/'http-request.private.json')==self._body(request), 'evaluator request drift')
                require(events[2*number-2]=={'kind':'reserved','id':number,'request_digest':request.content_hash}
                    and events[2*number-1]=={'kind':'completed','row':row},'evaluator append-only events drift')
                path=directory/'http-response.private.bin';raw=path.read_bytes() if path.exists() else b''
                require(parse_usage(raw)==row['usage'],'evaluator usage drift')
                total+=(row['usage'] or {}).get('total_tokens',0)
                if row['status']=='succeeded':
                    answer,_=self._parse(raw,row['benchmark'])
                    require(read(directory/'http-status.json')['status']==200 and answer.content_hash==row['response_digest']
                        and (directory/'response.private.json').read_bytes()==answer.encoded.encode(),'evaluator output drift')
                else: require(row['status']=='unknown_or_failed' and self.ledger['usage_incomplete'],'failed evaluator cannot promote')
            require(total==self.ledger['tokens'],'evaluator cumulative usage drift')
        except Exception as exc:
            # Preserve disk and memory independently before any terminal marker.
            for name,raw in (('ledger',self.ledger_path.read_bytes()),('memory',canonical(self.ledger).encode())):
                p=self.root/('replay-fault-'+name+'.json')
                if not p.exists(): original(p,raw)
            self.ledger['usage_incomplete']=True;write(self.ledger_path,self.ledger)
            raise ContractError('evaluator replay failed; originals preserved') from exc
