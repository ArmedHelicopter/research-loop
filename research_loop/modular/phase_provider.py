"""Versioned TRAIN phase accounting over closed, original-evidence providers.

Legacy Codex helpers and ledger schemas are deliberately not interpreted here.
One session partitions every actual call into an ordered, immutable scope. A
history prefix remains replayable after target calls append to the session.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.grok_acp_transport import TRAIN_OPPORTUNITY_CONTRACT
from research_loop.modular.grok_headless_transport import HEADLESS_TRAIN_TIMEOUT_MAX_SECONDS
from research_loop.modular.train_provider import (
    CodexTrainProvider, GrokTrainProvider, GrokHeadlessTrainProvider, FrozenTrainProviderLedgerV2,
    _validate_event_binding_arguments)
from research_loop.ontology import ContractError

PROVIDERS = (CodexTrainProvider, GrokTrainProvider, GrokHeadlessTrainProvider)


def _require(value, message):
    if not value: raise ContractError(message)


def _record(value): return FrozenRecord.from_dict(value)


def _write(path, record, *, exclusive=False):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    raw=record.encoded.encode('utf-8')
    if exclusive:
        with path.open('xb') as stream: stream.write(raw)
    else:
        temp=path.with_suffix('.tmp');temp.write_bytes(raw);temp.replace(path)


def provider_configuration(provider):
    _require(type(provider) in PROVIDERS, 'closed TRAIN provider required')
    return provider.configuration()


def validate_configuration(config, *, schemas, main_opportunities, exact=True):
    """Validate a new phase allocation; live originals are checked at dispatch."""
    _require(type(config) is FrozenRecord, 'frozen provider configuration required')
    b=config.data();native=b.get('native_config',{});limits=b.get('limits',{})
    _require(b.get('schema')=='public-train-provider-config-v1'
        and native.get('schemas')==schemas and type(main_opportunities) is int
        and main_opportunities>0 and type(exact) is bool, 'provider schemas/allocation differ')
    count=limits.get('main_opportunities')
    _require(type(count) is int and (count==main_opportunities if exact else count>=main_opportunities)
        and native.get('max_calls')==count, 'complete MAIN opportunities required')
    _require(_record(native).content_hash==b.get('native_config_digest'), 'native configuration digest differs')
    if b.get('provider_kind') in ('grok-acp-public-train-v1','grok-headless-public-train-v1'):
        headless=b['provider_kind']=='grok-headless-public-train-v1'
        _require(b.get('model')=='grok-4.6' and b.get('execution_mode')==('low' if headless else 'native_acp')
            and native.get('schema')==('grok-headless-train-solver-port-v1' if headless else 'grok-train-solver-port-v1')
            and native.get('included_only') is True and native.get('api_key_route_permitted') is False
            and native.get('max_retries')==0 and limits.get('max_retries')==0
            and limits.get('lifetime_seconds')==60
            and limits.get('possible_initial_title_opportunities')==count
            and b.get('accounting_scope')=='native_main'
            and b.get('title_and_all_opportunity_settlement')=='unknown', 'native TRAIN policy differs')
        if headless:
            recovery=native.get('account_read_recovery')
            _require(native.get('provider_kind')==b['provider_kind'] and native.get('reasoning_effort')=='low'
                and native.get('opportunity_contract')==TRAIN_OPPORTUNITY_CONTRACT
                and type(native.get('timeout_seconds')) is int and 1 <= native['timeout_seconds'] <= HEADLESS_TRAIN_TIMEOUT_MAX_SECONDS
                and native.get('paid_fallback') is False
                and (recovery is None or (type(recovery) is dict
                    and recovery=={'schema':'headless-account-read-recovery-v1','max_attempts':2}
                    and type(recovery['max_attempts']) is int)), 'headless phase contract differs')
        _require(native.get('model')==b['model'] and native.get('title_opportunities_per_main')==1
            and native.get('title_usage_and_all_call_totals')=='unknown', 'native model/title contract differs')
        for key in ('prompt_byte_caps','requested_output_token_caps'):
            values=limits.get(key)
            _require(type(values) is dict and set(values)==set(schemas)
                and all(type(v) is int and v>0 for v in values.values()), 'every native slot needs a positive bound')
        _require(limits['prompt_byte_caps']==native.get('slot_input_byte_caps')
            and limits['requested_output_token_caps']==native.get('slot_output_caps')
            and type(limits.get('observed_main_token_cap')) is int
            and limits['observed_main_token_cap']==native.get('observed_main_token_cap')
            and all(limits['observed_main_token_cap']>v for v in limits['requested_output_token_caps'].values()),
            'native observed MAIN bound differs')
    elif b.get('provider_kind')=='codex-cli-public-train-v1':
        _require(b.get('model')=='gpt-5.6-luna' and b.get('execution_mode')=='low'
            and native.get('model')==b['model'] and native.get('effort')=='low'
            and native.get('context_mode')=='reviewed'
            and type(limits.get('legacy_reported_token_limit')) is int
            and limits['legacy_reported_token_limit']>0
            and native.get('max_tokens')==limits['legacy_reported_token_limit'], 'reviewed Codex phase policy differs')
    else: raise ContractError('unadmitted provider configuration')
    return config


def call_accounting(calls):
    """Known MAIN is separate from unknown title/all-call settlement."""
    rows=[c.data() if type(c) is FrozenRecord else c for c in calls]
    _require(all(c.get('schema')=='public-train-provider-call-v1' for c in rows), 'checked call views required')
    scopes={c['known_usage_scope'] for c in rows}
    _require(len(scopes)<=1, 'one phase cannot mix usage scopes')
    return {'schema':'train-phase-call-accounting-v2','provider_calls':len(rows),
        'known_reported_tokens':sum(c['known_tokens'] or 0 for c in rows),
        'known_usage_scope':next(iter(scopes),None),
        'unknown_main_opportunities':sum(c['main_usage_incomplete'] for c in rows),
        'unsuccessful_opportunities':sum(not c['successful'] for c in rows),
        'possible_initial_title_opportunities':sum(c['possible_initial_title_opportunities'] or 0 for c in rows),
        'title_tokens':None,'all_opportunity_tokens':None,'settled_additional_charge_usd':None}


class PhaseProviderSession:
    """Own the complete run allocation; no call may occur outside its scopes."""
    def __init__(self, provider, path):
        _require(type(self) is PhaseProviderSession and type(provider) in PROVIDERS, 'closed phase provider required')
        self.provider=provider;self.path=Path(path);self.active=None;self.aborted=None;self._abort_record=None
        _require(not provider.inspect() and not provider.terminal(), 'phase requires a fresh healthy provider')
        self.record=_record({'schema':'train-phase-provider-scopes-v2',
            'configuration_digest':provider.configuration().content_hash,'scopes':[]})
        _write(self.path,self.record,exclusive=True)

    def verify(self):
        _require(self.aborted is None, 'phase provider is aborted; no original replay is eligible')
        _require(self.path.read_bytes()==self.record.encoded.encode('utf-8'), 'provider scope journal drift')
        configuration, calls = self.provider.inspect_configuration_and_calls()
        _require(self.record.data()['configuration_digest']==configuration.content_hash,
            'phase provider configuration drift')
        rows=self.record.data()['scopes'];flat=[n for row in rows for n in row['call_ids']]
        _require(flat==list(range(1,len(flat)+1)) and len({r['scope_id'] for r in rows})==len(rows),
            'global provider spans omit, reorder or reuse calls')
        count=len(calls)
        _require(count>=len(flat) if self.active is not None else count==len(flat), 'unscoped original provider call')

    @contextmanager
    def scope(self, scope_id):
        self.verify()
        _require(self.active is None and type(scope_id) is str and bool(scope_id)
            and scope_id not in {r['scope_id'] for r in self.record.data()['scopes']}, 'unique sequential provider scope required')
        start=len(self.provider.inspect());scope=PhaseProviderScope(self,scope_id,start)
        self.active=scope
        try: yield scope
        finally:
            if self.aborted is None:
                try:
                    _require(self.active is scope, 'active provider scope substituted')
                    calls=self.provider.calls_since(start)
                    row={'scope_id':scope_id,'start_cursor':start,'call_ids':[c.data()['id'] for c in calls],
                        'call_digests':[c.content_hash for c in calls]}
                    self.record=_record({**self.record.data(),'scopes':[*self.record.data()['scopes'],row]})
                    _write(self.path,self.record);self.active=None;self.verify()
                except ContractError:
                    # Only an existing durable core fault can yield a snapshot.
                    # Scope programming errors are not converted into valid evidence.
                    self.abort()
                    raise

    def abort(self):
        if self.aborted is not None:
            self.aborted.verify();return self.aborted
        snapshot=self.provider.failure_snapshot()
        scope_raw=self.path.read_bytes()
        _require(scope_raw==self.record.encoded.encode('utf-8'), 'aborted scope prefix lost its original journal')
        record=_record({'schema':'train-phase-provider-abort-v2',
            'completed_scope_prefix':self.record.data(),
            'scope_journal_path':str(self.path),'scope_journal_sha256':hashlib.sha256(scope_raw).hexdigest(),
            'unresolved_scope':None if self.active is None else {
                'scope_id':self.active.scope_id,'start_cursor':self.active.start_cursor},
            'provider_snapshot':snapshot.data(),'scope_partition_complete':False,
            'current_originals_verified':False,'score_eligible':False,'eligible_original_seal_created':False})
        path=self.path.with_name(self.path.stem+'-aborted.json')
        _write(path,record,exclusive=True)
        self._abort_record=record
        self.aborted=PhaseProviderAbort(path,record,snapshot,self)
        self.active=None;return self.aborted

    def terminal(self):
        if self.aborted is not None:return True
        try:return self.provider.terminal()
        except ContractError:
            self.abort();return True

    def usage(self):
        if self.aborted is not None:
            self.aborted.verify();return self.aborted.snapshot
        try:return self.provider.usage()
        except ContractError:return self.abort().snapshot

    def finish(self,path):
        """Explicit union: callers must reject aborts at every barrier/scorer."""
        if self.aborted is None:
            try:return self.seal(path)
            except ContractError:self.abort()
        self.aborted.verify();_write(path,self.aborted.record,exclusive=True)
        return PhaseProviderAbort(Path(path),self.aborted.record,self.aborted.snapshot,self)

    def seal(self,path):
        self.verify();_require(self.active is None, 'cannot seal an active provider scope')
        path=Path(path);original=self.provider.seal(path.with_name(path.stem+'-originals.json'))
        record=_record({'schema':'train-phase-provider-ledger-v2','scopes':self.record.data(),
            'original_seal_digest':original.record.content_hash,'original_seal_path':str(original.path)})
        _write(path,record,exclusive=True)
        return PhaseProviderLedger(path,record,original,self)


@dataclass(frozen=True)
class PhaseProviderScope:
    session: PhaseProviderSession
    scope_id: str
    start_cursor: int

    def __call__(self,request):
        _require(type(self) is PhaseProviderScope and self.session.active is self, 'inactive provider scope')
        self.session.verify();return self.session.provider.call(request)

    def cursor(self): return len(self.session.provider.inspect())
    def calls_since(self,cursor):
        _require(type(cursor) is int and cursor>=self.start_cursor, 'cursor precedes cell scope')
        return self.session.provider.calls_since(cursor)


@dataclass(frozen=True)
class PhaseProviderLedger:
    path: Path
    record: FrozenRecord
    original: FrozenTrainProviderLedgerV2
    session: PhaseProviderSession

    def verify(self):
        _require(type(self) is PhaseProviderLedger and type(self.original) is FrozenTrainProviderLedgerV2
            and type(self.session) is PhaseProviderSession, 'typed phase ledger required')
        _require(self.path.read_bytes()==self.record.encoded.encode('utf-8'), 'phase provider seal drift')
        self.session.verify();b=self.record.data();prefix=b['scopes'];live=self.session.record.data()
        _require(b['schema']=='train-phase-provider-ledger-v2'
            and prefix['configuration_digest']==live['configuration_digest']
            and prefix['scopes']==live['scopes'][:len(prefix['scopes'])]
            and b['original_seal_digest']==self.original.record.content_hash
            and b['original_seal_path']==str(self.original.path), 'sealed phase prefix differs')
        ids=[n for row in prefix['scopes'] for n in row['call_ids']]
        _require(ids==[c['view']['id'] for c in self.original.record.data()['calls']], 'scope partition differs from native originals')
        return self.original.verify_originals()

    def calls_for_scope(self,scope_id):
        self.verify();return self._calls_for_scope_after_verified(scope_id)

    def _calls_for_scope_after_verified(self,scope_id):
        """Select a scope only during the synchronous verification that precedes it."""
        matches=[r for r in self.record.data()['scopes']['scopes'] if r['scope_id']==scope_id]
        _require(len(matches)==1, 'scope absent from original provider seal')
        row=matches[0];calls={c['view']['id']:_record(c['view']) for c in self.original.record.data()['calls']}
        selected=tuple(calls[n] for n in row['call_ids'])
        _require([c.content_hash for c in selected]==row['call_digests'], 'scope call evidence changed')
        return selected

    def bind_events(self,events,*,scope_id,require_eligible=True):
        return self.bind_events_with_calls(events,scope_id=scope_id,require_eligible=require_eligible)[0]

    def bind_events_with_calls(self,events,*,scope_id,require_eligible=True):
        """Return exact IDs and immutable calls from this fresh binding pass.

        Consumers may use the returned views for the accounting they are already
        verifying. They are not a reusable verification token or an eligible seal.
        Every invocation still replays current session and original provider files.
        """
        verified=self.verify()
        calls=self._calls_for_scope_after_verified(scope_id)
        try:
            expected_call_ids=tuple(c.data()['id'] for c in calls)
            _validate_event_binding_arguments(expected_call_ids,require_eligible)
            ids=self.original._bind_events_after_verified(events,
                expected_call_ids=expected_call_ids,require_eligible=require_eligible,
                verified=verified)
        except Exception as exc:
            self.original.provider._poison('runtime_binding_fault')
            raise ContractError('runtime provider binding fault; dispatch closed') from exc
        return ids,calls


@dataclass(frozen=True)
class PhaseProviderAbort:
    """Disk-bound terminal accounting; never an original-evidence ledger."""
    path: Path
    record: FrozenRecord
    snapshot: FrozenRecord
    session: PhaseProviderSession

    def verify(self):
        _require(type(self) is PhaseProviderAbort and type(self.session) is PhaseProviderSession
            and type(self.session.provider) in PROVIDERS
            and type(self.record) is FrozenRecord and type(self.snapshot) is FrozenRecord,
            'exact typed phase abort required')
        _require(self.record is self.session._abort_record and self.session.aborted is not None
            and self.session.aborted.record is self.record and self.session.aborted.snapshot is self.snapshot,
            'abort differs from its originating phase and captured record')
        _require(self.path.read_bytes()==self.record.encoded.encode('utf-8'), 'terminal phase accounting bytes differ')
        b=self.record.data();s=self.snapshot.data()
        _require(set(b)=={'schema','completed_scope_prefix','scope_journal_path','scope_journal_sha256','unresolved_scope','provider_snapshot',
                'scope_partition_complete','current_originals_verified','score_eligible','eligible_original_seal_created'}
            and b['schema']=='train-phase-provider-abort-v2'
            and all(b[k] is False for k in ('scope_partition_complete','current_originals_verified','score_eligible','eligible_original_seal_created'))
            and b['provider_snapshot']==s and s.get('schema')=='public-train-provider-terminal-snapshot-v1'
            and s.get('terminal_fault') is True and s.get('current_originals_verified') is False
            and s.get('score_eligible') is False and self.session.provider.failure_snapshot()==self.snapshot,
            'terminal phase snapshot is not the original noneligible accounting evidence')
        prefix=b['completed_scope_prefix'];unresolved=b['unresolved_scope']
        _require(set(prefix)=={'schema','configuration_digest','scopes'}
            and prefix['schema']=='train-phase-provider-scopes-v2'
            and prefix==self.session.record.data() and b['scope_journal_path']==str(self.session.path)
            and type(prefix['configuration_digest']) is str and len(prefix['configuration_digest'])==64
            and all(c in '0123456789abcdef' for c in prefix['configuration_digest'])
            and type(prefix['scopes']) is list, 'aborted phase scope origin/configuration differs')
        ids=[];names=[]
        for row in prefix['scopes']:
            _require(type(row) is dict and set(row)=={'scope_id','start_cursor','call_ids','call_digests'}
                and type(row['scope_id']) is str and bool(row['scope_id']) and row['scope_id'] not in names
                and type(row['start_cursor']) is int and row['start_cursor']==len(ids)
                and type(row['call_ids']) is list and all(type(n) is int for n in row['call_ids'])
                and row['call_ids']==list(range(len(ids)+1,len(ids)+len(row['call_ids'])+1))
                and type(row['call_digests']) is list and len(row['call_digests'])==len(row['call_ids'])
                and all(type(v) is str and len(v)==64 and all(c in '0123456789abcdef' for c in v)
                    for v in row['call_digests']), 'aborted completed prefix shape differs')
            names.append(row['scope_id']);ids.extend(row['call_ids'])
        _require(unresolved is None or (type(unresolved) is dict and set(unresolved)=={'scope_id','start_cursor'}
            and type(unresolved['scope_id']) is str and bool(unresolved['scope_id']) and unresolved['scope_id'] not in names
            and type(unresolved['start_cursor']) is int and unresolved['start_cursor']==len(ids)),
            'aborted unresolved scope shape differs')
        historical=s.get('historical_observation')
        _require(historical is None or historical['configuration_digest']==prefix['configuration_digest'],
            'historical provider configuration belongs to another phase')
        raw=Path(b['scope_journal_path']).read_bytes()
        _require(raw==_record(b['completed_scope_prefix']).encoded.encode('utf-8')
            and hashlib.sha256(raw).hexdigest()==b['scope_journal_sha256'], 'terminal completed scope journal differs')
        return _record({'schema':'train-phase-abort-verification-v2','accounting_record_bound':True,
            'current_originals_verified':False,'score_eligible':False,'scope_partition_complete':False,
            'status':'terminal_accounting_only'})

    def bind_events(self,*args,**kwargs):
        raise ContractError('terminal phase accounting cannot bind a runtime or authorize scoring')

    def bind_events_with_calls(self,*args,**kwargs):
        raise ContractError('terminal phase accounting cannot bind a runtime or authorize scoring')
