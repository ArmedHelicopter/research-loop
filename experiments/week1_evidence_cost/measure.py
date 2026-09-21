"""Offline D1-D2 diagnostic. No model calls, core changes, or new optimization."""
from __future__ import annotations
import argparse, cProfile, hashlib, json, os, platform, pstats, random, statistics
import subprocess, sys, time, tracemalloc
from pathlib import Path
from datetime import datetime, timezone
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.modules.context import ContextBuilder, ContextCache
from research_loop.modular.modules.evidence import EvidenceLedger, ClaimLedger, _JsonlLog
from research_loop.ontology import canonical, digest

SERIES = ('actual-exploration-scheduler-grok130-run-r4',
          'actual-admission-prediction-exploration-grok130-run-r9',
          'actual-ordinary-q31-grok130-run-r2')
SOURCES = ('research_loop/ontology.py', 'research_loop/modular/contracts.py',
           'research_loop/modular/modules/evidence.py',
           'research_loop/modular/modules/context.py', 'research_loop/modular/runtime.py',
           'research_loop/modular/admission_prediction_exploration_driver.py')
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def events(p): return [json.loads(s) for s in p.read_text(encoding='utf-8').splitlines() if s.strip()]
def save(p, v):
    with p.open('x', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps(v, ensure_ascii=False, sort_keys=True, indent=2)+'\n')
def verify(rows):
    previous = None
    lock = digest(rows[0]['data'])
    for i, row in enumerate(rows):
        assert row['sequence'] == i and row['previous'] == previous
        assert row['lock_digest'] == lock
        if row['stage'] == 'model_request':
            assert digest(row['data']['request']) == row['data']['request_digest']
        previous = digest(row)
def freeze(a):
    out = HERE / a.run
    out.mkdir()
    inventory, selected = [], []
    for series in SERIES:
        count = 0
        for trace in sorted((a.work/series/'controller/cells').rglob('trace.jsonl')):
            rows = events(trace)
            identity = rows[0]['data']['identity']
            stages = [r['stage'] for r in rows]
            eligible = identity['domain']=='train' and identity['benchmark']=='discoverybench'
            complete = stages[-1]=='final_decision' and 'model_failure' not in stages
            reason = ('outside_domain' if not eligible else 'incomplete' if not complete
                      else 'beyond_first_three_per_series' if count>=3 else 'selected')
            item = dict(source=str(trace), sha256=sha(trace), identity=identity, stages=stages, reason=reason)
            if reason == 'selected':
                verify(rows)
                cell = trace.parent.parent.name
                dest = out/'inputs'/series/cell
                dest.mkdir(parents=True)
                files = {}
                for name in ('trace.jsonl','evidence.jsonl','claims.jsonl'):
                    source = trace.parent/name
                    (dest/name).write_bytes(source.read_bytes())
                    files[name] = dict(sha256=sha(source), bytes=source.stat().st_size)
                selected.append(dict(series=series, cell=cell, input_dir=str(dest.relative_to(out)),
                                     identity=identity, files=files, arm=rows[0]['data']['arm']['enabled']))
                count += 1
            inventory.append(item)
    assert 3 <= len(selected) <= 6
    public = a.work/'primary-prospective-export-live-r1/public-train/012ada98f13f89d78278ec9537777cf74e00c03ff41db441911f8fa6ec2ab299'
    save(out/'manifest.json', dict(schema='week1-cost-v1', frozen_at=datetime.now(timezone.utc).isoformat(),
        base_commit=subprocess.check_output(['git','-C',str(REPO),'rev-parse','HEAD'], text=True).strip(),
        selection='First three complete TRAIN DiscoveryBench traces by path per named series; no score selection.',
        inventory=inventory, selected=selected, repeats=30, inner=20, seed=20260921, timeout_seconds=60,
        normalization='None: canonical bytes must match exactly.',
        source_hashes={p:sha(REPO/p) for p in SOURCES}, harness_sha256=sha(Path(__file__)),
        brief=dict(path=str(a.brief), sha256=sha(a.brief)),
        public_data={n:dict(path=str(public/n),sha256=sha(public/n)) for n in ('public.json','data.csv')},
        budget=dict(new_paid_spend=0, external_model_calls=0, subagents=0,
                    subscription_before='unknown: live official usage unavailable', subscription_after='unknown',
                    reset_and_expiry='unknown', further_model_packages_dispatched=False),
        scope='First package: runtime context seam only; no new optimization.',
        unmeasured=['transient module-state reconstruction','nonempty dependency updates','model wait',
                    'new tool execution','S/C','end-to-end speedup','subscription usage delta']))
    print(json.dumps(dict(selected=len(selected),inventoried=len(inventory),manifest_sha256=sha(out/'manifest.json'))))
