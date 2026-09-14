"""Public metadata projection of the independently replayed review run."""
import hashlib
import json
from pathlib import Path
from collections import Counter

WORK = Path(__file__).parent
RUN = WORK / 'headless-review-run-r1'
TARGET = WORK.parent / 'artifact-evidence-provenance/results/modular-engineering-20260915/actual-headless-review-r1'
prepared = json.loads((TARGET / 'public-preparation.json').read_bytes())
manifest = json.loads(Path(prepared['consumer_manifest']['path']).read_bytes())
materials = json.loads(Path(prepared['materials']['path']).read_bytes())
rows = [json.loads(line) for line in (RUN / 'review.private.jsonl').read_text().splitlines()]
audit = json.loads((TARGET / 'independent-readback.json').read_bytes())
assert audit['full_memory_replay'].startswith('exact result and journal match')
nodes, edges = {}, []

def node(name, kind, **fields):
    value = {'id': name, 'kind': kind, **fields}
    assert name not in nodes or nodes[name] == value
    nodes[name] = value
    return name

def edge(child, parent, relation):
    assert child in nodes and parent in nodes
    value = {'child': child, 'parent': parent, 'relation': relation}
    if value not in edges:
        edges.append(value)

producer = node('producer-manifest', 'producer_manifest', **prepared['producer_manifest'])
consumer = node('consumer-manifest', 'consumer_manifest', **prepared['consumer_manifest'])
source = node('consumer-source', 'frozen_source', commit=prepared['source_commit'],
    check=prepared['engineering_check'])
inventory = node('request-inventory', 'frozen_request_inventory', **prepared['consumer_inventory'])
edge(consumer, producer, 'retains_original_material_slots')
edge(consumer, source, 'configured_by')
edge(inventory, consumer, 'compiled_from')
for slot in manifest['slots']:
    sid = slot['slot_id']
    support = node('support:' + sid, 'original_authoring_support',
        digest=materials[sid]['body']['payload']['support_digest'], private_container=prepared['supports'])
    material = node('material:' + sid, 'original_signed_material', digest=slot['material_digest'],
        slot_id=sid, identity_digest=slot['identity_digest'], category=slot['kind'],
        status=slot['status'], candidate_digest=slot['candidate_digest'], private_container=prepared['materials'])
    edge(support, producer, 'produced_under')
    edge(material, support, 'cites_provisional_support')
    edge(consumer, material, 'retains_original_material')

call_nodes = {}
for row in rows:
    if row['event'] != 'subscription_headless_receipt':
        continue
    d, receipt = row['data'], row['data']['receipt']
    e = d['binding']; oid, sid = e['opportunity_id'], e['slot_id']
    request = node('request:' + oid, 'rendered_request', role=e['role'], request_digest=e['request_digest'],
        prompt_sha256=e['prompt_sha256'], schema_digest=e['schema_digest'], input_bytes=e['input_bytes'])
    edge(request, 'material:' + sid, 'consumes')
    edge(request, inventory, 'selected_frozen_entry')
    attempt = node('attempt:' + oid, 'native_observer', role=e['role'], accepted=receipt['accepted'],
        faults=receipt['faults'], path='native-observers/' + oid + '.json',
        sha256=hashlib.sha256((TARGET / 'native-observers' / (oid + '.json')).read_bytes()).hexdigest())
    edge(attempt, request, 'observed_execution_of')
    edge(attempt, source, 'executed_by')
    stream_path = RUN / 'review.private.jsonl.headless' / oid / 'native/stdout.private.jsonl'
    stream = node('stream:' + oid, 'original_native_stream', path=str(stream_path),
        sha256=receipt['native_process']['stdout_sha256'], status='retained_private')
    assert hashlib.sha256(stream_path.read_bytes()).hexdigest() == nodes[stream]['sha256']
    edge(attempt, stream, 'accounts_for_observed_output')
    if d['headless_binding'] is not None:
        binding = node('binding:' + oid, 'independent_consumption_binding',
            digest=next(x['binding_digest'] for x in audit['native_readbacks'] if x['opportunity_id'] == oid))
        edge(binding, attempt, 'independently_checked')
        call_nodes.setdefault(sid, []).append(binding)
    else:
        call_nodes.setdefault(sid, []).append(attempt)

decisions = next(r['data']['decisions'] for r in rows if r['event'] == 'reviews_frozen')
final = node('final-result', 'signed_diagnostic_result', path='diagnostic-result.json',
    sha256=audit['result_sha256'], evaluator_calls=0, calibration_eligible=False, validation_eligible=False)
for sid, decision in decisions.items():
    item = node('decision:' + sid, 'review_decision', slot_id=sid, state=decision['state'])
    edge(item, 'material:' + sid, 'material_subject')
    for call in call_nodes.get(sid, []):
        edge(item, call, 'uses_review_or_failure_state')
    edge(final, item, 'summarizes_diagnostic_status')
check = node('independent-readback', 'memory_consumer_replay', path='independent-readback.json',
    sha256=hashlib.sha256((TARGET / 'independent-readback.json').read_bytes()).hexdigest())
edge(check, final, 'reproduces_result_and_journal')
assert len(call_nodes) == 5 and len(decisions) == 36
out = {'schema': 'actual-review-artifact-lineage-v1', 'scope': 'metadata projection of the independently replayed TRAIN review prefix',
    'nodes': list(nodes.values()), 'edges': edges,
    'limits': ['Provisional support is not independently certified ground truth.',
        'The failed postflight node is retained as a failure and has no accepted consumption binding.',
        'This graph adds no scientific validity or coverage claim for other modules.']}
with (TARGET / 'lineage.json').open('x', encoding='utf-8') as f:
    json.dump(out, f, indent=2)
(TARGET / 'helpers/render_actual_review_lineage_r1.py').write_bytes(Path(__file__).read_bytes())
print(json.dumps({'nodes': len(nodes), 'edges': len(edges),
    'decision_states': dict(Counter(v['state'] for v in decisions.values()))}))
