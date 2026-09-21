
"""Independent binding/count/timing audit of the completed richer TRAIN workflow."""
import sys,json,hashlib
from pathlib import Path
P=Path(__file__).resolve().parent;sys.path[:0]=[str(P),str(P.parents[1])]
import domain_rich as d
from research_loop.modular.benchmarks.execution import ExecutionReceipt
from research_loop.modular.modules.evidence import EvidenceLedger,ClaimLedger
from research_loop.modular.modules.context import ContextBuilder
def run(series,op):
 base=P/series;folder=base/op;m=d.read(base/'manifest.json');completion=d.read(folder/'completion.json')
 assert completion['status']=='completed'
 item=m['items'][0];identity=d.DataIdentity.parse(item['identity']);identity.require_train()
 trace=[json.loads(x) for x in (folder/'runtime/trace.jsonl').read_text(encoding='utf-8-sig').splitlines()]
 receipts={}
 for event in trace:
  if event['stage']!='execution_result':continue
  r=ExecutionReceipt.parse(event['data']['receipt']);assert r.content_hash==event['data']['execution_digest']
  assert r.identity==identity and r.record.data()['input_artifacts']['data']['sha256']==item['csv_sha256']
  assert r.artifact and d.sha(Path(r.artifact.path))==r.artifact.sha256
  receipts[r.content_hash]=r
 assert len(receipts)==3
 e=EvidenceLedger(identity,storage_path=folder/'runtime/evidence.jsonl');c=ClaimLedger(e,storage_path=folder/'runtime/claims.jsonl')
 claimmap={x.claim_id:x for x in c.claims()};facts=[];edges=0
 for label in ('primary','qualification'):
  mapping=d.read(folder/(label+'-domain-bindings.json'));r=receipts[mapping['execution_digest']]
  raw=r.record.data()['stdout'];report=json.loads(raw)
  assert hashlib.sha256(raw.encode()).hexdigest()==mapping['stdout_sha256']
  assert len(mapping['facts'])==len(report['facts'])
  for b in mapping['facts']:
   i=int(b['json_pointer'].split('/')[-1]);f=report['facts'][i]
   assert b['json_pointer']=='/facts/'+str(i) and d.digest(f)==b['fact_digest']
   root=e.record(b['root_id']);payload=root.payload.data();material=payload['root_material'];claim=claimmap[b['claim_id']]
   assert payload['content']['fact']==f and payload['content']['scientific_validated'] is False
   assert material=={'identity':identity.data(),'csv_sha256':item['csv_sha256'],'program_sha256':r.artifact.sha256,'execution_digest':r.content_hash,'json_pointer':b['json_pointer'],'fact_digest':d.digest(f)}
   statement=json.loads(claim.statement.removeprefix('Program-reported domain statistic: '))
   for k in ('label','value','unit','population','method'):assert statement[k]==f[k]
   assert statement['execution_digest']==r.content_hash and statement['json_pointer']==b['json_pointer']
   assert list(claim.support_roots)==[b['root_id']] and list(claim.depends_on)==b['depends_on']==sorted(f['premise_claim_ids'])
   if claim.depends_on:assert claim.needs_review
   edges+=len(claim.depends_on)
   facts.append({'stage':label,'claim_id':claim.claim_id,'fact':f,'needs_review':claim.needs_review})
 requests=[];usage=[]
 for slot in m['slots']:
  req=d.read(folder/slot/'request.json')
  se=EvidenceLedger(identity,storage_path=folder/slot/'evidence.jsonl');sc=ClaimLedger(se,storage_path=folder/slot/'claims.jsonl')
  bundle=ContextBuilder(identity,budget_bytes=req['context']['budget_bytes']).build(d.canonical(req['task']['payload']),se,sc,mode='candidate')
  assert bundle.public_data()==req['context']
  assert (folder/slot/'prompt.txt').read_text(encoding='utf-8-sig').split('\n',1)[1]==d.canonical(req)
  check=d.read(folder/slot/'client-check.json');assert check['turn_completed'] and check['unexpected_tool_items']==0
  usage.extend(check['usage'])
  allids={x.claim_id for x in sc.claims() if x.statement.startswith('Program-reported domain statistic: ')}
  visible={x['claim_id'] for x in req['context']['entries']['entries'] if x['kind']=='claim'} & allids
  requests.append({'slot':slot,'roots':len(se.roots()),'claims':len(sc.claims()),'domain_claims':len(allids),'visible_domain_claims':len(visible),'context_bytes':len(d.canonical(req['context']).encode()),'budget_bytes':req['context']['budget_bytes']})
 timing=d.read(folder/'timing.json')
 totals={}
 for row in timing:totals[row['operation']]=totals.get(row['operation'],0)+row['ns']
 q=totals.get('B_context_get_or_build',0)+totals.get('dependency_refresh',0)
 client=sum(v for k,v in totals.items() if k.startswith('official_client_'));tool=sum(v for k,v in totals.items() if k.startswith('tool_'))
 writes=sum(v for k,v in totals.items() if k.startswith('evidence_and_claim_append_') or k.startswith('register_domain_'))
 out={'status':'complete_binding_audit','new_operation_sequences':1,'new_independent_tasks':0,'source_families_in_this_run':1,'exact_context_checks':3,'exact_domain_fact_bindings':len(facts),'declared_dependency_edges':edges,
  'requests':requests,'facts':facts,'known_client_turn_usage':usage,'actual_client_invocations':3,
  'historical_operations_ms':{k:round(v/1e6,6) for k,v in totals.items()},'historical_context_and_refresh_ms':q/1e6,
  'historical_client_tool_ms':(client+tool)/1e6,'historical_domain_and_execution_registration_ms':writes/1e6,
  'query_fraction_of_client_plus_tool_percent':100*q/(client+tool),'registration_fraction_of_client_plus_tool_percent':100*writes/(client+tool),
  'timing_note':'Ratios compare measured components in this observed B workflow; not a counterfactual speedup or sum of nested wall times.',
  'scientific_validated':False,'native_AND':'unsupported; not manufactured','statistical_correctness_independently_validated':False}
 d.save(folder/'binding-and-cost-audit.json',out)
 print(json.dumps({k:v for k,v in out.items() if k not in ('facts','historical_operations_ms','known_client_turn_usage')}))
if __name__=='__main__':run(sys.argv[1],sys.argv[2])

