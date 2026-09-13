"""Freeze exact driver/fixture bytes for the four structural cases."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).parent
REPO = ROOT.parent.parent / 'grok-materials'
OUT = ROOT / 'frozen-check-r1'; OUT.mkdir(exist_ok=False)
def snapshot():
    paths = list(ROOT.glob('*.py')) + [REPO / 'research_loop/modular/grok_acp_transport.py',
        REPO / 'research_loop/modular/model_port.py', REPO / 'research_loop/modular/contracts.py',
        REPO / 'research_loop/ontology.py']
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
before = snapshot(); (OUT / 'before.json').write_text(json.dumps(before, indent=2))
env = dict(os.environ, PYTHONPATH=str(REPO), TEMP=str(OUT), TMP=str(OUT))
command = [sys.executable, '-m', 'pytest', str(ROOT / 'test_driver.py'), '-q', '--disable-warnings',
    '--basetemp', str(OUT / 'private-fixtures'), '--junitxml', str(OUT / 'pytest.xml')]
with (OUT / 'stdout.bin').open('xb') as stdout, (OUT / 'stderr.bin').open('xb') as stderr:
    run = subprocess.run(command, cwd=REPO, env=env, stdout=stdout, stderr=stderr)
after = snapshot(); (OUT / 'after.json').write_text(json.dumps(after, indent=2))
suites = ET.parse(OUT / 'pytest.xml').getroot().findall('testsuite')
receipt = {'schema': 'initialize-only-frozen-fixture-check-v1', 'exit_code': run.returncode,
    'sources_unchanged': before == after, 'source_count': len(before),
    **{k: sum(int(s.attrib[k]) for s in suites) for k in ('tests', 'failures', 'errors')},
    'preliminary_failures_preserved': 4,
    'preliminary_cause': 'fixture text-mode recording converted LF to CRLF; corrected to opaque byte capture',
    'native_launches': 0, 'model_prompts': 0}
(OUT / 'receipt.json').write_text(json.dumps(receipt, indent=2))
print(json.dumps(receipt))
raise SystemExit(run.returncode or int(before != after))
