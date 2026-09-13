"""File-only private preparation; no CLI/model/network invocation."""
import json
from pathlib import Path
import sys

REPO = Path('E:/_ryanDev/AI/research-loop-modular/grok-materials')
sys.path.insert(0, str(REPO))
from evaluation.modular.diagnostic_material_authoring import provision_native, write_record
from evaluation.modular.diagnostic_subscription import sha

work = REPO.parent / 'work'
check = json.loads((work / 'material-authoring-frozen-check-r2/receipt.json').read_text())
assert check['pytest_exit'] == 0 and check['failures'] == 0 and check['errors'] == 0
assert check['clean_before'] and check['clean_after'] and check['source_hashes_unchanged']
assert check['all_new_authoring_tests_included'] and check['native_timeout_tree_and_label_isolation_included']
before = json.loads((work / 'material-authoring-frozen-check-r2/before-source-sha256.json').read_text())
assert all(sha(REPO / name) == expected for name, expected in before.items())
source = work / 'primary-prospective-reference-live-r1'
def descriptor(name):
    path = source / name
    return {'path': str(path), 'sha256': sha(path)}

metadata = provision_native(descriptor('reference-publication-r1.json'), descriptor('actual-result-r1.json'),
    work / 'material-authoring-actual-preparation-r1',
    executable=Path('C:/Users/Administrator/.grok/bin/grok.exe'),
    existing_auth=Path('C:/Users/Administrator/.grok/auth.json'))
assert all(sha(REPO / name) == expected for name, expected in before.items())
preparation = {'schema': 'actual-authoring-file-only-preparation-v1',
    'tested_commit': check['commit'], 'tested_source_count': len(before),
    'source_hashes_unchanged_after_preparation': True,
    'frozen_check': {'path': str(work / 'material-authoring-frozen-check-r2/receipt.json'),
        'sha256': sha(work / 'material-authoring-frozen-check-r2/receipt.json')},
    'original_check': {'path': str(work / 'material-authoring-frozen-check-r1/receipt.json'),
        'sha256': sha(work / 'material-authoring-frozen-check-r1/receipt.json')},
    'preparation_script_sha256': sha(Path(__file__)), 'authoring_envelope': metadata['envelope'],
    'real_generation_requests': 0, 'native_executable_launches': 0,
    'account_tools_and_model_gates': 'required_fresh_at_dispatch_not_yet_run',
    'auth_handling': 'opaque_private_local_copy_excluded_from_evidence',
    'actual_material_availability': {'ready': 0, 'unresolved_material': 36, 'not_applicable': 0}}
write_record(work / 'material-authoring-actual-preparation-r1/public-preparation-receipt.json', preparation)
print(json.dumps(metadata))
