"""One fresh, bounded normal-CLI TRAIN control on the tested 1.0.30 deployment."""
import hashlib,json,shutil,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone
WORK=Path('E:/_ryanDev/AI/research-loop-modular/work')
ROOT=WORK/'grok130-normal-train-control-r2'
RUNTIME=WORK.parent/'grok130-evaluator-runtime-r1'
COMMIT='6ec1a7205680e8f21a0da1e826ea696aff0f1333'
EXE=WORK/'grok-cli-1.0.30/grok.exe'
PIN='ca24ea63272ba7881261f4a52498d1f5bd884b01da25845990422a10dd315266'
AUTH=Path('C:/Users/Administrator/.grok/auth.json')
ORIGINAL=WORK/'grok-normal-train-control-r1/request.public.json'
REQUEST_SHA='cb0c0fa56056540de382b615aacf8386731c6afbefa124fc742a0f7ad6614e28'
CONTROLLER=WORK/'actual-m4m5-headless-preparation-r1/controller.json'
CONTROLLER_SHA='2aafb0807691c73ecebd02c04bfc68cb007ddd546672b3da2547ce70928c64bf'

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load(path): return json.loads(Path(path).read_bytes())
def write(path,body):
    with Path(path).open('xb') as out: out.write((json.dumps(body,sort_keys=True,indent=2)+'\n').encode())
def metadata(path):
    stat=path.stat(); return {'bytes':stat.st_size,'mtime_ns':stat.st_mtime_ns}
def require(ok,msg):
    if not ok: raise RuntimeError(msg)

def prepare():
    require(not ROOT.exists(),'fresh control root required')
    require(subprocess.check_output(['git','rev-parse','HEAD'],cwd=RUNTIME,text=True).strip()==COMMIT,'runtime commit')
    require(not subprocess.check_output(['git','status','--porcelain'],cwd=RUNTIME).strip(),'runtime dirty')
    require(not (RUNTIME/'data/labels').exists(),'labels must be absent from run tree')
    source=load(WORK/'grok130-evaluator-runtime-frozen-r2-source-members.json')
    closed=load(WORK/'grok130-evaluator-runtime-frozen-r2-closed.json')
    require(source['commit']==closed['commit']==COMMIT and closed['exit_code']==0 and closed['source_unchanged'] is True,'frozen evaluator checks')
    pins={str((RUNTIME/r['path']).resolve()):r['sha256'] for r in source['members']}
    require(all(sha(p)==d for p,d in pins.items()),'tested source bytes changed')
    require(sha(EXE)==PIN and sha(ORIGINAL)==REQUEST_SHA and sha(CONTROLLER)==CONTROLLER_SHA,'original public request/schema/native pin')
    request=load(ORIGINAL)
    require(request.get('schema')=='public-model-request-v1' and request.get('slot')=='m4_plan' and request.get('execution_feedback')==[],'public TRAIN request')
    root_check=load(WORK/'grok130-provider-root-integration-r1-closed.json')
    root_before=load(WORK/'grok130-provider-root-integration-r1-before.json')
    require(root_check['exit_code']==0 and root_check['source_unchanged'] is True and 'tests/test_label_isolation.py' in root_before['pytest_args'],'merged label integration')
    ROOT.mkdir()
    shutil.copyfile(__file__,ROOT/'control.py'); shutil.copyfile(ORIGINAL,ROOT/'request.public.json')
    write(ROOT/'schema.json',load(CONTROLLER)['schemas']['m4_plan'])
    for p in (EXE,ROOT/'control.py',ROOT/'request.public.json',ROOT/'schema.json',ORIGINAL,CONTROLLER): pins[str(p.resolve())]=sha(p)
    write(ROOT/'manifest.json',{'schema':'grok130-normal-train-control-v1','runtime':str(RUNTIME),'source_commit':COMMIT,
        'frozen_files':pins,'request_sha256':REQUEST_SHA,'request_domain':'train',
        'prior_request_origin':'Already-exported public TRAIN m4_plan request from original M4/M5 run; unchanged bytes.',
        'limits':{'model_opportunities':1,'model_retries':0,'prompt_timeout_seconds':60,'main_output_cap':2048,
                  'observed_main_token_cap':131072,'input_byte_cap':262144,'api_key_route_permitted':False,'validation_opened':False},
        'native_deployment_sha256':PIN,'scientific_effectiveness_proven':False})
    print(json.dumps({'prepared':str(ROOT),'model_calls':0}))

def execute():
    require({p.name for p in ROOT.iterdir()}=={'control.py','manifest.json','request.public.json','schema.json'},'control already attempted')
    manifest=load(ROOT/'manifest.json'); pins=manifest['frozen_files']
    require(all(sha(p)==d for p,d in pins.items()),'frozen inputs changed')
    write(ROOT/'launch-reservation.json',{'schema':'grok130-normal-train-control-reservation-v1',
        'created_at':datetime.now(timezone.utc).isoformat(),'model_opportunities':1,'model_retries':0,
        'prompt_timeout_seconds':60,'manifest_sha256':sha(ROOT/'manifest.json'),'validation_opened':False})
    auth_before=metadata(AUTH); response=None; error_type=None
    try:
        home,profile,cwd=ROOT/'private-home',ROOT/'private-profile',ROOT/'public-cwd'
        for p in (home,profile,cwd): p.mkdir()
        shutil.copyfile(AUTH,home/'auth.json')
        require(metadata(AUTH)==auth_before,'global auth changed while copying')
        sys.path.insert(0,str(RUNTIME))
        from research_loop.modular.contracts import FrozenRecord
        from research_loop.modular.grok_native_deployment import FrozenHeadlessTrainDeployment
        from research_loop.modular.grok_headless_train_solver import GrokHeadlessTrainModelPort,replay_headless_train_ledger
        port=GrokHeadlessTrainModelPort(executable=EXE,work_root=ROOT/'control-model',private_home=home,
            private_profile=profile,public_cwd=cwd,frozen_files=pins,max_calls=1,
            schemas={'m4_plan':load(ROOT/'schema.json')},slot_output_caps={'m4_plan':2048},
            slot_input_byte_caps={'m4_plan':262144},observed_main_token_cap=131072,
            account_read_recovery={'schema':'headless-account-read-recovery-v1','max_attempts':2},
            deployment=FrozenHeadlessTrainDeployment.create(EXE))
        response=port(FrozenRecord.from_dict(load(ROOT/'request.public.json')))
        replay_headless_train_ledger(port)
    except Exception as error:
        error_type=type(error).__name__
    ledger=ROOT/'control-model/ledger.json'
    closure={'schema':'grok130-normal-train-control-closure-v1',
        'status':'succeeded' if response is not None and error_type is None else 'terminal_unknown_or_failed',
        'request_sha256':REQUEST_SHA,'response_sha256':response.content_hash if response is not None else None,
        'error_type':error_type,'ledger_sha256':sha(ledger) if ledger.exists() else None,
        'global_auth_metadata_unchanged':metadata(AUTH)==auth_before,'auth_metadata_before':auth_before,
        'source_unchanged':all(sha(p)==d for p,d in pins.items()),'validation_opened':False,
        'scientific_effectiveness_proven':False,'title_and_all_opportunity_settlement':'unknown'}
    write(ROOT/'closure.json',closure)
    print(json.dumps({'closed':True,'status':closure['status'],'response_observed':response is not None,
                      'error_type':error_type,'source_unchanged':closure['source_unchanged']}))

if __name__=='__main__':
    require(len(sys.argv)==2 and sys.argv[1] in ('prepare','execute'),'choose prepare or execute')
    prepare() if sys.argv[1]=='prepare' else execute()
