"""Freeze the complete M4/M5 two-task training factorial and isolated scorer."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import secrets
import subprocess
import sys

BASE=Path('E:/_ryanDev/AI/research-loop-modular')
SOURCE=BASE/'cp-check';sys.path.insert(0,str(SOURCE))
from evaluation.modular.custody import CustodyStore
from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from evaluation.modular.scorer_process import CombinationScorerProcessClient, serialize_combination_panel
from evaluation.modular.scoring_service import ScorerConfig
from evaluation.modular.train_io import PublicTrainPacket
from research_loop.modular.combination_train_controller import FrozenM4M5TrainConfig, compile_m4_m5_train_panel, run_m4_m5_train_panel, SLOTS, _ANALYSIS
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity,FrozenRecord,PublicTask
from research_loop.modular.model_port import CodexModelPort,FrozenBaseContextPolicy
from research_loop.modular.modules.improvement import CandidatePackage,TrainingManifest
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import canonical,digest

OUT=BASE/'work/m4m5-train-process-20260913-01'
PRIVATE=BASE/'custody-private/m4m5-scorer-process-20260913-01'
REFERENCES=BASE/'work/train-reference-deployment-20260913-01'
STORE=BASE/'custody-private/train-reference-store-20260913-01'
CUSTODY=BASE/'benchmarks/work/custody-live-20260912.json'
CUSTODY_SHA='933f158b947a0761ed297ea7cb713d816c2385e58f4d1df37dc7669071c9e96f'
POLICY=BASE/'work/linked-train-context-20260913-01/REVIEWED-POLICY.json'
POLICY_SHA='16f83e4c8cd78cb024fffcc6949090caeba939a56b1037e58264a57ed03da89b'
ENV_SOURCE=BASE/'work/q31-isolated-context/context_environment_v2.py'
SNAPSHOT=Path('E:/_ryanDev/AI/research-loop-benchmark-20260912')
EXECUTOR='m4m5-train-executor-20260913-01';SCORER='m4m5-train-scorer-20260913-01'
IMAGE='research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,data):
    with p.open('x',encoding='utf-8',newline='\n') as f:f.write(canonical(data)+'\n')
def commit():
    assert not subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=SOURCE,text=True).strip()
    return subprocess.check_output(['git','rev-parse','HEAD'],cwd=SOURCE,text=True).strip()
def environment():
    spec=importlib.util.spec_from_file_location('isolated_child_environment',ENV_SOURCE)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module.child_environment()
def packets():
    result=[]
    for benchmark in ('blade','discoverybench'):
        paths=list((REFERENCES/'public'/benchmark).glob('*/public.json'));assert len(paths)==1
        p=paths[0];body=read(p);identity=DataIdentity.parse(body['task']['identity']);identity.require_train()
        task=PublicTask.create(identity,body['task']['payload']);receipt=FrozenRecord.from_dict(body['receipt'])
        assert receipt.data()['packet_hash']==task.content_hash and sha(p.parent/'data.csv')==receipt.data()['csv_sha256']
        result.append(PublicTrainPacket(task,p,p.parent/'data.csv',receipt))
    return tuple(result)
def config():return FrozenM4M5TrainConfig(FrozenRecord.from_dict(read(OUT/'controller.json')))
def checked():
    p=read(OUT/'preflight.json')
    assert commit()==p['source_commit'] and sha(Path(__file__))==p['runner_sha256']
    assert sha(CUSTODY)==CUSTODY_SHA and sha(OUT/'controller.json')==p['controller_sha256']
    assert sha(PRIVATE/'server-config.json')==p['server_config_sha256'] and sha(ENV_SOURCE)==p['environment_sha256']
    frozen=config();compiled=compile_m4_m5_train_panel(frozen,packets());assert compiled.panel.digest==p['panel_digest']
    return frozen,compiled,p
def client(frozen,compiled,p):
    rubric=ScorerConfig(FrozenRecord.from_dict(frozen.data()['scorer']))
    return CombinationScorerProcessClient(panel=compiled.panel,config=rubric,
        command=[sys.executable,'-m','evaluation.modular.scorer_process','--config',str(PRIVATE/'server-config.json'),
            '--config-sha256',p['server_config_sha256'],'--journal',str(PRIVATE/'server.jsonl')],
        journal_path=OUT/'scorer-client.jsonl',environment=environment(),response_timeout_seconds=360,
        task_handle_bindings=frozen.data()['scorer_handle_bindings'],
        execution_authority_keys={EXECUTOR:(PRIVATE/(EXECUTOR+'.key')).read_bytes()},
        scorer_authority_keys={SCORER:(PRIVATE/(SCORER+'.key')).read_bytes()})
def prepare():
    assert not OUT.exists() and not PRIVATE.exists() and sha(CUSTODY)==CUSTODY_SHA
    source=commit();material=packets();policy=FrozenBaseContextPolicy(POLICY,POLICY_SHA).data()
    publication=read(REFERENCES/'publication.json')
    assert sha(REFERENCES/'publication.json')=='dcb2c224f9e730f92ffd9fd9e4becd9cf4b8d1214dfef144aef8fee4ee893974'
    inherited=read(BASE/'work/linked-train-scored-20260913-02/controls/controller.json')
    baseline=hashlib.sha256(('m4m5-first-train-factorial:'+source).encode()).hexdigest()
    design=default_compatibility(baseline).conditional_factorial(('M4','M5'))
    package=CandidatePackage.create(parent_digest=None,manifest=TrainingManifest.freeze([p.task.identity for p in material]),
        changes={'prompt':{'instructions':'Use only this public training task and actual supplied observations. Preserve unknown results and failed computations; execution alone does not establish scientific validity.'}},search_cost=0)
    review={'type':'object','properties':{'assessment':{'type':'string','enum':['accept','concern','unknown']},
        'evidence_refs':{'type':'array','items':{'type':'string'}},'counterexamples':{'type':'array','items':{'type':'string'}},'uncertainty':{'type':'string'}},
        'required':['assessment','evidence_refs','counterexamples','uncertainty'],'additionalProperties':False}
    schemas={'m4_plan':inherited['schemas']['scenario'],'m5_mechanism':review,'m5_measurement':review,
        'analysis_program':inherited['schemas']['analysis_program'],'final_answer':inherited['schemas']['final_answer']}
    handles=publication['task_handles']
    body={'schema':'m4-m5-train-controller-config-v1','domain':'train','stage':'m4m5-train-process-20260913-01',
        'item_ids':[f'{p.task.identity.benchmark}:{p.task.identity.task_id}' for p in material],
        'task_bindings':{f'{p.task.identity.benchmark}:{p.task.identity.task_id}':{'identity':p.task.identity.data(),
            'task_digest':p.task.content_hash,'csv_sha256':sha(p.csv_path)} for p in material},
        'baseline_digest':baseline,'packages_by_arm':{row['arm_digest']:package.record.data() for row in design.data()['cells']},
        'scorer':inherited['scorer'],'scorer_handle_bindings':{k:hashlib.sha256(v.encode()).hexdigest() for k,v in handles.items()},
        'acceptance_criteria':{'scope':'train_adapted_only','contrast_analysis':_ANALYSIS,'allowed_failures':0,
            'scientific_promotion':False,'matched_tokens':'not_claimed'},'replicates':['r1'],
        'model':'gpt-5.6-luna','effort':'low','max_calls':40,'max_tokens':750000,'schemas':schemas,
        'allocation':{'model_slots_per_cell':list(SLOTS),'docker_attempts_per_cell':1,'scorer_calls_per_cell':1,
            'scorer_call_limit':8,'scorer_token_accounting':'transport_not_provided'},'image':IMAGE,'timeout_seconds':20}
    frozen=FrozenM4M5TrainConfig(FrozenRecord.from_dict(body));compiled=compile_m4_m5_train_panel(frozen,material)
    assert len(compiled.panel.cells)==8
    OUT.mkdir();PRIVATE.mkdir()
    for name in (EXECUTOR,SCORER,'unused-a','unused-b'):(PRIVATE/(name+'.key')).write_bytes(secrets.token_bytes(32))
    rubric=ScorerConfig(FrozenRecord.from_dict(body['scorer']))
    server={'schema':'combination-scorer-process-config-v1','panel':serialize_combination_panel(compiled.panel),
        'scorer_config':rubric.record.data(),'scorer_config_digest':rubric.digest,
        'train_reference_store':{'root':str(STORE),**{key:publication[key] for key in ('manifest_sha256','inventory_digest','split_digest')}},
        'task_handles':handles,'execution_authority_key_files':{EXECUTOR:str(PRIVATE/(EXECUTOR+'.key'))},
        'scorer_authority':{'id':SCORER,'key_file':str(PRIVATE/(SCORER+'.key'))},
        'evaluator':{'executable':policy['binding']['cli_path'],'work_root':str(PRIVATE/'evaluator-model'),
            'evaluator_id':rubric.record.data()['evaluator_id'],'evaluator_version':'1','model':'gpt-5.6-luna','effort':'low',
            'max_calls':8,'max_tokens':700000,'timeout_seconds':240,'frozen_base_context':{'source':str(POLICY),'sha256':POLICY_SHA}}}
    write(OUT/'controller.json',body);write(PRIVATE/'server-config.json',server)
    write(OUT/'preflight.json',{'schema':'m4m5-train-process-preflight-v1','source_commit':source,'runner_sha256':sha(Path(__file__)),
        'controller_sha256':sha(OUT/'controller.json'),'server_config_sha256':sha(PRIVATE/'server-config.json'),
        'environment_sha256':sha(ENV_SOURCE),'custody_sha256':CUSTODY_SHA,'policy_sha256':POLICY_SHA,
        'panel_digest':compiled.panel.digest,'obligation':'pair:M4+M5','cells':8,'solver_calls_limit':40,'solver_tokens_limit':750000,
        'evaluator_calls_limit':8,'evaluator_tokens_limit':700000,'validation_items':0,'paid_calls':0,
        'calibration':'not_measured','scientific_validity':'not_measured','OS_isolation':'not_established',
        'scope':'first complete two-task training factorial; other pairs and all scientific confirmation remain required'})
    print(canonical({'stage':'frozen','cells':8,'solver_call_limit':40,'evaluator_call_limit':8,'paid_calls':0}),flush=True)
def probe():
    frozen,compiled,p=checked();assert not (OUT/'startup.json').exists()
    service=client(frozen,compiled,p)
    try:binding=service.binding.data()
    finally:service.close()
    ledger=read(PRIVATE/'evaluator-model/ledger.json')
    assert not ledger['calls'] and ledger['tokens']==0 and not (OUT/'scorer-client.jsonl').exists() and not (PRIVATE/'server.jsonl').exists()
    write(OUT/'startup.json',{'schema':'m4m5-process-startup-v1','source_commit':p['source_commit'],'binding':binding,
        'server_config_sha256':p['server_config_sha256'],'evaluator_calls':0,'evaluator_tokens':0,'worker_closed':True})
    print(canonical({'stage':'startup_binding_verified','evaluator_calls':0,'evaluator_tokens':0}),flush=True)
def run():
    frozen,compiled,p=checked();startup=read(OUT/'startup.json')
    assert startup['server_config_sha256']==p['server_config_sha256'] and startup['worker_closed']
    assert not (OUT/'run').exists() and not (OUT/'model').exists() and not (OUT/'scorer-client.jsonl').exists()
    data=frozen.data();policy=FrozenBaseContextPolicy(POLICY,POLICY_SHA)
    port=CodexModelPort(policy.data()['binding']['cli_path'],OUT/'model',model=data['model'],effort=data['effort'],
        max_calls=data['max_calls'],max_tokens=data['max_tokens'],schema_by_slot=data['schemas'],timeout_seconds=240,
        frozen_base_context=policy,environment=environment())
    port._require_frozen_context()
    service=client(frozen,compiled,p)
    try:
        result=run_m4_m5_train_panel(frozen,custody=CustodyStore(CUSTODY),snapshot_root=SNAPSHOT,export_root=OUT/'export',run_root=OUT/'run',
            model=port,audit_verifier=AuditVerifier({name:(PRIVATE/(name+'.key')).read_bytes() for name in ('unused-a','unused-b')}),
            execution_authority=LinkedExecutionAuthority(EXECUTOR,(PRIVATE/(EXECUTOR+'.key')).read_bytes()),
            scoring_service=service,scorer_authority_keys={SCORER:(PRIVATE/(SCORER+'.key')).read_bytes()})
    finally:service.close()
    evaluation=read(PRIVATE/'evaluator-model/ledger.json');r=result.receipt.data()
    summary={'schema':'m4m5-train-process-summary-v1','source_commit':p['source_commit'],'cells':8,'status':r['status'],
        'scored_cells':r['scored_cells'],'failed_cells':r['failed_cells'],'blocked_cells':r['blocked_cells'],
        'solver_calls':len(port.ledger['calls']),'solver_tokens':port.ledger['tokens'],
        'evaluator_calls':len(evaluation['calls']),'evaluator_tokens':evaluation['tokens'],
        'usage_incomplete':port.ledger['usage_incomplete'] or evaluation['usage_incomplete'],
        'calibration':'not_measured','scientific_validity':'not_measured','validation_items':0,'pruned_combinations':[]}
    write(OUT/'summary.json',summary);print(canonical(summary),flush=True)
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','probe','run']);args=parser.parse_args()
    assert Path.cwd().resolve()==SOURCE.resolve()
    try:{'prepare':prepare,'probe':probe,'run':run}[args.action]()
    except Exception as exc:
        if OUT.exists() and not (OUT/(args.action+'-failure.json')).exists():
            write(OUT/(args.action+'-failure.json'),{'error_type':type(exc).__name__,'action':args.action,'selection':'inconclusive','cells':8,'validation_items':0})
        print(canonical({'stage':'failed','action':args.action,'error_type':type(exc).__name__,'message':str(exc)[:180]}),flush=True)
        raise SystemExit(1) from None
