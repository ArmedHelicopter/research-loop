"""Append closed source-qualified reports; never replace prior evidence."""
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
ROOT = BASE / 'integration'
ARCHIVE = ROOT / 'results/modular-engineering-20260912'
DEST = ARCHIVE / 'semantic-custody-controller-20260913'

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')

old = json.loads((ARCHIVE / 'SHA256.json').read_text(encoding='utf-8'))
assert len(old) == 876 and not DEST.exists()
for name, expected in old.items():
    assert sha((ARCHIVE / name).read_bytes()) == expected, name

entries = [
 ('integration/work/semantic-controller-root-20260913-r1.xml', 'semantic-root-collection-failure.xml', 'e50d0d1: nonexistent test filename; exit 1; zero tests is not pass'),
 ('integration/work/semantic-controller-root-20260913-r2.xml', 'semantic-root-e50d0d1-failure.xml', 'e50d0d1: 16 failures; wrong compiled field and stale fixture scope'),
 ('integration/work/semantic-controller-root-20260913-r3.xml', 'semantic-root-0b146a4.xml', '0b146a4: 109 passed after repair'),
 ('work/semantic-panel-regression-junit.xml', 'semantic-agent-8cb5eac.xml', 'agent original driver report; overlaps root coverage'),
 ('work/semantic-panel-review-final.xml', 'semantic-review-ce43cfc.xml', 'agent trusted P0 review report; overlaps root coverage'),
 ('work/modular-full-check-fd985fa-r1.xml', 'full-fd985fa-failure.xml', 'fd985fa: 989 tests, 7 failures; earlier source predates M8 and semantic drivers'),
 ('work/cc-root-a14f618-r1.xml', 'custody-controller-root-collection-failure.xml', 'a14f618: nonexistent test filename; exit 1; zero tests is not pass'),
 ('work/cc-root-a14f618-r2.xml', 'custody-controller-root-a14f618-failure.xml', 'a14f618: 70 tests, 11 AIRS failures from missing PyYAML; all 42 non-AIRS checks passed'),
 ('work/m4m5-train-5635e7d-20260913.xml', 'm4m5-agent-5635e7d.xml', '5635e7d frozen source; agent 47 checks overlap root coverage'),
 ('work/m4m5-train-5635e7d-verification.json', 'm4m5-agent-verification.json', 'agent source hashes, interpreter and report qualification'),
 ('work/fresh-airs-custodian-checks/final-hf-r2-junit.xml', 'airs-agent-20bdd2e.xml', '20bdd2e agent 28 checks used globally installed PyYAML; dependency omission retained'),
 ('work/regression-compat-tests-2.xml', 'compat-agent-main.xml', 'agent targeted tests before 6d5b80c; current root source tested separately'),
 ('work/regression-compat-related-1.xml', 'compat-agent-related.xml', 'agent related tests before 6d5b80c; current root source tested separately'),
 ('work/yaml-compat-root-286f5b1-r1.xml', 'custody-compat-root-global-pytest7.xml', '286f5b1; existing global pytest 7.2.2 below declared dev requirement; retained but not final declared-environment check'),
 ('work/yaml-compat-root-286f5b1-r2.xml', 'custody-compat-root-286f5b1.xml', '286f5b1; separate environment with pytest 8.4.2 and PyYAML 6.0.3 copied from installed distributions; not a fresh PyPI installation'),
 ('work/semantic-custody-environment-20260913.json', 'environment.json', 'measured runtime versions and explicit TLS installation failure'),
 ('work/custody-root-offline-dependency-copy.json', 'offline-dependency-copy.json', 'exact copied local installed distribution files and SHA256; original official wheel provenance unknown'),
 ('integration/docs/data-source-metadata/airsbench-controlled-acquisition-attempt.json', 'airs-github-acquisition-attempt.json', 'fixed-schema metadata only; failed archive and license acquisitions'),
 ('integration/docs/data-source-metadata/airsbench-hf-controlled-acquisition.json', 'airs-hf-acquisition.json', 'fixed-schema metadata only; controlled official HF acquisition'),
 ('integration/docs/data-source-metadata/airsbench-hf-controlled-receipt.json', 'airs-hf-receipt.json', '20 source records; no validation eligible records'),
 ('work/publish_semantic_custody_checkpoint_20260913.py', 'publish_semantic_custody_checkpoint_20260913.py', 'append-only publisher'),
]
payloads, origins, reports = {}, {}, {}
for relative, target, qualification in entries:
    source = BASE / relative
    assert source.is_file() and not source.is_symlink(), str(source)
    raw = source.read_bytes()
    payloads[target] = raw
    origins[target] = {'source': str(source), 'sha256': sha(raw), 'qualification': qualification}
    if target.endswith('.xml'):
        suite = ET.fromstring(raw).find('testsuite')
        reports[target] = {key: suite.attrib[key] for key in ('tests', 'failures', 'errors', 'skipped', 'time')}
for target in ('semantic-root-0b146a4.xml', 'custody-compat-root-286f5b1.xml'):
    assert int(reports[target]['tests']) > 0
    assert all(reports[target][key] == '0' for key in ('failures', 'errors', 'skipped'))
assert reports['full-fd985fa-failure.xml']['failures'] == '7'
assert reports['custody-controller-root-a14f618-failure.xml']['failures'] == '11'
DEST.mkdir()
for target, raw in payloads.items():
    (DEST / target).write_bytes(raw)
write(DEST / 'origins.json', origins)
write(DEST / 'checkpoint.json', {
 'schema': 'semantic-custody-combination-checkpoint-v1',
 'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
 'production_question_drivers': 25, 'semantic_production_cells': 16,
 'reports': reports, 'latest_full_suite': '989 tests with 7 failures on fd985fa; targeted repair only',
 'm4_m5_controller': 'actual custody and Docker; mocked solver process and synthetic independent rubric',
 'airs_tasks': 20, 'airs_validation_eligible': 0,
 'new_paid_calls': 0, 'scientific_effectiveness_proven': False,
 'validation_opened': False, 'pruned_combinations': [],
 'overlapping_checks_are_not_independent_replications': True,
 'fresh_environment_installation': 'not_verified_due_to_TLS_failure',
 'remaining_scope': 'all 48 Q obligations, all pair/triple/full/LOO studies, separate Q6.3 phase and validation acceptance',
})
index = {p.relative_to(ARCHIVE).as_posix(): sha(p.read_bytes())
         for p in sorted(ARCHIVE.rglob('*')) if p.is_file() and p.name != 'SHA256.json'}
assert all(index[name] == expected for name, expected in old.items())
write(ARCHIVE / 'SHA256.json', index)
print(json.dumps({'old_files_preserved': len(old), 'new_files': len(index) - len(old), 'total': len(index), 'reports': reports}))
