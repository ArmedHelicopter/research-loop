"""Read-only replay of a failed training plan; never changes the live receipt."""
import json
from pathlib import Path
from research_loop.modular.contracts import DataIdentity
from research_loop.modular.modules.predictions import PredictionRegistry
from research_loop.ontology import canonical

root = Path(r'E:\_ryanDev\AI\research-loop-modular\work\q31-live-20260913-isolated')
rows = []
for path in sorted((root / 'run/cells').glob('*/trace.jsonl')):
    events = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    if events[-1]['stage'] != 'driver_failure':
        continue
    requests = [event['data']['request'] for event in events if event['stage'] == 'model_request']
    responses = [event['data']['response'] for event in events if event['stage'] == 'model_response']
    request, response = requests[-1], responses[-1]
    identity = DataIdentity.parse(request['task']['identity'])
    identity.require_train()
    detail = None
    try:
        PredictionRegistry(identity).freeze(response['question'], response['branches'], budget_units=response['budget_units'])
    except Exception as exc:
        detail = str(exc)
    rows.append({'trace_path': str(path), 'cell': request['module_context']['panel_cell'],
        'replayed_stage': 'PredictionRegistry.freeze', 'exact_rejection': detail,
        'branch_count': len(response['branches']), 'budget_units': response['budget_units'],
        'discriminator_ids_by_branch': [[p['discriminator_id'] for p in b['predictions']] for b in response['branches']],
        'original_status': 'failed', 'model_calls_added': 0, 'original_files_modified': False})
record = {'schema': 'q31-failed-plan-readonly-diagnostic-v1', 'diagnostics': rows}
out = root / 'failed-plan-diagnostic.json'
with out.open('x', encoding='utf-8') as handle:
    handle.write(canonical(record))
print(canonical(record))
