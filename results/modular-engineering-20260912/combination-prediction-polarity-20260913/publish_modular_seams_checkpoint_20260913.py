"""Archive exact closed engineering reports and approved metadata only."""
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
ROOT = BASE / 'integration'
ARCHIVE = ROOT / 'results/modular-engineering-20260912'
DEST = ARCHIVE / 'combination-prediction-polarity-20260913'
assert not DEST.exists()
old = json.loads((ARCHIVE / 'SHA256.json').read_text(encoding='utf-8'))
assert len(old) == 852
for name, expected in old.items():
    assert hashlib.sha256((ARCHIVE / name).read_bytes()).hexdigest() == expected, name
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip().startswith('fd985fa')
DEST.mkdir()
origins, reports = {}, {}

def copy(relative, target, source_ref=None, expected_hash=None):
    source = BASE / relative
    assert source.is_file() and not source.is_symlink()
    raw = source.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if expected_hash is not None:
        assert sha == expected_hash, relative
    (DEST / target).write_bytes(raw)
    origins[target] = {'source': str(source), 'sha256': sha, 'source_ref': source_ref}
    return raw

for relative, target, ref, expected in (
    ('integration/work/combination-public-root-20260913-r1.xml', 'combination-public-root-3532e62.xml', '3532e62', (63, 0, 0, 0)),
    ('work/prediction-root-semantics-r1.xml', 'prediction-semantic-first-failure.xml', 'uncommitted root semantic repair before a45c84d; no commit-pinned source claim', (40, 1, 0, 0)),
    ('work/prediction-root-semantics-r2.xml', 'prediction-semantic-repair-a45c84d.xml', 'a45c84d', (42, 0, 0, 0)),
    ('integration/work/prediction-controller-root-20260913-r1.xml', 'prediction-controller-1e54633.xml', '1e54633', (131, 0, 0, 0)),
    ('integration/work/polarity-controller-root-20260913-r1.xml', 'polarity-controller-1576525.xml', '1576525', (108, 0, 0, 0)),
    ('integration/work/combination-scoring-root-20260913-r1.xml', 'combination-scoring-fd985fa.xml', 'fd985fa', (34, 0, 0, 0)),
):
    raw = copy(relative, target, ref)
    suite = ET.fromstring(raw).find('testsuite')
    stats = {key: suite.attrib[key] for key in ('tests', 'failures', 'errors', 'skipped', 'time')}
    assert tuple(int(stats[key]) for key in ('tests', 'failures', 'errors', 'skipped')) == expected
    if len(ref) == 7:
        origins[target]['source_commit'] = subprocess.check_output(['git', 'rev-parse', ref], cwd=ROOT, text=True).strip()
    reports[target] = stats

copy('work/extended-data-qualification-custodian-live-r3/extended-custodian-metadata-receipt.json',
     'extended-custodian-metadata-receipt.json', 'metadata-only received artifact qualification',
     '18cd3ddcaeeacc6ea438ba792506f574567ee8c80928685bc79f0f20ad40a9bd')
copy('work/corebench-controlled-acquisition-r1/acquisition-receipt.json',
     'corebench-acquisition-receipt.json', 'acquisition event only; later exposure failure overrides unseen eligibility',
     '4925170ae599892d0d4b012e4ec46a38f17404c3eb50a8d4b6f1d935e9ffeec9')
copy('work/corebench-controlled-acquisition-r1/exposure-failure.json',
     'corebench-exposure-failure.json', 'dynamic result-key exposure; not validation eligible')
copy('work/corebench-controlled-acquisition-r1/extended-overlap-baseline.json',
     'extended-overlap-baseline.json', 'opaque equality baseline only; not lineage independence proof')
copy('work/publish_modular_seams_checkpoint_20260913.py', 'publish_modular_seams_checkpoint_20260913.py')

def record(name, value):
    (DEST / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')

record('origins.json', origins)
record('checkpoint.json', {
    'schema': 'modular-seams-checkpoint-v1', 'checked_source': 'fd985fa65d0c218559e2adb2d98bc706820b6ae5',
    'reports': reports, 'production_question_drivers': 20,
    'actual_combination_driver': 'pair:M4+M5 only; synthetic Docker scored-grid verification',
    'planning_only': ['Q3.2', 'Q5.3'],
    'signed_material_without_session_execution': ['Q2.5', 'Q2.6'],
    'new_paid_calls': 0, 'new_scientific_effect': 'not_measured', 'validation_acceptance': 'not_measured',
    'corebench_exposure': 'failed; not eligible for unseen validation in this optimization context',
    'full_suite': 'running separately on frozen fd985fa; no completion claim in this checkpoint',
    'all_48_and_singletons_pairs_triples_full_loo_and_separate_q63_still_required': True,
    'raw_private_payloads_or_keys_archived': False,
})
index = {p.relative_to(ARCHIVE).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
         for p in sorted(ARCHIVE.rglob('*')) if p.is_file() and p.name != 'SHA256.json'}
assert all(index[name] == expected for name, expected in old.items())
(ARCHIVE / 'SHA256.json').write_text(json.dumps(index, indent=2) + '\n', encoding='utf-8', newline='\n')
print(json.dumps({'old_files_preserved': len(old), 'new_files': len(index)-len(old), 'total': len(index), 'reports': reports}))
