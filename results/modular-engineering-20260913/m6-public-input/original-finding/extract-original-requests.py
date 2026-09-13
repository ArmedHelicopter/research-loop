import hashlib,json,sys
from pathlib import Path
from zipfile import ZipFile
r=Path('E:/_ryanDev/AI/research-loop-modular/m6-public');sys.path.insert(0,str(r))
from research_loop.modular.contracts import FrozenRecord
out=r/'results/modular-engineering-20260913/m6-public-input/original-finding';out.mkdir(parents=True,exist_ok=True)
rows=[];archives={}
for name in ('q81-q84-production/frozen-grid.zip','q85-q86-q87-production/frozen02-runtime.zip'):
 p=r/'results/modular-engineering-20260913'/name;archives[name]=hashlib.sha256(p.read_bytes()).hexdigest();z=ZipFile(p)
 attempt=json.loads(z.read('run/controller-attempt.json'));cells={FrozenRecord.from_dict(c).content_hash:c for c in attempt['cell_plan']}
 for name2 in z.namelist():
  if not name2.endswith('trace.jsonl'):continue
  raw=z.read(name2);events=[json.loads(line) for line in raw.decode('utf-8').splitlines()]
  requests=[e['data']['request'] for e in events if e['stage']=='model_request']
  cell=cells[requests[-1]['module_context']['panel_cell']['cell_digest']]
  rows.append({'cell':cell,'archive':name,'member':name2,'trace_sha256':hashlib.sha256(raw).hexdigest(),'requests':requests})
assert len(rows)==156
(out/'actual-requests.json').write_text(json.dumps(rows,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
report={'review_base':'2e3d880bfe040c1af9766ed1064c0925e74550fb','archives':archives,'cells':len(rows),'requests':sum(len(x['requests']) for x in rows),'original_evidence_unchanged':True,'historical_complete_blinding_claim':False}
(out/'REVIEW.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(report)
for coverage,variant in [('Q8.1','adversarial'),('Q8.1','retrospective'),('Q8.4','shared_root'),('Q8.6','pause_new_version'),('Q8.7','untested'),('Q8.7','anomaly')]:
 row=next(row for row in rows if row['cell']['coverage_id']==coverage and row['cell']['variant']==variant and row['cell']['runtime_arm']['enabled'])
 print(coverage,variant)
 for q in row['requests']:
  def keys(v,path=''):
   if isinstance(v,dict):
    for k,x in v.items():
     print(path+'.'+k) if not isinstance(x,(list,dict)) else None
     keys(x,path+'.'+k)
   elif isinstance(v,list) and v:keys(v[0],path+'[]')
  print(q['slot']);keys(q['module_context'])
