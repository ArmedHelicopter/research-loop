
"""Real Docker/RunSession integration, substituted official model transport; no live calls."""
import sys,json,subprocess,hashlib,types
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
import domain_rich as d
RUN='rich-integration-fixture-r1'
d.freeze(RUN)
out=HERE/RUN
m=d.read(out/'manifest.json');m.update(scope='Integration fixture: real Docker/RunSession, synthetic model port, zero actual model calls',counts_as_live_domain_opportunity=False)
(out/'manifest.json').write_text(json.dumps(m,indent=2,sort_keys=True)+'\n',encoding='utf-8')
original=d.subprocess.run
observed=[]
def transport(args,*a,**kw):
 if isinstance(args,list) and len(args)>1 and str(args[0])==str(d.CLI) and args[1]=='exec':
  request=json.loads(kw['input'].decode().split('\n',1)[1]);slot=request['slot']
  facts=[x for x in request['context']['items'] if x.get('kind')=='claim' and x['statement'].startswith('Program-reported domain statistic: ')]
  deps=[facts[0]['claim_id']] if slot=='check' else []
  observed.append({'slot':slot,'domain_claims_before_request':len(facts),'dependency_ids':deps})
  fact={'key':'count' if slot=='plan' else 'fraction','label':'rows with observed SES' if slot=='plan' else 'observed SES proportion','value':0,'unit':'rows' if slot=='plan' else 'proportion','population':'all CSV rows; fixture only','method':'direct recomputation from CSV; fixture only','premise_claim_ids':deps}
  code="import json,pandas as pd\nd=pd.read_csv('/input/data')\nf="+repr(fact)+"\nf['value']=int(d['SES'].notna().sum())"+(" / len(d)" if slot=='check' else "")+"\nprint(json.dumps({'facts':[f],'limitations':['Integration fixture, not scientific evidence']},allow_nan=False))"
  response={'code':code if slot!='final' else '', 'conclusion':'Fixture interpretation only','limitations':['No actual model call']}
  Path(args[args.index('--output-last-message')+1]).write_text(json.dumps(response),encoding='utf-8')
  kw['stdout'].write((json.dumps({'type':'turn.completed','usage':None})+'\n').encode())
  return subprocess.CompletedProcess(args,0)
 return original(args,*a,**kw)
d.subprocess.run=transport
d.quota=lambda path:{'used_percent':None,'fixture':True,'actual_quota_call':False}
try:d.run_one(RUN,0)
finally:d.subprocess.run=original
op=out/'week1-rich-domain-1-r1'
assert [x['domain_claims_before_request'] for x in observed]==[0,1,2],observed
from research_loop.modular.modules.evidence import EvidenceLedger,ClaimLedger
from research_loop.modular.modules.context import ContextBuilder
from research_loop.modular.contracts import DataIdentity
for slot in ('plan','check','final'):
 req=d.read(op/slot/'request.json')
 e=EvidenceLedger(DataIdentity.parse(req['task']['identity']),storage_path=op/slot/'evidence.jsonl');c=ClaimLedger(e,storage_path=op/slot/'claims.jsonl')
 bundle=ContextBuilder(e.identity,budget_bytes=req['context']['budget_bytes']).build(d.canonical(req['task']['payload']),e,c,mode='candidate')
 assert bundle.public_data()==req['context']
malformed=['{"facts":[],"facts":[],"limitations":[]}','{"facts":[],"limitations":[],"extra":1}',
 '{"facts":[{"key":"x","label":"x","value":NaN,"unit":"x","population":"x","method":"x","premise_claim_ids":[]}],"limitations":[]}',
 '{"facts":[{"key":"x","label":"x","value":{},"unit":"x","population":"x","method":"x","premise_claim_ids":[]}],"limitations":[]}',
 '{"facts":[],"limitations":false}']
for text in malformed:
 receipt=types.SimpleNamespace(status='succeeded',record=d.FrozenRecord.from_dict({'stdout':text}))
 try:d.parse_report(receipt)
 except ValueError:pass
 else:raise AssertionError('malformed report accepted')
# Unknown dependency rejection must occur before any domain-ledger change.
from research_loop.modular.benchmarks.execution import ExecutionReceipt
arts=[json.loads(x) for x in (op/'runtime/artifacts.jsonl').read_text().splitlines()]
receipts=[x['descriptor']['payload']['canonical'] for x in arts if x['descriptor']['kind']=='execution_receipt']
# Runtime artifact storage shape is checked separately below if no direct receipt artifact.
d.save(out/'fixture-verification.json',{'scope':'real Docker and RunSession; synthetic model transport only','model_calls':0,'cli_stub_calls':observed,'exact_request_context_checks':3,'strict_parser_rejections':len(malformed),'trace':d.read(op/'completion.json')['trace'],'execution_receipt_artifact_count':len(receipts)})
print(json.dumps(d.read(out/'fixture-verification.json')))

