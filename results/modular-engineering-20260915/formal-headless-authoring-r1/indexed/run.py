"""One new four-TRAIN production batch; no replay or reviewer dispatch."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

WORK=Path(__file__).parent
TREE=WORK.parent/'headless-authoring-indexed-runtime'
PREP=WORK/'headless-authoring-indexed-preparation-r1'
CHECK=WORK/'headless-indexed-references-root-r1-closed.json'
ROOT=WORK/'headless-authoring-indexed-run-r1'
sys.path.insert(0,str(TREE))
from evaluation.modular.diagnostic_material_authoring import write_record
from evaluation.modular.diagnostic_subscription import sha
from research_loop.modular.grok_headless_transport import _child

check=json.loads(CHECK.read_bytes());prepared=json.loads((PREP/'public-preparation.json').read_bytes())
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=TREE,text=True).strip()
assert head==check['commit']==prepared['source_commit'] and check['exit_code']==0 and check['source_unchanged']
assert not subprocess.check_output(['git','status','--porcelain'],cwd=TREE).strip()
assert not (TREE/'data/labels').exists() and not (TREE/'data/tasks').exists()
assert all(sha(TREE/n)==p for n,p in check['source_after'].items() if n.endswith('.py'))
envelope=prepared['authoring_envelope'];assert sha(envelope['path'])==envelope['sha256']
assert not Path(envelope['path']).with_suffix('.run-reservation.json').exists()
body=json.loads(Path(envelope['path']).read_bytes())
assert body['limits']['reasoning_effort']=='low' and len(body['entries'])==4
for slot in body['native_deployment']['slots'].values():
    accounts=[v for v in json.loads((Path(slot['private_home'])/'auth.json').read_bytes()).values()
        if type(v)is dict and v.get('auth_mode')=='oidc' and v.get('oidc_issuer')=='https://auth.x.ai'
        and v.get('oidc_client_id')=='b1a00492-073a-47ea-816f-4c329264a828']
    assert len(accounts)==1
    assert hashlib.sha256(accounts[0]['user_id'].encode()).hexdigest()==prepared['authorized_account_binding']
ROOT.mkdir(exist_ok=False)
command=[sys.executable,'-m','evaluation.modular.diagnostic_material_authoring','run',
    '--input',envelope['path'],'--sha256',envelope['sha256'],'--output-directory',str(ROOT/'private-output')]
environment={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','SYSTEMDRIVE',
    'COMSPEC','PATHEXT','PATH','NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE','OS'}}
environment.update(PYTHONPATH=str(TREE),TEMP=str(ROOT),TMP=str(ROOT))
write_record(ROOT/'parent-reservation.json',{'schema':'headless-low-effort-authoring-parent-v1',
    'source_commit':head,'source_files':check['source_after'],'authoring_envelope':envelope,
    'runner_sha256':sha(__file__),'preparation_sha256':sha(PREP/'public-preparation.json'),
    'authorized_account_binding':prepared['authorized_account_binding'],
    'command':command,'timeout_seconds':1500,'main_opportunities':4,
    'possible_initial_title_opportunities':4,'retry':False,'reasoning_effort':'low',
    'review_evaluator_requests':0,'additional_paid_api_budget':0,'validation_access':False})
raw,process=_child(command,{'cwd':str(TREE)},environment,ROOT/'worker',1500)
unchanged=all(sha(TREE/n)==p for n,p in check['source_after'].items() if n.endswith('.py'))
outcome=ROOT/'private-output/public-outcome.json'
receipt={'schema':'headless-low-effort-authoring-parent-closure-v1','source_commit':head,
    'worker_exit':process['process_exit_code'],'parent_timeout':process['timed_out'],
    'owned_tree_closed':process['owned_tree_closed'],'process_failure':process['failure'],
    'source_unchanged':unchanged,'authoring_envelope':envelope,
    'public_outcome':{'path':str(outcome),'sha256':sha(outcome)} if outcome.exists() else None,
    'main_opportunities':4,'possible_initial_title_opportunities':4,'retry':False,
    'reasoning_effort':'low','review_evaluator_requests':0,'validation_access':False,
    'settled_additional_charge_usd':None}
write_record(ROOT/'public-parent-closure.json',receipt)
print(json.dumps(receipt),flush=True)
raise SystemExit(int(not unchanged or process['process_exit_code']!=0 or process['timed_out']))
