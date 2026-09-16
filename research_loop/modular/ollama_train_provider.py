"""CPU-only local Ollama /api/chat TRAIN port.

This is deliberately a distinct provider family.  It sends no credentials and
only permits literal 127.0.0.1; successful output is TRAIN-only evidence, not
benchmark or validation evidence.
"""
import hashlib
import http.client
import json
import os
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.model_port import _schema_witness, _validate_schema
from research_loop.ontology import ContractError, canonical

KIND = 'ollama-local-chat-public-train-v1'
PREFIX = 'Return only a JSON object satisfying the supplied schema. No tools, files, browsing, labels, results, or evaluation material are available.\n'
FIELDS = {'schema','task','lock_digest','objective','slot','instruction','context','module_context','execution_feedback'}
OPTIONS = {'num_gpu':0,'num_thread':4,'num_ctx':8192,'num_predict':1024,'temperature':0,'seed':20260916}

def require(value, reason):
    if not value: raise ContractError(reason)
def sha(raw): return hashlib.sha256(raw).hexdigest()
def record(value): return FrozenRecord.from_dict(value)
def read(path): return json.loads(Path(path).read_bytes())
def write(path, value):
    temporary=Path(path).with_suffix('.tmp'); temporary.write_bytes(canonical(value).encode()); temporary.replace(path)
def original(path, raw):
    with Path(path).open('xb') as stream: stream.write(raw)

@contextmanager
def allocation_lock(path):
    try:
        with Path(path).open('x') as stream: stream.write(str(os.getpid()))
    except FileExistsError as exc: raise ContractError('Ollama allocator already in use') from exc
    try: yield
    finally: Path(path).unlink(missing_ok=True)

def parse_usage(raw):
    try:
        body=json.loads(raw)
        values={key:body.get(key) for key in ('prompt_eval_count','eval_count','total_duration','load_duration','prompt_eval_duration','eval_duration')}
        if any(type(values[k]) is not int or values[k] < 0 for k in ('prompt_eval_count','eval_count')): return None
        if any(v is not None and (type(v) is not int or v < 0) for v in values.values()): return None
        values['total_tokens']=values['prompt_eval_count']+values['eval_count']; return values
    except (TypeError, ValueError): return None

def parse_response(raw, config, slot):
    body=json.loads(raw)
    require(body.get('model')==config['model'] and body.get('done') is True and body.get('done_reason')=='stop', 'Ollama response identity or completion differs')
    message=body.get('message'); require(type(message) is dict and message.get('role')=='assistant' and type(message.get('content')) is str, 'Ollama assistant content differs')
    answer=record(json.loads(message['content'])); _validate_schema(config['schemas'][slot],answer.data())
    usage=parse_usage(raw); require(usage is not None and usage['eval_count']<=OPTIONS['num_predict'] and usage['total_tokens']<=config['observed_main_token_cap'], 'Ollama usage missing or over bound')
    return answer,usage

def verify_model_binding(port, phase):
    """Bind a mutable local tag to its expected digest before and after inference."""
    require(phase in ('before','after'), 'Ollama binding phase differs')
    path=port.root/f'model-binding-{phase}.json'; url=urlsplit(port.config.data()['endpoint'])
    connection=None
    try:
        connection=http.client.HTTPConnection(url.hostname,url.port,timeout=port.config.data()['timeout_seconds'])
        connection.request('GET','/api/tags'); response=connection.getresponse(); raw=response.read(port.config.data()['max_response_bytes']+1)
        require(response.status==200 and len(raw)<=port.config.data()['max_response_bytes'],'Ollama model inventory rejected')
        original(path,raw); body=json.loads(raw); models=body.get('models')
        require(type(models) is list and any(type(row) is dict and row.get('name')==port.model and row.get('digest')==port.model_digest for row in models),'Ollama model tag/digest binding differs')
        return body
    except FileExistsError:
        raw=path.read_bytes(); body=json.loads(raw); require(any(type(row) is dict and row.get('name')==port.model and row.get('digest')==port.model_digest for row in body.get('models',[])),'Ollama retained model binding differs'); return body
    finally:
        if connection is not None: connection.close()

