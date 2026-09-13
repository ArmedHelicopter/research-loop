"""Focused frozen repair closure; original full R1 remains unchanged."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

repo = Path('E:/_ryanDev/AI/research-loop-modular/grok-materials')
previous = repo.parent / 'work/material-authoring-frozen-check-r1'
prior = json.loads((previous / 'receipt.json').read_text())
assert prior['source_hashes_unchanged'] and prior['tests'] == 142
out = repo.parent / 'work/material-authoring-frozen-check-r2'; out.mkdir(exist_ok=False)
def git(*args):
    return subprocess.check_output(['git', *args], cwd=repo, text=True).strip()
def snapshot():
    files = git('ls-files', '*.py', 'pyproject.toml', 'docs/GROK_ACP_TRANSPORT.md',
        'docs/GROK_ACP_PROTOCOL_REVIEW.md', 'docs/GROK_SUBSCRIPTION_DIAGNOSTIC.md',
        'docs/GROK_DIAGNOSTIC_MATERIAL_AUTHORING.md').splitlines()
    return {p: hashlib.sha256((repo / p).read_bytes()).hexdigest() for p in files}
failed = [t.attrib['classname'].replace('.', '/') + '.py::' + t.attrib['name']
    for t in ET.parse(previous / 'pytest.xml').getroot().iter('testcase')
    if t.find('failure') is not None or t.find('error') is not None]
assert len(failed) == prior['failures'] + prior['errors']
commit = git('rev-parse', 'HEAD'); assert not git('status', '--porcelain')
before = snapshot()
(out / 'before-source-sha256.json').write_text(json.dumps(before, indent=2) + '\n')
env = dict(os.environ, TEMP=str(out), TMP=str(out)); env.pop('PYTHONPATH', None)
command = [sys.executable, '-m', 'pytest', '-q', '--disable-warnings',
    'tests/test_diagnostic_material_authoring.py', *failed,
    'tests/test_grok_acp_transport.py::test_timeout_kills_subprocess_tree_without_retry',
    'tests/test_label_isolation.py', '--basetemp', str(out / 'pytest-temp'),
    '--junitxml', str(out / 'pytest.xml')]
with (out / 'pytest.stdout.bin').open('xb') as stdout, (out / 'pytest.stderr.bin').open('xb') as stderr:
    process = subprocess.run(command, cwd=repo, env=env, stdout=stdout, stderr=stderr)
after = snapshot()
(out / 'after-source-sha256.json').write_text(json.dumps(after, indent=2) + '\n')
suites = ET.parse(out / 'pytest.xml').getroot().findall('testsuite')
receipt = {'schema': 'material-authoring-frozen-repair-check-v1', 'commit': commit,
    'source_count': len(before), 'source_hashes_unchanged': before == after,
    'clean_before': True, 'clean_after': git('status', '--porcelain') == '',
    'commit_unchanged': git('rev-parse', 'HEAD') == commit, 'pytest_exit': process.returncode,
    **{k: sum(int(s.attrib[k]) for s in suites) for k in ('tests', 'failures', 'errors')},
    'all_original_failures_included': failed, 'all_new_authoring_tests_included': True,
    'native_timeout_tree_and_label_isolation_included': True,
    'prior_full_check': {'path': str(previous / 'receipt.json'),
        'sha256': hashlib.sha256((previous / 'receipt.json').read_bytes()).hexdigest()},
    'repair_scope': 'test fixtures only: Python peer20s, parent240s, legacy caller360s; production native60s unchanged',
    'parent_pythonpath_removed': True, 'real_model_generation_requests': 0, 'command': command}
(out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt))
raise SystemExit(process.returncode or int(before != after) or int(not receipt['clean_after']))
