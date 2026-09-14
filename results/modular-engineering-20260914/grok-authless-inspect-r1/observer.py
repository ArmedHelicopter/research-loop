"""Bounded authless CLI configuration inspection; never sends a prompt."""
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
from research_loop.modular.grok_acp_transport import ProcessTree, SAFE_CONFIG

ROOT = Path('E:/_ryanDev/AI/research-loop-modular/work/grok-authless-inspect-r1')
ROOT.mkdir(exist_ok=False)
PINS = (
    ('1.0.13', Path('C:/Users/Administrator/.grok/bin/grok.exe'),
     'bf43dc75f5478a106eab1e86d422c963e4dbe9666cf14dab363733d27bf1e672'),
    ('1.0.30', Path('E:/_ryanDev/AI/research-loop-modular/work/grok-cli-1.0.30/grok.exe'),
     'ca24ea63272ba7881261f4a52498d1f5bd884b01da25845990422a10dd315266'),
)
sha = lambda raw: hashlib.sha256(raw).hexdigest()
source = TREE / 'research_loop/modular/grok_acp_transport.py'
source_pin = sha(source.read_bytes())
receipts = []
for version, executable, expected in PINS:
    if sha(executable.read_bytes()) != expected:
        raise RuntimeError('executable pin mismatch')
    root = ROOT / version
    home, user, cwd = (root / name for name in ('home', 'profile', 'cwd'))
    for path in (home, user, cwd):
        path.mkdir(parents=True, exist_ok=False)
    config = home / 'config.toml'
    config.write_bytes(SAFE_CONFIG.encode())
    env = {k: v for k, v in os.environ.items() if k.upper() in {
        'SYSTEMROOT', 'WINDIR', 'SYSTEMDRIVE', 'COMSPEC', 'PATHEXT', 'PATH',
        'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'OS'}}
    env.update(GROK_HOME=str(home), USERPROFILE=str(user), HOME=str(user),
        HOMEDRIVE='E:', HOMEPATH=str(user)[2:],
        APPDATA=str(user / 'AppData/Roaming'), LOCALAPPDATA=str(user / 'AppData/Local'),
        TEMP=str(user / 'temp'), TMP=str(user / 'temp'),
        GROK_DISABLE_AUTOUPDATER='1', GROK_TITLE_REFRESH='false',
        GROK_TURN_SUMMARY='false', GROK_MEMORY='false',
        GROK_WORKFLOWS='false', GROK_SUBAGENTS='false')
    for key in ('APPDATA', 'LOCALAPPDATA', 'TEMP'):
        Path(env[key]).mkdir(parents=True, exist_ok=True)
    command = [str(executable), '--cwd', str(cwd), 'inspect', '--json']
    frozen = {'executable_sha256': expected, 'config_sha256': sha(config.read_bytes()),
        'observer_sha256': sha(Path(__file__).read_bytes()), 'process_tree_source_sha256': source_pin,
        'argv': command, 'environment_names': sorted(env), 'auth_file_supplied': False,
        'stdin_bytes': 0, 'deadline_seconds': 10}
    (root / 'launch.json').write_text(json.dumps(frozen, sort_keys=True), encoding='utf-8')
    started = time.monotonic()
    with (root / 'stderr.private.txt').open('xb') as err:
        tree = ProcessTree(command, cwd, env, err)
        timed_out = False
        try:
            stdout, _ = tree.process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            timed_out = True
            # Closing the held Windows Job kills only this owned process tree.
            kernel, handle = tree.job
            kernel.CloseHandle(handle)
            tree.job = None
            stdout, _ = tree.process.communicate(timeout=5)
        finally:
            if tree.job is not None:
                tree.close()
        code = tree.process.returncode
    (root / 'stdout.private.json').write_bytes(stdout)
    try:
        payload = json.loads(stdout)
        keys = sorted(payload) if type(payload) is dict else []
        parsed = type(payload) is dict
    except (ValueError, UnicodeError):
        parsed, keys = False, []
    receipt = {'schema': 'authless-native-config-inspection-v1', 'version_pin': version,
        'observed_at': datetime.now(timezone.utc).isoformat(),
        'elapsed_seconds': round(time.monotonic() - started, 3), 'exit_code': code,
        'timed_out': timed_out, 'stdout_bytes': len(stdout),
        'stderr_bytes': (root / 'stderr.private.txt').stat().st_size,
        'stdout_sha256': sha(stdout), 'stderr_sha256': sha((root / 'stderr.private.txt').read_bytes()),
        'json_object': parsed, 'top_level_keys': keys, 'process_exited': code is not None,
        'owned_job_closed': tree.job is None, 'prompt_arguments_supplied': False,
        'protocol_methods_written': [], 'auth_file_created': (home / 'auth.json').exists(),
        'config_unchanged': sha(config.read_bytes()) == frozen['config_sha256'],
        'source_unchanged': sha(source.read_bytes()) == source_pin,
        'generation_readiness_verified': False, 'scientific_effectiveness_proven': False,
        'usage_and_settlement': 'not_observed'}
    (root / 'receipt.json').write_text(json.dumps(receipt, sort_keys=True), encoding='utf-8')
    receipts.append(receipt)
    print(json.dumps(receipt), flush=True)
(ROOT / 'closure.json').write_text(json.dumps(receipts, sort_keys=True), encoding='utf-8')