class OllamaChatTrainModelPort:
    provider_kind=KIND
    def __init__(self, *, work_root, endpoint, model, model_digest, schemas, max_calls, slot_output_caps, slot_input_byte_caps, observed_main_token_cap, timeout_seconds=120, max_response_bytes=2097152):
        url=urlsplit(endpoint)
        require(url.scheme=='http' and url.hostname=='127.0.0.1' and not url.username and not url.password and not url.query and not url.fragment and url.path=='/api/chat', 'literal loopback Ollama /api/chat endpoint required')
        require(type(model) is str and model and type(model_digest) is str and len(model_digest)==64 and all(x in '0123456789abcdef' for x in model_digest), 'immutable Ollama model digest required')
        require(type(max_calls) is int and max_calls>0 and type(observed_main_token_cap) is int and observed_main_token_cap>OPTIONS['num_predict'] and type(timeout_seconds) is int and 1<=timeout_seconds<=600 and type(max_response_bytes) is int and 1024<=max_response_bytes<=16777216, 'bounded Ollama allocation required')
        require(set(schemas)==set(slot_output_caps)==set(slot_input_byte_caps) and schemas, 'exact Ollama slot budgets required')
        for slot,schema in schemas.items():
            require(type(slot) is str and schema.get('type')=='object' and type(slot_output_caps[slot]) is int and 0<slot_output_caps[slot]<=OPTIONS['num_predict'] and type(slot_input_byte_caps[slot]) is int and slot_input_byte_caps[slot]>0, 'invalid Ollama slot policy')
            _validate_schema(schema,_schema_witness(schema))
        self.root=Path(work_root).resolve(); self.root.mkdir(parents=True,exist_ok=False); self.calls_root=self.root/'calls';self.calls_root.mkdir();self.ledger_path=self.root/'ledger.json';self.events_path=self.root/'events.jsonl'
        self.model=model;self.model_digest=model_digest;self.max_calls=max_calls;self.schemas=json.loads(canonical(schemas));self.slot_output_caps=dict(slot_output_caps);self.slot_input_byte_caps=dict(slot_input_byte_caps);self.observed_main_token_cap=observed_main_token_cap
        sources=[Path(__file__),Path(__file__).with_name('model_port.py'),Path(__file__).with_name('contracts.py'),Path(__file__).with_name('train_provider.py'),Path(__file__).with_name('phase_provider.py'),Path(__file__).parents[1]/'ontology.py']
        self.config=record({'schema':'ollama-local-chat-train-port-v1','provider_kind':KIND,'domain':'TRAIN','endpoint':endpoint,'model':model,'model_digest':model_digest,'format':'json_schema_per_slot','stream':False,'options':OPTIONS,'max_retries':0,'tools':False,'max_calls':max_calls,'schemas':self.schemas,'slot_output_caps':self.slot_output_caps,'slot_input_byte_caps':self.slot_input_byte_caps,'observed_main_token_cap':observed_main_token_cap,'timeout_seconds':timeout_seconds,'max_response_bytes':max_response_bytes,'source_files':{str(p.resolve()):sha(p.read_bytes()) for p in sources}})
        self.ledger={'config':self.config.data(),'calls':[],'tokens':0,'usage_incomplete':False};write(self.ledger_path,self.ledger);original(self.events_path,b'')
    def _event(self,value):
        with self.events_path.open('ab') as stream: stream.write(canonical(value).encode()+b'\n');stream.flush();os.fsync(stream.fileno())
    def __call__(self,request):
        with allocation_lock(self.root/'allocator.lock'): return self._dispatch(request)
    def _dispatch(self,request):
        native_configuration(self);require(read(self.ledger_path)==self.ledger and not self.ledger['usage_incomplete'],'Ollama ledger closed or changed')
        verify_model_binding(self,'before')
        require(type(request) is FrozenRecord and set(request.data())==FIELDS,'exact public TRAIN request required');b=request.data();slot=b['slot'];require(b['schema']=='public-model-request-v1' and slot in self.schemas,'Ollama public slot differs');DataIdentity.parse(b['task'].get('identity',{})).require_train();require(len(self.ledger['calls'])<self.max_calls,'Ollama allocation exhausted')
        prompt=PREFIX+canonical({'output_schema':self.schemas[slot],'request':b});require(len(prompt.encode())<=self.slot_input_byte_caps[slot],'Ollama prompt over bound')
        body={'model':self.model,'messages':[{'role':'user','content':prompt}],'format':self.schemas[slot],'stream':False,'options':OPTIONS};number=len(self.ledger['calls'])+1;directory=self.calls_root/f'{number:04d}-{slot}';directory.mkdir();original(directory/'request.json',request.encoded.encode());original(directory/'http-request.json',canonical(body).encode());row={'id':number,'slot':slot,'request_sha256':request.content_hash,'status':'reserved','response_sha256':None,'usage':None,'original_files':{}};self.ledger['calls'].append(row);self._event({'kind':'reserved','id':number,'request_digest':request.content_hash});write(self.ledger_path,self.ledger)
        connection=None;failure=None
        try:
            url=urlsplit(self.config.data()['endpoint']);connection=http.client.HTTPConnection(url.hostname,url.port,timeout=self.config.data()['timeout_seconds']);connection.request('POST',url.path,body=(directory/'http-request.json').read_bytes(),headers={'Content-Type':'application/json'});response=connection.getresponse();original(directory/'http-status.json',canonical({'status':response.status,'redirect_followed':False}).encode());raw=response.read(self.config.data()['max_response_bytes']+1);require(len(raw)<=self.config.data()['max_response_bytes'] and response.status==200,'Ollama HTTP response rejected');original(directory/'http-response.bin',raw);answer,usage=parse_response(raw,self.config.data(),slot);verify_model_binding(self,'after');original(directory/'response.json',answer.encoded.encode());row.update(status='succeeded',response_sha256=answer.content_hash,usage=usage)
        except Exception as exc:
            failure=exc;raw=(directory/'http-response.bin').read_bytes() if (directory/'http-response.bin').exists() else b'';row.update(status='unknown_or_failed',error_type=type(exc).__name__,usage=parse_usage(raw));self.ledger['usage_incomplete']=True
        finally:
            if connection is not None: connection.close()
            row['original_files']={p.name:sha(p.read_bytes()) for p in sorted(directory.iterdir())};self.ledger['tokens']+=(row['usage'] or {}).get('total_tokens',0);self._event({'kind':'completed','row':row});write(self.ledger_path,self.ledger)
        if failure: raise ContractError('Ollama attempt terminal; original evidence retained; no retry') from failure
        observation(self,row);return answer

