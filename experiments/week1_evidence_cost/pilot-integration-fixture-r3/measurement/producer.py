"""Exact pre-call replay and bounded B/R cost diagnostic; no new model calls."""
import argparse,hashlib,json,random,statistics,time,sys,tracemalloc
from pathlib import Path
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[1];sys.path.insert(0,str(REPO))
from research_loop.modular.contracts import DataIdentity,FrozenRecord
from research_loop.modular.modules.evidence import EvidenceLedger,ClaimLedger,_JsonlLog
from research_loop.modular.modules.context import ContextBuilder,ContextCache
from research_loop.modular.runtime import verify_trace
from research_loop.modular.artifact_catalogue import ArtifactCatalogue
from research_loop.modular.evidence_artifacts import verify_evidence_artifacts
from research_loop.ontology import canonical,digest
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):
 with p.open('x',encoding='utf-8',newline='\n') as f:f.write(json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
def run(name):
 root=HERE/name;m=read(root/'manifest.json');out=root/'measurement';out.mkdir()
 config={'schema':'week1-domain-replay-v1','source_sha256':sha(Path(__file__)),'manifest_sha256':sha(root/'manifest.json'),
 'repeats':30,'inner':10,'seed':20260921,'timeout_seconds':120,'candidate':None,
 'normalization':'none, exact canonical bytes','sample_units':'three frozen task opportunities, two broad source families'}
 save(out/'config.json',config)
 rng=random.Random(config['seed']);deadline=time.monotonic()+120;raw=[];checks=[];audits=[];denominator=[]
 for op in m['opportunity_ids']:
  folder=root/op
  status='complete' if (folder/'completion.json').exists() else 'failed' if (folder/'failure.json').exists() else 'unstarted_or_incomplete'
  denominator.append({'opportunity':op,'status':status})
  if not (folder/'runtime/trace.jsonl').exists():continue
  trace=verify_trace(folder/'runtime/trace.jsonl').data()
  first=json.loads((folder/'runtime/artifacts.jsonl').read_text(encoding='utf-8').splitlines()[0])['descriptor']
  catalogue=ArtifactCatalogue(folder/'runtime/artifacts.jsonl',identity=DataIdentity.parse(first['identity']),run_id=first['run_id'],
   experiment_id=first['experiment_id'],lock_digest=first['lock_digest'])
  audit=verify_evidence_artifacts(catalogue,folder/'runtime')
  audits.append({'opportunity':op,'trace':trace,'ledger_artifacts':audit.data() if isinstance(audit,FrozenRecord) else audit})
  for slot in ('plan','final'):
   call=folder/slot
   if not (call/'client-check.json').exists():continue
   req=read(call/'request.json');identity=DataIdentity.parse(req['task']['identity']);identity.require_train()
   def load_ledgers():
    e=EvidenceLedger(identity,storage_path=call/'evidence.jsonl')
    return e,ClaimLedger(e,storage_path=call/'claims.jsonl')
   e,c=load_ledgers();question=canonical(req['task']['payload'])
   builder=ContextBuilder(identity,budget_bytes=req['context']['budget_bytes']);cache=ContextCache()
   def build():return builder.build(question,e,c,mode='candidate')
   def B():return cache.get_or_build(builder,question,e,c,mode='candidate')
   def cold():return ContextCache().get_or_build(builder,question,e,c,mode='candidate')
   bundle=B();assert B() is bundle
   assert canonical(bundle.public_data())==canonical(req['context'])
   assert canonical(dict(req,context=bundle.public_data()))==canonical(req)
   assert (call/'prompt.txt').read_text(encoding='utf-8').split('\n',1)[1]==canonical(req)
   frozen=(sha(call/'evidence.jsonl'),sha(call/'claims.jsonl'))
   operations={'B_cache_hit':B,'B_object_cold':cold,'R_full_builder':build,
    'ledger_read_format_check':lambda:(_JsonlLog(call/'evidence.jsonl').events(),_JsonlLog(call/'claims.jsonl').events()),
    'ledger_load_semantic_replay':load_ledgers,'dependency_refresh_no_change':c.refresh_after_withdrawal,
    'bundle_hash_including_serialization':lambda:digest(bundle.data()),
    'bundle_serialize':lambda:canonical(bundle.data()),'public_context_expand':bundle.public_data,
    'full_request_freeze':lambda:FrozenRecord.from_dict(req)}
   tracemalloc.start();x=cold();_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
   checks.append({'opportunity':op,'slot':slot,'exact_context':True,'exact_request_other_fields_frozen':True,
    'prompt_matches_request':True,'evidence_roots':len(e.roots()),'claims':len(c.claims()),'context_bytes':len(canonical(req['context']).encode()),
    'request_bytes':len(canonical(req).encode()),'B_cold_python_tracemalloc_peak_bytes':peak,
    'scope':'peak Python allocations for one cold build only; not process RSS or full-system peak'})
   for repeat in range(config['repeats']):
    order=list(operations);rng.shuffle(order)
    for operation in order:
     if time.monotonic()>deadline:raise TimeoutError('frozen replay runtime budget')
     fn=operations[operation];t=time.perf_counter_ns()
     for _ in range(config['inner']):fn()
     elapsed=time.perf_counter_ns()-t
     raw.append({'opportunity':op,'slot':slot,'repeat':repeat,'operation':operation,'inner':config['inner'],'total_ns':elapsed,'ns_per_call':elapsed/config['inner']})
   assert frozen==(sha(call/'evidence.jsonl'),sha(call/'claims.jsonl'))
   assert canonical(B().public_data())==canonical(req['context'])
 save(out/'denominator.json',denominator);save(out/'checks.json',checks);save(out/'artifact-audit.json',audits)
 with (out/'timings.jsonl').open('x',encoding='utf-8') as f:
  for row in raw:f.write(json.dumps(row,sort_keys=True)+'\n')
 summary=[]
 for check in checks:
  rows=[r for r in raw if r['opportunity']==check['opportunity'] and r['slot']==check['slot']]
  for operation in sorted({r['operation'] for r in rows}):
   values=[r['ns_per_call'] for r in rows if r['operation']==operation]
   summary.append({'opportunity':check['opportunity'],'slot':check['slot'],'operation':operation,
    'median_us':statistics.median(values)/1000,'min_us':min(values)/1000,'max_us':max(values)/1000,'batch_count':len(values)})
 save(out/'summary.json',summary)
 print(json.dumps({'requests_checked':len(checks),'timing_batches':len(raw),'opportunities':denominator}))
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--run',default='domain-pilot-r1');run(a.parse_args().run)

