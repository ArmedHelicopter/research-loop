"""Bounded Messages HTTP TRAIN port; original bytes, no retries or CLI identity.

Credentials are loaded only at dispatch and never included in public configuration
or journals. Reported API tokens are not a price or settlement assertion.
"""
import hashlib
from contextlib import contextmanager
import http.client
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit

from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.model_port import _schema_witness, _validate_schema
from research_loop.ontology import ContractError, canonical

KIND = 'anthropic-messages-public-train-v1'
PREFIX = 'Return only a JSON object satisfying the output schema. No tools, browsing, files or evaluation material are available.\n'
FIELDS = {'schema','task','lock_digest','objective','slot','instruction','context','module_context','execution_feedback'}

def require(value, reason):
    if not value: raise ContractError(reason)

def sha(raw): return hashlib.sha256(raw).hexdigest()
def record(value): return FrozenRecord.from_dict(value)
def read(path): return json.loads(Path(path).read_bytes())
def write(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_bytes(canonical(value).encode()); temporary.replace(path)
def original(path, raw):
    with path.open('xb') as stream: stream.write(raw)


@contextmanager
def allocation_lock(path):
    try:
        with path.open('x') as stream: stream.write(str(os.getpid()))
    except FileExistsError as exc: raise ContractError('Messages allocator already in use') from exc
    try: yield
    finally: path.unlink()


def parse_response(raw, config, slot):
    body = json.loads(raw)
    require(body.get('type') == 'message' and body.get('role') == 'assistant'
        and body.get('model') in config['response_models'] and body.get('stop_reason') == 'end_turn',
        'API response identity or completion differs')
    blocks = body.get('content')
    require(type(blocks) is list and blocks and all(type(b) is dict and b.get('type') in ('text','thinking')
        and (type(b.get('text')) is str if b['type'] == 'text' else type(b.get('thinking')) is str)
        for b in blocks), 'only text and private thinking response blocks admitted')
    answer = record(json.loads(''.join(b['text'] for b in blocks if b['type'] == 'text')))
    _validate_schema(config['schemas'][slot], answer.data())
    usage = parse_usage(raw)
    require(usage is not None and usage['cache_usage_complete'] and usage['output_tokens'] <= config['slot_output_caps'][slot]
        and usage['total_tokens'] <= config['observed_main_token_cap'], 'API usage missing or over bound')
    return answer, usage


def parse_usage(raw):
    try:
        value = json.loads(raw)['usage']
        fields = ('input_tokens','output_tokens','cache_creation_input_tokens','cache_read_input_tokens')
        # Cache counters can be absent: retain unknown, never manufacture zero.
        usage = {key:value.get(key) for key in fields}
        if any(type(usage[k]) is not int or usage[k] < 0 for k in fields[:2]): return None
        if any(usage[k] is not None and (type(usage[k]) is not int or usage[k] < 0) for k in fields[2:]): return None
        usage['total_tokens'] = sum(v for v in usage.values() if v is not None)
        usage['cache_usage_complete'] = all(usage[k] is not None for k in fields[2:])
        return usage
    except (ValueError, KeyError, TypeError): return None


class AnthropicMessagesTrainModelPort:
    provider_kind = KIND

    def __init__(self, *, work_root, endpoint, model, response_models, credential_file,
                 schemas, max_calls, slot_output_caps, slot_input_byte_caps,
                 observed_main_token_cap, timeout_seconds=120, max_response_bytes=2097152):
        url = urlsplit(endpoint)
        require(url.scheme == 'https' or (url.scheme == 'http' and url.hostname == '127.0.0.1'),
                'HTTPS or explicit loopback test endpoint required')
        require(url.hostname and not url.username and not url.password and not url.query and not url.fragment
                and url.path.endswith('/v1/messages'), 'exact Messages endpoint required')
        require(type(model) is str and model and type(response_models) in (tuple,list) and response_models
                and all(type(v) is str and v for v in response_models) and len(set(response_models)) == len(response_models),
                'explicit model and exact response aliases required')
        require(type(observed_main_token_cap) is int and observed_main_token_cap > 1
                and type(max_calls) is int and max_calls > 0 and type(timeout_seconds) is int and 1 <= timeout_seconds <= 600
                and type(max_response_bytes) is int and 1024 <= max_response_bytes <= 16777216,
                'positive bounded allocation required')
        require(schemas and set(schemas) == set(slot_output_caps) == set(slot_input_byte_caps), 'exact slot budgets required')
        for slot, schema in schemas.items():
            require(type(slot) is str and slot.replace('_','').isalnum() and schema.get('type') == 'object', 'object slots required')
            _validate_schema(schema, _schema_witness(schema))
            require(type(slot_output_caps[slot]) is int and 0 < slot_output_caps[slot] < observed_main_token_cap
                    and type(slot_input_byte_caps[slot]) is int and slot_input_byte_caps[slot] > 0, 'positive slot bounds required')
        self.root = Path(work_root).resolve(); self.root.mkdir(parents=True, exist_ok=False)
        self.calls_root = self.root/'calls'; self.calls_root.mkdir()
        self.ledger_path = self.root/'ledger.json'; self.events_path = self.root/'events.jsonl'
        self.credential_file = Path(credential_file).resolve()
        self.model, self.effort, self.max_calls = model, 'thinking_disabled_requested', max_calls
        self.schemas = json.loads(canonical(schemas))
        self.slot_output_caps, self.slot_input_byte_caps = dict(slot_output_caps), dict(slot_input_byte_caps)
        self.observed_main_token_cap = observed_main_token_cap
        sources = [Path(__file__).with_name(name) for name in ('anthropic_train_provider.py','model_port.py',
            'contracts.py','train_provider.py','phase_provider.py','train_provider_preflight.py','train_controller.py')]
        sources.append(Path(__file__).parents[1]/'ontology.py')
        self.config = record({'schema':'anthropic-messages-train-port-v1','provider_kind':KIND,'domain':'TRAIN',
            'endpoint':endpoint,'model':model,'response_models':list(response_models),'auth_scheme':'bearer',
            'anthropic_version':'2023-06-01','temperature':0,'thinking':{'type':'disabled'},'stream':False,
            'max_retries':0,'tools':False,'max_calls':max_calls,'schemas':self.schemas,
            'slot_output_caps':self.slot_output_caps,'slot_input_byte_caps':self.slot_input_byte_caps,
            'observed_main_token_cap':observed_main_token_cap,'timeout_seconds':timeout_seconds,
            'max_response_bytes':max_response_bytes,'source_files':{str(p.resolve()):sha(p.read_bytes()) for p in sources}})
        self.ledger = {'config':self.config.data(),'calls':[],'tokens':0,'usage_incomplete':False}
        write(self.ledger_path, self.ledger); original(self.events_path, b'')

    def _event(self, value):
        raw = canonical(value).encode()+b'\n'
        with self.events_path.open('ab') as stream: stream.write(raw); stream.flush(); os.fsync(stream.fileno())

    def __call__(self, request):
        with allocation_lock(self.root/'allocator.lock'):
            return self._dispatch(request)

    def _dispatch(self, request):
        native_configuration(self)
        require(read(self.ledger_path) == self.ledger and not self.ledger['usage_incomplete'], 'API ledger closed or changed')
        for row in self.ledger['calls']: observation(self,row)
        require(type(request) is FrozenRecord and set(request.data()) == FIELDS, 'exact public request required')
        b = request.data(); slot = b['slot']
        require(b['schema'] == 'public-model-request-v1' and slot in self.schemas, 'public slot differs')
        DataIdentity.parse(b['task'].get('identity', {})).require_train()
        require(len(self.ledger['calls']) < self.max_calls, 'API allocation exhausted')
        config = self.config.data()
        prompt = PREFIX + canonical({'output_schema':self.schemas[slot], 'request':b})
        require(len(prompt.encode()) <= self.slot_input_byte_caps[slot], 'API prompt exceeds bound')
        body = {'model':self.model,'max_tokens':self.slot_output_caps[slot],'temperature':0,
                'thinking':{'type':'disabled'},'messages':[{'role':'user','content':prompt}]}
        number = len(self.ledger['calls'])+1; directory = self.calls_root/f'{number:04d}-{slot}'; directory.mkdir()
        original(directory/'request.json', request.encoded.encode())
        original(directory/'http-request.json', canonical(body).encode())
        row = {'id':number,'slot':slot,'request_sha256':request.content_hash,'status':'reserved',
               'response_sha256':None,'usage':None,'original_files':{}}
        self.ledger['calls'].append(row); self._event({'kind':'reserved','id':number,'request_digest':request.content_hash})
        write(self.ledger_path,self.ledger)
        connection = None; failure = None
        try:
            auth = read(self.credential_file)
            base = auth.get('base_url','').rstrip('/')
            require(config['endpoint'] in (base, base+'/v1/messages') and type(auth.get('token')) is str
                    and auth['token'] and '\n' not in auth['token'] and '\r' not in auth['token'], 'credential route differs')
            url = urlsplit(config['endpoint'])
            connection = (http.client.HTTPSConnection if url.scheme == 'https' else http.client.HTTPConnection)(
                url.hostname, url.port, timeout=config['timeout_seconds'])
            started = time.monotonic()
            connection.request('POST',url.path,body=(directory/'http-request.json').read_bytes(),headers={
                'Authorization':'Bearer '+auth['token'],'anthropic-version':'2023-06-01','Content-Type':'application/json'})
            sock = connection.sock
            response = connection.getresponse()
            original(directory/'http-status.json', canonical({'status':response.status,
                'content_type':response.getheader('Content-Type'),'redirect_followed':False}).encode())
            size = 0
            with (directory/'http-response.bin').open('xb') as stream:
                while True:
                    remaining = config['timeout_seconds'] - (time.monotonic()-started)
                    require(remaining > 0, 'API response deadline exceeded'); sock.settimeout(remaining)
                    chunk = response.read1(min(65536,config['max_response_bytes']+1-size))
                    if not chunk: break
                    stream.write(chunk); stream.flush(); size += len(chunk)
                    require(size <= config['max_response_bytes'], 'API response size exceeded')
            require(response.status == 200, 'API HTTP status rejected')
            answer, usage = parse_response((directory/'http-response.bin').read_bytes(), config, slot)
            original(directory/'response.json',answer.encoded.encode())
            row.update(status='succeeded',response_sha256=answer.content_hash,usage=usage)
        except Exception as exc:
            failure = exc
            raw = (directory/'http-response.bin').read_bytes() if (directory/'http-response.bin').exists() else b''
            row.update(status='unknown_or_failed',error_type=type(exc).__name__,usage=parse_usage(raw))
            self.ledger['usage_incomplete'] = True
        finally:
            if connection is not None: connection.close()
            row['original_files'] = {p.name:sha(p.read_bytes()) for p in sorted(directory.iterdir())}
            self.ledger['tokens'] += (row['usage'] or {}).get('total_tokens',0)
            self._event({'kind':'completed','row':row}); write(self.ledger_path,self.ledger)
        if failure is not None: raise ContractError('API attempt terminal; original evidence retained; no retry') from failure
        observation(self,row)
        return answer


def native_configuration(port):
    require(type(port) is AnthropicMessagesTrainModelPort and read(port.ledger_path)['config'] == port.config.data()
        == port.ledger['config'], 'API configuration drift')
    c = port.config.data()
    require(port.model == c['model'] and port.effort == 'thinking_disabled_requested' and port.max_calls == c['max_calls']
        and port.schemas == c['schemas'] and port.slot_output_caps == c['slot_output_caps']
        and port.slot_input_byte_caps == c['slot_input_byte_caps'] and port.observed_main_token_cap == c['observed_main_token_cap'],
        'API live policy drift')
    require(all(sha(Path(p).read_bytes()) == h for p,h in c['source_files'].items()), 'API source drift')
    return c


def configuration(port):
    c = native_configuration(port)
    return {'schema':'public-train-provider-config-v1','provider_kind':KIND,'model':port.model,
        'execution_mode':'thinking_disabled_requested','native_config':c,'native_config_digest':record(c).content_hash,
        'adapter_source_files':c['source_files'],'limits':{'main_opportunities':port.max_calls,
            'possible_initial_title_opportunities':0,'prompt_byte_caps':c['slot_input_byte_caps'],
            'schema_byte_caps':None,'request_envelope_byte_caps':None,'requested_output_token_caps':c['slot_output_caps'],
            'observed_main_token_cap':c['observed_main_token_cap'],'legacy_reported_token_limit':None,
            'lifetime_seconds':c['timeout_seconds'],'max_retries':0},
        'accounting_scope':'anthropic_messages_reported','title_and_all_opportunity_settlement':'not_applicable_cost_unknown'}


def validate_configuration_declaration(body, *, schemas):
    c, limits = body['native_config'], body['limits']
    require(c.get('schema') == 'anthropic-messages-train-port-v1' and c.get('provider_kind') == KIND
        and c.get('domain') == 'TRAIN' and body.get('model') == c.get('model')
        and body.get('execution_mode') == 'thinking_disabled_requested'
        and c.get('thinking') == {'type':'disabled'} and c.get('temperature') == 0
        and c.get('stream') is False and c.get('tools') is False and c.get('max_retries') == 0
        and c.get('auth_scheme') == 'bearer' and c.get('anthropic_version') == '2023-06-01'
        and body.get('accounting_scope') == 'anthropic_messages_reported'
        and body.get('title_and_all_opportunity_settlement') == 'not_applicable_cost_unknown', 'Messages declaration policy differs')
    require(type(c.get('timeout_seconds')) is int and 1 <= c['timeout_seconds'] <= 600
        and limits.get('lifetime_seconds') == c['timeout_seconds'] and limits.get('max_retries') == 0
        and limits.get('possible_initial_title_opportunities') == 0
        and type(c.get('response_models')) is list and c['response_models']
        and all(type(v) is str and v for v in c['response_models']), 'Messages allocation differs')
    for key, native in (('prompt_byte_caps','slot_input_byte_caps'),('requested_output_token_caps','slot_output_caps')):
        values = limits.get(key)
        require(type(values) is dict and set(values) == set(schemas) and values == c.get(native)
            and all(type(v) is int and v > 0 for v in values.values()), 'Messages slot bounds differ')
    require(type(c.get('observed_main_token_cap')) is int
        and limits.get('observed_main_token_cap') == c['observed_main_token_cap']
        and all(v < c['observed_main_token_cap'] for v in c['slot_output_caps'].values()), 'Messages observed bound differs')


def observation(port,row,*,failure=None):
    directory = port.calls_root/f'{row["id"]:04d}-{row["slot"]}'
    files = {str(p):sha(p.read_bytes()) for p in sorted(directory.iterdir())}
    raw = (directory/'http-response.bin').read_bytes() if (directory/'http-response.bin').exists() else b''
    usage = parse_usage(raw)
    if failure is None:
        require({Path(p).name:h for p,h in files.items()} == row['original_files'], 'API original bytes drift')
        public = record(read(directory/'request.json')); c = native_configuration(port)
        require(public.content_hash == row['request_sha256'] and public.data()['slot'] == row['slot'], 'API original subject drift')
        expected = {'model':c['model'],'max_tokens':c['slot_output_caps'][row['slot']],'temperature':0,
            'thinking':{'type':'disabled'},'messages':[{'role':'user','content':PREFIX+canonical({
                'output_schema':c['schemas'][row['slot']], 'request':public.data()})}]}
        require(read(directory/'http-request.json') == expected and row['usage'] == usage, 'API request or usage drift')
        events = [json.loads(line) for line in port.events_path.read_bytes().splitlines()]
        require(len(events) == 2*len(port.ledger['calls']), 'API journal denominator differs')
        for i,r in enumerate(port.ledger['calls']):
            require(events[2*i] == {'kind':'reserved','id':r['id'],'request_digest':r['request_sha256']}
                and events[2*i+1] == {'kind':'completed','row':r}, 'API append-only journal drift')
        if row['status'] == 'succeeded':
            require(read(directory/'http-status.json')['status'] == 200, 'API HTTP success absent')
            answer,_ = parse_response(raw,c,row['slot'])
            require(answer.content_hash == row['response_sha256'] and (directory/'response.json').read_bytes() == answer.encoded.encode(),
                'API response consumption drift')
    successful = failure is None and row['status'] == 'succeeded'
    view = {'schema':'public-train-provider-call-v1','id':row['id'],'slot':row['slot'],
        'request_digest':row['request_sha256'],'response_digest':row['response_sha256'] if successful else None,
        'native_status':row['status'],'successful':successful,'originals_verified':failure is None,
        'verification_error':None if failure is None else type(failure).__name__,
        'known_tokens':usage['total_tokens'] if usage else None,'known_usage_scope':'anthropic_messages_reported',
        'known_usage_binding_verified':successful,'main_usage_incomplete':not successful,
        'possible_initial_title_opportunities':0,'title_tokens':None,'all_opportunity_tokens':None,
        'settled_additional_charge_usd':None,'prompt_bytes':(directory/'http-request.json').stat().st_size,
        'schema_bytes':len(canonical(port.schemas[row['slot']]).encode()),'request_stream_bytes':None,
        'evidence_digest':record({'native_row':row,'original_files':files}).content_hash}
    return {'native_row':row,'original_files':files,'view':view}
