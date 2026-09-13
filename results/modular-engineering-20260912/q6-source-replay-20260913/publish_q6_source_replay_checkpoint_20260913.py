"""Append immutable engineering evidence; do not touch source or private payload."""
import hashlib
import json
from pathlib import Path
import shutil
import stat
import subprocess
import zipfile
import xml.etree.ElementTree as ET

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
ROOT = BASE / 'integration'
WORK = BASE / 'work'
ARCHIVE = ROOT / 'results/modular-engineering-20260912'
DEST = ARCHIVE / 'q6-source-replay-20260913'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read(path):
    return json.loads(path.read_bytes())

def write(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')

assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip() == '39cfac6e3702879b139af58c7d4f02b1acb00ad5'
assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip()
old = read(ARCHIVE / 'SHA256.json')
assert len(old) == 1396
assert all(sha(ARCHIVE / rel) == value for rel, value in old.items())
DEST.mkdir()
origins = {}

def add(path, relative, expected=None):
    value = sha(path)
    if expected is not None:
        assert value == expected, str(path)
    target = DEST / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    assert not target.exists()
    shutil.copyfile(path, target)
    assert sha(target) == value
    origins[relative] = {'source': str(path), 'sha256': value}

for manifest_name in ('q6-c60-verification.json', 'ff-verification.json'):
    manifest = read(WORK / manifest_name)
    add(WORK / manifest_name, manifest_name)
    reports = manifest['reports']
    reports = list(reports.values()) if isinstance(reports, dict) else reports
    for row in reports:
        path = Path(row['path'])
        add(path, 'reports/' + path.name, row['sha256'])

for name in ('q6-root-integrated-r1.xml', 'integration-q8-source-failure-r1.xml',
             'reverify_m4m5_closed_20260913_r2.py', 'm4m5-closed-reverification-20260913-r2.json'):
    add(WORK / name, name)

qual = read(ROOT / 'docs/source-process-qualification-verification.json')
add(ROOT / 'docs/source-process-qualification-verification.json', 'source-qualification/verification.json')
for key in ('public_seal_receipt', 'scope_review', 'seal_failure_r1', 'seal_failure_r2',
            'supplement_r1', 'supplement_reclassification'):
    row = qual['artifacts'][key]
    add(Path(row['path']), 'source-qualification/' + key + '.json', row['sha256'])
add(Path(qual['verification']['junit_path']), 'source-qualification/frozen-r1.xml', qual['verification']['junit_sha256'])

for path in sorted((ROOT / 'results/modular-engineering-20260913/q82-q83-production').iterdir()):
    if path.is_file():
        add(path, 'q82-q83-production/' + path.name)

source_paths = set(read(WORK / 'q6-c60-verification.json')['source_sha256'])
source_paths.update(read(WORK / 'ff-verification.json')['source_sha256'])
source_paths.update(('evaluation/modular/process_source_qualification.py',
                     'evaluation/modular/source_repository_supplement.py',
                     'research_loop/modular/retrieval_panel_drivers.py',
                     'research_loop/modular/recorded_retrieval.py',
                     'research_loop/modular/train_controller.py',
                     'research_loop/modular/panel_runner.py'))
for relative in sorted(source_paths):
    add(ROOT / relative, 'source/' + relative)

# Only the closed synthetic Q6 regression directory; no actual source snapshots.
fixture = WORK / 'q6-root-integrated-r1'
files = []
def walk(path):
    for item in sorted(path.iterdir()):
        info = item.stat(follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            continue
        if item.is_dir():
            walk(item)
        elif item.is_file():
            files.append(item)
walk(fixture)
pins = {p.relative_to(fixture).as_posix(): sha(p) for p in files}
with zipfile.ZipFile(DEST / 'q6-root-synthetic-runtime.zip', 'x', compression=zipfile.ZIP_DEFLATED) as archive:
    for path in files:
        archive.write(path, path.relative_to(fixture).as_posix())
assert all(sha(fixture / relative) == value for relative, value in pins.items())
write(DEST / 'q6-root-synthetic-runtime-hashes.json', pins)
reports = {}
for name, commit in (('q6-root-integrated-r1', '9ca3214b4b624f2084bbfeb35dacbcba7d813629'),
                     ('integration-q8-source-failure-r1', '39cfac6e3702879b139af58c7d4f02b1acb00ad5')):
    suite = ET.parse(WORK / (name + '.xml')).getroot().find('testsuite')
    reports[name] = {'source_commit': commit, **{key: suite.attrib[key] for key in ('tests','failures','errors','skipped','time')}}
write(DEST / 'checkpoint.json', {
    'schema': 'q6-source-replay-checkpoint-v1', 'source_commit': '39cfac6e3702879b139af58c7d4f02b1acb00ad5',
    'registered_question_drivers': 38, 'separate_train_phases': ['Q6.1','Q6.2','Q6.3','Q6.5','Q6.6'],
    'remaining_question_driver_ids': ['Q8.1','Q8.4','Q8.5','Q8.6','Q8.7'],
    'new_live_validation_payload_reads': 0, 'new_paid_model_calls': 0, 'root_reports': reports,
    'q6_synthetic_runtime_files': len(pins), 'original_paid_trial_files_unchanged': 302,
    'm4m5_readonly_replay_verified': 8, 'm4m5_original_scores': 5, 'm4m5_original_failures': 3,
    'm4m5_conclusion': 'inconclusive', 'pruned_combinations': [],
    'prospective_extended_partition': {'train':164,'sealed_validation':18,'legacy_custody_mutated':False},
    'actual_train_exporter': 'separate_worktree_first_actual_export_failed_under_repair',
    'primary_validation': 'process_and_lineage_audit_required', 'scientific_effectiveness': 'not_established',
    'old_q82_git_eol_mismatch_files': 6, 'q82_original_worktree_bytes_copied_in_this_archive': True})
add(Path(__file__), Path(__file__).name)
write(DEST / 'ORIGINS.json', origins)
new = dict(old)
for path in DEST.rglob('*'):
    if path.is_file():
        relative = path.relative_to(ARCHIVE).as_posix()
        assert relative not in new
        new[relative] = sha(path)
assert all(sha(ARCHIVE / rel) == value for rel, value in old.items())
(ARCHIVE / 'SHA256.json').write_text(json.dumps(dict(sorted(new.items())), indent=2) + '\n', encoding='utf-8', newline='\n')
print(json.dumps({'old_files_unchanged':len(old),'new_files':len(new)-len(old),'indexed_files':len(new),
                  'q6_synthetic_runtime_files':len(pins),'reports':reports}))
