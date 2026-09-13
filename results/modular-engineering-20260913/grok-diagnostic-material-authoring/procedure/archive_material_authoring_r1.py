"""Explicit public allowlist; actual private bodies and login material excluded."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

WORK = Path('E:/_ryanDev/AI/research-loop-modular/work')
REPO = WORK.parent / 'grok-materials'; sys.path.insert(0, str(REPO))
from evaluation.modular.diagnostic_material_authoring import own_sources

OUT = REPO / 'results/modular-engineering-20260913/grok-diagnostic-material-authoring'
RUN = WORK / 'material-authoring-actual-run-r1'
PREP = WORK / 'material-authoring-actual-preparation-r1'
CHECK = WORK / 'material-authoring-frozen-check-r2'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(path, value):
    with Path(path).open('x', encoding='utf-8') as out:
        json.dump(value, out, indent=2, sort_keys=True); out.write('\n')
def git(*args):
    return subprocess.check_output(['git', *args], cwd=REPO, text=True).strip()
check = json.loads((CHECK / 'receipt.json').read_text())
assert check['pytest_exit'] == 0 and check['tests'] == 32 and check['source_hashes_unchanged']
assert git('rev-parse', 'HEAD') == check['commit'] and not git('status', '--porcelain')
closure = json.loads((RUN / 'public-parent-closure.json').read_text())
assert closure['parent_tree_closed'] and closure['source_hashes_unchanged']
assert not closure['parent_timeout'] and closure['worker_exit'] == 0
public = json.loads((RUN / 'private-output/public-outcome.json').read_text())
assert public['further_authoring_io_blocked'] and public['review_dispatch_blocked']
assert public['material_availability'] == {'ready': 0, 'unresolved_material': 36, 'not_applicable': 0}
native_path = next((RUN / 'private-output').glob('*/native/observer-receipt.json'))
native = json.loads(native_path.read_text())
assert native['faults'] == ['timeout'] and native['prompt_may_have_been_dispatched'] is False
assert native['prompt_requests_reserved'] == 0 and native['runtime_empty_inventory_count'] == 0
assert native['billing_before'] is None and native['billing_after'] is None
requests = [json.loads(line) for line in (native_path.parent / 'requests.private.jsonl').read_text().splitlines()]
assert [r['method'] for r in requests] == ['initialize']
assert (native_path.parent / 'stdout.private.jsonl').stat().st_size == 0
assert (native_path.parent / 'stderr.private.txt').stat().st_size == 0
inventory = json.loads((RUN / 'private-output/ready-review-request-inventory.json').read_text())
assert not inventory['entries'] and inventory['slot_count'] == 36 and inventory['evaluator_opportunity_count'] == 72

# Only this outside-Git manifest inventories actual private artifact bytes.
# Native auth, authority keys and entire runtime profiles are excluded entirely.
private_files = [p for p in RUN.rglob('*') if p.is_file()]
private_files += [PREP / 'config.private.json', PREP / 'native-deployment.private.json',
    PREP / 'freeze/authoring-envelope.json', PREP / 'freeze/authoring-envelope.run-reservation.json']
private_files += list((PREP / 'freeze/private-prompts').glob('*.json'))
private_files = sorted(set(private_files))
private_manifest = WORK / 'material-authoring-private-integrity-r1.json'
write(private_manifest, {'schema': 'private-authoring-artifact-integrity-v1',
    'terminal': True, 'auth_and_authority_key_bytes_and_hashes_excluded': True,
    'entries': [{'path': str(p), 'bytes': p.stat().st_size, 'sha256': sha(p)} for p in private_files]})

OUT.mkdir(parents=True, exist_ok=False)
def copy(source, destination):
    target = OUT / destination; target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target); assert target.read_bytes() == Path(source).read_bytes()
pins = json.loads((CHECK / 'before-source-sha256.json').read_text())
sources = {p.relative_to(REPO).as_posix() for p in own_sources().values()}
sources |= {'tests/fixtures/grok_acp_peer.py', 'tests/helpers/material_authoring_fixture.py',
    'tests/helpers/material_authoring_worker.py', 'tests/helpers/subscription_worker.py',
    'tests/test_diagnostic_material_authoring.py', 'tests/test_diagnostic_subscription.py',
    'tests/test_grok_acp_transport.py', 'tests/test_calibration_pilot.py',
    'tests/test_diagnostic_private_ports.py', 'tests/test_label_isolation.py',
    'docs/GROK_DIAGNOSTIC_MATERIAL_AUTHORING.md', 'docs/GROK_SUBSCRIPTION_DIAGNOSTIC.md',
    'docs/GROK_ACP_TRANSPORT.md', 'docs/GROK_ACP_PROTOCOL_REVIEW.md'}
for name in sorted(sources):
    assert sha(REPO / name) == pins[name]
    copy(REPO / name, 'source/' + name)
for number in (1, 2):
    check_root = WORK / f'material-authoring-frozen-check-r{number}'
    for name in ('receipt.json', 'before-source-sha256.json', 'after-source-sha256.json',
                 'pytest.stdout.bin', 'pytest.stderr.bin', 'pytest.xml'):
        copy(check_root / name, f'frozen-check-r{number}/' + name)
    copy(WORK / f'material-authoring-preliminary-r{number}.xml', f'preliminary-r{number}/pytest.xml')
for name in ('verify_material_authoring_frozen_r1.py', 'verify_material_authoring_frozen_r2.py',
             'prepare_material_authoring_actual_r1.py', 'run_material_authoring_actual_once_r1.py',
             'diagnostic-material-authoring-next-scope.md', 'material-authoring-root-metadata-review-r1.md'):
    copy(WORK / name, 'procedure/' + name)
copy(PREP / 'freeze/public-freeze-metadata.json', 'actual/public-freeze-metadata.json')
copy(PREP / 'public-preparation-receipt.json', 'actual/public-preparation-receipt.json')
copy(RUN / 'public-parent-closure.json', 'actual/public-parent-closure.json')
copy(RUN / 'private-output/public-outcome.json', 'actual/public-outcome.json')
copy(native_path, 'actual/native-observer-receipt.json')
summary = {'schema': 'provisional-train-authoring-terminal-closure-v1',
    'tested_source_commit': check['commit'], 'production_commit': '5826fa3fd3a855d57e4dc4d684bb1ec1ea3bda1b',
    'original_frozen_check': {'tests': 142, 'passed': 141, 'failures': 1,
        'failure': 'synthetic peer timeout; retained unknown usage and blocked later fixture calls'},
    'repaired_frozen_check': {'tests': 32, 'passed': 32, 'failures': 0, 'source_hashes_unchanged': 681},
    'preliminary_checks_not_frozen': [17, 8], 'preliminary_separate_stdout_capture': False,
    'authoring_envelope_sha256': closure['authoring_envelope_sha256'],
    'planned_main_opportunities': 4, 'planned_possible_title_opportunities': 4,
    'native_process_attempts': 1, 'native_request_methods': ['initialize'],
    'model_prompt_requests': 0, 'native_prompt_reservations': 0, 'accepted_authoring_responses': 0,
    'terminal_failure': 'native initialize timed out without stdout/stderr or session creation',
    'native_account_model_and_empty_tools_gates_completed': False,
    'known_main_usage': None, 'known_response_usage': [], 'title_usage': None,
    'all_opportunity_tokens': None, 'all_opportunity_cost_usd': None, 'settled_additional_charge_usd': None,
    'remaining_authoring_tasks_blocked': 3, 'retry_allowed': False,
    'material_availability': public['material_availability'], 'all_expected_targets_unknown': True,
    'slot_count': 36, 'evaluator_opportunity_count': 72, 'ready_review_request_count': 0,
    'separate_review_evaluator_main_allocation': 180, 'review_evaluator_requests_dispatched': 0,
    'review_dispatch_blocked': True, 'expert_certification': False, 'validation_eligible': False,
    'private_integrity_manifest': {'path': str(private_manifest), 'sha256': sha(private_manifest),
        'file_count': len(private_files)},
    'actual_auth_and_authority_key_material_excluded': True,
    'actual_prompt_reference_candidate_support_raw_stream_bodies_excluded': True}
write(OUT / 'closure-summary.json', summary)
(OUT / 'README.md').write_text('''# Provisional TRAIN authoring: terminal pre-prompt timeout

The reviewed four-task authoring envelope was executed once. The first native
process wrote only initialize and received no stdout/stderr before its timeout.
No session, account/model/tool gate, native prompt reservation, model prompt or
accepted authoring response completed. The other three authoring tasks remained
blocked. This terminal envelope is not retried. Its main/title/accounting fields
remain unknown; zero observed model prompts is not a claim of settled zero cost.

All36 signed material slots remain unresolved with unknown expected targets.
All72 evaluator opportunities remain represented. The ready review inventory
has zero entries, and the separate180-main diagnostic remains undispatched and
blocked. No expert certification, calibration or scientific validity is claimed.

The public allowlist preserves production source and procedures, original frozen
R1 (141/142 passes, one synthetic timeout) and repaired R2 (32/32 passes), including
original streams/XML and unchanged681-file source snapshots. Preliminary17/8
checks are explicitly not frozen; their original XML survives, but separate
stdout/stderr was not captured. Only fixture deadlines changed after R1; native
60 seconds and the reviewed authoring4+4 opportunity contract stayed fixed.

Actual references/prompts/candidates/supports/raw ACP streams remain private.
The outside-Git integrity manifest binds their retained bytes; only its digest,
path and count appear here. Auth and authority keys are neither copied nor hashed
into this archive. Native observer/public outcome metadata contains no bodies.

payload-sha256.json is the public payload allowlist. evidence.zip contains exactly
those entries. verify_archive.py checks every disk/index/Git blob and decompressed
ZIP byte. The post-commit verification receipt stays outside Git to avoid a cycle.
''', encoding='utf-8')
(OUT / '.gitattributes').write_text('* -text\n')
copy(WORK / 'verify_grok_acp_archive.py', 'verify_archive.py')
copy(__file__, 'procedure/archive_material_authoring_r1.py')
entries = [{'path': p.relative_to(OUT).as_posix(), 'size': p.stat().st_size, 'sha256': sha(p)}
    for p in sorted(OUT.rglob('*')) if p.is_file()]
write(OUT / 'payload-sha256.json', entries)
with zipfile.ZipFile(OUT / 'evidence.zip', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
    for item in entries:
        info = zipfile.ZipInfo(item['path'], date_time=(2026, 9, 14, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, (OUT / item['path']).read_bytes())
print(json.dumps({'archive': str(OUT), 'payload_files': len(entries), 'total_files': len(entries) + 2,
    'private_manifest_sha256': sha(private_manifest), 'private_manifest_file_count': len(private_files)}))
