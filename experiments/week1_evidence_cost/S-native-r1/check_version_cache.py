"""Frozen deterministic S/B/R checks; fixtures are not domain benchmark samples."""
import argparse,hashlib,json,random,sys,time
from pathlib import Path
from datetime import datetime,timezone
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[1]
sys.path[:0]=[str(REPO),str(HERE)]
from version_cache import VersionCache
from research_loop.modular.contracts import DataIdentity,FrozenRecord
from research_loop.modular.modules.evidence import EvidenceLedger,ClaimLedger
from research_loop.modular.modules.context import ContextBuilder,ContextCache
from research_loop.ontology import ContractError,canonical,digest

SOURCES=['research_loop/modular/modules/evidence.py','research_loop/modular/modules/context.py',
'research_loop/modular/contracts.py','research_loop/ontology.py']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):
    with p.open('x',encoding='utf-8',newline='\n') as f:
        f.write(json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
class Fixture:
    def __init__(self,domain='train'):
        self.identity=DataIdentity('synthetic-correctness','native-semantics','fixture','v1','fixture-only',domain)
        self.forwarded=[]
        self.e=EvidenceLedger(self.identity,event_sink=lambda x:self.forwarded.append(('e',x.content_hash)))
        self.c=ClaimLedger(self.e,event_sink=lambda x:self.forwarded.append(('c',x.content_hash)))
        self.s=VersionCache();self.b=ContextCache();self.builder=ContextBuilder(self.identity,budget_bytes=60000)
        self.roots={};self.ids={};self.checks=[];self.ops=[]
    def root(self,name):
        r=self.e.append({'kind':'observation','root_material':{'fixture_id':name},'representation':'raw',
            'content':{'fixture':True,'value':name},'subject_bindings':{'subject':'fixture'},
            'independent_group':self.identity.group_id},
            {'trusted_validator':'synthetic-fixture-only','validator_verified':True,'admitted':True})
        self.roots[name]=r.root_id;self.ops.append({'op':'root','name':name});return r
    def claim(self,name):
        c=self.c.create(name,subject_bindings={'subject':'fixture'});self.ids[name]=c.claim_id
        self.ops.append({'op':'claim','name':name});return c
    def current(self,name):return next(c for c in self.c.claims() if c.claim_id==self.ids[name])
    def apply(self,name,supports=(),refutes=()):
        rev=self.current(name).revision
        self.c.apply(self.ids[name],{'supports':[self.roots[x] for x in supports],
            'refutes':[self.roots[x] for x in refutes],'subject_bindings':{'subject':'fixture'}},expected_revision=rev)
        self.ops.append({'op':'apply','name':name,'supports':list(supports),'refutes':list(refutes),'revision':rev})
    def withdraw(self,name):
        self.e.withdraw(self.roots[name],'synthetic correctness operation')
        self.c.refresh_after_withdrawal();self.ops.append({'op':'withdraw_refresh','name':name})
    def link(self,name,parents):
        rev=self.current(name).revision
        self.c.link_dependencies(self.ids[name],[self.ids[p] for p in parents],expected_revision=rev)
        self.ops.append({'op':'link','name':name,'parents':parents,'revision':rev})
    def check(self,label,*,question='fixture question',mode='candidate',summary=None,budget=None):
        if budget is not None:self.builder=ContextBuilder(self.identity,budget_bytes=budget)
        before=(self.e.snapshot().encoded,self.c.snapshot().encoded)
        kw={'mode':mode,'baseline_summary':summary}
        r=self.builder.build(question,self.e,self.c,**kw)
        b=self.b.get_or_build(self.builder,question,self.e,self.c,**kw)
        s=self.s.get_or_build(self.builder,question,self.e,self.c,**kw)
        assert canonical(r.data())==canonical(b.data())==canonical(s.data()),label
        assert before==(self.e.snapshot().encoded,self.c.snapshot().encoded),label
        self.checks.append({'label':label,'bundle_sha256':r.content_hash,'exact_R_B_S':True,'state_unchanged_by_query':True,
                            'evidence_version':r.evidence_version,'claim_version':r.claim_version,'S':self.s.stats()})
        return r
def freeze(run):
    out=HERE/run;out.mkdir()
    save(out/'manifest.json',{'schema':'week1-S-native-checks-v1','frozen_at':datetime.now(timezone.utc).isoformat(),
        'source_sha256':sha(Path(__file__)),'S_sha256':sha(HERE/'version_cache.py'),
        'core_sha256':{x:sha(REPO/x) for x in SOURCES},'seed':20260921,'random_steps':80,
        'wall_limit_seconds':60,'model_calls':0,'scorer_calls':0,'formal_VAL_inputs':0,
        'contract':'Exact native R/B semantics; public serial ledger writes observed by S; full canonical bundle equality. No direct private-state or external-file mutation.',
        'AND':'Native multi-root support is disjunctive; mandatory coverage includes an explicit inability-to-represent counterexample, never an AND pass.',
        'cases':['alternative_support','withdrawal','revision_change','unrelated_update','clear','illegal_cycle',
                 'dependency_review_propagation','refute','identity_budget_question_summary','ephemeral_synthetic_validation',
                 'ledger_rebinding','sink_preservation','observer_displacement','write_failure','real_saved_requests'],
        'domain_requests':[['domain-pilot-r2','week1-domain-2-r2'],['domain-pilot-r2','week1-domain-3-r2'],['domain-pilot-r3','week1-domain-1-r3']]})
    for source in (Path(__file__),HERE/'version_cache.py'):(out/source.name).write_bytes(source.read_bytes())
    print(json.dumps({'frozen':str(out)}))
def run(run):
    out=HERE/run;m=read(out/'manifest.json');deadline=time.monotonic()+m['wall_limit_seconds']
    assert sha(Path(__file__))==m['source_sha256'] and sha(HERE/'version_cache.py')==m['S_sha256']
    for p,h in m['core_sha256'].items():assert sha(REPO/p)==h
    f=Fixture();f.check('empty');f.check('empty_hit');assert f.s.hits==1 and f.s.builds==1
    for x in ('a','b','r','u'):f.root(x)
    for x in ('A','B','C'):f.claim(x)
    f.apply('A',['a','b']);f.check('alternative_roots')
    f.withdraw('a');f.check('alternative_survives_withdrawal')
    assert f.current('A').status=='supported' and f.current('A').needs_review
    and_gap={'requirement':'AND support group','representation_available':False,'operation_log':list(f.ops),
        'after_withdrawing_a':f.current('A').data(),
        'native_meaning':'b independently remains support; this is valid OR semantics',
        'if_encoded_as_AND':'incorrectly remains supported; there is no grouping field to distinguish AND from OR',
        'verdict':'AND requirement not implemented by native reference; not a cache-induced mismatch'}
    save(out/'and-capability-gap.json',and_gap)
    f.apply('A',['b'],['r']);f.check('support_and_refutation');assert f.current('A').status=='undetermined'
    f.apply('A',['b']);f.check('claim_revision_change')
    f.apply('B',['u']);f.apply('C',['u']);f.link('B',['A']);f.link('C',['B'])
    f.check('dependency_edges');before=f.current('C').revision
    f.apply('A',['b']);f.check('transitive_dependency_review');assert f.current('C').revision>before and f.current('C').needs_review
    prior=(f.e.snapshot().encoded,f.c.snapshot().encoded)
    try:f.link('A',['C']);raise AssertionError('cycle accepted')
    except ContractError:pass
    assert prior==(f.e.snapshot().encoded,f.c.snapshot().encoded);f.check('illegal_cycle_rejected_atomically')
    old=f.check('before_unrelated');miss=f.s.misses;f.root('unrelated');new=f.check('unrelated_global_version_change')
    assert old.evidence_version!=new.evidence_version and f.s.misses==miss+1
    f.s.clear();f.check('cache_clear');f.check('question_change',question='different question')
    f.check('budget_change',budget=200);f.check('baseline_summary',mode='baseline',summary='untrusted')
    f.check('baseline_summary_change',mode='baseline',summary='changed');f.check('restore_budget',budget=60000)
    f.withdraw('b');f.check('last_alternative_withdrawn');assert f.current('A').status=='undetermined'
    rng=random.Random(m['seed'])
    active=['r','u','unrelated']
    for i in range(m['random_steps']):
        if time.monotonic()>deadline:raise TimeoutError('check budget')
        op=rng.choice(('root','apply','notice','query','clear'))
        if op=='root':
            name='random-'+str(i);f.root(name);active.append(name)
        elif op=='apply':f.apply(rng.choice(('A','B','C')),[rng.choice(active)])
        elif op=='notice':
            name=rng.choice(('A','B','C'));c=f.current(name)
            f.c.mark_unattributed_summary(c.claim_id,'synthetic no-provenance notice',expected_revision=c.revision)
            f.ops.append({'op':'summary_notice','name':name,'revision':c.revision})
        elif op=='clear':f.s.clear();f.ops.append({'op':'clear'})
        f.check('random-'+str(i))
    assert f.s.events==len(f.forwarded),'existing event sink lost or duplicated'
    save(out/'native-checks.json',{'checks':f.checks,'operations':f.ops,'sink_events_preserved':len(f.forwarded),
                                'S':f.s.stats(),'sample_kind':'synthetic correctness, not domain outcomes'})
    edge=[]
    v=Fixture('validation');v.check('synthetic_val_1');v.check('synthetic_val_2')
    assert v.s.size()==0 and v.s.hits==0;edge.append('synthetic_validation_never_retained')
    other=Fixture();other.root('other');other.claim('A');other.apply('A',['other'])
    rebound=f.s.get_or_build(other.builder,'new pair',other.e,other.c)
    assert canonical(rebound.data())==canonical(other.builder.build('new pair',other.e,other.c).data());edge.append('rebind_discards_old_cache')
    displaced=Fixture();displaced.check('prime');displaced.e._log.event_sink=lambda e:None
    try:displaced.check('displaced');raise AssertionError('displaced observer accepted')
    except ContractError:edge.append('observer_displacement_fails_closed')
    failed=Fixture()
    def reject(event):raise RuntimeError('synthetic audit sink failure')
    failed.e._log.event_sink=reject;failed.check('prime')
    try:failed.root('failure');raise AssertionError('sink failure swallowed')
    except RuntimeError:pass
    try:failed.s.get_or_build(failed.builder,'fixture question',failed.e,failed.c);raise AssertionError('failed write reused')
    except ContractError:edge.append('failed_write_poisons_cache')
    save(out/'edge-checks.json',edge)
    real=[]
    for series,op in m['domain_requests']:
        for slot in ('plan','final'):
            d=HERE/series/op/slot;req=read(d/'request.json');identity=DataIdentity.parse(req['task']['identity']);identity.require_train()
            before={n:sha(d/(n+'.jsonl')) for n in ('evidence','claims')}
            e=EvidenceLedger(identity,storage_path=d/'evidence.jsonl');c=ClaimLedger(e,storage_path=d/'claims.jsonl')
            builder=ContextBuilder(identity,budget_bytes=req['context']['budget_bytes']);cache=VersionCache()
            kw={'mode':'candidate'};question=canonical(req['task']['payload'])
            s=cache.get_or_build(builder,question,e,c,**kw)
            assert canonical(s.public_data())==canonical(req['context'])
            assert cache.get_or_build(builder,question,e,c,**kw) is s
            assert cache.builds==1 and cache.hits==1
            for n,h in before.items():assert sha(d/(n+'.jsonl'))==h
            real.append({'series':series,'opportunity':op,'slot':slot,'exact_recorded_context':True,
                         'request_digest_other_fields_frozen':digest(dict(req,context=s.public_data())),'S':cache.stats()})
            cache.close()
    save(out/'real-request-checks.json',real)
    save(out/'result.json',{'native_R_B_S_mismatches':0,'native_differential_checks':len(f.checks),'real_saved_requests':len(real),
        'edge_checks':len(edge),'AND':'unsupported by native reference, counterexample retained',
        'all_brief_semantics_satisfied':False,'model_calls':0,'scope':'S correctness on current native semantics; performance unmeasured'})
    print(json.dumps(read(out/'result.json')))
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('action',choices=['freeze','run']);a.add_argument('--run',default='S-native-r1');v=a.parse_args()
    if v.action=='freeze':freeze(v.run)
    else:run(v.run)

