"""Closed public TRAIN provider evidence adapters; no controller admission changes."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import TypeAlias

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.grok_train_solver import GrokTrainModelPort, _replay_native_call
from research_loop.modular.grok_headless_train_solver import GrokHeadlessTrainModelPort
from research_loop.modular import train_provider_headless as headless
from research_loop.modular.grok_acp_transport import known_usage, run_native_train, TRAIN_OPPORTUNITY_CONTRACT, MODEL
from research_loop.modular.model_port import (CodexModelPort, _events, _usage, _tool_events,
    _context_diagnostics, _base_context_bytes, _validate_schema)
from research_loop.ontology import ContractError, canonical

_PROMPT = 'Return only JSON conforming to the supplied schema. Tools, browsing, filesystem access, and evaluation material are unavailable.\n'


def _sha(raw): return hashlib.sha256(raw).hexdigest()
def _record(value): return FrozenRecord.from_dict(value)
def _read(path): return json.loads(Path(path).read_bytes())
def _require(value, message):
    if not value: raise ContractError(message)
def _write(path, value):
    path=Path(path);temp=path.with_suffix('.tmp')
    temp.write_bytes(canonical(value).encode('utf-8'));temp.replace(path)
def _exclusive(path, raw):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as stream: stream.write(raw)


def _original_files(root, grok):
    # Do not traverse the native login home or hash opaque login/body files.
    names=(('request.private.json','prompt.private.txt','schema.private.json',
        'response.private.json','observer-receipt.private.json','reservation.private.json',
        'native-home/config.toml','native-private/requests.private.jsonl',
        'native-private/stdout.private.jsonl','native-private/stderr.private.txt',
        'native-private/observer-receipt.json') if grok else
        ('prompt.txt','schema.json','output.json','events.jsonl','stderr.txt'))
    return {str(root/name):_sha((root/name).read_bytes()) for name in names if (root/name).is_file()}


def _native_config(backend):
    if type(backend) is GrokHeadlessTrainModelPort:
        return headless.configuration(backend)
    config=_read(backend.ledger_path)['config']
    _require(config==backend.ledger['config'], 'native configuration memory/disk drift')
    _require(config['model']==backend.model and config['schemas']==backend.schemas
             and config['max_calls']==backend.max_calls, 'live provider configuration drift')
    if type(backend) is GrokTrainModelPort:
        _require(backend.native_invoke is run_native_train, 'default native TRAIN entry required')
        _require(config['provider_kind']==backend.provider_kind and config['executable']==backend.executable
            and config['slot_output_caps']==backend.slot_output_caps
            and config['slot_input_byte_caps']==backend.slot_input_byte_caps
            and config['observed_main_token_cap']==backend.observed_main_token_cap
            and config['frozen_files']==backend.frozen_files, 'native Grok configuration drift')
        _require(config['private_home']==str(backend.private_home)
            and config['private_profile_root']==str(backend.private_profile)
            and config['public_cwd_root']==str(backend.public_cwd)
            and config['opportunity_contract']==TRAIN_OPPORTUNITY_CONTRACT and backend.model==MODEL
            and config['included_only'] is True and config['api_key_route_permitted'] is False
            and config['max_retries']==0 and config['title_opportunities_per_main']==1
            and config['title_usage_and_all_call_totals']=='unknown', 'native launch or billing gate drift')
        _require(_sha(Path(backend.executable).read_bytes())==config['executable_sha256'], 'native executable drift')
        _require(all(_sha(Path(p).read_bytes())==h for p,h in config['frozen_files'].items()), 'native source drift')
    else:
        _require(not backend.mock_context and backend.frozen_base_context is not None
            and backend.policy_data==backend.frozen_base_context.data()
            and backend.policy_data['status']=='REVIEWED', 'reviewed original Codex context required')
        _require(config['max_tokens']==backend.max_tokens and config['effort']==backend.effort
            and config['timeout_seconds']==backend.timeout_seconds
            and config['context_policy']['sha256']==backend.frozen_base_context.sha256, 'Codex budget/context drift')
        _require(config['executable']==backend.executable and config['shared_argv']==backend.shared
            and config['fixed_cwd']==str(backend.fixed_cwd)
            and config['context_mode']=='reviewed'
            and config['context_policy']['binding']==backend.context_binding
            and config['context_policy']['allowed_startup_notices']==backend.allowed_startup_notices
            and config['environment_sha256']==_sha(canonical(backend.environment).encode())
            and backend._ledger_purpose is None, 'public Codex launch contract drift')
        backend._verify_context_binding()  # Read-only binding check; never starts a context probe.
    return config


def _configuration(backend):
    native=_native_config(backend);grok=type(backend) in (GrokTrainModelPort,GrokHeadlessTrainModelPort)
    sources=[Path(__file__),Path(__file__).with_name('contracts.py'),
        Path(__file__).with_name('grok_train_solver.py'),Path(__file__).with_name('grok_acp_transport.py'),
        Path(__file__).with_name('model_port.py'),Path(__file__).parents[1]/'ontology.py']
    if type(backend) is GrokHeadlessTrainModelPort:
        sources.extend(Path(__file__).with_name(name) for name in (
            'train_provider_headless.py','grok_headless_train_solver.py','grok_headless_transport.py','grok_cli_protocol.py'))
    return {'schema':'public-train-provider-config-v1','provider_kind':
        backend.provider_kind if grok else 'codex-cli-public-train-v1',
        'model':backend.model,'execution_mode':backend.effort,'native_config':native,
        'native_config_digest':_record(native).content_hash,
        'adapter_source_files':{str(path.resolve()):_sha(path.read_bytes()) for path in sources},
        'limits':{'main_opportunities':backend.max_calls,
            'possible_initial_title_opportunities':backend.max_calls if grok else None,
            'prompt_byte_caps':backend.slot_input_byte_caps if grok else None,
            'schema_byte_caps':None,'request_envelope_byte_caps':None,
            'requested_output_token_caps':backend.slot_output_caps if grok else None,
            'observed_main_token_cap':backend.observed_main_token_cap if grok else None,
            'legacy_reported_token_limit':None if grok else backend.max_tokens,
            'lifetime_seconds':60 if grok else backend.timeout_seconds,'max_retries':0 if grok else None},
        'accounting_scope':'native_main' if grok else 'codex_turn_completed',
        'title_and_all_opportunity_settlement':'unknown' if grok else 'not_reported_by_legacy_contract'}


def _verify_call(backend, row, ledger):
    """Return checked originals and reported usage; failed attempts are never eligible."""
    if type(backend) is GrokHeadlessTrainModelPort:
        return headless.observation(backend,row)
    number=row['id'];slot=row['slot'];grok=type(backend) is GrokTrainModelPort
    root=(backend.calls_root if grok else backend.call_root)/f'{number:04d}-{slot}'
    prompt=root/('prompt.private.txt' if grok else 'prompt.txt')
    schema=root/('schema.private.json' if grok else 'schema.json')
    prompt_raw=prompt.read_bytes();schema_raw=schema.read_bytes()
    # Legacy Codex writes its prompt in text mode on Windows but records the
    # original LF input hash. Preserve that meaning and additionally seal bytes.
    prompt_text=prompt_raw.decode('utf-8') if grok else prompt.read_text(encoding='utf-8')
    _require(_sha(prompt_text.encode())==row['prompt_sha256' if grok else 'prompt_hash'], 'original prompt drift')
    _require(_sha(schema_raw)==row['schema_sha256' if grok else 'schema_hash'], 'original schema drift')
    _require(json.loads(schema_raw)==backend.schemas[slot], 'original schema/config mismatch')
    _require(prompt_text.startswith(_PROMPT), 'original public request prefix missing')
    request=_record(json.loads(prompt_text[len(_PROMPT):]))
    request_hash=row['request_sha256' if grok else 'request_hash']
    _require(request.content_hash==request_hash and request.data().get('slot')==slot, 'original request/slot drift')
    response_hash=row.get('response_sha256' if grok else 'output_hash');usage=None;usage_bound=False
    originals=_original_files(root,grok)
    if grok:
        _require(row['native_private_path']==str(root/'native-private')
            and row['reservation_path']==str(root/'reservation.private.json'), 'native original path drift')
        _require((root/'request.private.json').read_bytes()==request.encoded.encode(), 'native request bytes drift')
        receipt_path=root/'observer-receipt.private.json'
        if receipt_path.exists():
            receipt=_read(receipt_path);native=Path(row['native_private_path'])
            _require(_sha(receipt_path.read_bytes())==row['native_receipt_sha256'], 'native observer hash drift')
            _require(_read(native/'observer-receipt.json')==receipt, 'native observer substitution')
            _require(_sha((native/'stdout.private.jsonl').read_bytes())==receipt['private_stream_sha256'], 'native stdout drift')
            usage=known_usage(receipt.get('known_usage'))
            usage_bound=receipt.get('known_usage_binding_verified') is True
            _require(receipt.get('known_usage')==row.get('known_main_usage'), 'native reported usage drift')
            candidates=_native_usage_candidates(native/'stdout.private.jsonl')
            _require(usage is None or usage in candidates, 'native reported usage has no raw frame')
            if usage is None and row['status']!='succeeded' and len(candidates)==1:
                usage=candidates[0]
                usage_bound=False  # Scalar recovery does not repair a failed frame.
            if row['status']=='succeeded':
                _require(receipt['accepted'] is True and receipt['requested_model']==backend.model, 'native success admission missing')
                _require(_sha(Path(row['reservation_path']).read_bytes())==row['reservation_sha256'], 'native reservation drift')
                _require(_sha((root/'response.private.json').read_bytes())==response_hash, 'native response bytes drift')
                _replay_native_call(backend,row,root,receipt)
        else:
            _require(row['status']!='succeeded' and row.get('known_main_usage') is None, 'successful native receipt absent')
    else:
        _require(row['provider']=={'id':'codex-cli','model':backend.model}, 'Codex provider mismatch')
        config=ledger['config'];expected_argv=[backend.executable,'exec',*backend.shared,'--ephemeral','--skip-git-repo-check',
            '--json','--output-schema',str(schema),'-o',str(root/'output.json'),'-']
        _require(row['argv']==expected_argv and row['cwd']==config['fixed_cwd']
            and row['environment_sha256']==config['environment_sha256']
            and row['context_policy_sha256']==config['context_policy']['sha256'], 'Codex launch binding drift')
        probe=ledger['context_probes'][row['context_probe']-1];raw=Path(probe['raw_path']).read_bytes()
        originals[probe['raw_path']]=_sha(raw)
        _require(_sha(raw)==probe['raw_sha256'] and probe['status']=='frozen_matched'
            and probe['exit_code']==0 and probe['argv']==[backend.executable,'debug','prompt-input',*backend.shared]
            and probe['cwd']==config['fixed_cwd'] and probe['environment_sha256']==config['environment_sha256']
            and _sha(_base_context_bytes(raw))==backend.context_binding['context_digest'], 'Codex original context probe drift')
        events_path=root/'events.jsonl'
        if events_path.exists():
            raw=events_path.read_bytes();events=_events(raw.decode('utf-8'));usage=_usage(events)
            usage_bound=usage is not None
            faults,notices=_context_diagnostics(events,backend.allowed_notice_messages)
            _require(_sha(raw)==row['events_hash'] and _sha((root/'stderr.txt').read_bytes())==row['stderr_hash'], 'Codex raw stream drift')
            _require(usage==row['usage'] and _tool_events(events)==row['tool_events']
                and faults==row['context_faults'] and notices==row['reviewed_startup_notices'], 'Codex original accounting/context drift')
            if row['status']=='succeeded':
                _require(row['exit_code']==0 and usage is not None and not faults and not row['tool_events'], 'Codex failed result cannot be consumed')
                output=_record(_read(root/'output.json'));_validate_schema(backend.schemas[slot],output.data())
                _require(output.content_hash==response_hash, 'Codex original response drift')
        else:
            _require(row['status']!='succeeded' and row.get('usage') is None, 'successful Codex events absent')
    known=usage['totalTokens' if grok else 'total_tokens'] if usage is not None else None
    view={'schema':'public-train-provider-call-v1','id':number,'slot':slot,'request_digest':request_hash,
        'response_digest':response_hash,'native_status':row['status'],'successful':row['status']=='succeeded',
        'originals_verified':True,'verification_error':None,
        'known_tokens':known,'known_usage_scope':'native_main' if grok else 'codex_turn_completed',
        'known_usage_binding_verified':usage_bound,
        'main_usage_incomplete':bool(usage is None or not usage_bound or (grok and usage.get('usageIsIncomplete'))),
        'possible_initial_title_opportunities':1 if grok else None,'title_tokens':None,
        'all_opportunity_tokens':None,'settled_additional_charge_usd':None,
        'prompt_bytes':len(prompt_raw),'schema_bytes':len(schema_raw),
        'request_stream_bytes':(root/'native-private/requests.private.jsonl').stat().st_size if grok and (root/'native-private/requests.private.jsonl').exists() else None,
        'evidence_digest':_record({'native_row':row,'original_files':originals}).content_hash}
    return {'native_row':row,'original_files':originals,'view':view}


def _native_usage_candidates(path):
    candidates=[]
    for raw in Path(path).read_bytes().splitlines():
        try:
            frame=json.loads(raw)
            for branch in (('result','_meta','usage'),('params','update','usage'),('error','data','promptUsage')):
                candidate=frame
                for key in branch:
                    candidate=candidate.get(key) if isinstance(candidate,dict) else None
                usage=known_usage(candidate)
                if usage is not None and usage not in candidates:candidates.append(usage)
        except (ValueError,AttributeError):
            continue
    return candidates


def _failed_observation(backend,row,error):
    """Capture even unverifiable attempts; only independently parsed scalar usage
    survives. This record is never a response or a successful provenance claim.
    """
    if type(backend) is GrokHeadlessTrainModelPort:
        return headless.observation(backend,row,failure=error)
    grok=type(backend) is GrokTrainModelPort
    root=(backend.calls_root if grok else backend.call_root)/f'{row["id"]:04d}-{row["slot"]}'
    originals=_original_files(root,grok)
    usage=None
    try:
        if grok:
            candidates=_native_usage_candidates(root/'native-private/stdout.private.jsonl')
            usage=candidates[0] if len(candidates)==1 else None
        else:usage=_usage(_events((root/'events.jsonl').read_text(encoding='utf-8')))
    except (OSError,ValueError):pass
    return {'native_row':row,'original_files':originals,'view':{
        'schema':'public-train-provider-call-v1','id':row['id'],'slot':row['slot'],
        'request_digest':row.get('request_sha256' if grok else 'request_hash'),
        'response_digest':None,'native_status':row['status'],'successful':False,
        'originals_verified':False,'verification_error':type(error).__name__,
        'known_tokens':usage['totalTokens' if grok else 'total_tokens'] if usage else None,
        'known_usage_scope':'native_main' if grok else 'codex_turn_completed',
        'known_usage_binding_verified':False,
        'main_usage_incomplete':True,'possible_initial_title_opportunities':1 if grok else None,
        'title_tokens':None,'all_opportunity_tokens':None,'settled_additional_charge_usd':None,
        'prompt_bytes':None,'schema_bytes':None,'request_stream_bytes':None,
        'evidence_digest':_record({'native_row':row,'original_files':originals}).content_hash}}


class _TrainProvider:
    """Only the concrete wrappers below may own a provider session."""
    def __init__(self, backend):
        wanted={CodexTrainProvider:CodexModelPort,GrokTrainProvider:GrokTrainModelPort,
            GrokHeadlessTrainProvider:GrokHeadlessTrainModelPort}.get(type(self))
        _require(wanted is not None and type(backend) is wanted, 'exact admitted public TRAIN backend required')
        self.backend=backend;self.root=backend.root/'train-provider-v1';self.root.mkdir(exist_ok=True)
        self._last_verified_accounting=None
        self.state_path=self.root/'state.json';config=_configuration(backend)
        if self.state_path.exists():
            self.state=_read(self.state_path);_require(self.state['configuration']==config, 'provider wrapper configuration changed')
            self.inspect()
        else:
            _require(not backend.ledger['calls'], 'new adapter requires a fresh backend; no imported callable assertions')
            self.state={'schema':'public-train-provider-state-v1','configuration':config,'terminal_fault':False,'reason':None,'calls':[]}
            _write(self.state_path,self.state)
        self._remember_verified_accounting(self.inspect())

    def _remember_verified_accounting(self,calls):
        """Pin historical scalars only after a complete original inspection."""
        rows=[c.data() for c in calls];grok=type(self) in (GrokTrainProvider,GrokHeadlessTrainProvider)
        record=_record({'schema':'public-train-provider-observed-accounting-v1',
            'configuration_digest':_record(self.state['configuration']).content_hash,
            'observed_main_opportunities':len(rows),
            'known_reported_tokens':sum(c['known_tokens'] or 0 for c in rows),
            'known_usage_scope':'native_main' if grok else 'codex_turn_completed',
            'observed_unknown_main_opportunities':sum(c['main_usage_incomplete'] for c in rows),
            'possible_initial_title_opportunities':len(rows) if grok else None})
        path=self.root/('observed-accounting-'+record.content_hash+'.json')
        if not path.exists():_exclusive(path,record.encoded.encode())
        _require(path.read_bytes()==record.encoded.encode(), 'observed accounting checkpoint drift')
        self._last_verified_accounting=(path,record)

    def failure_snapshot(self) -> FrozenRecord:
        """Non-eligible terminal accounting; never inspect or retry the backend.

        A retained checkpoint says what was observed before the fault. It does
        not assert that any current original is still valid, or that no further
        opportunity occurred. It contains no request/response or eligible view.
        """
        _require(type(self) in (CodexTrainProvider,GrokTrainProvider,GrokHeadlessTrainProvider), 'closed provider required')
        durable=_read(self.state_path)
        _require(durable.get('terminal_fault') is True and self.state.get('terminal_fault') is True,
            'existing durable terminal fault required')
        checkpoint=self._last_verified_accounting;historical=None;binding=None
        if checkpoint is not None:
            path,record=checkpoint
            if path.is_file() and path.read_bytes()==record.encoded.encode():
                historical=record.data();binding={'path':str(path),'sha256':_sha(path.read_bytes())}
        faults={str(self.root/name):_sha((self.root/name).read_bytes())
            for name in ('fault-state.json','fault-native-ledger.json') if (self.root/name).is_file()}
        body={'schema':'public-train-provider-terminal-snapshot-v1',
            'terminal_fault':True,'score_eligible':False,'current_originals_verified':False,
            'reason':durable.get('reason'),'historical_observation':historical,
            'historical_observation_binding':binding,'preserved_fault_files':faults,
            'observed_main_opportunities_lower_bound':None if historical is None else historical['observed_main_opportunities'],
            'known_reported_tokens_lower_bound':None if historical is None else historical['known_reported_tokens'],
            'unknown_unobserved_opportunities':True,'current_main_usage_complete':False,
            'total_main_opportunities':None,'total_main_tokens':None,
            'title_tokens':None,'all_opportunity_tokens':None,'settled_additional_charge_usd':None}
        record=_record(body);path=self.root/('terminal-snapshot-'+record.content_hash+'.json')
        if not path.exists():_exclusive(path,record.encoded.encode())
        _require(path.read_bytes()==record.encoded.encode(), 'terminal snapshot bytes differ')
        return record

    def _poison(self, reason):
        # Keep pre-stop disk evidence even if the fault is memory/disk mismatch.
        # Stopping must not silently replace the only copy of a corrupt ledger.
        for source,name in ((self.state_path,'fault-state.json'),(self.backend.ledger_path,'fault-native-ledger.json')):
            target=self.root/name
            if source.exists() and not target.exists():_exclusive(target,source.read_bytes())
        self.state['terminal_fault']=True;self.state['reason']=reason;_write(self.state_path,self.state)
        self.backend.ledger['usage_incomplete']=True;_write(self.backend.ledger_path,self.backend.ledger)

    def configuration(self) -> FrozenRecord:
        self.inspect();return _record(self.state['configuration'])

    def inspect_configuration_and_calls(self) -> tuple[FrozenRecord, tuple[FrozenRecord, ...]]:
        """One fresh pass for callers that need both configuration and calls.

        This is an immutable local observation, not a seal or scoring authority.
        A subsequent call always inspects every original again; nothing is
        cached between verification passes.
        """
        calls = self.inspect()
        return _record(self.state['configuration']), calls

    def inspect(self) -> tuple[FrozenRecord, ...]:
        """Read-only successful/failed evidence audit; never promotes failed output."""
        try:
            _require(_read(self.state_path)==self.state, 'adapter state bytes changed')
            _require(_configuration(self.backend)==self.state['configuration'], 'provider configuration drift')
            ledger=_read(self.backend.ledger_path)
            _require(ledger==self.backend.ledger, 'original provider ledger memory/disk mismatch')
            _require(len(ledger['calls'])==len(self.state['calls']), 'unobserved native call or truncated ledger')
            for number,(row,saved) in enumerate(zip(ledger['calls'],self.state['calls'],strict=True),1):
                _require(row['id']==number and row==saved['native_row'], 'original call reordered or substituted')
                if saved['view']['originals_verified']:
                    actual=_verify_call(self.backend,row,ledger)
                    _require(actual==saved, 'original evidence changed after observation')
                else:
                    _require(self.state['terminal_fault'] and not saved['view']['successful'], 'unchecked call cannot become eligible')
                    actual=_failed_observation(self.backend,row,ContractError())
                    _require(actual['original_files']==saved['original_files']
                        and actual['view']['known_tokens']==saved['view']['known_tokens'], 'failed-attempt raw evidence changed')
            return tuple(_record(entry['view']) for entry in self.state['calls'])
        except Exception as exc:
            self._poison('provenance_fault')
            raise ContractError('provider provenance fault; dispatch closed') from exc

    def terminal(self) -> bool:
        self.inspect();return bool(self.state['terminal_fault'] or self.backend.ledger['usage_incomplete'])

    def calls_since(self,cursor: int=0) -> tuple[FrozenRecord, ...]:
        _require(type(cursor) is int and 0<=cursor<=len(self.state['calls']), 'invalid provider cursor')
        return self.inspect()[cursor:]

    def usage(self) -> FrozenRecord:
        calls=self.inspect();grok=type(self) in (GrokTrainProvider,GrokHeadlessTrainProvider)
        rows=[c.data() for c in calls];known=sum(c['known_tokens'] or 0 for c in rows)
        return _record({'schema':'public-train-provider-usage-v1','main_opportunities':len(rows),
            'known_reported_tokens':known,'known_usage_scope':'native_main' if grok else 'codex_turn_completed',
            'legacy_ledger_reported_tokens':(self.backend.ledger['known_main_tokens']
                if type(self) is GrokHeadlessTrainProvider else self.backend.ledger['tokens']),
            'unknown_main_opportunities':sum(c['main_usage_incomplete'] for c in rows),
            'possible_initial_title_opportunities':len(rows) if grok else None,'title_tokens':None,
            'all_opportunity_tokens':None,'settled_additional_charge_usd':None,
            'terminal_fault':bool(self.state['terminal_fault'] or self.backend.ledger['usage_incomplete'])})

    def call(self, request: FrozenRecord) -> FrozenRecord:
        _require(type(request) is FrozenRecord, 'frozen public request required')
        self.inspect();_require(not self.terminal(), 'provider is terminal')
        _require(len(self.state['calls'])<self.backend.max_calls, 'provider opportunity allocation exhausted')
        response=None;failure=None
        try: response=self.backend(request)
        except Exception as exc: failure=exc
        try:
            ledger=_read(self.backend.ledger_path)
            _require(ledger==self.backend.ledger and ledger['calls'][:len(self.state['calls'])]==[e['native_row'] for e in self.state['calls']], 'native call altered previous prefix')
            rows=ledger['calls'][len(self.state['calls']):]
            _require(len(rows)<=1, 'one public request created multiple native attempts')
            for row in rows:
                try:
                    entry=_verify_call(self.backend,row,ledger)
                    _require(entry['view']['request_digest']==request.content_hash, 'backend dispatched a foreign request')
                except Exception as exc:
                    entry=_failed_observation(self.backend,row,exc)
                    failure=failure or exc
                self.state['calls'].append(entry)
            snapshot=self.root/f'ledger-{len(self.state["calls"]):04d}.json'
            if not snapshot.exists():_exclusive(snapshot,self.backend.ledger_path.read_bytes())
            _write(self.state_path,self.state)
            if failure is not None or not rows or not rows[0]['status']=='succeeded':
                self._poison('backend_failure')
                self._remember_verified_accounting(self.inspect())
                raise ContractError('provider attempt failed; original evidence retained') from failure
            _require(type(response) is FrozenRecord and response.content_hash==self.state['calls'][-1]['view']['response_digest'], 'returned response differs from originals')
            self._remember_verified_accounting(self.inspect());return response
        except Exception as exc:
            self._poison('terminal_call_failure')
            raise ContractError('provider call is terminal; inspect retained evidence') from exc

    __call__=call

    def seal(self,path: Path,*,prefix: int | None=None) -> FrozenTrainProviderLedgerV2:
        self.inspect();count=len(self.state['calls']) if prefix is None else prefix
        _require(type(count) is int and 0<=count<=len(self.state['calls']), 'invalid seal prefix')
        body={'schema':'frozen-train-provider-ledger-v2','configuration':self.state['configuration'],
            'calls':self.state['calls'][:count],'original_ledger_path':str(self.backend.ledger_path),
            'prefix_length':count,'terminal_at_seal':self.terminal()}
        record=_record(body);_exclusive(path,record.encoded.encode('utf-8'))
        return FrozenTrainProviderLedgerV2(Path(path),record,self)


class CodexTrainProvider(_TrainProvider):
    """Checked wrapper over an actual reviewed CodexModelPort."""


class GrokTrainProvider(_TrainProvider):
    """Checked wrapper over an actual native GrokTrainModelPort."""


class GrokHeadlessTrainProvider(_TrainProvider):
    """Checked wrapper over the distinct headless Grok TRAIN originals."""


TrainProvider: TypeAlias = CodexTrainProvider | GrokTrainProvider | GrokHeadlessTrainProvider


def wrap_train_provider(backend: CodexModelPort | GrokTrainModelPort | GrokHeadlessTrainModelPort) -> TrainProvider:
    if type(backend) is CodexModelPort:return CodexTrainProvider(backend)
    if type(backend) is GrokTrainModelPort:return GrokTrainProvider(backend)
    if type(backend) is GrokHeadlessTrainModelPort:return GrokHeadlessTrainProvider(backend)
    raise ContractError('unadmitted provider type; callable assertions are not evidence')


@dataclass(frozen=True)
class FrozenTrainProviderLedgerV2:
    path: Path
    record: FrozenRecord
    provider: TrainProvider

    def verify_originals(self) -> FrozenRecord:
        try:return self._verify_originals()
        except Exception as exc:
            if type(self.provider) in (CodexTrainProvider,GrokTrainProvider,GrokHeadlessTrainProvider):self.provider._poison('sealed_provenance_fault')
            raise ContractError('sealed provider provenance fault; dispatch closed') from exc

    def _verify_originals(self):
        _require(type(self) is FrozenTrainProviderLedgerV2 and type(self.provider) in (CodexTrainProvider,GrokTrainProvider,GrokHeadlessTrainProvider), 'typed provider seal required')
        _require(self.path.read_bytes()==self.record.encoded.encode('utf-8'), 'sealed provider record drift')
        b=self.record.data();self.provider.inspect()
        # inspect() already bound the in-memory state and native ledger to their
        # current original bytes. Derive eligibility from that same observation;
        # terminal() would immediately replay the identical original set again.
        terminal=bool(self.provider.state['terminal_fault'] or self.provider.backend.ledger['usage_incomplete'])
        _require(b['schema']=='frozen-train-provider-ledger-v2' and b['configuration']==self.provider.state['configuration']
            and b['original_ledger_path']==str(self.provider.backend.ledger_path)
            and b['prefix_length']==len(b['calls']) and b['calls']==self.provider.state['calls'][:b['prefix_length']], 'sealed original prefix differs')
        success=bool(b['calls']) and all(c['view']['originals_verified'] and c['view']['successful'] and not c['view']['main_usage_incomplete'] for c in b['calls'])
        return _record({'schema':'train-provider-seal-verification-v1','seal_digest':self.record.content_hash,
            'originals_verified':True,'successful_prefix':success,
            'score_eligible':success and not b['terminal_at_seal'] and not terminal,
            'later_calls':len(self.provider.state['calls'])-b['prefix_length']})

    def bind_events(self,events,*,expected_call_ids: tuple[int, ...] | None=None,
                    require_eligible: bool=True) -> tuple[int, ...]:
        try:return self._bind_events(events,expected_call_ids=expected_call_ids,require_eligible=require_eligible)
        except Exception as exc:
            if type(self.provider) in (CodexTrainProvider,GrokTrainProvider,GrokHeadlessTrainProvider):self.provider._poison('runtime_binding_fault')
            raise ContractError('runtime provider binding fault; dispatch closed') from exc

    def _bind_events(self,events,*,expected_call_ids,require_eligible):
        _require(type(require_eligible) is bool, 'eligibility mode must be an explicit bool')
        _require(expected_call_ids is None or (type(expected_call_ids) is tuple
            and all(type(number) is int and number>0 for number in expected_call_ids)
            and all(a<b for a,b in zip(expected_call_ids,expected_call_ids[1:]))), 'immutable strictly ordered call IDs required')
        verified=self.verify_originals().data()
        _require(not require_eligible or verified['score_eligible'], 'terminal or failed evidence is not score-eligible')
        calls=self.record.data()['calls'];used=[];pending=None
        if expected_call_ids is not None:
            _require(set(expected_call_ids)<=set(c['view']['id'] for c in calls), 'declared call ID is outside sealed prefix')
        for event in events:
            if event['stage']=='model_request':
                _require(pending is None or not pending['successful'], 'successful original response omitted from runtime')
                request=_record(event['data']['request'])
                if expected_call_ids is not None:
                    _require(len(used)<len(expected_call_ids), 'runtime exceeds declared call span')
                    wanted=expected_call_ids[len(used)]
                    matches=[c['view'] for c in calls if c['view']['id']==wanted and c['view']['request_digest']==request.content_hash]
                else:
                    matches=[c['view'] for c in calls if c['view']['request_digest']==request.content_hash
                        and c['view']['id']>(used[-1] if used else 0)]
                _require(matches, 'request lacks an ordered sealed original call')
                pending=matches[0];used.append(pending['id'])
                _require(pending['slot']==request.data()['slot'], 'sealed original slot mismatch')
            elif event['stage']=='model_response':
                data=event['data']
                _require(pending is not None and pending['request_digest']==data['request_digest'], 'duplicate or foreign runtime response')
                _require(pending['successful'] and _record(data['response']).content_hash==pending['response_digest'], 'runtime response differs from original provider')
                pending=None
        _require(pending is None or not pending['successful'], 'successful original response omitted from runtime')
        _require(expected_call_ids is None or tuple(used)==expected_call_ids, 'runtime omitted a declared original call')
        _require(used or not require_eligible, 'no runtime requests bound for eligibility')
        return tuple(used)
