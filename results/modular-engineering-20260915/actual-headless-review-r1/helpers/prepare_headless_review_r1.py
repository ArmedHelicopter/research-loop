"""Freeze a new diagnostic consumer of retained TRAIN material; no model calls."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

WORK = Path(__file__).parent
TREE = WORK.parent / 'headless-review-runtime'
CHECK = WORK / 'headless-review-adapter-root-r1-closed.json'
ROOT = WORK / 'headless-review-preparation-r1'
RUN = WORK / 'headless-review-run-r1'
OLD_RUN = WORK / 'headless-authoring-indexed-run-r1'
sys.path.insert(0, str(TREE))
from evaluation.modular.diagnostic_material_authoring import own_sources, write_record
from evaluation.modular.diagnostic_subscription import CONFIG_SCHEMA_V3, compile_inventory, load_private, sha
from evaluation.modular.calibration_pilot_process import load_record
from research_loop.modular.grok_acp_transport import EXECUTABLE_SHA256, diagnostic_config


def desc(path):
    return {'path': str(path), 'sha256': sha(path)}


def account_binding(auth_path):
    rows = [v for v in json.loads(auth_path.read_bytes()).values()
        if type(v) is dict and v.get('auth_mode') == 'oidc'
        and v.get('oidc_issuer') == 'https://auth.x.ai'
        and v.get('oidc_client_id') == 'b1a00492-073a-47ea-816f-4c329264a828']
    assert len(rows) == 1
    return hashlib.sha256(rows[0]['user_id'].encode()).hexdigest()


assert sha(CHECK) == '4c22d1ecd353bd1cc714186e86756165db8ed8ef7d3b9fdc52c1138e281b610a'
check = json.loads(CHECK.read_bytes())
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=TREE, text=True).strip()
assert head == check['commit'] and check['exit_code'] == 0 and check['source_unchanged']
assert check['junit']['failures'] == check['junit']['errors'] == check['junit']['skipped'] == 0
assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=TREE).strip()
assert not (TREE / 'data').exists()
assert all(sha(TREE / name) == pin for name, pin in check['source_after'].items())

outcome_path = OLD_RUN / 'private-output/public-outcome.json'
outcome = json.loads(outcome_path.read_bytes())
assert sha(outcome_path) == '7ce822b54e46a7fa2fe9c796b29b2560f68403813753cd97a9cec56128589240'
assert outcome['material_availability'] == {'ready': 26, 'unresolved_material': 7, 'not_applicable': 3}
assert not outcome['review_dispatch_blocked'] and not outcome['calibration_eligible'] and not outcome['validation_eligible']
old_config_path = OLD_RUN / 'private-output/review-compiled-config.private.json'
assert sha(old_config_path) == 'b3c2860176e9dd1526b2ca5f5b160cb8e7bdab6435c443a71f7593c385f03da3'
old = json.loads(old_config_path.read_bytes())
old_manifest = load_record(outcome['review_manifest']).data()
old_inventory = load_record(outcome['ready_review_inventory']).data()
assert old['manifest'] == outcome['review_manifest'] and old['materials'] == outcome['materials']
assert old['request_inventory'] == outcome['ready_review_inventory']
load_record(outcome['materials']); load_record(outcome['supports'])

old_preparation = WORK / 'headless-authoring-indexed-preparation-r1/public-preparation.json'
old_prep = json.loads(old_preparation.read_bytes())
old_envelope = load_record(old_prep['authoring_envelope']).data()
assert old_envelope['tasks'] == old_manifest['tasks']
assert old_envelope['reference_store'] == old['reference_store']
assert outcome['authoring_envelope_sha256'] == old_prep['authoring_envelope']['sha256']
assert old_prep['authorized_account_binding'] == 'b13ba3f652654cf9907b60161d7cd397e5edd8da74646e642e4105768d511c2e'
auth_path = Path('C:/Users/Administrator/.grok/auth.json')
assert account_binding(auth_path) == old_prep['authorized_account_binding']
assert not ROOT.exists() and not RUN.exists()
ROOT.mkdir()

# Producer signatures bind each original slot, not the new consumer manifest.
# Preserve those signatures/candidates/unknown targets; change only source pins.
input_files = {name: str(path.absolute()) for name, path in own_sources().items()}
assert set(input_files) == set(old_manifest['input_pins']) | {'native_headless_code'}
manifest = copy.deepcopy(old_manifest)
manifest['input_pins'] = {name: sha(path) for name, path in input_files.items()}
assert {k: v for k, v in manifest.items() if k != 'input_pins'} == {
    k: v for k, v in old_manifest.items() if k != 'input_pins'}
assert all(p['timeout_seconds'] == 60 and p['main_output_cap'] == 2048
    and p['max_input_bytes'] == 262144 and p['observed_main_token_cap'] == 131072
    and p['max_retries'] == 0 for p in manifest['policy']['ports'].values())
manifest_desc = write_record(ROOT / 'review-manifest.json', manifest)
config = copy.deepcopy(old)
config.update(schema=CONFIG_SCHEMA_V3, transport='headless', manifest=manifest_desc,
    input_files=input_files, journal_path=str(RUN / 'review.private.jsonl'),
    request_inventory=None, native_deployment=None)
uncompiled = write_record(ROOT / 'uncompiled-config.private.json', config)
inventory_desc = compile_inventory(uncompiled, ROOT / 'request-inventory.json')
inventory = load_record(inventory_desc).data()
assert len(inventory['entries']) == len(old_inventory['entries']) == 130
keys = ('opportunity_id', 'slot_id', 'role', 'repeat', 'schema_digest', 'port_digest')
assert [{k: e[k] for k in keys} for e in inventory['entries']] == [
    {k: e[k] for k in keys} for e in old_inventory['entries']]
counts = {r: sum(e['role'] == r for e in inventory['entries']) for r in manifest['policy']['ports']}
assert counts == {'reviewer1': 26, 'reviewer2': 26, 'arbitrator': 26, 'evaluator': 52}

executable = Path('C:/Users/Administrator/.grok/bin/grok.exe')
assert sha(executable) == EXECUTABLE_SHA256
# Retain the producer's original sources, TRAIN references and config anchors.
frozen = dict(old_envelope['frozen_files'])
for path, expected in frozen.items():
    assert sha(path) == expected
frozen.update({str(TREE / name): pin for name, pin in check['source_after'].items()})
for descriptor in (desc(outcome_path), desc(old_config_path), outcome['materials'], outcome['supports'],
        outcome['review_manifest'], outcome['ready_review_inventory'], old_prep['authoring_envelope'],
        desc(OLD_RUN / 'independent-readback.json'), desc(CHECK), desc(Path(__file__)), manifest_desc, inventory_desc):
    frozen[descriptor['path']] = descriptor['sha256']
frozen[str(executable)] = EXECUTABLE_SHA256
slots = {}
for entry in inventory['entries']:
    native = ROOT / 'native-slots' / entry['opportunity_id']
    slot = {k: str(native / k) for k in ('cwd', 'private_home', 'private_profile')}
    for path in slot.values():
        Path(path).mkdir(parents=True, exist_ok=False)
    home = Path(slot['private_home'])
    shutil.copyfile(auth_path, home / 'auth.json')
    assert account_binding(home / 'auth.json') == old_prep['authorized_account_binding']
    config_path = home / 'config.toml'
    config_path.write_bytes(diagnostic_config(manifest['policy']['ports'][entry['role']]['main_output_cap']).encode())
    frozen[str(config_path)] = sha(config_path)
    slots[entry['opportunity_id']] = slot
deployment = write_record(ROOT / 'native-deployment.private.json', {
    'schema': 'frozen-native-subscription-headless-deployment-v1', 'executable': str(executable),
    'slots': slots, 'frozen_files': frozen})
config.update(request_inventory=inventory_desc, native_deployment=deployment)
config_desc = write_record(ROOT / 'worker-config.private.json', config)
load_private(config_desc)
assert all(sha(path) == pin for path, pin in frozen.items())
assert all(sha(TREE / name) == pin for name, pin in check['source_after'].items())
receipt = {'schema': 'headless-diagnostic-review-preparation-v1', 'source_commit': head,
    'engineering_check': desc(CHECK), 'preparer': desc(Path(__file__)),
    'producer_outcome': desc(outcome_path), 'producer_independent_readback': desc(OLD_RUN / 'independent-readback.json'),
    'producer_manifest': outcome['review_manifest'], 'consumer_manifest': manifest_desc,
    'producer_inventory': outcome['ready_review_inventory'], 'consumer_inventory': inventory_desc,
    'worker_config': config_desc, 'native_deployment': deployment,
    'materials': outcome['materials'], 'supports': outcome['supports'],
    'lineage': 'new consumer source pins; original signed material bytes, slot identities, tasks, policy and authorities retained',
    'material_availability': outcome['material_availability'], 'ready_request_count': 130,
    'ready_role_counts': counts, 'design_main_opportunities': 180, 'design_possible_title_opportunities': 180,
    'main_timeout_seconds': 60, 'reasoning_effort': 'low', 'max_retries': 0,
    'model_calls': 0, 'validation_access': False, 'calibration_eligible': False,
    'additional_paid_api_budget': 0, 'settled_additional_charge_usd': None,
    'authorized_account_binding': old_prep['authorized_account_binding'],
    'auth_handling': 'opaque private copy; contents never logged, hashed or published',
    'source_unchanged_after_preparation': True}
write_record(ROOT / 'public-preparation.json', receipt)
print(json.dumps(receipt), flush=True)