def worker(a):
    out = HERE/a.run
    m = read(out/'manifest.json')
    assert m['harness_sha256']==sha(Path(__file__))
    for p,h in m['source_hashes'].items(): assert sha(REPO/p)==h,p
    output = out/'measurement'
    output.mkdir()
    deadline = time.monotonic()+55
    raw, checks, profiles = [], [], []
    rng = random.Random(m['seed'])
    for item in m['selected']:
        folder = out/item['input_dir']
        for n,v in item['files'].items(): assert sha(folder/n)==v['sha256']
        rows = events(folder/'trace.jsonl')
        verify(rows)
        identity = DataIdentity.parse(item['identity'])
        identity.require_train()
        # Empty sidecars only: final-state replay is invalid for nonempty histories.
        assert not events(folder/'evidence.jsonl') and not events(folder/'claims.jsonl')
        e = EvidenceLedger(identity,storage_path=folder/'evidence.jsonl')
        c = ClaimLedger(e,storage_path=folder/'claims.jsonl')
        requests = [r['data']['request'] for r in rows if r['stage']=='model_request']
        mode = 'candidate' if 'M3' in item['arm'] else 'baseline'
        cache = ContextCache()
        for number,request in enumerate(requests):
            recorded = request['context']
            builder = ContextBuilder(identity,budget_bytes=recorded['budget_bytes'])
            question = canonical(request['task']['payload'])
            summary = recorded['entries']['entries'][0]['text'] if mode=='baseline' else None
            kw = dict(mode=mode,baseline_summary=summary)
            bundle = cache.get_or_build(builder,question,e,c,**kw)
            assert canonical(bundle.public_data())==canonical(recorded)
            assert canonical(dict(request,context=bundle.public_data()))==canonical(request)
            assert cache.get_or_build(builder,question,e,c,**kw) is bundle
            checks.append(dict(series=item['series'],cell=item['cell'],request=number,slot=request['slot'],
                exact_context=True,exact_request_with_other_fields_frozen=True,context_sha256=digest(recorded),
                request_sha256=digest(request),request_bytes=len(canonical(request).encode()),
                context_bytes=len(canonical(recorded).encode()),evidence_roots=len(e.roots()),claims=len(c.claims()),
                mode=mode,module_context_recomputed=False))
        # Consistently time first saved request after checking every saved request.
        request = requests[0]
        recorded = request['context']
        builder = ContextBuilder(identity,budget_bytes=recorded['budget_bytes'])
        question = canonical(request['task']['payload'])
        kw = dict(mode=mode,baseline_summary=recorded['entries']['entries'][0]['text'] if mode=='baseline' else None)
        cache = ContextCache()
        bundle = cache.get_or_build(builder,question,e,c,**kw)
        before = (e.snapshot().encoded,c.snapshot().encoded)
        def load_pair():
            ev = EvidenceLedger(identity,storage_path=folder/'evidence.jsonl')
            return ClaimLedger(ev,storage_path=folder/'claims.jsonl')
        ops = {
            'ledger_read_validate':lambda:(_JsonlLog(folder/'evidence.jsonl').events(),_JsonlLog(folder/'claims.jsonl').events()),
            'ledger_load_replay':load_pair,
            'dependency_refresh_noop':c.refresh_after_withdrawal,
            'R_builder_diagnostic':lambda:builder.build(question,e,c,**kw),
            'B_cache_object_cold':lambda:ContextCache().get_or_build(builder,question,e,c,**kw),
            'B_cache_hit':lambda:cache.get_or_build(builder,question,e,c,**kw),
            'bundle_hash':lambda:bundle.content_hash,
            'bundle_serialization':lambda:canonical(bundle.data()),
            'full_recorded_request_freeze':lambda:FrozenRecord.from_dict(request)}
        for repeat in range(m['repeats']):
            order = list(ops)
            rng.shuffle(order)
            for label in order:
                assert time.monotonic()<deadline,'batch deadline exceeded'
                start = time.perf_counter_ns()
                for _ in range(m['inner']): ops[label]()
                raw.append(dict(series=item['series'],cell=item['cell'],repeat=repeat,
                                operation=label,inner=m['inner'],elapsed_ns=time.perf_counter_ns()-start))
        prof = cProfile.Profile()
        prof.runcall(lambda:[ops['B_cache_hit']() for _ in range(100)])
        for (filename,line,name),(cc,nc,own,cumulative,callers) in pstats.Stats(prof).stats.items():
            if 'research_loop' in filename or name in ('dumps','loads','encode','decode'):
                profiles.append(dict(series=item['series'],cell=item['cell'],file=filename,line=line,function=name,
                                     calls=nc,self_seconds=own,cumulative_seconds=cumulative))
        tracemalloc.start()
        ops['B_cache_object_cold']()
        _,peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        checks.append(dict(series=item['series'],cell=item['cell'],python_peak_bytes=peak,
            peak_scope='one object-cold B call; excludes RSS and existing objects',cache_entries=cache.size(),
            historical_tool_wall_seconds=[r['data']['record'].get('wall_seconds') for r in rows if r['stage']=='execution_result'],
            historical_model_wait_seconds=None))
        assert before==(e.snapshot().encoded,c.snapshot().encoded)
        for n,v in item['files'].items(): assert sha(folder/n)==v['sha256'],'input mutated'
    for p,h in m['source_hashes'].items(): assert sha(REPO/p)==h
    with (output/'raw_timings.jsonl').open('x',encoding='utf-8') as f:
        for row in raw: f.write(canonical(row)+'\n')
    summary = []
    for key in sorted({(r['series'],r['cell'],r['operation']) for r in raw}):
        vals = [r['elapsed_ns']/r['inner']/1000 for r in raw if (r['series'],r['cell'],r['operation'])==key]
        summary.append(dict(series=key[0],cell=key[1],operation=key[2],samples=len(vals),
                            median_us=statistics.median(vals),min_us=min(vals),max_us=max(vals)))
    save(output/'summary.json',summary)
    save(output/'checks.json',checks)
    save(output/'profile.json',profiles)
    save(output/'environment.json',dict(python=sys.version,platform=platform.platform(),logical_cpus=os.cpu_count(),
        concurrency=1,filesystem_cache='not flushed',cpu_affinity='not pinned',other_host_activity='uncontrolled',
        manifest_sha256=sha(out/'manifest.json'),completed_at=datetime.now(timezone.utc).isoformat(),
        new_model_calls=0,new_paid_spend=0))
    print(json.dumps(dict(status='completed',timed_rows=len(raw),exact_requests=sum('request' in c for c in checks))))
def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['freeze','run','_worker'])
    p.add_argument('--run',default='r1')
    p.add_argument('--work',type=Path,default=Path('E:/_ryanDev/AI/research-loop-modular/work'))
    p.add_argument('--brief',type=Path,default=Path('C:/Users/Administrator/Downloads/week1_research_brief.md'))
    a = p.parse_args()
    assert a.run.replace('-','').isalnum()
    if a.action=='freeze': freeze(a)
    elif a.action=='_worker': worker(a)
    else:
        command = [sys.executable,'-B',str(Path(__file__)),'_worker','--run',a.run]
        env = dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
        try:
            r = subprocess.run(command,capture_output=True,text=True,timeout=60,env=env)
            receipt = dict(command=command,exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr)
        except subprocess.TimeoutExpired as exc:
            receipt = dict(command=command,exit_code=None,timeout=True,error=str(exc))
        save(HERE/a.run/'execution_receipt.json',receipt)
        print(json.dumps(receipt))
        if receipt.get('exit_code')!=0: raise SystemExit(1)
if __name__=='__main__': main()

