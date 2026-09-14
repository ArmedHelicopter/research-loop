"""One reviewed authless initialize-only diagnostic; no credential accessor."""
import ctypes
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
INTEGRATION = ROOT.parent.parent / 'integration'
EXE = ROOT.parent / 'grok-cli-1.0.30/grok.exe'
EXE_PIN = 'ca24ea63272ba7881261f4a52498d1f5bd884b01da25845990422a10dd315266'
ENGINE_PIN = '48fe670938e8d523d6e9cf6cb7da6f78f883655b9e47f1a79e60029dea36928c'
ORIGINAL_ENGINE_PIN = '2396bfa21457ae89a3a7bf631ab3ea74faf207e15d3587701743f33e7bcb8db3'
WIRE_PIN = '4ff2a6301d0f60b08451d890fb2bff5ee7067be81658cd46845e64bc1edac4dd'
sys.path.insert(0, str(INTEGRATION))
from research_loop.modular.grok_acp_transport import ProcessTree
from research_loop.modular.grok_skill_isolation import isolated_config, context_record, observe_context
from research_loop.ontology import ContractError


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())


def creation_time(process):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetProcessTimes.argtypes = [ctypes.c_void_p] * 5
    kernel.GetProcessTimes.restype = ctypes.c_int
    values = [ctypes.c_ulonglong() for _ in range(4)]
    if not kernel.GetProcessTimes(int(process._handle), *[ctypes.byref(v) for v in values]):
        raise OSError('owned_handle_creation_query_failed')
    return values[0].value


class OwnedTree(ProcessTree):
    instances = []

    def __init__(self, command, cwd, env, stderr):
        super().__init__(command, cwd, env, stderr)
        self.closed = False
        self.record = {'pid': self.process.pid, 'argv': list(command),
            'job_owned': self.job is not None, 'creation_filetime': None,
            'creation_matches_at_close': False, 'closed': False}
        self.instances.append(self)
        try:
            self.record['creation_filetime'] = creation_time(self.process)
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.closed:
            return
        try:
            expected = self.record['creation_filetime']
            actual = creation_time(self.process)
            self.record['creation_matches_at_close'] = expected is not None and actual == expected
        finally:
            # Existing Job/held process handle; no PID-based rediscovery or delayed kill.
            super().close()
            self.process._handle.Close()
            self.closed = True
            self.record.update(closed=True, held_handle_closed=True, exit_code=self.process.returncode)


def env_for(home, profile):
    keep = {'SYSTEMROOT', 'WINDIR', 'SYSTEMDRIVE', 'COMSPEC', 'PATHEXT', 'PATH',
        'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'OS'}
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}
    env.update(GROK_HOME=str(home), USERPROFILE=str(profile), HOME=str(profile),
        HOMEDRIVE=profile.drive, HOMEPATH=str(profile)[len(profile.drive):],
        APPDATA=str(profile / 'AppData/Roaming'), LOCALAPPDATA=str(profile / 'AppData/Local'),
        TEMP=str(profile / 'temp'), TMP=str(profile / 'temp'), GROK_DISABLE_AUTOUPDATER='1',
        GROK_TITLE_REFRESH='false', GROK_TURN_SUMMARY='false', GROK_MEMORY='false',
        GROK_WORKFLOWS='false', GROK_SUBAGENTS='false')
    for key in ('APPDATA', 'LOCALAPPDATA', 'TEMP'):
        Path(env[key]).mkdir(parents=True, exist_ok=True)
    return env


