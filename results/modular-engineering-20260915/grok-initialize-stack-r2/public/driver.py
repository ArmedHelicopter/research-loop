"""One frozen ACP initialize, with native documented debug-file instrumentation."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from stack_capture import CDB, capture

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent
INTEGRATION = WORK.parent / 'integration'
EXE = WORK / 'grok-cli-1.0.30/grok.exe'
PIN = 'ca24ea63272ba7881261f4a52498d1f5bd884b01da25845990422a10dd315266'
AUTH = Path('C:/Users/Administrator/.grok/auth.json')
sys.path.insert(0, str(INTEGRATION))

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def metadata(path):
    s = Path(path).stat()
    return {'bytes': s.st_size, 'mtime_ns': s.st_mtime_ns}
def write(path, body):
    with path.open('x', encoding='utf-8') as out:
        json.dump(body, out, indent=2, sort_keys=True); out.write('\n')
def private_env(home, profile):
    keep = {'SYSTEMROOT','WINDIR','SYSTEMDRIVE','COMSPEC','PATHEXT','PATH',
            'NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE','OS'}
    result = {k:v for k,v in os.environ.items() if k.upper() in keep}
    result.update({'GROK_HOME':str(home), 'USERPROFILE':str(profile), 'HOME':str(profile),
        'HOMEDRIVE':profile.drive, 'HOMEPATH':str(profile)[len(profile.drive):],
        'APPDATA':str(profile/'AppData/Roaming'), 'LOCALAPPDATA':str(profile/'AppData/Local'),
        'TEMP':str(profile/'temp'), 'TMP':str(profile/'temp'), 'GROK_DISABLE_AUTOUPDATER':'1',
        'GROK_TITLE_REFRESH':'false', 'GROK_TURN_SUMMARY':'false', 'GROK_MEMORY':'false',
        'GROK_WORKFLOWS':'false', 'GROK_SUBAGENTS':'false'})
    for key in ('APPDATA','LOCALAPPDATA','TEMP'): Path(result[key]).mkdir(parents=True)
    return result

def main():
    if sha(EXE) != PIN: raise RuntimeError('executable pin differs')
    expected = {'driver.py','init_engine.py','stack_capture.py','parser_smoke.py','cdb-help.txt','cdb-help.stderr.txt','cdb-help-result.json','preparation-manifest.json','README.md','fixture-diagnosis-r2.md','cdb-argument-diagnosis-r1.md'}
    if {p.name for p in ROOT.iterdir()} != expected:
        raise RuntimeError('diagnostic root not fresh; never retry this directory')
    prepared = json.loads((ROOT/'preparation-manifest.json').read_text(encoding='utf-8'))
    if (prepared.get('schema') != 'grok130-initialize-stack-preparation-v3'
            or prepared.get('execution_performed') is not False):
        raise RuntimeError('prepared manifest version or execution guard differs')
    cdb_help = (ROOT/'cdb-help.txt').read_text(encoding='utf-8')
    required_cdb_help = ('-p <pid>', '-pvr specifies that any attach should be noninvasive and nonsuspending',
                         '-pd specifies that the debugger should automatically detach',
                         '-netsym:yes|no', '-sins ignores the symbol path environment variables',
                         '-noshell disables the .shell (!!) command', '-c "<command>"')
    if not all(item in cdb_help for item in required_cdb_help):
        raise RuntimeError('prepared CDB help does not establish required no-prompt stack semantics')
    write(ROOT/'launch-reservation.json', {'schema':'private-log-initialize-reservation-v1',
        'at':datetime.now(timezone.utc).isoformat(), 'initialize_launches_max':1, 'retries':0,
        'prompt_writes':0, 'session_new_writes':0, 'authenticate_writes':0, 'billing_rpc_writes':0,
        'additional_paid_api_budget_usd':0, 'cdb_stack_capture_max':1,
        'difference':'agent --debug --debug-file plus a conditional private stack-only CDB capture after 15 seconds; fresh paths remain a context difference'})
    home, profile, cwd = (ROOT/name for name in ('home','profile','cwd'))
    for path in (home,profile,cwd): path.mkdir()
    env = private_env(home,profile)
    # This help path is argument parsing only and receives no authentication copy.
    help_result = subprocess.run([str(EXE),'agent','--help'],cwd=cwd,env=env,
        stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        timeout=10,creationflags=subprocess.CREATE_NO_WINDOW,check=False)
    (ROOT/'agent-help.stdout.txt').write_bytes(help_result.stdout)
    (ROOT/'agent-help.stderr.txt').write_bytes(help_result.stderr)
    write(ROOT/'help-receipt.json', {'exit_code':help_result.returncode,
        'stdout_sha256':hashlib.sha256(help_result.stdout).hexdigest(),
        'stderr_sha256':hashlib.sha256(help_result.stderr).hexdigest(), 'auth_supplied':False})
    if help_result.returncode != 0 or b'--debug-file' not in help_result.stdout or b'--debug' not in help_result.stdout:
        raise RuntimeError('native help did not confirm logging options')
    from research_loop.modular.grok_skill_isolation import isolated_config,context_record,observe_context
    (home/'config.toml').write_text(isolated_config(cwd,home,profile),encoding='utf-8')
    record = context_record(cwd,home,profile)
    auth_before = metadata(AUTH)
    shutil.copyfile(AUTH,home/'auth.json')
    if metadata(AUTH) != auth_before: raise RuntimeError('global auth metadata changed during copy')
    before_context = observe_context(record)
    spec = importlib.util.spec_from_file_location('private_log_engine',ROOT/'init_engine.py')
    engine = importlib.util.module_from_spec(spec); spec.loader.exec_module(engine)
    assert len(engine.WIRE) == 261
    frozen_paths = [Path(__file__), ROOT/'init_engine.py', ROOT/'stack_capture.py', ROOT/'parser_smoke.py',
        ROOT/'cdb-help.txt', ROOT/'cdb-help.stderr.txt', ROOT/'cdb-help-result.json',
        ROOT/'preparation-manifest.json', ROOT/'README.md', ROOT/'fixture-diagnosis-r2.md', ROOT/'cdb-argument-diagnosis-r1.md',
        home/'config.toml', EXE, CDB,
        INTEGRATION/'research_loop/modular/grok_acp_transport.py',
        INTEGRATION/'research_loop/modular/grok_skill_isolation.py']
    frozen = {str(p.resolve()):sha(p) for p in frozen_paths}
    log_path = ROOT/'native-startup.private.log'
    command = [str(EXE),'--cwd',str(cwd),'agent','--debug','--debug-file',str(log_path),'stdio']
    cdb_sha = frozen[str(CDB.resolve())]
    write(ROOT/'envelope.json', {'schema':'private-log-initialize-stack-envelope-v1',
        'executable_sha256':PIN,'cdb_executable_sha256':cdb_sha,'command':command,'frozen_files':frozen,
        'wire_sha256':hashlib.sha256(engine.WIRE).hexdigest(),'wire_bytes':len(engine.WIRE),
        'private_env_keys':sorted(env),'context_digest':record.content_hash,
        'before_context':before_context,'auth_metadata_before':auth_before,
        'native_initialize_launches':1,'wall_timeout_seconds':60,'stack_capture_after_seconds':15,
        'stack_capture_timeout_seconds':20,'logging_option_authority':'fresh pinned executable agent --help',
        'cdb_help_receipt':json.loads((ROOT/'cdb-help-result.json').read_text(encoding='utf-8')),
        'earlier_envvar_report_claim_not_relied_on':True})
    stack_capture = {'schema':'grok130-cdb-stack-capture-v2','status':'not_started'}
    def capture_stalled_child(pid, alive):
        nonlocal stack_capture
        stack_capture={'schema':'grok130-cdb-stack-capture-v2','status':'attempt_started','known_child_pid':pid}
        try:
            raw=capture(pid,ROOT/'private-cdb',cdb_sha,alive)
        except Exception as error:
            stack_capture={'schema':'grok130-cdb-stack-capture-v2','status':'capture_exception','known_child_pid':pid,'error_type':type(error).__name__,'detach_independently_observed':False}
            raise
        with (ROOT/'private-cdb'/'capture.private.json').open('x',encoding='utf-8') as out:
            json.dump(raw,out,indent=2,sort_keys=True);out.write('\n')
        stack_capture={**{k:v for k,v in raw.items() if k!='raw_private_files'},'status':'capture_success_established' if raw['success_established'] else 'capture_inconclusive','detach_independently_observed':False}
    result=engine.run_once(command,cwd=cwd,env=env,directory=ROOT/'private',frozen_files=frozen,timeout=60,close_stdin=False,on_stalled=capture_stalled_child,stall_after_seconds=15)
    context_after = None; context_fault = None
    try: context_after = observe_context(record)
    except Exception as error: context_fault = type(error).__name__
    assert result['initialize_writes_completed'] <= 1
    assert all(result['outbound_method_counts'][method] == 0 for method in
               ('session/new','session/prompt','authenticate','_x.ai/billing','_x.ai/auto-topup-rule'))
    closure = {'schema':'private-log-initialize-stack-closure-v2','result':result,
        'context_after':context_after,'context_fault':context_fault,
        'auth_metadata_before':auth_before,'auth_metadata_after':metadata(AUTH),
        'global_auth_metadata_unchanged':metadata(AUTH)==auth_before,
        'native_log':{'exists':log_path.exists(),**({'sha256':sha(log_path),**metadata(log_path)} if log_path.exists() else {})},
        'cdb_stack_capture':stack_capture,
        'source_unchanged':all(sha(p)==h for p,h in frozen.items()),
        'model_prompt_writes':0,'retry_count':0,'known_model_usage':None,
        'settled_additional_charge_usd':None,'scientific_effectiveness_proven':False}
    write(ROOT/'closure.json',closure)
    print(json.dumps({'closure':str(ROOT/'closure.json'),'accepted_initialize':result['accepted_initialize'],
        'response_observed':result['response'] is not None,'faults':result['faults'],
        'process_tree_closed':result['process_tree_closed'],'elapsed_seconds':result['elapsed_seconds'],
        'native_log':closure['native_log'],'cdb_stack_capture':stack_capture,
        'source_unchanged':closure['source_unchanged']}),flush=True)

if __name__ == '__main__': main()
