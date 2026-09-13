import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = Path('E:/_ryanDev/AI/research-loop-modular')

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def verify(tree, stem, manifest_name, report_name):
    root = BASE / tree
    before_path = BASE / 'work' / manifest_name
    before = json.loads(before_path.read_text(encoding='utf-8-sig'))
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    assert head == before['source_commit'], (tree, head)
    status = subprocess.check_output(['git', 'status', '--porcelain'], cwd=root, text=True)
    assert not status.strip(), (tree, status)
    after = {name: sha(root / name) for name in before['files']}
    assert after == before['files'], tree
    junit = BASE / 'work' / report_name
    suites = ET.parse(junit).getroot()
    if suites.tag == 'testsuite':
        suites = [suites]
    totals = {key: sum(int(s.get(key, 0)) for s in suites) for key in ['tests', 'failures', 'errors', 'skipped']}
    totals['seconds'] = sum(float(s.get('time', 0)) for s in suites)
    assert totals['tests'] > 0 and not any(totals[k] for k in ['failures', 'errors', 'skipped']), totals
    output = BASE / 'work' / (stem + '-closed-freeze-verification-r1.json')
    assert not output.exists(), output
    record = {'schema': 'closed-root-pytest-source-verification-v1', 'source_commit': head,
        'checkout': str(root), 'source_manifest_before': str(before_path),
        'source_manifest_before_sha256': sha(before_path), 'source_file_count': len(after),
        'source_files_after': after, 'source_unchanged': True, 'checkout_clean': True,
        'junit': str(junit), 'junit_sha256': sha(junit), 'totals': totals,
        'scientific_validity': 'not_measured', 'live_paid_calls': 0}
    output.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    return {'path': str(output), 'sha256': sha(output), 'source_file_count': len(after), 'totals': totals}

if __name__ == '__main__':
    print(json.dumps([
        verify('integration', 'reference-lineage-root', 'reference-lineage-root-source-before-r1.json', 'reference-lineage-root-r1.xml'),
        verify('pred-link', 'pred-linked-root', 'pred-linked-source-before-r1.json', 'pred-linked-frozen-r1.xml')
    ], indent=2))
