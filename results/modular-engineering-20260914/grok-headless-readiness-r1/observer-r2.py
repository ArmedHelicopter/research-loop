"""One native constant prompt under a fresh zero-paid-balance observation.

Separate from experimental TRAIN/VAL ports. Unknown title/settlement is retained.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
import urllib.error
import urllib.request

TREE = Path('E:/_ryanDev/AI/research-loop-modular/artifact-evidence-provenance')
sys.path.insert(0, str(TREE))
from research_loop.modular.grok_acp_transport import ProcessTree, SAFE_CONFIG, DENIED_TOOLS, profile
from research_loop.modular.grok_cli_protocol import inspect_grok_stream

ROOT = Path('E:/_ryanDev/AI/research-loop-modular/work/grok-headless-constant-readiness-r2')
EXE = Path('C:/Users/Administrator/.grok/bin/grok.exe')
EXE_PIN = 'bf43dc75f5478a106eab1e86d422c963e4dbe9666cf14dab363733d27bf1e672'
PROXY = 'https://cli-chat-proxy.grok.com/v1'
SCHEMA = {'type':'object','properties':{'transport_ok':{'type':'boolean','enum':[True]}},
          'required':['transport_ok'],'additionalProperties':False}
PROMPT = 'Return exactly this JSON object: {"transport_ok":true}'
SYSTEM = 'This is a constant JSON transport check. Return only the requested JSON object. Do not use tools.'
sha = lambda b: hashlib.sha256(b).hexdigest()
encode = lambda x: json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
class Rejected(Exception): pass
def require(value, code):
    if not value: raise Rejected(code)
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None

def gate(credits, topup, user, expected_user, now):
    require(type(credits) is dict and type(topup) is dict and type(user) is dict,'account_shapes')
    require(user.get('userId') == expected_user, 'account_binding')
    require(user.get('hasGrokCodeAccess') is True and user.get('userBlockedReason') in (None,'')
            and user.get('teamBlockedReasons') == [], 'account_access')
    cfg = credits.get('config')
    require(type(cfg) is dict and cfg.get('isUnifiedBillingUser') is True,'unified_pool')
    for field in ('onDemandCap','onDemandUsed','prepaidBalance'):
        value = cfg.get(field)
        require(type(value) is dict and set(value) <= {'val'} and
                type(value.get('val',0)) is int and value.get('val',0) == 0,'paid_fallback_or_unknown')
    require(topup == {} or topup == {'rule':None}, 'auto_topup_or_unknown')
    period = cfg.get('currentPeriod')
    require(type(period) is dict, 'period_shape')
    require(datetime.fromisoformat(period['start'].replace('Z','+00:00')) <= now <
            datetime.fromisoformat(period['end'].replace('Z','+00:00')), 'period_stale')
    percent = cfg.get('creditUsagePercent')
    require(type(percent) in (int,float) and 0 <= percent < 100, 'included_balance_unknown_or_empty')
    return {'schema':'fresh-zero-paid-fallback-account-observation-v1',
        'unified_pool':True,'code_access':True,'account_binding':True,
        'remaining_percentage':100-percent,'on_demand_cap':0,'on_demand_used':0,'prepaid_balance':0,
        'auto_topup_configured':False,'reported_subscription_tier':user.get('subscriptionTier'),
        'tier_display_mapping_asserted':False,'atomic_per_request_spending_lock':False,
        'observed_at':now.isoformat()}

def account(home, destination):
    destination.mkdir(exist_ok=False)
    store=json.loads((home/'auth.json').read_bytes())
    candidates=[v for v in store.values() if type(v) is dict and v.get('auth_mode')=='oidc' and
        v.get('oidc_issuer')=='https://auth.x.ai' and
        v.get('oidc_client_id')=='b1a00492-073a-47ea-816f-4c329264a828']
    require(len(candidates)==1, 'native_login_identity')
    auth=candidates[0]
    require(all(type(auth.get(k)) is str and auth[k] and '\n' not in auth[k] and '\r' not in auth[k]
                for k in ('key','user_id')), 'native_login_shape')
    require(datetime.fromisoformat(auth['expires_at'].replace('Z','+00:00')).timestamp() > time.time()+120,
            'native_login_near_expiry')
    rows=[]; payloads=[]; first_request=time.monotonic()
    opener=urllib.request.build_opener(NoRedirect)
    for name, route in (('credits','/billing?format=credits'),('topup','/auto-topup-rule'),
                        ('user','/user?include=subscription')):
        request=urllib.request.Request(PROXY+route, method='GET', headers={
            'Authorization':'Bearer '+auth['key'], 'X-XAI-Token-Auth':'xai-grok-cli',
            'x-userid':auth['user_id'], 'x-grok-client-version':'1.0.13','Accept':'application/json'})
        row={'name':name,'method':'GET','url':PROXY+route,'status':'reserved',
             'started_at':datetime.now(timezone.utc).isoformat()}
        rows.append(row); (destination/'requests.json').write_bytes(encode(rows))
        start=time.monotonic()
        try:
            with opener.open(request,timeout=10) as response:
                require(response.geturl()==PROXY+route,'redirect')
                raw=response.read(1048577)
                require(len(raw)<=1048576,'account_response_size')
                row['http_status']=response.status
        except urllib.error.HTTPError as exc:
            row.update(status='http_error',http_status=exc.code)
            raise Rejected('account_http_error') from None
        finally:
            row['elapsed_seconds']=round(time.monotonic()-start,3)
            (destination/'requests.json').write_bytes(encode(rows))
        (destination/(name+'.private.json')).write_bytes(raw)
        row.update(status='received',bytes=len(raw),sha256=sha(raw),
                   received_at=datetime.now(timezone.utc).isoformat())
        (destination/'requests.json').write_bytes(encode(rows))
        payloads.append(json.loads(raw))
    result=gate(*payloads,auth['user_id'],datetime.now(timezone.utc))
    result['first_request_age_seconds']=time.monotonic()-first_request
    (destination/'observation.json').write_bytes(encode(result))
    return result

def child(command,cwd,env,out,timeout):
    with (out/'stderr.private.txt').open('xb') as err:
        tree=ProcessTree(command,cwd,env,err)
        expired=False; started=time.monotonic()
        try: raw,_=tree.process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            expired=True
            kernel,handle=tree.job
            kernel.CloseHandle(handle); tree.job=None
            raw,_=tree.process.communicate(timeout=5)
        finally:
            if tree.job is not None: tree.close()
    (out/'stdout.private.jsonl').write_bytes(raw)
    return raw, {'exit_code':tree.process.returncode,'timeout':expired,
        'elapsed_seconds':round(time.monotonic()-started,3),'process_exited':tree.process.poll() is not None,
        'owned_job_closed':tree.job is None,'stdout_bytes':len(raw),'stdout_sha256':sha(raw),
        'stderr_bytes':(out/'stderr.private.txt').stat().st_size,
        'stderr_sha256':sha((out/'stderr.private.txt').read_bytes())}

def self_test():
    import copy
    now=datetime.now(timezone.utc)
    cfg={'isUnifiedBillingUser':True,'onDemandCap':{'val':0},'onDemandUsed':{'val':0},
         'prepaidBalance':{'val':0},'creditUsagePercent':2,
         'currentPeriod':{'start':'2026-01-01T00:00:00+00:00','end':'2027-01-01T00:00:00+00:00'}}
    user={'userId':'fixture','hasGrokCodeAccess':True,'userBlockedReason':None,'teamBlockedReasons':[],
          'subscriptionTier':'GrokPro'}
    require(gate({'config':cfg},{},user,'fixture',now)['remaining_percentage']==98,'fixture_accept')
    cases=[]
    for field in ('onDemandCap','onDemandUsed','prepaidBalance'):
        c=copy.deepcopy(cfg); c[field]={'val':1}; cases.append(({'config':c},{},user,'fixture',now))
        c=copy.deepcopy(cfg); del c[field]; cases.append(({'config':c},{},user,'fixture',now))
    for value in (100,None,True):
        c=copy.deepcopy(cfg); c['creditUsagePercent']=value; cases.append(({'config':c},{},user,'fixture',now))
    cases.extend([({'config':cfg},{'rule':{'enabled':True}},user,'fixture',now),
                  ({'config':cfg},{},user,'other-account',now),
                  ({'config':cfg},{},{**user,'hasGrokCodeAccess':False},'fixture',now)])
    for case in cases:
        try: gate(*case)
        except Rejected: pass
        else: raise AssertionError('unqualified account accepted')
    print(json.dumps({'account_gate_checks':len(cases)+1,'passed':len(cases)+1,'network_calls':0}))

def run_once():
    ROOT.mkdir(exist_ok=False)
    home,user,cwd=[ROOT/name for name in ('private-home','private-profile','public-cwd')]
    for path in (home,user,cwd): path.mkdir()
    require(sha(EXE.read_bytes())==EXE_PIN,'executable_pin')
    shutil.copyfile('C:/Users/Administrator/.grok/auth.json',home/'auth.json')
    (home/'config.toml').write_bytes(SAFE_CONFIG.replace('max_completion_tokens = 128', 'max_completion_tokens = 512').encode())
    prompt=ROOT/'prompt.txt'; prompt.write_text(PROMPT,encoding='utf-8')
    session=str(uuid.uuid4())
    command=[str(EXE),'--no-auto-update','--cwd',str(cwd),'--model','grok-4.6',
        '--prompt-file',str(prompt),'--json-schema',encode(SCHEMA).decode(),'--output-format','streaming-json',
        '--max-turns','1','--session-id',session,'--no-subagents','--no-plan','--disable-web-search',
        '--disallowed-tools',','.join(DENIED_TOOLS),'--agents',encode({'transport-no-tools':profile()}).decode(),
        '--agent','transport-no-tools','--permission-mode','dontAsk','--deny','MCPTool',
        '--system-prompt-override',SYSTEM,'--verbatim']
    env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','SYSTEMDRIVE','COMSPEC',
        'PATHEXT','PATH','NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE','OS'}}
    env.update(GROK_HOME=str(home),USERPROFILE=str(user),HOME=str(user),HOMEDRIVE='E:',HOMEPATH=str(user)[2:],
        APPDATA=str(user/'AppData/Roaming'),LOCALAPPDATA=str(user/'AppData/Local'),TEMP=str(user/'temp'),TMP=str(user/'temp'),
        GROK_DISABLE_AUTOUPDATER='1',GROK_DISABLE_API_KEY_AUTH='1',GROK_TITLE_REFRESH='false',GROK_TURN_SUMMARY='false',
        GROK_MEMORY='false',GROK_WORKFLOWS='false',GROK_SUBAGENTS='false')
    for key in ('APPDATA','LOCALAPPDATA','TEMP'): Path(env[key]).mkdir(parents=True,exist_ok=True)
    pins={str(p):sha(p.read_bytes()) for p in (EXE,Path(__file__),home/'config.toml',prompt,
        TREE/'research_loop/modular/grok_acp_transport.py',TREE/'research_loop/modular/grok_cli_protocol.py')}
    receipt={'schema':'native-headless-constant-readiness-v1','status':'reserved','command':command,
        'environment_names':sorted(env),'session_id':session,'source_pins':pins,
        'data_scope':'constant_only_no_benchmark_material','main_opportunities':1,'possible_initial_title_opportunities':1,
        'requested_main_output_cap':512,'requested_title_output_cap':100,'requested_retries':0,
        'initial_title_usage':None,'all_opportunity_tokens':None,'settled_additional_charge_usd':None,
        'extra_api_fee_budget':0,'prompt_process_launched':False,'fault':None,
        'scientific_effectiveness_proven':False,'experimental_provider_admitted':False}
    (ROOT/'reservation.json').write_bytes(encode(receipt))
    try:
        inspect_dir=ROOT/'inspect'; inspect_dir.mkdir()
        raw,closed=child([str(EXE),'--no-auto-update','--cwd',str(cwd),'inspect','--json'],cwd,env,inspect_dir,10)
        receipt['inspect_process']=closed
        require(closed['exit_code']==0 and not closed['timeout'],'inspect_failed')
        inventory=json.loads(raw)
        require(all(inventory.get(k)==[] for k in ('skills','hooks','plugins','mcpServers','projectInstructions')),
                'external_context_discovered')
        require(inventory.get('loginPolicy',{}).get('apiKeyAuthDisabled') is True,'api_key_lockdown_unobserved')
        receipt['billing_before']=account(home,ROOT/'billing-before')
        billed=time.monotonic()
        require(all(sha(Path(p).read_bytes())==h for p,h in pins.items()),'source_drift')
        require(receipt['billing_before']['first_request_age_seconds']+time.monotonic()-billed<=5,
                'account_snapshot_stale')
        model_dir=ROOT/'model'; model_dir.mkdir()
        receipt['prompt_process_launched']=True
        (ROOT/'reservation.json').write_bytes(encode(receipt))
        raw,closed=child(command,cwd,env,model_dir,60)
        receipt['model_process']=closed
        inspected=inspect_grok_stream(raw,schema=SCHEMA,session_id=session,max_output_tokens=512,
            max_total_tokens=20000,process_exit_code=closed['exit_code'])
        receipt['stream_inspection']=inspected.receipt.data()
        (ROOT/'stream-inspection.json').write_bytes(inspected.receipt.encoded.encode())
        if inspected.response is not None: (ROOT/'response.json').write_bytes(inspected.response.encoded.encode())
        receipt['billing_after']=account(home,ROOT/'billing-after')
        require(all(sha(Path(p).read_bytes())==h for p,h in pins.items()),'source_drift')
        require(not closed['timeout'] and inspected.receipt.data()['accepted'],'native_stream_rejected')
        receipt['status']='constant_transport_verified'
    except Rejected as exc:
        receipt.update(status='rejected',fault=str(exc))
    except Exception as exc:
        receipt.update(status='rejected',fault=type(exc).__name__)
    (ROOT/'receipt.json').write_bytes(encode(receipt))
    public={k:receipt.get(k) for k in ('schema','status','prompt_process_launched','fault','billing_before','billing_after',
        'model_process','stream_inspection','settled_additional_charge_usd','experimental_provider_admitted')}
    print(json.dumps(public),flush=True)

if __name__=='__main__':
    if sys.argv[1:]==['--self-test']: self_test()
    elif sys.argv[1:]==['--run-once']: run_once()
    else: raise SystemExit('Use --self-test or --run-once')
