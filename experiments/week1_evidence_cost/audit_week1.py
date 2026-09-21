
"""Finite requirement evidence inventory. It reports gaps; does not declare goal completion."""
import json,hashlib,sys,subprocess
from pathlib import Path
from datetime import datetime,timezone
P=Path(__file__).resolve().parent;ROOT=P.parents[1]
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):
 with p.open('x',encoding='utf-8',newline='\n') as f:f.write(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
CASES=[('domain-pilot-r1','week1-domain-1-r1'),('domain-pilot-r2','week1-domain-2-r2'),('domain-pilot-r2','week1-domain-3-r2'),('domain-pilot-r3','week1-domain-1-r3'),('domain-rich-r1','week1-rich-domain-1-r1'),('domain-rich-r2','week1-rich-domain-1-r2')]
def run():
 output=P/'requirement-audit-r1';output.mkdir()
 registry=[];turns=0;prompt_checks=0;input_tokens=0;output_tokens=0
 for series,op in CASES:
  p=P/series/op;m=read(P/series/'manifest.json')
  started=(p/'started.json').exists()
  state='controller_completed' if (p/'completion.json').exists() else 'controller_failed' if (p/'failure.json').exists() else 'incomplete'
  calls=[]
  for slot in m['slots']:
   call=p/slot
   if not (call/'dispatch.json').exists():continue
   dispatch=read(call/'dispatch.json');assert dispatch['prompt_sha256']==sha(call/'prompt.txt');prompt_checks+=1
   done=[]
   if (call/'events.jsonl').exists():
    done=[json.loads(l) for l in (call/'events.jsonl').read_text(encoding='utf-8').splitlines() if l and json.loads(l).get('type')=='turn.completed']
   turns+=len(done)
   for x in done:
    usage=x.get('usage') or {};input_tokens+=usage.get('input_tokens',0);output_tokens+=usage.get('output_tokens',0)
   calls.append({'slot':slot,'completed_client_turns':len(done)})
  row={'series':series,'opportunity':op,'started':started,'control_status':state,'dispatches':calls}
  if 'rich' in series:
   for label in ('primary','qualification'):
    f=p/(label+'-domain-bindings.json');row[label+'_complete_binding_manifest']=f.exists()
    row[label+'_fact_count']=len(read(f)['facts']) if f.exists() else None
   row['domain_qualification_measured']=bool(row['qualification_fact_count'])
  registry.append(row)
 for series in {x[0] for x in CASES}:
  m=read(P/series/'manifest.json')
  for name,h in m['core_sha256'].items():assert sha(ROOT/name)==h,(series,name)
 index=read(P/'qualification/r4/public-index.json')
 for item in index:
  assert item['identity']['domain']=='train'
  for key in ('csv','public'):assert sha(Path(item[key+'_path']))==item[key+'_sha256']
 native=read(P/'S-native-r1/result.json')
 rbs=read(P/'RBS-replay-r1/measurement/result.json')
 checks={
  'scope':'bounded DiscoveryBench social-science TRAIN workload, no claims of benchmark accuracy',
  'brief_sha256':sha(Path('C:/Users/Administrator/Downloads/week1_research_brief.md')),
  'initial_brief_hash_matches':sha(Path('C:/Users/Administrator/Downloads/week1_research_brief.md'))==read(P/'r1/manifest.json')['brief']['sha256'],
  'controller_registry':registry,'original_started_opportunities':sum(x['started'] for x in registry),
  'superseded_before_io_retained':read(P/'delivery-audit.json')['superseded_before_io'],
  'actual_official_client_completed_turns':turns,'prompt_hash_checks':prompt_checks,
  'reported_client_input_tokens':input_tokens,'reported_client_output_tokens':output_tokens,
  'tokens_scope':'observed official client turns only; not root/review usage, pure model billing or quota conversion',
  'distinct_real_tasks':len({x['identity']['task_id'] for x in index}),'broad_source_families':2,
  'all_current_input_hashes_match':True,'all_frozen_core_hashes_match':True,
  'solver_labels_present':(ROOT/'data/labels').exists(),
  'native_differential_checks':native['native_differential_checks'],'native_mismatches':native['native_R_B_S_mismatches'],
  'AND_implementation_satisfied':False,'AND_case_examined_with_counterexample':(P/'S-native-r1/and-capability-gap.json').exists(),
  'original_RBS_replay':rbs,
  'new_candidate_implemented':False,'candidate_gate':'No observed meaningful query/context bottleneck or C distinction from ordinary S. Conditional D4 not entered.',
  'scientific_validation_performed':False,'formal_VAL_answers_read':False,
  'open_before_final_decision':['verify new rich replay result and instrumentation boundary','decide whether negative AND capability finding satisfies D3 investigation without implementing new semantics','review all named deliverables before closing goal'],
  'recorded_at':datetime.now(timezone.utc).isoformat()
 }
 save(output/'inventory.json',checks)
 print(json.dumps({k:checks[k] for k in ('original_started_opportunities','actual_official_client_completed_turns','prompt_hash_checks','distinct_real_tasks','AND_implementation_satisfied')}))
if __name__=='__main__':run()

