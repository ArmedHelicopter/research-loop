"""Only the reviewed initialize-only native launch; no material loading."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

SOURCE = Path(__file__).parent
WORK = SOURCE.parent
REPO = WORK.parent / 'grok-materials'
sys.path.insert(0, str(REPO))
from research_loop.modular.grok_acp_transport import native_launch, diagnostic_config, EXECUTABLE_SHA256
from driver import run_once, WIRE

sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
check_path = SOURCE / 'frozen-check-r1/receipt.json'
check = json.loads(check_path.read_text())
assert check['exit_code'] == 0 and check['sources_unchanged'] and check['tests'] == 4
assert check['failures'] == check['errors'] == 0
pins = json.loads((SOURCE / 'frozen-check-r1/before.json').read_text())
assert all(sha(p) == value for p, value in pins.items())
assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=REPO, text=True).strip()
ROOT = WORK / 'init-only-r1'; ROOT.mkdir(exist_ok=False)
for name in ('home', 'profile', 'cwd'): (ROOT / name).mkdir()
auth_source = WORK / ('material-authoring-actual-preparation-r1/native-runtime/'
    'a58aad11cfbe02781e5c22dc44f8da919604522fa149619dab5712cbdb9c553c/private_home/auth.json')
auth_before = (auth_source.stat().st_size, auth_source.stat().st_mtime_ns)
shutil.copyfile(auth_source, ROOT / 'home/auth.json')
(ROOT / 'home/config.toml').write_text(diagnostic_config(8192), encoding='utf-8')
executable = Path('C:/Users/Administrator/.grok/bin/grok.exe')
assert sha(executable) == EXECUTABLE_SHA256
pins[str(executable)] = EXECUTABLE_SHA256
pins[str(ROOT / 'home/config.toml')] = sha(ROOT / 'home/config.toml')
pins[str(check_path)] = sha(check_path)
proposal = WORK / 'material-authoring-initialize-only-proposal-r1.md'
pins[str(proposal)] = sha(proposal)
envelope = {'schema': 'reviewed-initialize-only-native-envelope-v1',
    'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(),
    'frozen_files': pins, 'executable_sha256': EXECUTABLE_SHA256,
    'wire_sha256': hashlib.sha256(WIRE).hexdigest(), 'only_outbound_method': 'initialize',
    'launches_max': 1, 'timeout_seconds': 60, 'retry': False,
    'session_new_max': 0, 'authenticate_max': 0, 'account_rpc_max': 0, 'prompt_max': 0,
    'changed_conditions': ['fresh shorter paths', 'opaque copy of refreshed existing private login'],
    'private_material_inputs': False, 'auth_hashing_or_body_inspection': False}
envelope_path = ROOT / 'frozen-envelope.json'
with envelope_path.open('x', encoding='utf-8') as out:
    json.dump(envelope, out, indent=2); out.flush(); os.fsync(out.fileno())
pins[str(envelope_path)] = sha(envelope_path)
command, env = native_launch(executable=executable, cwd=ROOT / 'cwd', private_home=ROOT / 'home',
    private_profile=ROOT / 'profile', frozen_files=pins, expected_config=diagnostic_config(8192))
result = run_once(command, cwd=ROOT / 'cwd', env=env, directory=ROOT / 'private-receipt',
    frozen_files=pins, timeout=60)
assert (auth_source.stat().st_size, auth_source.stat().st_mtime_ns) == auth_before
result['source_login_copy_stat_unchanged'] = True
result['changed_conditions'] = envelope['changed_conditions']
result['frozen_envelope_sha256'] = sha(envelope_path)
result['source_commit'] = envelope['source_commit']
result['original_authoring_envelope_reused'] = False
(ROOT / 'public-result.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result))
