"""Append only closed engineering evidence and immutable live-attempt controls."""
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
ROOT = BASE/'integration'
ARCHIVE = ROOT/'results/modular-engineering-20260912'
DEST = ARCHIVE/'protocol-exploration-20260913'

def sha(raw): return hashlib.sha256(raw).hexdigest()
def write(path, data):
    with path.open('x', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2)+'\n')

old = json.loads((ARCHIVE/'SHA256.json').read_text(encoding='utf-8'))
assert len(old) == 924 and not DEST.exists()
for name, expected in old.items(): assert sha((ARCHIVE/name).read_bytes()) == expected
payloads, origins, reports = {}, {}, {}
def add(source, target, qualification, expected=None):
    source = Path(source)
    assert source.is_file() and not source.is_symlink()
    raw = source.read_bytes()
    if expected is not None: assert sha(raw) == expected, target
    assert target not in payloads
    payloads[target] = raw
    origins[target] = {'source':str(source), 'sha256':sha(raw), 'qualification':qualification}
    if target.endswith('.xml'):
        s = ET.fromstring(raw).find('testsuite')
        reports[target] = {k:s.attrib[k] for k in ('tests','failures','errors','skipped','time')}

q27 = json.loads((BASE/'work/q27-controller-d21fa3a-verification.json').read_text())
add(BASE/'work/q27-controller-d21fa3a-verification.json', 'q27-agent-verification.json',
    'Frozen source and retained failures; final repair changes only old fixture classification')
for name, row in q27['reports'].items():
    add(BASE/'work'/name, name, 'Agent Q27 source-qualified development and final reports; overlaps root checks', row['sha256'])
for name, note in (
    ('q27-root-a8449fa-r1.xml', 'Root a8449fa: 149 pass, one stale generic fixture failure; label isolation passed'),
    ('q27-root-fixture-r2.xml', 'Root 744387a: 55 pass; only generic fixture classification repaired'),
    ('q27-repair-70b061b-20260913.xml', 'Standalone source-qualified Q27 repair: 80 pass'),
    ('q27-repair-70b061b-verification.json', 'Standalone repair source bindings'),
    ('exploration-root-seam-r1.xml', 'Root d4d393d: 91 pass, including actual custody/export/controller 52-cell seam')):
    add(BASE/'work'/name, name, note)
exploration = json.loads((ROOT/'docs/exploration_panel_verification.json').read_text())
add(ROOT/'docs/exploration_panel_verification.json', 'exploration-agent-verification.json',
    'Frozen b55c170, 52 synthetic public cells, actual Docker and fixture audit; not benchmark scientific effect')
for row in exploration['junit_reports']:
    add(row['path'], 'exploration-'+Path(row['path']).name,
        'Source-qualified exploration revision; overlapping checks are not independent replications', row['sha256'])
trace_root = BASE/'work/exploration-production-checks/review-final/test_full_52_cell_real_docker_0/runs'
for row in exploration['main_grid_traces']:
    i = row['cell_index']
    add(trace_root/str(i)/'trace.jsonl', f'exploration-traces/{i:02d}.jsonl',
        'Closed b55c170 public synthetic trace; exact bytes from the retained final grid', row['trace_sha256'])
trial = BASE/'work/linked-train-scored-20260913-02'
pre = json.loads((trial/'controls/preflight.json').read_text())
add(trial/'controls/preflight.json', 'train-repeat-preflight.json', 'Immutable controls only; live run remains separate')
add(trial/'controls/worker-probe.json', 'train-repeat-worker-probe.json', 'Worker startup with zero evaluator calls; no runtime outcome')
add(BASE/'t2-check/work/linked_train_scored_20260913_r2.py', 'train-repeat-runner.py',
    'Frozen a8449fa runner; new 02 paths retain old attempt and old training references', pre['runner_sha256'])
add(Path(__file__), Path(__file__).name, 'Append-only publisher')
assert reports['exploration-root-seam-r1.xml']['tests'] == '91'
assert reports['exploration-root-seam-r1.xml']['failures'] == '0'
assert reports['q27-root-fixture-r2.xml']['tests'] == '55'
DEST.mkdir()
for name, raw in payloads.items():
    target = DEST/name
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as f: f.write(raw)
write(DEST/'origins.json', origins)
write(DEST/'checkpoint.json', {
    'schema':'protocol-exploration-engineering-checkpoint-v1',
    'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
    'production_question_drivers':30, 'reports':reports,
    'q27_full_custody_cells':8, 'exploration_full_custody_cells':52,
    'exploration_agent_traces':52, 'scientific_effectiveness_proven':False,
    'current_head_full_suite_pass':False, 'validation_opened':False, 'validation_eligible_records':0,
    'pruned_combinations':[], 'deployment_performed':False,
    'ongoing_training_attempt':'linked-train-scored-20260913-02',
    'ongoing_training_source':pre['source_commit'], 'ongoing_training_terminal_result':'not_in_this_checkpoint',
    'all_48_scientific_obligations_and_all_required_combinations_remain_open':True,
})
index = {p.relative_to(ARCHIVE).as_posix():sha(p.read_bytes())
         for p in sorted(ARCHIVE.rglob('*')) if p.is_file() and p.name != 'SHA256.json'}
assert all(index[name] == expected for name,expected in old.items())
(ARCHIVE/'SHA256.json').write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps({'old_files_preserved':len(old),'new_files':len(index)-len(old),'total':len(index),'reports':reports}))
