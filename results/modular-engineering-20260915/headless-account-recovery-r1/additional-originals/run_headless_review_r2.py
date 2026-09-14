"""Run a frozen correlated TRAIN review batch within the cumulative allowance."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

WORK = Path(__file__).parent
TREE = WORK.parent / 'headless-review-recovery-runtime'
PREP = WORK / 'headless-review-preparation-r2'
CHECK = WORK / 'headless-account-recovery-root-r1-closed.json'
ROOT = WORK / 'headless-review-run-r2'
RECOVERY = {'schema': 'headless-account-read-recovery-v1', 'max_attempts': 2}
CAPS = {'reviewer1': 36, 'reviewer2': 36, 'arbitrator': 36, 'evaluator': 72}
SPENT = {'reviewer1': 5, 'reviewer2': 5, 'arbitrator': 1, 'evaluator': 0}
REMAINING = {role: CAPS[role] - SPENT[role] for role in CAPS}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engineering-check-sha256', required=True)
    parser.add_argument('--preparation-sha256', required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(TREE))
    from evaluation.modular.diagnostic_material_authoring import write_record
    from evaluation.modular.diagnostic_subscription import load_private, sha
    from research_loop.modular.grok_headless_transport import _child

    assert sha(CHECK) == args.engineering_check_sha256
    check = json.loads(CHECK.read_bytes())
    assert sha(PREP / 'public-preparation.json') == args.preparation_sha256
    prepared = json.loads((PREP / 'public-preparation.json').read_bytes())
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=TREE, text=True).strip()
    assert head == check['commit'] == prepared['source_commit']
    assert check['exit_code'] == 0 and check['source_unchanged'] and prepared['model_calls'] == 0
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=TREE).strip()
    assert not (TREE / 'data').exists() and not (TREE / 'results').exists()
    assert all(sha(TREE / name) == pin for name, pin in check['source_after'].items())
    config_desc = prepared['worker_config']
    config, manifest, _, _, _, guard = load_private(config_desc)
    assert config['schema'] == 'diagnostic-subscription-worker-config-v4'
    assert config['transport'] == 'headless' and config['account_read_recovery'] == RECOVERY
    assert Path(config['journal_path']) == ROOT / 'review.private.jsonl' and not ROOT.exists()
    allocation_desc = prepared['allocation_envelope']
    assert sha(allocation_desc['path']) == allocation_desc['sha256']
    allocation = json.loads(Path(allocation_desc['path']).read_bytes())
    assert allocation['spent_main'] == SPENT | {'total_main': 11}
    assert allocation['remaining_main'] == REMAINING | {'total_main': 169}
    assert allocation['cumulative_main_caps'] == CAPS | {'total_main': 180}
    assert allocation['parent'] == {
        'diagnostic_result': prepared['parent_result'],
        'independent_readback': prepared['parent_independent_readback'],
        'worker_config': prepared['parent_worker_config'],
        'public_parent_closure': prepared['parent_public_closure']}
    assert prepared['parent_result']['sha256'] == '86003a6b1d654fc03646aaf24c60cd51ebdb53a1dd7fe1ff0779d137f3fcaa71'
    assert prepared['parent_independent_readback']['sha256'] == '275fde0086447697b169c105cb549196748fefd2317d17f705100ffa789666b1'
    assert prepared['parent_worker_config']['sha256'] == 'ae394ced8833f0b750c485a2a474682ded1ea786dbe2307449ed1fed0b357799'
    for descriptor in allocation['parent'].values():
        assert sha(descriptor['path']) == descriptor['sha256']
    policy = manifest.data()['policy']
    assert policy['max_main_opportunities'] == policy['max_title_opportunities'] == 169
    assert policy['max_total_opportunities'] == 338
    assert {role: port['max_calls'] for role, port in policy['ports'].items()} == REMAINING
    deployment_desc = config['native_deployment']
    assert sha(deployment_desc['path']) == deployment_desc['sha256']
    deployment = json.loads(Path(deployment_desc['path']).read_bytes())
    assert deployment['schema'] == 'frozen-native-subscription-headless-deployment-v2'
    assert deployment['account_read_recovery'] == RECOVERY
    assert len(deployment['slots']) == prepared['ready_request_count'] == 130
    assert deployment['frozen_files'][allocation_desc['path']] == allocation_desc['sha256']
    assert all(sha(path) == pin for path, pin in deployment['frozen_files'].items())
    for slot in deployment['slots'].values():
        rows = [v for v in json.loads((Path(slot['private_home']) / 'auth.json').read_bytes()).values()
            if type(v) is dict and v.get('auth_mode') == 'oidc'
            and v.get('oidc_issuer') == 'https://auth.x.ai'
            and v.get('oidc_client_id') == 'b1a00492-073a-47ea-816f-4c329264a828']
        assert len(rows) == 1
        assert hashlib.sha256(rows[0]['user_id'].encode()).hexdigest() == prepared['authorized_account_binding']
    guard()
    ROOT.mkdir()
    output = ROOT / 'diagnostic-result.private.json'
    command = [sys.executable, '-m', 'evaluation.modular.diagnostic_subscription', 'run',
        '--config', config_desc['path'], '--sha256', config_desc['sha256'], '--output', str(output)]
    environment = {k: v for k, v in os.environ.items() if k.upper() in {
        'SYSTEMROOT', 'WINDIR', 'SYSTEMDRIVE', 'COMSPEC', 'PATHEXT', 'PATH',
        'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'OS'}}
    environment.update(PYTHONPATH=str(TREE), TEMP=str(ROOT), TMP=str(ROOT))
    write_record(ROOT / 'parent-reservation.json', {
        'schema': 'headless-diagnostic-review-parent-v2', 'source_commit': head,
        'source_files': check['source_after'], 'worker_config': config_desc,
        'runner_sha256': sha(__file__), 'preparation_sha256': args.preparation_sha256,
        'allocation_envelope': allocation_desc, 'account_read_recovery': RECOVERY,
        'authorized_account_binding': prepared['authorized_account_binding'], 'command': command,
        'timeout_seconds': 10800, 'main_timeout_seconds': 60,
        'cumulative_max_main': 180, 'previous_main_spent': 11, 'new_max_main': 169,
        'ready_request_upper_bound': 130, 'main_retry': False, 'reasoning_effort': 'low',
        'additional_paid_api_budget': 0, 'validation_access': False,
        'material_generation_calls': 0, 'correlated_with_parent': True})
    _, process = _child(command, {'cwd': str(TREE)}, environment, ROOT / 'worker', 10800)
    unchanged = all(sha(TREE / name) == pin for name, pin in check['source_after'].items())
    receipt = {'schema': 'headless-diagnostic-review-parent-closure-v2', 'source_commit': head,
        'worker_exit': process['process_exit_code'], 'parent_timeout': process['timed_out'],
        'owned_tree_closed': process['owned_tree_closed'], 'process_failure': process['failure'],
        'source_unchanged': unchanged, 'worker_config': config_desc,
        'diagnostic_result': {'path': str(output), 'sha256': sha(output)} if output.exists() else None,
        'allocation_envelope': allocation_desc, 'cumulative_max_main': 180,
        'previous_main_spent': 11, 'new_max_main': 169, 'ready_request_upper_bound': 130,
        'main_retry': False, 'reasoning_effort': 'low', 'validation_access': False,
        'calibration_eligible': False, 'correlated_with_parent': True,
        'settled_additional_charge_usd': None}
    write_record(ROOT / 'public-parent-closure.json', receipt)
    print(json.dumps(receipt), flush=True)
    raise SystemExit(int(not unchanged or process['process_exit_code'] != 0 or process['timed_out']))


if __name__ == '__main__':
    main()
