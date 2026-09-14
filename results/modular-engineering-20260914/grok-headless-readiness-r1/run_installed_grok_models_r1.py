"""One bounded official models command; existing native login may refresh."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone

TREE = Path('E:/_ryanDev/AI/research-loop-modular/artifact-evidence-provenance')
sys.path.insert(0, str(TREE))
from research_loop.modular.grok_acp_transport import ProcessTree

ROOT = Path('E:/_ryanDev/AI/research-loop-modular/work/grok-installed-models-r1')
ROOT.mkdir(exist_ok=False)
CWD = ROOT / 'empty-cwd'; CWD.mkdir()
TEMP = ROOT / 'temp'; TEMP.mkdir()
HOME = Path('C:/Users/Administrator/.grok')
EXE = HOME / 'bin/grok.exe'
PIN = 'bf43dc75f5478a106eab1e86d422c963e4dbe9666cf14dab363733d27bf1e672'
if hashlib.sha256(EXE.read_bytes()).hexdigest() != PIN:
    raise RuntimeError('executable pin mismatch')
def login_metadata():
    store = json.loads((HOME / 'auth.json').read_bytes())
    values = [v for v in store.values() if type(v) is dict and
              v.get('auth_mode') == 'oidc' and v.get('oidc_issuer') == 'https://auth.x.ai' and
              v.get('oidc_client_id') == 'b1a00492-073a-47ea-816f-4c329264a828']
    if len(values) != 1:
        return {'unique_first_party_oidc': False}
    value = values[0]
    expires = value.get('expires_at')
    return {'unique_first_party_oidc': True,
            'expiry_in_past': datetime.fromisoformat(expires.replace('Z', '+00:00')) <= datetime.now(timezone.utc)
                if type(expires) is str else None}
env = {k: v for k, v in os.environ.items() if k.upper() in {
    'SYSTEMROOT', 'WINDIR', 'SYSTEMDRIVE', 'COMSPEC', 'PATHEXT', 'PATH',
    'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'OS'}}
env.update(GROK_HOME=str(HOME), USERPROFILE='C:/Users/Administrator', HOME='C:/Users/Administrator',
    HOMEDRIVE='C:', HOMEPATH='/Users/Administrator',
    APPDATA='C:/Users/Administrator/AppData/Roaming', LOCALAPPDATA='C:/Users/Administrator/AppData/Local',
    TEMP=str(TEMP), TMP=str(TEMP), GROK_DISABLE_AUTOUPDATER='1', GROK_DISABLE_API_KEY_AUTH='1',
    GROK_TITLE_REFRESH='false', GROK_TURN_SUMMARY='false', GROK_MEMORY='false',
    GROK_WORKFLOWS='false', GROK_SUBAGENTS='false')
command = [str(EXE), '--no-auto-update', '--cwd', str(CWD), 'models']
record = {'schema': 'official-native-model-list-observation-v1',
    'observed_at': datetime.now(timezone.utc).isoformat(), 'command': command,
    'executable_sha256': PIN, 'observer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'deadline_seconds': 60, 'prompt_arguments_supplied': False, 'stdin_bytes': 0,
    'credential_copy_or_hash': False, 'existing_native_login_may_refresh': True,
    'login_before': login_metadata(), 'native_home': 'existing_user_native_home',
    'api_key_auth_disabled_requested': True, 'status': 'reserved'}
(ROOT / 'receipt.json').write_text(json.dumps(record, sort_keys=True), encoding='utf-8')
started = time.monotonic()
with (ROOT / 'stdout.private.txt').open('xb') as stdout, (ROOT / 'stderr.private.txt').open('xb') as stderr:
    tree = ProcessTree(command, CWD, env, stderr)
    try:
        raw, _ = tree.process.communicate(timeout=60)
        record['status'] = 'exited'
    except subprocess.TimeoutExpired:
        record['status'] = 'timeout'
        kernel, handle = tree.job
        kernel.CloseHandle(handle); tree.job = None
        raw, _ = tree.process.communicate(timeout=5)
    finally:
        if tree.job is not None:
            tree.close()
    stdout.write(raw)
record.update(elapsed_seconds=round(time.monotonic()-started, 3), exit_code=tree.process.returncode,
    stdout_bytes=len(raw), stderr_bytes=(ROOT/'stderr.private.txt').stat().st_size,
    stdout_sha256=hashlib.sha256(raw).hexdigest(),
    stderr_sha256=hashlib.sha256((ROOT/'stderr.private.txt').read_bytes()).hexdigest(),
    process_exited=tree.process.poll() is not None, owned_job_closed=tree.job is None,
    grok_46_listed=b'grok-4.6' in raw, login_after=login_metadata(),
    generation_readiness_verified=False, scientific_effectiveness_proven=False)
(ROOT / 'receipt.json').write_text(json.dumps(record, sort_keys=True), encoding='utf-8')
print(json.dumps(record), flush=True)
