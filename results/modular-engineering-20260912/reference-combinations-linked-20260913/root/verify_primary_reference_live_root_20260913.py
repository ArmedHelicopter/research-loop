"""Read metadata and hash bytes; never deserialize a private reference payload."""
import hashlib
import json
import subprocess
from pathlib import Path

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
WORK = BASE / 'work/primary-prospective-reference-live-r1'

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def digest(value): return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()

delivery_path = WORK / 'delivery-manifest-r1.json'
assert sha(delivery_path) == '1c5b4ad41c2eb834b32d62c2eb85148c9f76f1a6a53996a0029ad92a4717526a'
delivery = read(delivery_path)
assert delivery['status'] == 'success' and delivery['attempts'] == 1 and delivery['failed_attempts'] == 0
for entry in delivery['metadata_artifacts']:
    path = Path(entry['path'])
    assert sha(path) == entry['sha256'] and path.stat().st_size == entry['bytes'], path
assert len(delivery['metadata_artifacts']) == 13

request_path = WORK / 'frozen-reference-request-r1.json'
request = read(request_path)
assert sha(request_path) == 'd7f94a0968c05f0e16ebd7506213746dd621504f7c661e80362e546dfc77efb2'
plan_path = BASE / 'work/primary-reference-checks/actual-four-train-reference-plan-r1.json'
assert sha(plan_path) == '5e6a79bc55c1385b25f7eb73b61381adffb1a085d6a20b0c9ea68931e7208818'
plan = read(plan_path)
assert request['requests'] == plan['requests'] and len(request['requests']) == 4
assert request['selection_rule'] == plan['selection_rule']
assert request['attempt_limit'] == 1 and request['validation_access_enabled'] is False
assert all(request[key] is False for key in ('model_calls_authorized', 'scorer_calls_authorized', 'network_calls_authorized', 'docker_calls_authorized'))
for key in ('split_digest', 'audit_digest', 'split_raw_sha256', 'audit_raw_sha256'):
    assert request[key] == plan[key]
before, after = read(WORK / 'before-pins-r1.json'), read(WORK / 'after-pins-r1.json')
assert before['request_sha256'] == sha(request_path)
assert after['all_unchanged'] is True
for key in ('source_files', 'source_pins', 'protected_pins'):
    assert before[key] == after[key] == request[key], key
tree = BASE / 'pr-ref'
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=tree, text=True).strip()
assert head == request['source_commit'] == delivery['source_commit']
assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=tree, text=True).strip()
for name, expected in before['source_files'].items(): assert sha(tree / name) == expected, name
for entry in list(before['source_pins'].values()) + before['protected_pins']:
    assert sha(entry['path']) == entry['sha256'], entry['path']
assert (len(before['source_files']), len(before['source_pins']), len(before['protected_pins'])) == (261, 24, 37)

store = Path(request['store_root'])
manifest = read(store / 'manifest.json')  # Metadata only: no reference text.
publication = read(WORK / 'reference-publication-r1.json')
assert publication['scope'] == manifest['scope'] == 'train_only'
assert publication['manifest_sha256'] == sha(store / 'manifest.json')
assert publication['split_digest'] == manifest['split_digest'] == request['split_digest']
assert publication['inventory_digest'] == manifest['inventory_digest']
assert len(manifest['rows']) == publication['reference_count'] == 4
private = {Path(entry['path']).name: entry for entry in delivery['private_reference_artifacts']}
assert len(private) == 4 and {p.name for p in store.iterdir()} == {'manifest.json', *private}
requests_by_task = {row['task_sha256']: row for row in request['requests']}
tokens = sorted(row['item']['token'] for row in request['requests'])
for row in manifest['rows']:
    bound = requests_by_task[row['task_digest']]
    assert row['identity']['domain'] == 'train'
    assert row['identity']['benchmark'] == bound['item']['source']
    assert row['identity']['group_id'] == bound['item']['group_sha256']
    assert row['identity']['split_id'] == manifest['split_digest']
    assert row['identity_digest'] == digest(row['identity'])
    assert row['task_handle'] == publication['task_handles'][row['identity_digest']]
    entry = private[row['file']]
    assert entry['token'] == bound['item']['token']
    assert row['reference_sha256'] == entry['sha256'] == sha(store / row['file'])
    # Hash only. This root verification never parses the private reference file.

events = [json.loads(line) for line in (Path(request['audit_root']) / 'references.jsonl').read_text(encoding='utf-8').splitlines()]
attempt = read(WORK / 'attempt-metadata-r1.json')
assert [e['event'] for e in events] == ['attempt_reserved', 'sources_verified', *(['reference_read_reserved'] * 4), 'publication_reserved', 'completed']
previous = '0' * 64
for index, event in enumerate(events, 1):
    assert event['sequence'] == index and event['previous_sha256'] == previous
    assert event['entry_sha256'] == digest({k: v for k, v in event.items() if k != 'entry_sha256'})
    assert event['request_sha256'] == attempt['bridge_request_canonical_sha256']
    assert event['attempt'] == 1 and event['error'] is None
    assert event['model_calls'] == event['network_calls'] == event['validation_reference_count'] == 0
    assert event['possibly_read_train_tokens'] == tokens[:min(4, max(0, index - 2))]
    previous = event['entry_sha256']
assert [e['entry_sha256'] for e in events] == attempt['journal_event_sha256']
assert events[-1]['publication_sha256'] == digest(publication) == attempt['publication_canonical_sha256']
assert digest(attempt) == delivery['attempt_metadata_canonical_sha256']
assert attempt['failed'] is False and attempt['status'] == 'completed'

output = BASE / 'work/primary-reference-live-root-metadata-verification-r1.json'
assert not output.exists()
record = {'schema': 'primary-reference-root-metadata-verification-v1',
    'delivery_manifest_sha256': sha(delivery_path), 'source_commit': head,
    'source_files_unchanged': 261, 'input_pins_unchanged': 24, 'protected_files_unchanged': 37,
    'metadata_artifacts_verified': 13, 'fixed_train_items': 4,
    'private_reference_files_hash_verified': 4, 'private_reference_payloads_parsed': 0,
    'private_store_exact_file_count': 5, 'journal_events_verified': 8,
    'attempt_count': 1, 'failed_attempts': 0, 'request_matches_predeclared_plan': True,
    'validation_access_enabled': False, 'model_calls': 0, 'scorer_calls': 0, 'docker_calls': 0,
    'network_calls': 0, 'scientific_validity': 'not_measured', 'calibration': 'not_measured',
    'standard_resolver_checks': 'custodian_report_bound_by_verified_artifact_hashes_not_reexecuted_by_root',
    'original_public_export_and_seals_unchanged': True}
output.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'path': str(output), 'sha256': sha(output), 'verified_train_items': 4, 'verified_journal_events': 8}))
