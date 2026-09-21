"""Fresh-process native R/B/S replay. Saved domain operations and warm probes stay separate."""
import argparse,ctypes,hashlib,json,os,platform,random,statistics,subprocess,sys,time,tracemalloc
from datetime import datetime,timezone
from pathlib import Path
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[1];sys.path[:0]=[str(REPO),str(HERE)]
from version_cache import VersionCache
from research_loop.modular.contracts import DataIdentity
from research_loop.modular.modules.evidence import EvidenceLedger,ClaimLedger
from research_loop.modular.modules.context import ContextBuilder,ContextCache
from research_loop.ontology import canonical,digest
SOURCES=['research_loop/modular/modules/evidence.py','research_loop/modular/modules/context.py','research_loop/modular/contracts.py','research_loop/ontology.py']
CASES=[('domain-rich-r1','week1-rich-domain-1-r1')]
WORK=Path('E:/_ryanDev/AI/research-loop-modular/work')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def save(p,x):
    with p.open('x',encoding='utf-8',newline='\n') as f:f.write(json.dumps(x,sort_keys=True,ensure_ascii=False,indent=2)+'\n')
def peak_working_set():
    class PM(ctypes.Structure):
        _fields_=[('cb',ctypes.c_ulong),('PageFaultCount',ctypes.c_ulong),('PeakWorkingSetSize',ctypes.c_size_t),
        ('WorkingSetSize',ctypes.c_size_t),('QuotaPeakPagedPoolUsage',ctypes.c_size_t),('QuotaPagedPoolUsage',ctypes.c_size_t),
        ('QuotaPeakNonPagedPoolUsage',ctypes.c_size_t),('QuotaNonPagedPoolUsage',ctypes.c_size_t),
        ('PagefileUsage',ctypes.c_size_t),('PeakPagefileUsage',ctypes.c_size_t)]
    p=PM();p.cb=ctypes.sizeof(p)
    fn=ctypes.windll.psapi.GetProcessMemoryInfo
    fn.argtypes=[ctypes.c_void_p,ctypes.POINTER(PM),ctypes.c_ulong];fn.restype=ctypes.c_int
    get=ctypes.windll.kernel32.GetCurrentProcess;get.restype=ctypes.c_void_p
    if not fn(get(),ctypes.byref(p),p.cb):raise OSError('GetProcessMemoryInfo failed')
    return p.PeakWorkingSetSize
def freeze(name):
    out=HERE/name;out.mkdir()
    cases=[]
    for series,op in CASES:
        runtime=HERE/series/op/'runtime';rows=[json.loads(l) for l in (runtime/'artifacts.jsonl').read_text(encoding='utf-8').splitlines()]
        schedule=[]
        for row in rows:
            d=row['descriptor'];payload=d['payload']['canonical']
            if d['kind']=='ledger_event':schedule.append({'kind':'update','journal':payload['journal'],'event':payload['event']})
            elif d['kind']=='trace_event' and payload['stage']=='model_request':
                schedule.append({'kind':'query','request':payload['data']['request']})
        assert sum(x['kind']=='query' for x in schedule)==3
        assert sum(x['kind']=='update' for x in schedule)>=9
        save(out/(op+'.json'),schedule)
        cases.append({'opportunity':op,'series':series,'schedule_sha256':sha(out/(op+'.json')),
                      'source_artifacts_sha256':sha(runtime/'artifacts.jsonl')})
    save(out/'manifest.json',{'schema':'week1-RBS-native-replay-v1','frozen_at':datetime.now(timezone.utc).isoformat(),
        'source_sha256':sha(Path(__file__)),'S_sha256':sha(HERE/'version_cache.py'),
        'core_sha256':{x:sha(REPO/x) for x in SOURCES},'cases':cases,'schemes':['R','B','S'],'repeats':20,'seed':20260921,
        'warm_probe_queries':10,'per_child_timeout_seconds':15,'parent_timeout_seconds':600,
        'child_peak_working_set_stop_bytes':134217728,'external_model_calls':0,
        'python':sys.version,'platform':platform.platform(),
        'normalization':'none; exact public context and both native ledger snapshots after each recorded query',
        'scope':'Actual saved operation sequence, recorded native domain-statistic events and three queries. Warm repetitions are a separate probe, not actual domain reuse.',
        'resource_note':'serial fresh child process per task/scheme/repetition; persistent native journals; no container/model execution or runtime artifact-catalogue reconstruction'})
    for p in (Path(__file__),HERE/'version_cache.py'):(out/p.name).write_bytes(p.read_bytes())
    print(json.dumps({'frozen':str(out),'cases':len(cases)}))
