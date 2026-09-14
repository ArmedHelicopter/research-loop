"""Retain the closed native review prefix, including its terminal failure."""
import hashlib
import json
from pathlib import Path
import shutil
from collections import Counter

WORK = Path(__file__).parent
RUN = WORK / 'headless-review-run-r1'
PREP = WORK / 'headless-review-preparation-r1'
TARGET = WORK.parent / 'artifact-evidence-provenance/results/modular-engineering-20260915/actual-headless-review-r1'
READBACK = WORK / 'headless-review-independent-readback-r1.json'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


assert READBACK.is_file() and not TARGET.exists()
closure = json.loads((RUN / 'public-parent-closure.json').read_bytes())
assert closure['source_unchanged'] and closure['worker_exit'] == 0 and closure['owned_tree_closed'] and not closure['parent_timeout']
assert sha(closure['diagnostic_result']['path']) == closure['diagnostic_result']['sha256']
readback = json.loads(READBACK.read_bytes())
assert readback['result_sha256'] == closure['diagnostic_result']['sha256']
assert Counter(row['verification'] for row in readback['native_readbacks']) == {
    'independently_bound': 10, 'rejected_receipt_preserved_unbound': 1}
assert readback['source_metadata_before'] == readback['source_metadata_after']
assert readback['full_memory_replay'].startswith('exact result and journal match')
report = json.loads(Path(closure['diagnostic_result']['path']).read_bytes())['body']['payload']
assert report['budget']['reserved_main_opportunities'] == 11
assert report['budget']['further_io_blocked'] and report['budget']['calls']['evaluator'] == 0
TARGET.mkdir(parents=True)
copied = []


def copy(source, name):
    source, destination = Path(source), TARGET / name
    assert source.is_file() and not source.is_symlink()
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    assert sha(destination) == sha(source)
    copied.append({'path': name, 'source': str(source), 'bytes': source.stat().st_size, 'sha256': sha(source)})


for source, name in (
        (RUN / 'public-parent-closure.json', 'public-parent-closure.json'),
        (RUN / 'parent-reservation.json', 'parent-reservation.json'),
        (RUN / 'diagnostic-result.private.json', 'diagnostic-result.json'),
        (PREP / 'public-preparation.json', 'public-preparation.json'),
        (READBACK, 'independent-readback.json'),
        (WORK / 'headless-review-source-byte-sync-r1.json', 'source-byte-sync.json'),
        (WORK / 'headless-review-account-readonly-r1/public-observation.json', 'later-account-readonly-observation.json')):
    copy(source, name)
native_root = RUN / 'review.private.jsonl.headless'
observers = sorted(native_root.glob('*/native/observer-receipt.json'))
assert len(observers) == 11
for path in observers:
    copy(path, 'native-observers/' + path.parent.parent.name + '.json')
for name in ('prepare_headless_review_r1.py', 'run_headless_review_r1.py', 'audit_headless_review_r1.py',
        'create_headless_review_runtime_r1.py', 'finalize_headless_review_runtime_r1.py',
        'check_headless_review_account_r1.py', 'archive_actual_headless_review_r1.py'):
    copy(WORK / name, 'helpers/' + name)

inventory = []
omitted = 0
for base in (RUN, PREP, WORK / 'headless-review-account-readonly-r1'):
    for path in sorted(base.rglob('*')):
        if not path.is_file():
            continue
        assert not path.is_symlink()
        if path.name == 'auth.json' or path.suffix == '.key':
            omitted += 1
            continue
        inventory.append({'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha(path)})
(TARGET / 'private-artifact-inventory.json').write_text(json.dumps({'schema': 'private-artifact-pointers-v1',
    'purpose': 'exact local byte pointers; private request/response/account bodies are not copied into this archive',
    'omitted_auth_or_key_files': omitted, 'files': inventory}, indent=2) + '\n', encoding='utf-8')
(TARGET / '.gitattributes').write_bytes(b'* -text\n')
manifest = {'schema': 'closed-native-review-archive-v1', 'source_commit': closure['source_commit'],
    'copied_originals': copied, 'source_check_archive': '../headless-review-adapter-r1',
    'main_reservations': 11, 'accepted_native_and_consumer_calls': 10, 'rejected_with_known_usage': 1,
    'evaluator_calls': 0, 'model_retries': 0, 'extra_paid_api_budget': 0,
    'title_usage': None, 'all_opportunity_tokens': None, 'settled_additional_charge_usd': None,
    'calibration_eligible': False, 'validation_access': False,
    'limits': ['The last call has a complete model stream but incomplete postflight account observation.',
        'A later successful account GET cannot fill the historical missing observation.',
        'No benchmark effectiveness or independent scientific sample claim follows from this diagnostic prefix.']}
(TARGET / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'archive': str(TARGET), 'copied_originals': len(copied), 'private_artifact_pointers': len(inventory),
    'omitted_auth_or_key_files': omitted}))
