"""Count original frozen fixture requests and actual Docker argv receipts."""
import json
import os
from pathlib import Path
import sys

prefix = Path(sys.argv[1])
closed = json.loads(Path(str(prefix)+'-closed.json').read_bytes())
assert closed['source_unchanged']
rows = []
docker = {}
for directory, dirs, files in os.walk(prefix, followlinks=False):
    dirs[:] = [name for name in dirs if name != 'attack'
        and not (Path(directory)/name).is_symlink() and not (Path(directory)/name).is_junction()]
    if 'trace.jsonl' not in files: continue
    path = Path(directory)/'trace.jsonl'
    if path.is_symlink(): continue
    events = [json.loads(line) for line in path.read_bytes().splitlines()]
    if not any(e.get('stage') == 'q32_plans_frozen' for e in events): continue
    actual = []
    for event in events:
        if event['stage'] != 'execution_result': continue
        receipt = event['data']['receipt']
        argv = receipt['record'].get('argv', [])
        if argv[:2] != ['docker', 'run']: continue
        invocation = argv[argv.index('--name') + 1]
        if invocation in docker: assert docker[invocation] == receipt
        docker[invocation] = receipt
        actual.append(invocation)
    rows.append({'trace': str(path), 'model_requests': sum(e['stage'] == 'model_request' for e in events),
        'execution_requests': sum(e['stage'] == 'execution_request' for e in events),
        'actual_docker_invocations': actual})
value = {'schema': 'q32-frozen-execution-accounting-v1', 'source_commit': closed['commit'],
    'scope': 'original fixture trace requests; no synthetic receipt interpreted as a real Docker invocation',
    'original_traces': len(rows), 'model_requests': sum(row['model_requests'] for row in rows),
    'execution_requests': sum(row['execution_requests'] for row in rows),
    'distinct_actual_docker_receipts': len(docker), 'rows': rows,
    'model_transport': 'synthetic; no service dispatch', 'new_paid_api_calls': 0, 'real_val_access': False}
out = Path(str(prefix)+'-accounting.json')
with out.open('xb') as stream: stream.write((json.dumps(value, indent=2)+'\n').encode())
print(json.dumps({key: val for key, val in value.items() if key != 'rows'}))
