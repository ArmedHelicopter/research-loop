"""Bounded official-client TRAIN pilot; exact pre-call M2/M3 contexts, no scoring."""
from __future__ import annotations
import argparse,hashlib,json,os,subprocess,sys,time,shutil,traceback,math
from datetime import datetime,timezone
from pathlib import Path
HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
sys.path.insert(0,str(REPO))
from research_loop.modular.contracts import DataIdentity,FrozenRecord,PublicTask
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.runtime import RunSession,AuditVerifier,verify_trace
from research_loop.modular.modules.context import ContextCache
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.ontology import canonical,digest
WORK=Path('E:/_ryanDev/AI/research-loop-modular/work')
INPUT=HERE/'qualification/r4/public-index.json'
CLI=Path('C:/Users/Administrator/AppData/Roaming/npm/node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe')
IMAGE='research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349'
SOURCES=['research_loop/modular/runtime.py','research_loop/modular/contracts.py','research_loop/modular/modules/context.py','research_loop/modular/modules/evidence.py','research_loop/modular/benchmarks/execution.py','research_loop/ontology.py']
PROFILE="""import pandas as pd,json
d=pd.read_csv('/input/data')
p={'rows':len(d),'columns':{}}
for c in d:
 s=d[c]; v={'dtype':str(s.dtype),'missing':int(s.isna().sum()),'unique':int(s.nunique())}
 if pd.api.types.is_numeric_dtype(s):
  v.update(min=float(s.min()) if s.notna().any() else None,max=float(s.max()) if s.notna().any() else None)
 else:v['examples']=[str(x)[:100] for x in s.dropna().unique()[:3]]
 p['columns'][str(c)]=v
print(json.dumps(p,allow_nan=False))
"""
PLAN="""Write a complete Python analysis program for the public research question. Read only /input/data CSV. It is a single regular CSV file mounted at this exact path, not a directory. Use pd.read_csv('/input/data'); do not search for the metadata filename. Available: pandas, numpy, scipy, statsmodels. No network, no installs, no other input. CPU 1, memory 1GB, 60 seconds. Print one compact JSON object under 9000 characters. Use the observed profile to choose sensible missing/sentinel handling; report sample counts, descriptive effect sizes and limitations. Distinguish association from causality. Check actual indicator labels, never substitute a different outcome silently. No benchmark answers available. Return code without markdown in the code field; conclusion and limitations describe the planned analysis, not invented results. Do not call tools yourself."""
FINAL="""Interpret the actual profile and analysis execution output in this request. Answer the research question with concrete numbers where available, note missing data, outcome/indicator mismatches and uncertainty. Failed code is a failed opportunity: report the limitation, do not pretend it succeeded. The ledger validator validates recorded execution only; scientific truth is not established. Cite evidence root IDs in your conclusion. Set code to an empty string; do not call tools or write another program."""
SCHEMA={'type':'object','properties':{'code':{'type':'string'},'conclusion':{'type':'string'},'limitations':{'type':'array','items':{'type':'string'}}},'required':['code','conclusion','limitations'],'additionalProperties':False}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def save(p,x):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('x',encoding='utf-8',newline='\n') as f:f.write(json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
def quota(out):
 r=subprocess.run([sys.executable,'-B',str(HERE/'quota_check.py'),str(out)],capture_output=True,text=True,encoding='utf-8',timeout=60)
 if r.returncode:raise RuntimeError('quota helper failed')
 q=read(out/'receipt.json')
 if q['status']!='read_success' or q['account_type']!='chatgpt':raise RuntimeError('subscription identity unavailable')
 w=q['rate_limits']['codex']['primary']
 if w['windowDurationMins']!=10080 or w['resetsAt']!=1790579847 or w['usedPercent']>=61:raise RuntimeError('frozen quota boundary reached or changed')
 return {'used_percent':w['usedPercent'],'observed_at_utc':q['observed_at_utc']}

REPORT_CONTRACT="""Print exactly one finite JSON object, <=12000 characters, with keys facts, limitations.
facts is a list of at most 8 objects, each with exactly: key (unique short identifier),
label (measured variable or contrast), value (finite number, boolean, string or null),
unit (string), population (explicit analysis sample and n), method (specific calculation),
premise_claim_ids (list of existing claim IDs actually used to define or interpret this check).
Use [] if no actual prior claim is a premise; never invent links to inflate a graph.
These are program-reported statistics, not established scientific truth.
No causal claims. Do not force significance. limitations is a list of strings.
Use json.dumps(...,allow_nan=False); round sensibly and handle undefined statistics with null."""
PLAN=PLAN+"\n"+REPORT_CONTRACT+"\nThis is the primary observational analysis; all premise_claim_ids must be []."
CHECK="""Write a Python program that performs one scientifically relevant qualification or sensitivity check on the preceding primary analysis, using only /input/data and the observed profile. /input/data is one regular CSV file, not a directory. Open pd.read_csv('/input/data') directly; the metadata filename is not mounted. Do not catch execution errors and disguise them as an inapplicable empty report; let unexpected errors fail the execution.
Select exactly one appropriate family from this predeclared menu: (1) sensitivity to missing/sentinel sample handling, (2) sensitivity to SES operationalization/functional form, (3) descriptive adjustment for observed demographic or academic covariates with explicit noncausal interpretation. State which family and why. Freeze the chosen method in the emitted program before execution; no post-result replacement. If none is defensible, report that gap.
Do not manufacture dependency changes or withdraw evidence.
Recompute quantities from the CSV. Do not just copy the prior output as a result.
If comparing to a previous program-reported statistic, cite its exact claim ID in premise_claim_ids and explain the relationship in method.
A dependency records a model-declared interpretive relationship, not verified logical entailment or AND support.
No network, installs or tools. pandas/numpy/scipy/statsmodels; CPU 1, memory 1GB, 60 seconds.
Return program in code and describe the planned check in conclusion/limitations. If no check is defensible, print facts:[] with the actual reason.
"""+REPORT_CONTRACT
FINAL=FINAL+"""
Separate the primary result from the actual qualification/sensitivity result. Cite claim IDs and evidence root IDs, preserving population/method qualifiers.
Supported ledger status means faithfully recorded program output only. Declared dependencies do not prove joint support or scientific validity.
Do not claim that rerunning statistics establishes the benchmark answer or a causal effect."""

def parse_report(receipt):
 if receipt.status!='succeeded':raise ValueError('domain analysis did not succeed')
 text=receipt.record.data()['stdout']
 if len(text)>12000:raise ValueError('domain report too long')
 def pairs(xs):
  out={}
  for k,v in xs:
   if k in out:raise ValueError('duplicate JSON key')
   out[k]=v
  return out
 def reject(x):raise ValueError('nonfinite JSON')
 report=json.loads(text,object_pairs_hook=pairs,parse_constant=reject)
 if not isinstance(report,dict) or set(report)!={'facts','limitations'}:raise ValueError('report keys')
 if not isinstance(report['limitations'],list) or any(not isinstance(x,str) for x in report['limitations']):raise ValueError('limitations')
 facts=report['facts']
 if not isinstance(facts,list) or len(facts)>8:raise ValueError('facts count')
 keys=set()
 for f in facts:
  if not isinstance(f,dict) or set(f)!={'key','label','value','unit','population','method','premise_claim_ids'}:raise ValueError('fact keys')
  for k in ('key','label','unit','population','method'):
   if not isinstance(f[k],str) or not f[k].strip() or len(f[k])>1200:raise ValueError('fact text')
  if f['key'] in keys:raise ValueError('duplicate fact key')
  keys.add(f['key'])
  if type(f['value']) not in (str,int,float,bool,type(None)):raise ValueError('fact value')
  if isinstance(f['value'],float) and not math.isfinite(f['value']):raise ValueError('nonfinite value')
  ids=f['premise_claim_ids']
  if not isinstance(ids,list) or any(not isinstance(x,str) for x in ids) or len(set(ids))!=len(ids):raise ValueError('premises')
 return report

def register_report(session,receipt,item,label,folder):
 # Validate the entire report and all prior dependencies before any domain mutation.
 report=parse_report(receipt);prior={c.claim_id:c for c in session.claims.claims()}
 bindings={'dataset_sha256':item['csv_sha256']}
 body=receipt.record.data()
 if receipt.artifact is None or receipt.artifact.identity!=session.task.identity or sha(Path(receipt.artifact.path))!=receipt.artifact.sha256:raise ValueError('program binding')
 if receipt.identity!=session.task.identity or body['input_artifacts']['data']['sha256']!=item['csv_sha256']:raise ValueError('receipt binding')
 for f in report['facts']:
  for dep in f['premise_claim_ids']:
   if dep not in prior or dict(prior[dep].subject_bindings)!=bindings or not prior[dep].statement.startswith('Program-reported domain statistic: '):raise ValueError('invalid domain premise')
  if label=='primary' and f['premise_claim_ids']:raise ValueError('primary has no prior domain premises')
 links=[]
 for i,f in enumerate(report['facts']):
  pointer='/facts/'+str(i)
  material={'identity':session.task.identity.data(),'execution_digest':receipt.content_hash,'program_sha256':receipt.artifact.sha256,'csv_sha256':item['csv_sha256'],'json_pointer':pointer,'fact_digest':digest(f)}
  root=session.evidence.append({'kind':'measurement','root_material':material,'representation':'raw',
   'content':{'stage':label,'fact':f,'json_pointer':pointer,'scientific_validated':False,
    'validation_scope':'exact program output and input/receipt binding only; statistics and dependency entailment not independently validated'},
   'subject_bindings':bindings,'independent_group':session.task.identity.group_id},
   {'trusted_validator':'week1-program-output-binding-only','validator_verified':True,'admitted':True})
  statement='Program-reported domain statistic: '+canonical({'stage':label,'label':f['label'],'value':f['value'],'unit':f['unit'],'population':f['population'],'method':f['method'],'execution_digest':receipt.content_hash,'json_pointer':pointer})
  claim=session.claims.create(statement,subject_bindings=bindings)
  revised=session.claims.apply(claim.claim_id,{'supports':[root.root_id],'refutes':[],'subject_bindings':bindings},expected_revision=0).claim
  if f['premise_claim_ids']:revised=session.claims.link_dependencies(claim.claim_id,f['premise_claim_ids'],expected_revision=revised.revision).claim
  links.append({'key':f['key'],'claim_id':claim.claim_id,'root_id':root.root_id,'json_pointer':pointer,'fact_digest':digest(f),'depends_on':list(revised.depends_on)})
 save(folder/(label+'-domain-bindings.json'),{'execution_digest':receipt.content_hash,'stdout_sha256':hashlib.sha256(body['stdout'].encode()).hexdigest(),'facts':links,'scientific_validated':False,'dependency_status':'model-declared, not independently validated'})
 return links

def freeze(run):
 out=HERE/run;out.mkdir()
 items=read(INPUT)[:1]
 for i in items:
  DataIdentity.parse(i['identity']).require_train()
  for field in ('csv','public'):assert sha(Path(i[field+'_path']))==i[field+'_sha256']
 save(out/'schema.json',SCHEMA)
 save(out/'domain-output-contract.json',{'schema':'strict-program-report-v1','max_stdout_characters':12000,'max_facts':8,'allowed_pointers':['/facts/'+str(i) for i in range(8)],'required_report_keys':['facts','limitations'],'required_fact_keys':['key','label','value','unit','population','method','premise_claim_ids'],'value_types':['string','finite_number','boolean','null'],'duplicate_json_keys':'reject','primary_dependencies':'empty','later_dependencies':'existing same-subject program-reported domain statistics only','scientific_validation':False,'strict_parser_source_sha256':sha(Path(__file__))})
 save(out/'manifest.json',{'schema':'week1-real-domain-pilot-v1','frozen_at':datetime.now(timezone.utc).isoformat(),
  'base_commit':subprocess.check_output(['git','-C',str(REPO),'rev-parse','HEAD'],text=True).strip(),
  'source_sha256':sha(Path(__file__)),'quota_helper_sha256':sha(HERE/'quota_check.py'),
  'core_sha256':{p:sha(REPO/p) for p in SOURCES},'input_index_sha256':sha(INPUT),'items':items,
  'model':'gpt-6-astra','reasoning_effort':'low','official_cli_sha256':sha(CLI),'cli_version':subprocess.check_output([str(CLI),'--version'],text=True).strip(),
  'image':IMAGE,'slots':['plan','check','final'],'max_new_trajectories':1,'max_client_invocations':3,'allowed_indices':[0],'predecessor':'Five previous live opportunities: three initial completed analyses, one controller failure, and a richer controller-complete workflow with failed qualification. Sixth and final original opportunity; only mounted-file instruction and explicit failure wording changed.',
  'client_timeout_seconds':240,'tool_timeout_seconds':60,'context_budget_bytes':60000,
  'profile_code':PROFILE,'instructions':{'plan':PLAN,'check':CHECK,'final':FINAL},'response_schema_sha256':sha(out/'schema.json'),'domain_contract_sha256':sha(out/'domain-output-contract.json'),
  'stop_used_percent':61,'reset_epoch':1790579847,'paid_spend_limit':0,
  'scope':'Official client feasibility pilot, not bare-model or official leaderboard reproduction. Raw execution visibility is not scientific validation.',
  'normalization':'none; exact canonical context and requests','selection':'single preselected existing TRAIN NLS SES question; no score-based selection',
  'opportunity_ids':['week1-rich-domain-'+str(i+1)+'-r2' for i in range(1)]})
 shutil.copyfile(Path(__file__),out/'producer.py')
 print(json.dumps({'frozen':str(out),'manifest_sha256':sha(out/'manifest.json')}))
class TimedCache(ContextCache):
 def __init__(self,timings):super().__init__();self.timings=timings
 def get_or_build(self,*a,**kw):
  t=time.perf_counter_ns()
  try:return super().get_or_build(*a,**kw)
  finally:self.timings.append({'operation':'B_context_get_or_build','ns':time.perf_counter_ns()-t})
def run_one(run,index):
 out=HERE/run;m=read(out/'manifest.json')
 assert m['source_sha256']==sha(Path(__file__))
 assert m['quota_helper_sha256']==sha(HERE/'quota_check.py')
 assert m['response_schema_sha256']==sha(out/'schema.json')
 assert m['domain_contract_sha256']==sha(out/'domain-output-contract.json')
 assert sha(REPO/'tests/test_label_isolation.py')==read(HERE/'isolation-check.json')['test_file_sha256']
 assert not (REPO/'data/labels').exists()
 assert m['official_cli_sha256']==sha(CLI)
 for p,h in m['core_sha256'].items():assert sha(REPO/p)==h
 assert index in m['allowed_indices'],'index not in this frozen continuation'
 item=m['items'][index];op=m['opportunity_ids'][index]
 folder=out/op;folder.mkdir()
 private=WORK/(run+'-operations')/op;private.mkdir(parents=True)
 timing=[];start=time.perf_counter_ns();session=None
 try:
  qbefore=quota(private/'before')
  save(folder/'started.json',{'opportunity_id':op,'manifest_sha256':sha(out/'manifest.json'),'time':datetime.now(timezone.utc).isoformat()})
  for f in ('csv','public'):assert sha(Path(item[f+'_path']))==item[f+'_sha256']
  packet=read(Path(item['public_path']))['task']
  task=PublicTask.create(DataIdentity.parse(packet['identity']),packet['payload'])
  objective=FrozenRecord.from_dict({'question':item['question'],'scope':'bounded TRAIN observational analysis, no scoring'})
  t=time.perf_counter_ns()
  session=RunSession(task,package_digest=sha(out/'manifest.json'),arm=default_compatibility(digest({'week1':'pilot'})).arm(['M2','M3']),
   objective=objective,slots=('plan','check','final'),execution_limit=3,sidecar=folder/'runtime',verifier=AuditVerifier({'unused1':os.urandom(32),'unused2':os.urandom(32)}),
   required_audit=('not_performed',),context_budget=m['context_budget_bytes'],experiment_id=op)
  timing.append({'operation':'session_startup','ns':time.perf_counter_ns()-t})
  session.cache=TimedCache(timing)
  refresh=session.claims.refresh_after_withdrawal
  def timed_refresh():
   t=time.perf_counter_ns()
   try:return refresh()
   finally:timing.append({'operation':'dependency_refresh','ns':time.perf_counter_ns()-t})
  session.claims.refresh_after_withdrawal=timed_refresh
  broker=DockerExecutionBroker([folder/'runtime',Path(item['csv_path']).parent])
  def execute(code,label):
   t=time.perf_counter_ns()
   receipt=session.execute(code,broker=broker,image=IMAGE,inputs={'data':Path(item['csv_path'])},timeout_seconds=60)
   timing.append({'operation':'tool_'+label,'ns':time.perf_counter_ns()-t,'status':receipt.status})
   return receipt
  def append_execution(receipt,label):
   body=receipt.record.data()
   # Only an observed, identity-bound execution is admitted for model visibility.
   assert receipt.identity==task.identity and body['input_artifacts']['data']['sha256']==item['csv_sha256']
   t=time.perf_counter_ns()
   root=session.evidence.append({'kind':'observation','root_material':{'execution_digest':receipt.content_hash,'csv_sha256':item['csv_sha256']},
    'representation':'raw','content':{'stage':label,'status':receipt.status,'stdout':body.get('stdout',''),'stderr':body.get('stderr',''),
      'validation_scope':'identity, input hash, original execution receipt only','scientific_validated':False},
    'subject_bindings':{'dataset_sha256':item['csv_sha256']},'independent_group':task.identity.group_id},
    {'trusted_validator':'week1-execution-receipt-only','validator_verified':True,'admitted':True})
   claim=session.claims.create('The recorded '+label+' execution has status '+receipt.status+'. This asserts execution only.',
    subject_bindings={'dataset_sha256':item['csv_sha256']})
   session.claims.apply(claim.claim_id,{'supports':[root.root_id],'refutes':[],'subject_bindings':{'dataset_sha256':item['csv_sha256']}},expected_revision=0)
   timing.append({'operation':'evidence_and_claim_append_'+label,'ns':time.perf_counter_ns()-t})
  profile=execute(PROFILE,'profile')
  if profile.status!='succeeded':raise RuntimeError('profile execution failed')
  json.loads(profile.record.data()['stdout'])
  append_execution(profile,'profile')
  def model(request):
   port_started=time.perf_counter_ns()
   slot=request.data()['slot'];call=folder/slot;call.mkdir()
   # Snapshot before I/O, not final-state reconstruction after the model finished.
   for name in ('evidence','claims'):shutil.copyfile(folder/'runtime'/(name+'.jsonl'),call/(name+'.jsonl'))
   save(call/'request.json',request.data())
   prompt='Analyze only the following immutable public TRAIN request. Return the required JSON object. No tools or external sources.\n'+request.encoded
   (call/'prompt.txt').write_text(prompt,encoding='utf-8',newline='\n')
   q0=quota(private/(slot+'-before'))
   args=[str(CLI),'exec','--ignore-user-config','--ephemeral','--skip-git-repo-check','--sandbox','read-only',
    '--model',m['model'],'-c','forced_login_method="chatgpt"','-c','model_reasoning_effort="low"','-c','web_search="disabled"',
    '-c','project_doc_max_bytes=0','--disable','shell_tool','--disable','multi_agent','--disable','apps','--disable','tool_suggest',
    '--cd',str(private),'--json','--output-schema',str(out/'schema.json'),'--output-last-message',str(call/'response.json'),'-']
   save(call/'dispatch.json',{'argv':args,'prompt_sha256':sha(call/'prompt.txt'),'request_digest':request.content_hash,'timeout_seconds':240})
   t=time.perf_counter_ns()
   try:
    with (call/'events.jsonl').open('xb') as log,(call/'stderr.txt').open('xb') as err:
     result=subprocess.run(args,input=prompt.encode(),stdout=log,stderr=err,timeout=240,creationflags=subprocess.CREATE_NO_WINDOW,env={k:v for k,v in os.environ.items() if k not in ('OPENAI_API_KEY','CODEX_API_KEY')})
    if result.returncode:raise RuntimeError('official client failed: '+str(result.returncode))
    response=read(call/'response.json')
    assert set(response)=={'code','conclusion','limitations'}
    assert isinstance(response['code'],str) and isinstance(response['conclusion'],str) and isinstance(response['limitations'],list)
    events=[json.loads(l) for l in (call/'events.jsonl').read_text(encoding='utf-8').splitlines() if l]
    completed=[e for e in events if e.get('type')=='turn.completed']
    assert completed,'no terminal client completion'
    forbidden=[e for e in events if e.get('type')=='item.completed' and e.get('item',{}).get('type') not in ('agent_message','reasoning','error')]
    diagnostics=[e['item']['message'] for e in events if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='error']
    assert all(x.startswith('Skill descriptions were shortened to fit the skills context budget.') for x in diagnostics),'unrecognized client error'
    assert not forbidden,'unexpected client tool execution'
    save(call/'client-check.json',{'turn_completed':True,'unexpected_tool_items':0,'nonfatal_diagnostics':diagnostics,'usage':[e.get('usage') for e in completed]})
    return FrozenRecord.from_dict(response)
   finally:
    timing.append({'operation':'official_client_'+slot,'ns':time.perf_counter_ns()-t})
    try:quota(private/(slot+'-after'))
    finally:timing.append({'operation':'model_port_total_'+slot,'ns':time.perf_counter_ns()-port_started})
  t=time.perf_counter_ns()
  plan=session.invoke('plan',model,instruction=PLAN)
  timing.append({'operation':'invoke_total_plan','ns':time.perf_counter_ns()-t})
  code=plan.data()['code']
  if not code.strip():raise RuntimeError('empty analysis code')
  result=execute(code,'primary')
  append_execution(result,'primary')
  t=time.perf_counter_ns()
  primary_links=register_report(session,result,item,'primary',folder)
  timing.append({'operation':'register_domain_primary','ns':time.perf_counter_ns()-t})
  t=time.perf_counter_ns()
  check=session.invoke('check',model,instruction=CHECK)
  timing.append({'operation':'invoke_total_check','ns':time.perf_counter_ns()-t})
  if not check.data()['code'].strip():raise RuntimeError('empty qualification code')
  qualification=execute(check.data()['code'],'qualification')
  append_execution(qualification,'qualification')
  t=time.perf_counter_ns()
  qualification_links=register_report(session,qualification,item,'qualification',folder)
  timing.append({'operation':'register_domain_qualification','ns':time.perf_counter_ns()-t})
  t=time.perf_counter_ns()
  final=session.invoke('final',model,instruction=FINAL)
  timing.append({'operation':'invoke_total_final','ns':time.perf_counter_ns()-t})
  decision=session.finish(FrozenRecord.from_dict({'objective_digest':objective.content_hash,'outcome':'unknown',
   'evidence_ids':list(session.executions),'conclusion':final.data()['conclusion'],'programme_complete':False}))
  save(folder/'completion.json',{'status':'completed','decision':decision.data(),'trace':verify_trace(folder/'runtime/trace.jsonl').data(),
   'analysis_execution_status':result.status,'qualification_execution_status':qualification.status,'primary_domain_claims':len(primary_links),'qualification_domain_claims':len(qualification_links),'declared_dependency_edges':sum(len(x['depends_on']) for x in qualification_links),'scientific_validated':False})
 except Exception as exc:
  save(folder/'failure.json',{'status':'failed','error_type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc(),
   'opportunity_reusable':False,'scientific_validated':False})
  raise
 finally:
  timing.append({'operation':'trajectory_wall_including_quota_checks','ns':time.perf_counter_ns()-start})
  save(folder/'timing.json',timing)
  try:quota(private/'after')
  except Exception as exc:save(folder/'quota-after-failure.json',{'error_type':type(exc).__name__})
 print(json.dumps({'opportunity':op,'status':'completed'}))
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('command',choices=['freeze','run']);a.add_argument('--run',default='domain-rich-r2');a.add_argument('--index',type=int,choices=range(3),default=0)
 v=a.parse_args()
 if v.command=='freeze':freeze(v.run)
 else:
  import msvcrt
  lockpath=WORK/'week1-domain-pilot.lock'
  with lockpath.open('a+b') as lock:
   if lockpath.stat().st_size==0:lock.write(b'0');lock.flush()
   lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
   try:run_one(v.run,v.index)
   finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)

