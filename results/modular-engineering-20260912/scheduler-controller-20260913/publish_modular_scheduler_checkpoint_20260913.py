"""Preserve source-qualified M8 reports and explicitly unfrozen reports."""
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
ROOT = BASE / 'integration'
ARCHIVE = ROOT / 'results/modular-engineering-20260912'
DEST = ARCHIVE / 'scheduler-controller-20260913'
assert not DEST.exists()
old = json.loads((ARCHIVE / 'SHA256.json').read_text(encoding='utf-8'))
assert len(old) == 865
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip().startswith('ce2e81b')
for name, expected in old.items():
    assert hashlib.sha256((ARCHIVE / name).read_bytes()).hexdigest() == expected, name
DEST.mkdir()
origins, reports = {}, {}
names = [
    ('integration/work/scheduler-controller-root-20260913-r1.xml', 'scheduler-controller-root-ce2e81b.xml', 'ce2e81b'),
    ('work/m8-causal-52985b3-focused-20260913.xml', 'm8-causal-52985b3-focused.xml', '52985b3'),
    ('work/m8-causal-final-frozen-20260913.xml', 'm8-causal-final-source-frozen.xml', 'source hash frozen before commit; overlaps focused checks'),
    ('work/m8-causal-verified-20260913-1138.xml', 'm8-intermediate-source-unfrozen-1138.xml', 'source_unfrozen; not final verification'),
    ('work/m8-causal-failure-final-20260913-1147.xml', 'm8-intermediate-source-unfrozen-1147.xml', 'source_unfrozen; not final verification'),
    ('work/m8-causal-source-unfrozen-notice-20260913.json', 'source-unfrozen-notice.json', 'exclusion record'),
    ('work/m8-causal-52985b3-verification.json', 'agent-verification.json', 'agent report; exact XML and source manifest retained'),
    ('work/m8-causal-final-frozen-source-20260913.json', 'agent-frozen-source.json', 'source byte hashes'),
    ('work/publish_modular_scheduler_checkpoint_20260913.py', 'publish_modular_scheduler_checkpoint_20260913.py', 'archive publisher'),
]
for relative, target, qualification in names:
    source = BASE / relative
    assert source.is_file() and not source.is_symlink()
    raw = source.read_bytes(); (DEST / target).write_bytes(raw)
    origins[target] = {'source': str(source), 'sha256': hashlib.sha256(raw).hexdigest(), 'qualification': qualification}
    if target.endswith('.xml'):
        suite = ET.fromstring(raw).find('testsuite')
        reports[target] = {key: suite.attrib[key] for key in ('tests', 'failures', 'errors', 'skipped', 'time')}
assert reports['scheduler-controller-root-ce2e81b.xml']['tests'] == '212'
assert reports['m8-causal-52985b3-focused.xml']['tests'] == '100'
assert reports['m8-causal-final-source-frozen.xml']['tests'] == '152'
for name in ('scheduler-controller-root-ce2e81b.xml', 'm8-causal-52985b3-focused.xml', 'm8-causal-final-source-frozen.xml'):
    assert all(reports[name][key] == '0' for key in ('failures', 'errors', 'skipped'))
def record(name, value):
    (DEST / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
record('origins.json', origins)
record('checkpoint.json', {'schema': 'scheduler-production-checkpoint-v1',
    'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
    'production_question_drivers': 23, 'reports': reports,
    'actual_production_cells': 36, 'worker_scope': 'bounded caller-owned public integers',
    'model_transport': 'actual CodexModelPort with mocked process transport',
    'remaining_measurements': ['benchmark scientific quality', 'Q3.3 throughput and fairness pressure',
        'Q3.4 unfinished scientific worker context contamination', 'OS process crash durability'],
    'new_paid_calls': 0, 'scientific_effectiveness_proven': False, 'validation_acceptance': 'not_measured',
    'overlapping_tests_must_not_be_summed_as_independent_evidence': True,
    'intermediate_source_unfrozen_reports_are_not_final_verification': True})
index = {p.relative_to(ARCHIVE).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
         for p in sorted(ARCHIVE.rglob('*')) if p.is_file() and p.name != 'SHA256.json'}
assert all(index[name] == expected for name, expected in old.items())
(ARCHIVE / 'SHA256.json').write_text(json.dumps(index, indent=2) + '\n', encoding='utf-8', newline='\n')
print(json.dumps({'old_files_preserved': len(old), 'new_files': len(index)-len(old), 'total': len(index), 'reports': reports}))
