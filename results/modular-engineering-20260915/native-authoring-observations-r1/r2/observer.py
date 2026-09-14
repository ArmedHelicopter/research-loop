"""One separately reserved, instrumented TRAIN authoring request; no retries.

This observation does not produce a production headless receipt or admit any
material, reviewer or evaluator. Raw model/debug/account data remain private.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone

WORK = Path(__file__).parent
TREE = WORK.parent / 'headless-instrumented-diagnostic'
ROOT = WORK / 'headless-instrumented-request-r2'
CHECK = WORK / 'headless-instrumented-prerequisite-r1-closed.json'
OLD = WORK / 'headless-authoring-actual-preparation-r1/freeze/authoring-envelope.json'
OLD_SHA = 'ace54e08e4f1872442ba7dbd3eb027ef524cc891e7d5ae45a3142520bf2f73b2'
sys.path.insert(0, str(TREE))
import research_loop.modular.grok_headless_transport as t
from research_loop.modular.grok_acp_transport import EXECUTABLE_SHA256, diagnostic_config
from research_loop.modular.grok_cli_protocol import inspect_grok_stream
from evaluation.modular.diagnostic_material_authoring import own_sources, validate_authored
from evaluation.modular.reference_store import FrozenTrainReferenceResolver
from research_loop.modular.contracts import DataIdentity

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write(path, body):
    raw = t._canon(body)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    return {'path': str(path), 'sha256': sha(path)}

def native_account_binding(home):
    values=json.loads((Path(home)/'auth.json').read_bytes()).values()
    accounts=[v for v in values if type(v) is dict and v.get('auth_mode')=='oidc'
        and v.get('oidc_issuer')=='https://auth.x.ai'
        and v.get('oidc_client_id')=='b1a00492-073a-47ea-816f-4c329264a828']
    assert len(accounts)==1 and type(accounts[0].get('user_id')) is str and accounts[0]['user_id']
    return hashlib.sha256(accounts[0]['user_id'].encode()).hexdigest()


def prepare():
    check = json.loads(CHECK.read_bytes())
    head = subprocess.check_output(['git','rev-parse','HEAD'],cwd=TREE,text=True).strip()
    assert head == check['commit'] and check['exit_code'] == 0 and check['source_unchanged']
    assert check['junit']['failures'] == check['junit']['errors'] == check['junit']['skipped'] == 0
    assert not (TREE/'data/labels').exists() and not (TREE/'data/tasks').exists()
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=TREE).strip()
    # Match executed Python code byte-for-byte to the checked integration source.
    for name, pin in check['source_after'].items():
        if name.endswith('.py'):
            assert sha(TREE/name) == pin, name
    assert sha(OLD) == OLD_SHA
    old = json.loads(OLD.read_bytes()); entry = old['entries'][0]
    task = next(row for row in old['tasks'] if row['task_handle'] == entry['task_handle'])
    DataIdentity.parse(task['identity']).require_train()
    request_path = Path(entry['private_request']['path'])
    assert sha(request_path) == entry['private_request']['sha256']
    request = json.loads(request_path.read_bytes())
    assert hashlib.sha256(request['prompt'].encode()).hexdigest() == entry['prompt_sha256']
    assert len(request['prompt'].encode()) == entry['input_bytes']
    store = old['reference_store']
    resolver = FrozenTrainReferenceResolver(Path(store['root']), **{k:store[k] for k in
        ('manifest_sha256','inventory_digest','split_digest')})
    reference = resolver(entry['task_handle'], task['identity']['benchmark'])
    assert reference.content_hash == entry['reference_digest']
    exe = Path('C:/Users/Administrator/.grok/bin/grok.exe')
    assert sha(exe) == EXECUTABLE_SHA256
    expected_account = native_account_binding(Path('C:/Users/Administrator/.grok'))
    old_reservation = OLD.with_suffix('.run-reservation.json')
    assert old_reservation.is_file()
    ROOT.mkdir(exist_ok=False)
    home, profile, cwd = [ROOT/name for name in ('home','profile','cwd')]
    for path in (home, profile, cwd): path.mkdir()
    shutil.copyfile('C:/Users/Administrator/.grok/auth.json', home/'auth.json')
    assert native_account_binding(home)==expected_account
    account_descriptor=write(ROOT/'account-binding.private.json', {'account_binding':expected_account,'issuer':'https://auth.x.ai','client_id':'b1a00492-073a-47ea-816f-4c329264a828'})
    (home/'config.toml').write_bytes(diagnostic_config(8192).encode())
    native = ROOT/'native'; native.mkdir()
    (native/'prompt.private.txt').write_bytes(request['prompt'].encode())
    write(native/'schema.private.json', request['output_schema'])
    request_desc = write(ROOT/'request.private.json', request)
    import uuid
    session = str(uuid.uuid4())
    context = {'executable':str(exe),'cwd':str(cwd),'private_home':str(home),'private_profile':str(profile)}
    environment = t._fresh_env(home, profile)
    base_command = t._command(context, native, session, request['output_schema'])
    command = base_command + ['--debug','--debug-file',str(native/'debug.private.log')]
    files = {str(p):sha(p) for p in own_sources().values()}
    files.update({str(p):sha(p) for p in (Path(__file__),CHECK,OLD,exe,home/'config.toml',
        Path(request_desc['path']), Path(account_descriptor['path']), old_reservation, request_path, Path(store['root'])/'manifest.json',
        Path(store['root'])/(entry['task_handle']+'.json'))})
    envelope = {'schema':'headless-instrumented-request-v1','commit':head,'check':str(CHECK),
        'context':context,'environment':environment,'session_id':session,'request':request_desc,
        'original_entry':entry,'task':task,'reference_store':store,'frozen_files':files,
        'original_envelope_sha256':OLD_SHA,'retained_original_reservation':{'path':str(old_reservation),'sha256':sha(old_reservation)},'account_descriptor':account_descriptor,'base_command':base_command,'command':command,
        'command_delta':['--debug','--debug-file','private absolute destination'],
        'main_opportunities':1,'possible_initial_title_opportunities':1,'main_output_cap':8192,
        'observed_main_token_cap':131072,'input_byte_cap':262144,'timeout_seconds':240,
        'retry':False,'extra_paid_api_budget':0,'review_evaluator_requests':0,'validation_access':False}
    desc = write(ROOT/'envelope.json', envelope)
    print(json.dumps({'prepared':desc,'source_check_tests':check['junit']['tests'],
        'input_bytes':entry['input_bytes'],'main_opportunities':1,'new_model_calls':0}),flush=True)

def run(expected):
    envelope_path = ROOT/'envelope.json'
    assert sha(envelope_path) == expected
    e = json.loads(envelope_path.read_bytes()); t._sources(e['frozen_files'])
    request = json.loads(Path(e['request']['path']).read_bytes())
    assert sha(e['request']['path']) == e['request']['sha256']
    native = ROOT/'native'; context = e['context']; home = Path(context['private_home'])
    assert not (native/'debug.private.log').exists()
    reservation = dict(e, envelope_sha256=expected, reserved_at=datetime.now(timezone.utc).isoformat())
    write(ROOT/'reservation.json', reservation)
    record = {'schema':'headless-instrumented-observation-v1','envelope_sha256':expected,
        'status':'rejected','fault':None,'inspect_process':None,'native_process':None,
        'account_preflight':None,'account_postflight':None,'stream_inspection':None,
        'debug_file':None,'authoring_shape_and_excerpts_valid':False,'material_status_counts':None,
        'initial_title_usage':None,'all_opportunity_usage':None,'settled_additional_charge_usd':None,
        'production_receipt':False,'material_admitted':False,'validation_access':False}
    stage='account_binding_before_inspect'
    try:
        expected_account=json.loads(Path(e['account_descriptor']['path']).read_bytes())['account_binding']
        assert native_account_binding(home)==expected_account
        stage='inspect'
        raw, process = t._child(t._inspect_command(context),context,e['environment'],native/'inspect',10)
        record['inspect_process']=process
        assert t._process_ok(process); t._inspect(raw)
        stage='account_preflight'; record['account_preflight']=t._account(home,native/'billing-before')
        assert record['account_preflight']['account_binding']==expected_account
        t._sources(e['frozen_files'])
        age=(datetime.now(timezone.utc)-t._instant(record['account_preflight']['oldest_observed_at'])).total_seconds()
        assert 0 <= age <= 5
        stage='native_request'
        raw, process = t._child(e['command'],context,e['environment'],native,240)
        record['native_process']=process
        inspected=inspect_grok_stream(raw,schema=request['output_schema'],session_id=e['session_id'],
            max_output_tokens=8192,max_total_tokens=131072,
            process_exit_code=process['process_exit_code'] if type(process['process_exit_code']) is int else -1)
        record['stream_inspection']=inspected.receipt.data()
        if inspected.response is not None:write(native/'response.private.json',inspected.response.data())
        stage='account_postflight';record['account_postflight']=t._account(home,native/'billing-after')
        assert record['account_preflight']['account_binding']==record['account_postflight']['account_binding']==expected_account
        stage='independent_readback'
        check_raw,check_process=t._reread_process(native,e['command'],reservation,240)
        assert check_raw==raw and check_process==process
        for suffix,field in (('before','account_preflight'),('after','account_postflight')):
            assert t._reread_account(native/('billing-'+suffix))==record[field]
        t._sources(e['frozen_files'])
        stage='native_acceptance'
        assert t._process_ok(process) and inspected.receipt.data()['accepted'] and inspected.response is not None
        stage='material_shape_and_excerpts'
        store=e['reference_store'];resolver=FrozenTrainReferenceResolver(Path(store['root']),**{k:store[k]
            for k in ('manifest_sha256','inventory_digest','split_digest')})
        reference=resolver(e['original_entry']['task_handle'],e['task']['identity']['benchmark'])
        assert reference.content_hash==e['original_entry']['reference_digest']
        rows=validate_authored(inspected.response.data(),reference.data()['references'])
        record['authoring_shape_and_excerpts_valid']=True
        record['material_status_counts']={key:sum(r['status']==key for r in rows)
            for key in ('ready','unresolved_material','not_applicable')}
        record['status']='provisional_response_observed'
    except Exception as exc:
        record['fault']=stage+':'+type(exc).__name__
    finally:
        debug=native/'debug.private.log'
        if debug.is_file():
            record['debug_file']={'path':str(debug),'sha256':sha(debug),'bytes':debug.stat().st_size}
        record['source_unchanged']=all(sha(path)==pin for path,pin in e['frozen_files'].items())
        write(ROOT/'observation.private.json',record)
        public={k:v for k,v in record.items() if k not in ('inspect_process','native_process')}
        for key in ('inspect_process','native_process'):
            p=record[key]
            public[key]=None if p is None else {k:p[k] for k in ('started_at','finished_at','timed_out',
                'failure','pid','launched','process_exit_code','owned_tree_closed','stdout_sha256','stderr_sha256')}
        write(ROOT/'public-observation.json',public)
        print(json.dumps(public),flush=True)

if __name__=='__main__':
    if sys.argv[1:]==['--prepare']:prepare()
    elif len(sys.argv)==3 and sys.argv[1]=='--run-once':run(sys.argv[2])
    else:raise SystemExit('Use --prepare or --run-once <envelope sha256>')
