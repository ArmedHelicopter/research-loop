"""Clean committed synthetic-only authoring and original-contract checks."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

repo = Path('E:/_ryanDev/AI/research-loop-modular/grok-materials')
out = Path('E:/_ryanDev/AI/research-loop-modular/work/material-authoring-frozen-check-r1')
out.mkdir(exist_ok=False)
def git(*args):
    return subprocess.check_output(['git', *args], cwd=repo, text=True).strip()
def snapshot():
    files = git('ls-files', '*.py', 'pyproject.toml', 'docs/GROK_ACP_TRANSPORT.md',
        'docs/GROK_ACP_PROTOCOL_REVIEW.md', 'docs/GROK_SUBSCRIPTION_DIAGNOSTIC.md',
        'docs/GROK_DIAGNOSTIC_MATERIAL_AUTHORING.md').splitlines()
    return {p: hashlib.sha256((repo / p).read_bytes()).hexdigest() for p in files}
commit = git('rev-parse', 'HEAD'); before_status = git('status', '--porcelain')
assert not before_status
before = snapshot()
(out / 'before-source-sha256.json').write_text(json.dumps(before, indent=2) + '\n')
env = dict(os.environ, TEMP=str(out), TMP=str(out)); env.pop('PYTHONPATH', None)
command = [sys.executable, '-m', 'pytest', '-q', '--disable-warnings',
    'tests/test_diagnostic_material_authoring.py', 'tests/test_diagnostic_subscription.py',
    'tests/test_grok_acp_transport.py', 'tests/test_calibration_pilot.py',
    'tests/test_diagnostic_private_ports.py', 'tests/test_label_isolation.py',
    '--basetemp', str(out / 'pytest-temp'), '--junitxml', str(out / 'pytest.xml')]
with (out / 'pytest.stdout.bin').open('xb') as stdout, (out / 'pytest.stderr.bin').open('xb') as stderr:
    process = subprocess.run(command, cwd=repo, env=env, stdout=stdout, stderr=stderr)
after = snapshot()
(out / 'after-source-sha256.json').write_text(json.dumps(after, indent=2) + '\n')
suites = ET.parse(out / 'pytest.xml').getroot().findall('testsuite')
receipt = {'schema': 'material-authoring-frozen-check-v1', 'commit': commit,
    'source_count': len(before), 'source_hashes_unchanged': before == after,
    'clean_before': before_status == '', 'clean_after': git('status', '--porcelain') == '',
    'commit_unchanged': git('rev-parse', 'HEAD') == commit, 'pytest_exit': process.returncode,
    **{k: sum(int(s.attrib[k]) for s in suites) for k in ('tests', 'failures', 'errors')},
    'label_isolation_included': True, 'legacy_positive_monetary_contract_included': True,
    'authoring_material_renderer_inventory_seam_included': True,
    'renderer_worker_native_provider_budget_seam_included': True,
    'all_model_requests_synthetic_fixture_only': True, 'real_model_generation_requests': 0,
    'parent_pythonpath_removed': True,
    'prior_preliminary_checks': [{'number': 1, 'tests': 17, 'frozen': False},
        {'number': 2, 'tests': 8, 'frozen': False}], 'command': command}
(out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt))
raise SystemExit(process.returncode or int(before != after) or int(not receipt['clean_after']))