def engine():
    path = ROOT / 'init_engine.py'
    if sha(path) != ENGINE_PIN:
        raise ValueError('engine_pin_mismatch')
    spec = importlib.util.spec_from_file_location('frozen_authless_engine', path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    if len(mod.WIRE) != 261 or hashlib.sha256(mod.WIRE).hexdigest() != WIRE_PIN:
        raise ValueError('wire_mismatch')
    mod.ProcessTree = OwnedTree
    return mod


def source_pins():
    paths = {ROOT / 'driver.py', ROOT / 'init_engine.py', ROOT / 'peer.py'}
    for name, module in tuple(sys.modules.items()):
        filename = getattr(module, '__file__', None)
        if name.startswith('research_loop') and filename:
            path = Path(filename).resolve()
            if not path.is_relative_to(INTEGRATION):
                raise ValueError('source_outside_frozen_checkout')
            paths.add(path)
    return {str(path): sha(path) for path in sorted(paths)}


def self_test():
    target = ROOT / 'synthetic'; target.mkdir(exist_ok=False)
    native = engine(); pins = source_pins(); cases = []
    for name, mode, timeout in (('delay-short', 'delay', 0.25), ('delay-long', 'delay', 0.5),
                                ('response-and-notification', 'notification', 2), ('new-auth-path', 'auth-path', 2)):
        base = target / name; base.mkdir()
        home, profile, cwd = (base / n for n in ('home', 'profile', 'cwd'))
        for p in (home, profile, cwd): p.mkdir()
        result = native.run_once([sys.executable, '-B', str(ROOT / 'peer.py'), mode],
            cwd=cwd, env=env_for(home, profile), directory=base / 'private',
            frozen_files=pins, timeout=timeout, close_stdin=False, forbidden_paths=(home/'auth.json',))
        owner = OwnedTree.instances[-1].record
        expected = ['timeout'] if mode == 'delay' else ['unexpected_auth_path' if mode == 'auth-path' else 'unexpected_notification']
        assert set(result['faults']) == set(expected), result['faults']
        assert result['initialize_writes_completed'] == 1
        assert result['process_tree_closed'] and owner['closed'] and owner['creation_matches_at_close'] and owner['held_handle_closed']
        assert result['outbound_method_counts'] == {'initialize': 1, 'session/new': 0,
            'authenticate': 0, '_x.ai/billing': 0, '_x.ai/auto-topup-rule': 0, 'session/prompt': 0}
        assert not result['accepted_initialize']
        assert (result['response'] is not None) == (mode == 'notification')
        assert result['elapsed_seconds'] < timeout + 7
        cases.append({'name': name, 'passed': True, 'faults': result['faults'],
            'response_received': result['response'] is not None, 'strict_acceptance': False,
            'elapsed_seconds': result['elapsed_seconds'], 'owner': owner})
    write_json(ROOT / 'synthetic-checks.json', {'schema': 'authless-initialize-helper-checks-v1',
        'source_pins': pins, 'native_launches': 0, 'cases': cases, 'passed': True})
    print(json.dumps({'status': 'synthetic_checks_passed', 'cases': len(cases), 'native_launches': 0}))


def native_run():
    if (ROOT / 'native-reservation.json').exists():
        raise ValueError('native_reservation_already_spent')
    checks = json.loads((ROOT / 'synthetic-checks.json').read_text(encoding='utf-8'))
    native = engine(); pins = source_pins()
    if checks.get('passed') is not True or checks.get('source_pins') != pins:
        raise ValueError('checks_or_source_pins_differ')
    if sha(EXE) != EXE_PIN:
        raise ValueError('executable_pin_mismatch')
    home, profile, cwd = (ROOT / name for name in ('home', 'profile', 'cwd'))
    for path in (home, profile, cwd): path.mkdir(exist_ok=False)
    config = home / 'config.toml'
    config.write_text(isolated_config(cwd, home, profile), encoding='utf-8')
    context = context_record(cwd, home, profile)
    observe_context(context)
    env = env_for(home, profile)
    if set(p.name for p in home.iterdir()) != {'config.toml'}:
        raise ValueError('home_not_authless')
    pins.update({str(EXE): EXE_PIN, str(config): sha(config),
        str(ROOT / 'synthetic-checks.json'): sha(ROOT / 'synthetic-checks.json')})
    command = [str(EXE), '--cwd', str(cwd), 'agent', 'stdio']
    envelope = {'schema': 'authless-initialize-envelope-v1', 'frozen_files': pins,
        'argv': command, 'wire_sha256': WIRE_PIN, 'wire_bytes': 261,
        'native_launches_max': 1, 'timeout_seconds': 60, 'retry_count': 0,
        'home_initial_entries': ['config.toml'], 'auth_read_copy_hash': False,
        'original_engine_sha256': ORIGINAL_ENGINE_PIN,
        'engine_change': 'metadata-only credential-path guard; same request and response parser',
        'initialize_writes_max': 1, 'session_prompt_authenticate_billing_writes_max': 0,
        'source_binary_equivalence': False, 'synthetic_checks_sha256': sha(ROOT / 'synthetic-checks.json')}
    write_json(ROOT / 'envelope.json', envelope)
    write_json(ROOT / 'native-reservation.json', {'schema': 'authless-initialize-reservation-v1',
        'envelope_sha256': sha(ROOT / 'envelope.json'), 'reserved_at': datetime.now(timezone.utc).isoformat(),
        'native_launches_max': 1, 'retry_allowed': False})
    result = native.run_once(command, cwd=cwd, env=env, directory=ROOT / 'private',
        frozen_files=pins, timeout=60, close_stdin=False,
        forbidden_paths=(home/'auth.json', profile/'.grok/auth.json'))
    auth_appeared = os.path.lexists(home / 'auth.json')
    context_valid = True
    try:
        observe_context(context)
    except ContractError:
        context_valid = False
    owner = OwnedTree.instances[-1].record if OwnedTree.instances else None
    fields = ('faults', 'initialize_writes_completed', 'outbound_method_counts', 'response',
        'stdout_bytes', 'stderr_bytes', 'stdout_frames_parsed', 'elapsed_seconds',
        'process_tree_closed', 'native_exit_code_after_shutdown')
    safe = {k: result[k] for k in fields}
    safe.update(schema='authless-initialize-closure-v1', native_launches=len(OwnedTree.instances),
        response_received=result['response'] is not None, strict_acceptance=result['accepted_initialize'],
        owner=owner, post_context_valid=context_valid, auth_path_appeared=auth_appeared,
        auth_read_copy_hash=False, model_calls_dispatched=0, retry_count=0,
        known_model_usage=None, settled_additional_charge_usd=None, settlement_status='unknown',
        envelope_sha256=sha(ROOT / 'envelope.json'), validation_eligible=False)
    if auth_appeared or not context_valid or not owner or not owner.get('creation_matches_at_close'):
        safe['strict_acceptance'] = False
        safe['context_or_ownership_fault'] = True
    write_json(ROOT / 'closure.json', safe)
    print(json.dumps({'status': 'native_closed', 'response_received': safe['response_received'],
        'strict_acceptance': safe['strict_acceptance'], 'faults': safe['faults'],
        'closure_sha256': sha(ROOT / 'closure.json')}))


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in ('self-test', 'run-once'):
        raise SystemExit('usage: driver.py self-test | run-once')
    self_test() if sys.argv[1] == 'self-test' else native_run()
