
import sys,json,types,dataclasses
from pathlib import Path
p=Path('experiments/week1_evidence_cost');sys.path.insert(0,str(p.resolve()))
import domain_rich as d
from research_loop.modular.benchmarks.execution import ExecutionReceipt
from research_loop.modular.modules.evidence import EvidenceLedger,ClaimLedger
from research_loop.modular.contracts import PublicTask,DataIdentity
out=p/'rich-integration-fixture-r2';folder=out/'week1-rich-domain-1-r1'
events=[json.loads(x) for x in (folder/'runtime/trace.jsonl').read_text().splitlines()]
receipts=[ExecutionReceipt.parse(x['data']['receipt']) for x in events if x['stage']=='execution_result']
item=d.read(out/'manifest.json')['items'][0]
request=d.read(folder/'final/request.json');task=PublicTask.create(DataIdentity.parse(request['task']['identity']),request['task']['payload'])
e=EvidenceLedger(task.identity);c=ClaimLedger(e)
for name,obj in [('evidence',e),('claims',c)]:
 for line in (folder/'runtime'/(name+'.jsonl')).read_text().splitlines():obj._apply_event(json.loads(line),persist=False)
session=types.SimpleNamespace(task=task,evidence=e,claims=c)
exact=0
for label,receipt in [('primary',receipts[1]),('qualification',receipts[2])]:
 report=d.parse_report(receipt)
 mapping=d.read(folder/(label+'-domain-bindings.json'))
 for f,b in zip(report['facts'],mapping['facts'],strict=True):
  root=e.record(b['root_id']);body=root.payload.data()
  assert body['content']['fact']==f
  assert body['root_material']['fact_digest']==d.digest(f)
  assert body['root_material']['program_sha256']==receipt.artifact.sha256
  assert body['root_material']['execution_digest']==receipt.content_hash
  assert body['root_material']['json_pointer']==b['json_pointer']
  assert report['facts'][int(b['json_pointer'].split('/')[-1])]==f
  claim=next(x for x in c.claims() if x.claim_id==b['claim_id'])
  assert list(claim.depends_on)==b['depends_on']
  if b['depends_on']:assert claim.needs_review is True
  exact+=1
before=(e.snapshot(),c.snapshot());bad=[]
report=d.parse_report(receipts[2]);report['facts'][0]['premise_claim_ids']=['unknown']
body=receipts[2].record.data();body['stdout']=json.dumps(report)
bad.append(dataclasses.replace(receipts[2],record=d.FrozenRecord.from_dict(body)))
bad.append(dataclasses.replace(receipts[2],artifact=dataclasses.replace(receipts[2].artifact,sha256='0'*64)))
body=receipts[2].record.data();body['input_artifacts']['data']['sha256']='0'*64
bad.append(dataclasses.replace(receipts[2],record=d.FrozenRecord.from_dict(body)))
bad.append(dataclasses.replace(receipts[2],status='failed'))
for receipt in bad:
 try:d.register_report(session,receipt,item,'qualification',folder)
 except ValueError:pass
 else:raise AssertionError('bad evidence accepted')
 assert before==(e.snapshot(),c.snapshot())
d.save(out/'binding-negative-checks.json',{'exact_fact_pointer_receipt_program_bindings':exact,'invalid_input_cases_rejected_without_ledger_mutation':len(bad),'dependent_claim_needs_review':True,'model_calls':0,'fixture_only':True})
print('2 exact fact bindings; 4 negative input checks preserved ledgers; native dependency needs_review confirmed.')

