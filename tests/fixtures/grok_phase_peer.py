"""Synthetic native ACP peer for complete TRAIN phase fixtures; no network."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import uuid

log=Path(sys.argv[1]);fault=sys.argv[2];sid=str(uuid.uuid5(uuid.NAMESPACE_URL,str(log)))
answer=json.loads(log.with_suffix('.answer.json').read_bytes())


def send(value): print(json.dumps({'jsonrpc':'2.0',**value}),flush=True)


for line in sys.stdin:
    req=json.loads(line)
    with log.open('a',encoding='utf-8') as out: out.write(line)
    method=req['method'];result={}
    if method=='initialize': result={'protocolVersion':1}
    elif method=='session/new':
        send({'method':'session/update','params':{'sessionId':sid,'update':{
            'sessionUpdate':'available_commands_update','availableCommands':[],'_meta':{'tools':[]}}}})
        result={'sessionId':sid,'models':{'currentModelId':'grok-4.6'}}
    elif method=='_x.ai/billing':
        now=datetime.now(timezone.utc)
        result={'config':{'isUnifiedBillingUser':True,'onDemandCap':{'val':0},'onDemandUsed':{'val':0},
            'prepaidBalance':{'val':0},'currentPeriod':{'start':(now-timedelta(hours=1)).isoformat(),
            'end':(now+timedelta(hours=1)).isoformat()}},'subscription_tier':'SuperGrok'}
    elif method=='_x.ai/auto-topup-rule': pass
    elif method=='session/prompt':
        pid=req['params']['_meta']['promptId']
        send({'method':'session/update','params':{'sessionId':sid,'update':{
            'sessionUpdate':'agent_message_chunk','content':{'type':'text','text':json.dumps(answer)}}}})
        usage={'inputTokens':10,'outputTokens':2,'totalTokens':12,'cachedReadTokens':2,
            'cacheCreationTokens':0,'reasoningTokens':0,'modelCalls':1,'apiDurationMs':20,'costUsdTicks':123}
        usage={**usage,'numTurns':1,'modelUsage':{'grok-4.6-build':dict(usage)}}
        if fault=='unknown_main': usage['usageIsIncomplete']=True
        send({'method':'_x.ai/session_notification','params':{'sessionId':sid,'update':{
            'sessionUpdate':'turn_completed','prompt_id':pid,'stop_reason':'end_turn','usage':usage}}})
        result={'stopReason':'end_turn','_meta':{'sessionId':sid,'promptId':pid,'requestId':pid,
            'modelId':'grok-4.6','usage':usage,'structuredOutput':answer,'totalTokens':12}}
    else: raise AssertionError(method)
    send({'id':req['id'],'result':result})
