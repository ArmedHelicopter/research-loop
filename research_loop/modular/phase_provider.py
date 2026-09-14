"""Versioned TRAIN phase accounting over closed, original-evidence providers.

Legacy Codex helpers and ledger schemas are deliberately not interpreted here.
One session partitions every actual call into an ordered, immutable scope. A
history prefix remains replayable after target calls append to the session.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.train_provider import (
    CodexTrainProvider, GrokTrainProvider, FrozenTrainProviderLedgerV2)
from research_loop.ontology import ContractError

PROVIDERS = (CodexTrainProvider, GrokTrainProvider)


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
    if b.get('provider_kind')=='grok-acp-public-train-v1':
        _require(b.get('model')=='grok-4.6' and b.get('execution_mode')=='native_acp'
            and native.get('schema')=='grok-train-solver-port-v1'
            and native.get('included_only') is True and native.get('api_key_route_permitted') is False
            and native.get('max_retries')==0 and limits.get('max_retries')==0
            and limits.get('lifetime_seconds')==60
            and limits.get('possible_initial_title_opportunities')==count
            and b.get('accounting_scope')=='native_main'
            and b.get('title_and_all_opportunity_settlement')=='unknown', 'native TRAIN policy differs')
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
        self.provider=provider;self.path=Path(path);self.active=None
        _require(not provider.inspect() and not provider.terminal(), 'phase requires a fresh healthy provider')
        self.record=_record({'schema':'train-phase-provider-scopes-v2',
            'configuration_digest':provider.configuration().content_hash,'scopes':[]})
        _write(self.path,self.record,exclusive=True)

    def verify(self):
        _require(self.path.read_bytes()==self.record.encoded.encode('utf-8'), 'provider scope journal drift')
        _require(self.record.data()['configuration_digest']==self.provider.configuration().content_hash,
            'phase provider configuration drift')
        rows=self.record.data()['scopes'];flat=[n for row in rows for n in row['call_ids']]
        _require(flat==list(range(1,len(flat)+1)) and len({r['scope_id'] for r in rows})==len(rows),
            'global provider spans omit, reorder or reuse calls')
        count=len(self.provider.inspect())
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
            _require(self.active is scope, 'active provider scope substituted')
            calls=self.provider.calls_since(start)
            row={'scope_id':scope_id,'start_cursor':start,'call_ids':[c.data()['id'] for c in calls],
                'call_digests':[c.content_hash for c in calls]}
            self.record=_record({**self.record.data(),'scopes':[*self.record.data()['scopes'],row]})
            _write(self.path,self.record);self.active=None;self.verify()

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
        self.verify();matches=[r for r in self.record.data()['scopes']['scopes'] if r['scope_id']==scope_id]
        _require(len(matches)==1, 'scope absent from original provider seal')
        row=matches[0];calls={c['view']['id']:_record(c['view']) for c in self.original.record.data()['calls']}
        selected=tuple(calls[n] for n in row['call_ids'])
        _require([c.content_hash for c in selected]==row['call_digests'], 'scope call evidence changed')
        return selected

    def bind_events(self,events,*,scope_id,require_eligible=True):
        calls=self.calls_for_scope(scope_id)
        return self.original.bind_events(events,expected_call_ids=tuple(c.data()['id'] for c in calls),require_eligible=require_eligible)