def worker(name,index,scheme,repeat):
    out=HERE/name;m=read(out/'manifest.json');case=m['cases'][index]
    assert m['source_sha256']==sha(Path(__file__)) and m['S_sha256']==sha(HERE/'version_cache.py')
    for p,h in m['core_sha256'].items():assert sha(REPO/p)==h
    schedule_path=out/(case['opportunity']+'.json');assert sha(schedule_path)==case['schedule_sha256']
    dest=WORK/name/f"{index}-{scheme}-{repeat}";dest.mkdir(parents=True)
    measurements=[];tracemalloc.start()
    t=time.perf_counter_ns();schedule=read(schedule_path);measurements.append({'operation':'schedule_read','ns':time.perf_counter_ns()-t})
    req=next(x['request'] for x in schedule if x['kind']=='query');identity=DataIdentity.parse(req['task']['identity']);identity.require_train()
    t=time.perf_counter_ns()
    e=EvidenceLedger(identity,storage_path=dest/'evidence.jsonl');c=ClaimLedger(e,storage_path=dest/'claims.jsonl')
    cache=ContextCache() if scheme=='B' else VersionCache() if scheme=='S' else None
    # Bind S before updates, so observation and invalidation maintenance are timed.
    if scheme=='S':cache._bind(e,c)
    measurements.append({'operation':'cold_session_and_index_bind','ns':time.perf_counter_ns()-t})
    checks=[];sequence_started=time.perf_counter_ns()
    for step in schedule:
        t=time.perf_counter_ns()
        if step['kind']=='update':
            event=step['event'];kind=event['event']
            if step['journal']=='evidence':
                assert kind=='append';p=event['payload']
                v=e.append({'kind':p['kind'],'root_material':p['root_material'],'content':p['content'],
                    'representation':event['representation'],'subject_bindings':event['subject_bindings'],'independent_group':event['independent_group']},
                    {'trusted_validator':p['trusted_validator'],'validator_verified':p['validator_verified'],'admitted':event['admitted']})
                assert v.root_id==event['root_id'] and v.record_id==event['record_id']
            elif kind=='create':
                v=c.create(event['statement'],subject_bindings=event['subject_bindings']);assert v.claim_id==event['claim_id']
            elif kind=='apply':
                c.apply(event['claim_id'],{k:event[k] for k in ('supports','refutes','subject_bindings')},expected_revision=event['expected_revision'])
            elif kind=='dependency_update':
                c.link_dependencies(event['claim_id'],event['depends_on'],expected_revision=event['expected_revision'])
            else:raise AssertionError('unexpected event in fixed native domain schedule')
            measurements.append({'operation':'update_with_journal_and_index','ns':time.perf_counter_ns()-t})
        else:
            req=step['request'];builder=ContextBuilder(identity,budget_bytes=req['context']['budget_bytes']);question=canonical(req['task']['payload'])
            c.refresh_after_withdrawal()
            bundle=builder.build(question,e,c,mode='candidate') if cache is None else cache.get_or_build(builder,question,e,c,mode='candidate')
            measurements.append({'operation':'actual_query_with_refresh','ns':time.perf_counter_ns()-t})
            t=time.perf_counter_ns();encoded=canonical(bundle.public_data());measurements.append({'operation':'actual_full_expand_serialize','ns':time.perf_counter_ns()-t})
            assert encoded==canonical(req['context'])
            checks.append({'slot':req['slot'],'context_digest':digest(bundle.public_data()),'evidence_digest':e.snapshot().content_hash,'claims_digest':c.snapshot().content_hash})
    sequence_wall=time.perf_counter_ns()-sequence_started
    actual_stats=cache.stats() if scheme=='S' else {'retained_entries':cache.size()} if cache else {}
    actual_peak_python=tracemalloc.get_traced_memory()[1];actual_peak_ws=peak_working_set()
    warm=[]
    for _ in range(m['warm_probe_queries']):
        t=time.perf_counter_ns()
        bundle=builder.build(question,e,c,mode='candidate') if cache is None else cache.get_or_build(builder,question,e,c,mode='candidate')
        warm.append(time.perf_counter_ns()-t)
        assert canonical(bundle.public_data())==canonical(req['context'])
    peak=tracemalloc.get_traced_memory()[1];tracemalloc.stop()
    if scheme=='S':cache.close()
    assert actual_peak_ws<=m['child_peak_working_set_stop_bytes']
    print(json.dumps({'opportunity':case['opportunity'],'scheme':scheme,'repeat':repeat,'measurements':measurements,'checks':checks,
        'actual_sequence_wall_ns_including_checks':sequence_wall,'actual_cache_stats':actual_stats,'separate_warm_probe_ns':warm,
        'actual_peak_python_tracemalloc_bytes':actual_peak_python,'actual_sequence_peak_working_set_bytes':actual_peak_ws,'whole_child_peak_working_set_bytes':peak_working_set(),
        'python_peak_including_warm_probe_bytes':peak}))
