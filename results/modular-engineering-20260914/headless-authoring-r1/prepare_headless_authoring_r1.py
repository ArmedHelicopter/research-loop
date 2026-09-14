"""File-only v3 preparation after the final frozen engineering/label checks."""
import json
from pathlib import Path
import subprocess
import sys

TREE = Path('E:/_ryanDev/AI/research-loop-modular/artifact-evidence-provenance')
WORK = TREE.parent/'work'
sys.path.insert(0, str(TREE))
from evaluation.modular.diagnostic_material_authoring import provision_native, write_record
from evaluation.modular.diagnostic_subscription import sha

CHECK = WORK/'headless-authoring-frozen-r2-closed.json'
check = json.loads(CHECK.read_bytes())
head = subprocess.check_output(['git','rev-parse','HEAD'], cwd=TREE, text=True).strip()
assert check['commit'] == head and check['exit_code'] == 0 and check['source_unchanged']
assert check['junit']['failures'] == check['junit']['errors'] == check['junit']['skipped'] == 0
assert all(sha(TREE/name) == pin for name,pin in check['source_after'].items())
assert not subprocess.check_output(['git','status','--porcelain'],cwd=TREE).strip()
source = WORK/'primary-prospective-reference-live-r1'
def descriptor(path): return {'path':str(path),'sha256':sha(path)}

root = WORK/'headless-authoring-actual-preparation-r1'
metadata = provision_native(descriptor(source/'reference-publication-r1.json'),
    descriptor(source/'actual-result-r1.json'), root,
    executable=Path('C:/Users/Administrator/.grok/bin/grok.exe'),
    existing_auth=Path('C:/Users/Administrator/.grok/auth.json'), transport='headless')
assert all(sha(TREE/name) == pin for name,pin in check['source_after'].items())
receipt = {'schema':'headless-authoring-private-preparation-v1', 'source_commit':head,
    'engineering_check':descriptor(CHECK), 'preparer':descriptor(Path(__file__)),
    'authoring_envelope':metadata['envelope'], 'task_count':metadata['task_count'],
    'slot_count':metadata['slot_count'], 'model_calls':0, 'validation_access':False,
    'source_unchanged_after_preparation':True, 'auth_handling':'opaque_private_copy_no_hash_or_publication'}
write_record(root/'public-preparation.json',receipt)
print(json.dumps(receipt))