def native_configuration(port):
    require(type(port) is OllamaChatTrainModelPort and read(port.ledger_path)['config']==port.config.data()==port.ledger['config'],'Ollama configuration drift');c=port.config.data();require(c['model']==port.model and c['model_digest']==port.model_digest and c['options']==OPTIONS and urlsplit(c['endpoint']).hostname=='127.0.0.1','Ollama live policy drift');require(all(sha(Path(p).read_bytes())==h for p,h in c['source_files'].items()),'Ollama source drift');return c
def configuration(port):
    c=native_configuration(port);return {'schema':'public-train-provider-config-v1','provider_kind':KIND,'model':port.model,'execution_mode':'local_cpu_structured_json','native_config':c,'native_config_digest':record(c).content_hash,'adapter_source_files':c['source_files'],'limits':{'main_opportunities':port.max_calls,'possible_initial_title_opportunities':0,'prompt_byte_caps':c['slot_input_byte_caps'],'schema_byte_caps':None,'request_envelope_byte_caps':None,'requested_output_token_caps':c['slot_output_caps'],'observed_main_token_cap':c['observed_main_token_cap'],'legacy_reported_token_limit':None,'lifetime_seconds':c['timeout_seconds'],'max_retries':0},'accounting_scope':'ollama_reported_counts_and_durations','title_and_all_opportunity_settlement':'not_applicable_local_unpriced'}
def validate_configuration_declaration(body,*,schemas):
    c=body['native_config'];require(c.get('schema')=='ollama-local-chat-train-port-v1' and c.get('provider_kind')==KIND and c.get('domain')=='TRAIN' and c.get('options')==OPTIONS and c.get('stream') is False and c.get('tools') is False and c.get('max_retries')==0 and c.get('model_digest'),'Ollama declaration differs');require(body.get('accounting_scope')=='ollama_reported_counts_and_durations' and body.get('limits',{}).get('prompt_byte_caps')==c['slot_input_byte_caps'] and set(c['schemas'])==set(schemas),'Ollama declaration bounds differ')
def observation(port,row,*,failure=None):
    directory=port.calls_root/f'{row["id"]:04d}-{row["slot"]}';files={p.name:sha(p.read_bytes()) for p in sorted(directory.iterdir())};raw=(directory/'http-response.bin').read_bytes() if (directory/'http-response.bin').exists() else b'';usage=parse_usage(raw);require(files==row['original_files'],'Ollama original bytes drift');request=record(read(directory/'request.json'));c=native_configuration(port);expected={'model':c['model'],'messages':[{'role':'user','content':PREFIX+canonical({'output_schema':c['schemas'][row['slot']],'request':request.data()})}],'format':c['schemas'][row['slot']],'stream':False,'options':OPTIONS};require(request.content_hash==row['request_sha256'] and read(directory/'http-request.json')==expected and usage==row['usage'],'Ollama original replay differs');events=[json.loads(x) for x in port.events_path.read_bytes().splitlines()];require(len(events)==2*len(port.ledger['calls']),'Ollama denominator differs');return {'native_row':row,'original_files':files,'view':{'schema':'public-train-provider-call-v1','id':row['id'],'slot':row['slot'],'request_digest':row['request_sha256'],'response_digest':row['response_sha256'],'native_status':row['status'],'successful':row['status']=='succeeded','originals_verified':failure is None,'verification_error':None if failure is None else type(failure).__name__,'known_tokens':usage['total_tokens'] if usage else None,'known_usage_scope':'ollama_reported_counts_and_durations','known_usage_binding_verified':usage is not None,'main_usage_incomplete':usage is None,'possible_initial_title_opportunities':0,'title_tokens':None,'all_opportunity_tokens':None,'settled_additional_charge_usd':None,'prompt_bytes':len((directory/'http-request.json').read_bytes()),'schema_bytes':len(canonical(c['schemas'][row['slot']]).encode()),'request_stream_bytes':None,'evidence_digest':record({'native_row':row,'original_files':files}).content_hash}}