def run(name):
    out=HERE/name;m=read(out/'manifest.json');result=out/'measurement';result.mkdir()
    jobs=[(i,s,r) for i in range(len(m['cases'])) for s in m['schemes'] for r in range(m['repeats'])]
    random.Random(m['seed']).shuffle(jobs);save(result/'order.json',jobs)
    deadline=time.monotonic()+m['parent_timeout_seconds'];rows=[];reference={}
    with (result/'raw.jsonl').open('x',encoding='utf-8',newline='\n') as stream:
        for index,scheme,repeat in jobs:
            if time.monotonic()>deadline:raise TimeoutError('parent budget')
            t=time.perf_counter_ns()
            p=subprocess.run([sys.executable,'-B',str(Path(__file__)),'worker','--run',name,'--index',str(index),'--scheme',scheme,'--repeat',str(repeat)],
                             capture_output=True,text=True,encoding='utf-8',timeout=m['per_child_timeout_seconds'],creationflags=subprocess.CREATE_NO_WINDOW)
            if p.returncode:
                save(result/'failure.json',{'job':[index,scheme,repeat],'exit_code':p.returncode,'stdout':p.stdout,'stderr':p.stderr});raise RuntimeError('worker failed; stop comparison')
            row=json.loads(p.stdout);row['whole_child_wall_ns']=time.perf_counter_ns()-t
            key=row['opportunity'];ref=reference.setdefault(key,row['checks']);assert row['checks']==ref,'semantic mismatch; stop performance comparison'
            stream.write(json.dumps(row,sort_keys=True)+'\n');stream.flush();rows.append(row)
    summary=[]
    for case in m['cases']:
        for scheme in m['schemes']:
            selected=[x for x in rows if x['opportunity']==case['opportunity'] and x['scheme']==scheme]
            def total(row,op):return sum(x['ns'] for x in row['measurements'] if x['operation']==op)
            summary.append({'opportunity':case['opportunity'],'scheme':scheme,'fresh_process_repeats':len(selected),
                'median_cold_bind_us':statistics.median(total(x,'cold_session_and_index_bind') for x in selected)/1000,
                'median_updates_with_journal_us':statistics.median(total(x,'update_with_journal_and_index') for x in selected)/1000,
                'median_three_actual_queries_us':statistics.median(total(x,'actual_query_with_refresh') for x in selected)/1000,
                'median_full_expand_us':statistics.median(total(x,'actual_full_expand_serialize') for x in selected)/1000,
                'median_actual_sequence_including_checks_ms':statistics.median(x['actual_sequence_wall_ns_including_checks'] for x in selected)/1e6,
                'median_whole_child_ms':statistics.median(x['whole_child_wall_ns'] for x in selected)/1e6,
                'median_separate_warm_query_us':statistics.median(v for x in selected for v in x['separate_warm_probe_ns'])/1000,
                'max_actual_python_tracemalloc_bytes':max(x['actual_peak_python_tracemalloc_bytes'] for x in selected),
                'max_whole_child_peak_working_set_bytes':max(x['whole_child_peak_working_set_bytes'] for x in selected),
                'actual_cache_stats_first_repeat':selected[0]['actual_cache_stats']})
    save(result/'summary.json',summary)
    save(result/'result.json',{'child_runs':len(rows),'independent_tasks':len(m['cases']),'broad_source_families':1,'new_independent_tasks':0,
         'exact_context_and_state_comparisons':len(rows)*3,'observed_semantic_mismatches':0,'new_model_calls':0,
         'AND':'unsupported native capability remains; this comparison is scoped to existing native domain operations'})
    print(json.dumps(read(result/'result.json')))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['freeze','run','worker']);p.add_argument('--run',default='RBS-rich-r1b')
    p.add_argument('--index',type=int,default=0);p.add_argument('--scheme',choices=['R','B','S'],default='B');p.add_argument('--repeat',type=int,default=0);v=p.parse_args()
    if v.action=='freeze':freeze(v.run)
    elif v.action=='run':run(v.run)
    else:worker(v.run,v.index,v.scheme,v.repeat)

