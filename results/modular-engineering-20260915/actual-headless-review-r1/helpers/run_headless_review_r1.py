"""Run one frozen TRAIN diagnostic review batch with the native subscription CLI."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

WORK = Path(__file__).parent
TREE = WORK.parent / 'headless-review-runtime'
PREP = WORK / 'headless-review-preparation-r1'
CHECK = WORK / 'headless-review-adapter-root-r1-closed.json'
ROOT = WORK / 'headless-review-run-r1'
sys.path.insert(0, str(TREE))
from evaluation.modular.diagnostic_material_authoring import write_record
from evaluation.modular.diagnostic_subscription import sha
from research_loop.modular.grok_headless_transport import _child

assert sha(CHECK) == '4c22d1ecd353bd1cc714186e86756165db8ed8ef7d3b9fdc52c1138e281b610a'
check = json.loads(CHECK.read_bytes())
assert sha(PREP / 'public-preparation.json') == '06091b79d15bf70b02a413e5d6d3e2466b2080bfb0094db1f35d5c290f44c366'
prepared = json.loads((PREP / 'public-preparation.json').read_bytes())
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=TREE, text=True).strip()
assert head == check['commit'] == prepared['source_commit']
assert check['exit_code'] == 0 and check['source_unchanged'] and prepared['model_calls'] == 0
assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=TREE).strip()
assert not (TREE / 'data').exists()
assert all(sha(TREE / name) == pin for name, pin in check['source_after'].items())
config_desc = prepared['worker_config']
assert sha(config_desc['path']) == config_desc['sha256']
config = json.loads(Path(config_desc['path']).read_bytes())
assert config['schema'] == 'diagnostic-subscription-worker-config-v3' and config['transport'] == 'headless'
assert Path(config['journal_path']) == ROOT / 'review.private.jsonl' and not ROOT.exists()
deployment_desc = config['native_deployment']
assert sha(deployment_desc['path']) == deployment_desc['sha256']
deployment = json.loads(Path(deployment_desc['path']).read_bytes())
assert len(deployment['slots']) == prepared['ready_request_count'] == 130
assert all(sha(path) == pin for path, pin in deployment['frozen_files'].items())
for slot in deployment['slots'].values():
    rows = [v for v in json.loads((Path(slot['private_home']) / 'auth.json').read_bytes()).values()
        if type(v) is dict and v.get('auth_mode') == 'oidc'
        and v.get('oidc_issuer') == 'https://auth.x.ai'
        and v.get('oidc_client_id') == 'b1a00492-073a-47ea-816f-4c329264a828']
    assert len(rows) == 1
    assert hashlib.sha256(rows[0]['user_id'].encode()).hexdigest() == prepared['authorized_account_binding']
ROOT.mkdir()
output = ROOT / 'diagnostic-result.private.json'
command = [sys.executable, '-m', 'evaluation.modular.diagnostic_subscription', 'run',
    '--config', config_desc['path'], '--sha256', config_desc['sha256'], '--output', str(output)]
environment = {k: v for k, v in os.environ.items() if k.upper() in {
    'SYSTEMROOT', 'WINDIR', 'SYSTEMDRIVE', 'COMSPEC', 'PATHEXT', 'PATH',
    'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'OS'}}
environment.update(PYTHONPATH=str(TREE), TEMP=str(ROOT), TMP=str(ROOT))
write_record(ROOT / 'parent-reservation.json', {
    'schema': 'headless-diagnostic-review-parent-v1', 'source_commit': head,
    'source_files': check['source_after'], 'worker_config': config_desc,
    'runner_sha256': sha(__file__), 'preparation_sha256': sha(PREP / 'public-preparation.json'),
    'authorized_account_binding': prepared['authorized_account_binding'], 'command': command,
    'timeout_seconds': 10800, 'main_timeout_seconds': 60,
    'design_main_opportunities': 180, 'ready_request_upper_bound': 130,
    'design_possible_title_opportunities': 180, 'retry': False, 'reasoning_effort': 'low',
    'additional_paid_api_budget': 0, 'validation_access': False,
    'material_generation_calls': 0})
raw, process = _child(command, {'cwd': str(TREE)}, environment, ROOT / 'worker', 10800)
unchanged = all(sha(TREE / name) == pin for name, pin in check['source_after'].items())
receipt = {'schema': 'headless-diagnostic-review-parent-closure-v1', 'source_commit': head,
    'worker_exit': process['process_exit_code'], 'parent_timeout': process['timed_out'],
    'owned_tree_closed': process['owned_tree_closed'], 'process_failure': process['failure'],
    'source_unchanged': unchanged, 'worker_config': config_desc,
    'diagnostic_result': {'path': str(output), 'sha256': sha(output)} if output.exists() else None,
    'design_main_opportunities': 180, 'ready_request_upper_bound': 130,
    'retry': False, 'reasoning_effort': 'low', 'validation_access': False,
    'calibration_eligible': False, 'settled_additional_charge_usd': None}
write_record(ROOT / 'public-parent-closure.json', receipt)
print(json.dumps(receipt), flush=True)
raise SystemExit(int(not unchanged or process['process_exit_code'] != 0 or process['timed_out']))
