"""Archive separate root bridge failures and the bounded fixture repair closure."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

TREE = Path('E:/_ryanDev/AI/research-loop-modular/integration')
WORK = TREE.parent / 'work'
OUT = TREE / 'results/modular-engineering-20260913/grok-subscription-bridge-root'


def read(path):
    return json.loads(path.read_bytes())


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=TREE, text=True).strip()
closures = [read(WORK / f'grok-subscription-bridge-integrated-r{i}-closed.json') for i in (1, 2, 3)]
assert all(c['source_unchanged'] and c['new_paid_calls'] == 0 for c in closures)
assert closures[0]['junit'] == {'tests': 37, 'failures': 11, 'errors': 0, 'skipped': 0}
assert closures[1]['junit'] == {'tests': 37, 'failures': 3, 'errors': 0, 'skipped': 0}
assert closures[2]['junit'] == {'tests': 20, 'failures': 0, 'errors': 0, 'skipped': 0}
assert closures[2]['commit'] == head and closures[2]['exit_code'] == 0
changed = subprocess.check_output(['git', 'diff', '--name-only', closures[0]['commit'], head], cwd=TREE, text=True).splitlines()
assert set(changed) == {'tests/helpers/subscription_worker.py', 'tests/test_diagnostic_subscription.py', 'tests/test_calibration_pilot.py'}
OUT.mkdir(parents=True, exist_ok=False)
for i in (1, 2, 3):
    for suffix in ('-before.json', '-closed.json', '.xml'):
        path = WORK / f'grok-subscription-bridge-integrated-r{i}{suffix}'
        shutil.copyfile(path, OUT / path.name)
for name in ('grok-subscription-bridge-source-root-r1.json', 'subscription-root-fixture-repair-plan.md',
             'subscription-root-r2-closure-findings.md'):
    shutil.copyfile(WORK / name, OUT / name)
shutil.copyfile(__file__, OUT / Path(__file__).name)

# Keep the original synthetic timeout/partial-call records. Only allowlisted
# journal/observer streams enter this archive; key/config/reference files do not.
members = {}
names = {'observer-receipt.json', 'native-reservation.json', 'private-journal.jsonl', 'parent.jsonl',
         'stderr.private.txt', 'fixture-worker.stdout.bin', 'fixture-worker.stderr.bin'}
with zipfile.ZipFile(OUT / 'original-synthetic-observations.zip', 'x', compression=zipfile.ZIP_DEFLATED) as archive:
    for i in (1, 2):
        root = WORK / f'grok-subscription-bridge-integrated-r{i}'
        for case in sorted(root.iterdir()):
            if not case.is_dir() or case.is_symlink() or case.name.endswith('current'):
                continue
            for path in sorted(case.rglob('*')):
                if not path.is_file() or path.is_symlink():
                    continue
                if path.name not in names and not path.name.startswith('parent.jsonl.'):
                    continue
                name = f'r{i}/' + path.relative_to(root).as_posix()
                members[name] = sha(path)
                archive.write(path, name)
write(OUT / 'original-synthetic-observations-zip-members.json', members)
with zipfile.ZipFile(OUT / 'original-synthetic-observations.zip') as archive:
    assert {n: hashlib.sha256(archive.read(n)).hexdigest() for n in archive.namelist()} == members
write(OUT / 'FINAL-VERIFICATION.json', {
    'source_commit': head, 'production_bridge_commit': 'e6c8abd764ee85bb4eaaac555ef27b66b871c5b4',
    'source_archive_commit': 'bb046b7ea8c5bfd6f25484bf1c8f765eb5d6ff25',
    'original_closures': [{k: v for k, v in c.items() if k != 'source_after'} for c in closures],
    'latest_scope': '3 prior failures, normal and unknown worker integration,5 native faults,10 label checks',
    'production_changed_during_root_repair': False, 'test_only_changed_paths': changed,
    'root_coverage_across_r2_r3': 37, 'not_a_fresh_37_test_run_at_final_source': True,
    'source_archive_files': 28, 'source_archive_zip_payloads': 26,
    'r2_legacy_partial': {'closed_port_calls': 132, 'planned_port_calls': 144,
                          'closed_evaluator_opportunities': 60, 'planned_evaluator_opportunities': 72},
    'fixture_bounds_seconds': {'python_peer': 20, 'eight_session_parent': 240, 'legacy_144_port_parent': 360},
    'actual_native_bound_seconds': 60, 'original_observation_zip_members': len(members),
    'new_generation_calls': 0, 'actual_materials_prepared': 0,
    'validation_opened': False, 'calibration_established': False, 'scientific_effectiveness_proven': False,
    'limits': ['synthetic model and reference fixtures', 'adapted primary metrics',
               'native title and total settlement accounting remain distinct from known main usage'],
})
write(OUT / 'SHA256.json', {path.name: sha(path) for path in OUT.iterdir() if path.is_file()})
print(json.dumps({'files': len(list(OUT.iterdir())), 'original_observation_zip_members': len(members)}))
