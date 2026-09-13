"""Read-only, metadata/hash verification of the fixed four TRAIN exports."""
import hashlib, json, subprocess
from pathlib import Path

B = Path('E:/_ryanDev/AI/research-loop-modular')
W = B / 'work/primary-prospective-export-live-r1'
S = B / 'custody-private/primary-process-split-20260913-r2'
def read(p): return json.loads(p.read_bytes())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def canonical(v): return json.dumps(v, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
def digest(v): return hashlib.sha256(canonical(v).encode()).hexdigest()

manifest = read(W / 'delivery-manifest-r1.json')
assert sha(W / 'delivery-manifest-r1.json') == '8f30d619bec9227d1064bf597d580b3a54426a76e3e683205dab50e3f17416d3'
for row in manifest['artifacts']:
    p = Path(row['path'])
    assert p.is_file() and not p.is_symlink() and not p.is_junction()
    assert sha(p) == row['sha256'] and p.stat().st_size == row['bytes']
request = read(W / 'frozen-request-r1.json')
before = read(W / 'before-bindings-r1.json')
after = read(W / 'after-bindings-r1.json')
for section in ('input_pins', 'protected_files', 'source_files'):
    assert before[section] == after[section]
for row in list(before['input_pins'].values()) + before['protected_files']:
    assert sha(Path(row['path'])) == row['sha256']
assert len(before['input_pins']) == 24 and len(before['protected_files']) == 4
for relative, value in request['source_files'].items():
    assert sha(B / 'primary-prospective-export' / relative) == value
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=B/'primary-prospective-export', text=True).strip()
assert head == request['source_commit']
assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=B/'primary-prospective-export', text=True).strip()
assert sha(S/'prospective-split.json') == request['split_raw_sha256']
assert sha(S/'process-audit.json') == request['audit_raw_sha256']
split, audit = read(S/'prospective-split.json'), read(S/'process-audit.json')
assert digest(split) == request['split_digest'] and digest(audit) == request['audit_digest']
groups = {token: group for group in split['groups'] for token in group['member_tokens']}
expected = []
for source in ('discoverybench', 'blade'):
    eligible = sorted(row['token'] for row in audit['rows'] if row['source'] == source
                      and row['original_train'] is True and groups[row['token']]['split'] == 'train')
    expected.extend(eligible[:2])
assert [row['token'] for row in request['items']] == expected
assert all(row['group_sha256'] == groups[row['token']]['group_sha256'] for row in request['items'])
assert request['validation_access_enabled'] is False
eligibility = read(W/'primary-eligibility-r1.json')
assert eligibility['validation_access_enabled'] is False and eligibility['train_export_enabled'] is True
assert eligibility['split_sha256'] == request['split_digest'] and eligibility['audit_sha256'] == request['audit_digest']
assert not set(expected) & set(eligibility['held_member_tokens'])
assert not {groups[t]['group_sha256'] for t in expected} & set(eligibility['held_group_sha256'])
events = [json.loads(line) for line in (W/'export-audit/exports.jsonl').read_text(encoding='utf-8').splitlines()]
previous = '0'*64
for number, event in enumerate(events, 1):
    body = {key: value for key, value in event.items() if key != 'entry_sha256'}
    assert event['sequence'] == number and event['previous_sha256'] == previous
    assert digest(body) == event['entry_sha256']
    assert event['model_calls'] == event['network_calls'] == 0
    assert set(event['possibly_exposed_tokens']) <= set(expected)
    previous = event['entry_sha256']
assert len(events) == 7 and events[-1]['event'] == 'export_completed'
assert set(events[-1]['possibly_exposed_tokens']) == set(expected)
receipt = read(W/'public-train/export-receipt.json')
assert digest(receipt) == events[-1]['receipt_sha256']
result = read(W/'actual-result-r1.json')
assert result['status'] == 'success' and result['requested_train_count'] == 4
assert {row['token'] for row in result['packets']} == set(expected)
outputs = {p for p in (W/'public-train').rglob('*') if p.is_file()}
declared_outputs = {Path(row['path']) for row in manifest['artifacts'] if Path(row['path']).is_relative_to(W/'public-train')}
assert outputs == declared_outputs and len(outputs) == 13
output = {'schema': 'primary-live-root-metadata-verification-v1', 'status': 'verified',
          'delivery_manifest_sha256': sha(W/'delivery-manifest-r1.json'),
          'source_commit': head, 'artifacts_verified': len(manifest['artifacts']),
          'input_pins_verified': 24, 'protected_files_verified': 4,
          'original_train_and_new_train_selection_recomputed': True,
          'selected_sources': {'discoverybench': 2, 'blade': 2}, 'public_output_files': 13,
          'journal_events': len(events), 'journal_chain_verified': True,
          'public_task_and_csv_bytes_hashed_not_parsed': True,
          'validation_and_reference_payloads_parsed': False,
          'new_model_scorer_docker_network_calls': 0,
          'scientific_effectiveness': 'not_established',
          'script_sha256': sha(Path(__file__))}
path = B/'work/primary-live-root-metadata-verification-r1.json'
with path.open('x', encoding='utf-8', newline='\n') as handle:
    json.dump(output, handle, indent=2); handle.write('\n')
print(json.dumps(output))
