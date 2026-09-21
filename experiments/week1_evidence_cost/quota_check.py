import json,subprocess,threading,queue,time,sys
from pathlib import Path
from datetime import datetime,timezone
exe=Path(r'C:\Users\Administrator\AppData\Roaming\npm\node_modules\@openai\codex\node_modules\@openai\codex-win32-x64\vendor\x86_64-pc-windows-msvc\bin\codex.exe')
out=Path(sys.argv[1])
out.mkdir(parents=True,exist_ok=False)
q=queue.Queue()
p=subprocess.Popen([str(exe),'app-server','--stdio'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                   stderr=subprocess.DEVNULL,text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW)
def pump():
    for line in p.stdout:
        try:q.put(json.loads(line))
        except ValueError:pass
threading.Thread(target=pump,daemon=True).start()
sent=[]
def call(method,i=None,params=None):
    packet=dict(method=method)
    if i is not None:packet['id']=i
    if params is not None:packet['params']=params
    sent.append(packet)
    p.stdin.write(json.dumps(packet)+'\n');p.stdin.flush()
    if i is None:return None
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        msg=q.get(timeout=max(.01,deadline-time.monotonic()))
        if msg.get('id')==i:
            if 'error' in msg:raise RuntimeError('RPC error: '+str(msg['error'].get('code')))
            return msg.get('result')
    raise TimeoutError(method)
try:
    call('initialize',0,dict(clientInfo=dict(name='week1_quota_readonly',version='1.0')))
    call('initialized')
    account=call('account/read',1,dict(refreshToken=False))
    limits=call('account/rateLimits/read',2)
    acc=account.get('account') or {}
    buckets=limits.get('rateLimitsByLimitId') or {'default':limits.get('rateLimits')}
    cleaned={}
    for key,value in buckets.items():
        if not value:continue
        record={k:value.get(k) for k in ('limitId','limitName','planType','rateLimitReachedType')}
        for window in ('primary','secondary'):
            v=value.get(window)
            record[window]=({k:v.get(k) for k in ('usedPercent','windowDurationMins','resetsAt')} if v else None)
        cleaned[key]=record
    receipt=dict(observed_at_utc=datetime.now(timezone.utc).isoformat(),status='read_success',
        source='Official installed Codex CLI app-server account/read and account/rateLimits/read',
        cli=str(exe),protocol_reference='https://learn.chatgpt.com/docs/app-server',
        account_type=acc.get('type'),plan_type=acc.get('planType'),rate_limits=cleaned,
        monthly_expiry='unknown: not exposed by this response',tier_multiplier='unknown',
        current_desktop_account_match='not established by available tool',
        model_requests=0,reset_or_topup_requests=0,sent_methods=[r['method'] for r in sent])
except Exception as e:
    receipt=dict(observed_at_utc=datetime.now(timezone.utc).isoformat(),status='read_failed',
        error_type=type(e).__name__,model_requests=0,reset_or_topup_requests=0)
finally:
    p.terminate()
    try:p.wait(timeout=5)
    except subprocess.TimeoutExpired:p.kill();p.wait(timeout=5)
receipt['helper_terminated']=p.poll() is not None
(out/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
(out/'requests.json').write_text(json.dumps(sent,indent=2),encoding='utf-8')
print(json.dumps(receipt))

