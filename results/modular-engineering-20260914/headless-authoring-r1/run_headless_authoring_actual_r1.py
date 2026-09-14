"""One four-TRAIN authoring opportunity set; no retry and no review dispatch."""
import json
import os
from pathlib import Path
import subprocess
import sys

TREE = Path('E:/_ryanDev/AI/research-loop-modular/artifact-evidence-provenance')
WORK = TREE.parent/'work'
sys.path.insert(0,str(TREE))
from evaluation.modular.diagnostic_material_authoring import write_record
from evaluation.modular.diagnostic_subscription import sha
from research_loop.modular.grok_headless_transport import _child

check = json.loads((WORK/'headless-authoring-frozen-r2-closed.json').read_bytes())
prepared = json.loads((WORK/'headless-authoring-actual-preparation-r1/public-preparation.json').read_bytes())
head = subprocess.check_output(['git','rev-parse','HEAD'],cwd=TREE,text=True).strip()
assert head == check['commit'] == prepared['source_commit'] and check['exit_code'] == 0 and check['source_unchanged']
assert not subprocess.check_output(['git','status','--porcelain'],cwd=TREE).strip()
assert all(sha(TREE/name)==pin for name,pin in check['source_after'].items())
envelope=prepared['authoring_envelope']; assert sha(envelope['path'])==envelope['sha256']
assert not Path(envelope['path']).with_suffix('.run-reservation.json').exists()
root=WORK/'headless-authoring-actual-run-r1'; root.mkdir(exist_ok=False)
command=[sys.executable,'-m','evaluation.modular.diagnostic_material_authoring','run',
    '--input',envelope['path'],'--sha256',envelope['sha256'],'--output-directory',str(root/'private-output')]
environment={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','SYSTEMDRIVE',
    'COMSPEC','PATHEXT','PATH','NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE','OS'}}
environment.update(PYTHONPATH=str(TREE),TEMP=str(root),TMP=str(root))
write_record(root/'parent-reservation.json',{'schema':'headless-authoring-parent-reservation-v1',
    'source_commit':head,'source_files':check['source_after'],'authoring_envelope':envelope,
    'runner_sha256':sha(__file__),'command':command,'timeout_seconds':1500,
    'main_opportunities':4,'possible_initial_title_opportunities':4,'retry':False,
    'review_evaluator_requests':0,'additional_paid_api_budget':0})
raw,process=_child(command,{'cwd':str(TREE)},environment,root/'worker',1500)
unchanged=all(sha(TREE/name)==pin for name,pin in check['source_after'].items())
outcome=root/'private-output/public-outcome.json'
receipt={'schema':'headless-authoring-parent-closure-v1','source_commit':head,
    'worker_exit':process['process_exit_code'],'parent_timeout':process['timed_out'],
    'owned_tree_closed':process['owned_tree_closed'],'process_failure':process['failure'],
    'source_unchanged':unchanged,'authoring_envelope':envelope,
    'public_outcome':{'path':str(outcome),'sha256':sha(outcome)} if outcome.exists() else None,
    'main_opportunities':4,'possible_initial_title_opportunities':4,'retry':False,
    'review_evaluator_requests':0,'settled_additional_charge_usd':None}
write_record(root/'public-parent-closure.json',receipt)
print(json.dumps(receipt),flush=True)
raise SystemExit(int(not unchanged or process['process_exit_code']!=0 or process['timed_out']))
