"""Read one already authorized train controller receipt; never read references."""
from pathlib import Path
import hashlib
import json
from datetime import datetime, timezone

ROOT = Path(r'E:\_ryanDev\AI\research-loop-modular\work\linked-train-scored-20260913-01')
DEST = Path(r'E:\_ryanDev\AI\research-loop-modular\work\linked-train-diagnosis-20260913-01')
source = ROOT / 'run/controller-attempt.json'
raw = source.read_bytes()
attempt = json.loads(raw)
assert attempt['status'] == 'execution_incomplete'
rows = attempt['linked_receipts']
assert len(rows) == 12
ALLOWED = {('blade', 'fish'), ('discoverybench', 'synth:test:philosophical-debates_0_0')}
FIELDS = {'arm_id', 'enabled', 'variant', 'candidate_package', 'scenario_controller_input',
          'driver_stage', 'm4_control_response', 'arm', 'cell_key', 'mechanism_stages'}

def paths(value, path=''):
    result = []
    if isinstance(value, dict):
        for key, item in value.items():
            next_path = path + '/' + key
            if key in FIELDS:
                result.append(next_path)
            result.extend(paths(item, next_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            result.extend(paths(item, path + '/' + str(index)))
    return result

observed, failures = [], []
for row in rows:
    identity = row['identity']
    assert identity['domain'] == 'train'
    assert (identity['benchmark'], identity['task_id']) in ALLOWED
    call_findings = []
    for phase in ('mechanism_calls', 'solver_calls'):
        for call in row[phase]:
            findings = paths(call['request'])
            call_findings.append({'phase': phase, 'slot': call['slot'],
                'request_digest': call['request_digest'], 'controller_metadata_paths': findings})
    observed.append({'cell_key': row['cell_key'], 'status': row['status'], 'calls': call_findings})
    if row['status'] == 'solver_execution_failed':
        receipt = row['execution']['record']
        failures.append({'cell_key': row['cell_key'], 'exit_code': receipt['exit_code'],
            'stderr': receipt['stderr'], 'actual_input_mount': '/input/public_csv'})

report = {'schema': 'train-attempt-request-diagnostic-v1',
    'diagnosed_at': datetime.now(timezone.utc).isoformat(),
    'source_path': str(source), 'source_sha256': hashlib.sha256(raw).hexdigest(),
    'frozen_source_commit': 'c3a4b21040e419692a74382c973104d5fe5cf7e1',
    'read_scope': 'exact 12 authorized train linked receipts; no reference or validation payload',
    'cells': 12, 'linked_successes': 10, 'execution_failures': failures,
    'request_metadata_findings': observed,
    'interpretation': 'Unblinded mechanism/solver requests and incomplete execution preclude a clean module-effect inference. Base-context review did not cover these dynamic request fields.',
    'action': 'Preserve frozen attempt; repair later source before a separately frozen run. No rerun or retry in this diagnostic.',
    'validation_items': 0, 'new_model_calls': 0}
DEST.mkdir(exist_ok=False)
(DEST / 'request-diagnosis.json').write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(',', ':')), encoding='utf-8')
print(json.dumps({'cells': len(observed), 'metadata_affected_cells': sum(any(call['controller_metadata_paths'] for call in row['calls']) for row in observed),
                  'execution_failures': len(failures), 'new_model_calls': 0, 'output': str(DEST / 'request-diagnosis.json')}))
