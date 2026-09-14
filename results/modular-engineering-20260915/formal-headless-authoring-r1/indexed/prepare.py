"""Prepare four TRAIN requests using the tested production authoring seam."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

WORK = Path(__file__).parent
TREE = WORK.parent/'headless-authoring-indexed-runtime'
CHECK = WORK/'headless-indexed-references-root-r1-closed.json'
ROOT = WORK/'headless-authoring-indexed-preparation-r1'
sys.path.insert(0, str(TREE))
from evaluation.modular.diagnostic_material_authoring import provision_native, write_record, HEADLESS_LIMITS
from evaluation.modular.diagnostic_subscription import sha

def binding(home):
    accounts=[v for v in json.loads((home/'auth.json').read_bytes()).values()
        if type(v) is dict and v.get('auth_mode')=='oidc'
        and v.get('oidc_issuer')=='https://auth.x.ai'
        and v.get('oidc_client_id')=='b1a00492-073a-47ea-816f-4c329264a828']
    assert len(accounts)==1
    return hashlib.sha256(accounts[0]['user_id'].encode()).hexdigest()

def descriptor(path):
    return {'path':str(path),'sha256':sha(path)}

check=json.loads(CHECK.read_bytes())
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=TREE,text=True).strip()
assert head==check['commit'] and check['exit_code']==0 and check['source_unchanged']
assert check['junit']['failures']==check['junit']['errors']==check['junit']['skipped']==0
assert not subprocess.check_output(['git','status','--porcelain'],cwd=TREE).strip()
assert not (TREE/'data/labels').exists() and not (TREE/'data/tasks').exists()
assert all(sha(TREE/name)==pin for name,pin in check['source_after'].items() if name.endswith('.py'))
assert HEADLESS_LIMITS['reasoning_effort']=='low'
native_home=Path('C:/Users/Administrator/.grok')
authorized_account=binding(native_home)
successful_probe=WORK/'headless-low-effort-request-r1/public-observation.json'
prior=json.loads(successful_probe.read_bytes())
assert prior['status']=='provisional_response_observed' and prior['source_unchanged']
assert prior['account_preflight']['account_binding']==authorized_account
source=WORK/'primary-prospective-reference-live-r1'
metadata=provision_native(descriptor(source/'reference-publication-r1.json'),
    descriptor(source/'actual-result-r1.json'),ROOT,
    executable=Path('C:/Users/Administrator/.grok/bin/grok.exe'),
    existing_auth=native_home/'auth.json',transport='headless')
envelope=json.loads(Path(metadata['envelope']['path']).read_bytes())
assert envelope['limits']==HEADLESS_LIMITS
for slot in envelope['native_deployment']['slots'].values():
    assert binding(Path(slot['private_home']))==authorized_account
receipt={'schema':'headless-low-effort-authoring-preparation-v1','source_commit':head,
    'engineering_check':descriptor(CHECK),'preparer':descriptor(Path(__file__)),
    'authoring_envelope':metadata['envelope'],'task_count':metadata['task_count'],
    'slot_count':metadata['slot_count'],'authorized_account_binding':authorized_account,
    'provisional_probe':descriptor(successful_probe),'reasoning_effort':'low',
    'model_calls':0,'validation_access':False,'extra_paid_api_budget':0,
    'source_unchanged_after_preparation':all(sha(TREE/n)==p for n,p in check['source_after'].items() if n.endswith('.py')),
    'auth_handling':'opaque_private_copy_no_hash_or_publication'}
write_record(ROOT/'public-preparation.json',receipt)
print(json.dumps(receipt),flush=True)
