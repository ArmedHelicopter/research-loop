"""Synthetic ACP subprocess; never imports a provider or contacts a network."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

scenario, log_path = sys.argv[1:]
sid = '00000000-0000-4000-8000-000000000001'
bill_count = 0


def send(value):
    print(json.dumps({'jsonrpc': '2.0', **value}), flush=True)


def event(kind, **fields):
    send({'method': 'session/update' if kind in ('available_commands_update',
         'agent_message_chunk', 'agent_thought_chunk', 'tool_call') else '_x.ai/session_notification',
         'params': {'sessionId': sid, 'update': {'sessionUpdate': kind, **fields}}})


for line in sys.stdin:
    req = json.loads(line)
    with open(log_path, 'a', encoding='utf-8') as out:
        out.write(line)
    method = req['method']; result = {}
    if method == 'initialize':
        result = {'protocolVersion': 1}
    elif method == 'session/new':
        if scenario == 'pre_timeout':
            child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
            Path(log_path + '.child').write_text(str(child.pid))
            time.sleep(120)
        if scenario == 'malformed':
            print('{"jsonrpc":"2.0","method":"x","method":"y"}', flush=True)
            time.sleep(120)
        if scenario == 'unknown':
            send({'method': '_x.ai/future_work', 'params': {}})
        event('available_commands_update', availableCommands=[],
              _meta={'tools': ['read_file'] if scenario == 'tools' else []})
        result = {'sessionId': '00000000-0000-4000-8000-000000000002' if scenario == 'new_binding' else sid,
                  'models': {'currentModelId': 'other' if scenario == 'model' else 'grok-4.6'}}
    elif method == '_x.ai/billing':
        bill_count += 1
        now = datetime.now(timezone.utc)
        config = {'isUnifiedBillingUser': True, 'onDemandCap': {'val': 0},
                  'onDemandUsed': {'val': 0}, 'prepaidBalance': {'val': 0},
                  'currentPeriod': {'start': (now - timedelta(hours=1)).isoformat(),
                                    'end': (now + timedelta(hours=1)).isoformat()}}
        if scenario == 'paid' or (scenario == 'post_paid' and bill_count > 1):
            config['prepaidBalance']['val'] = 1
        if scenario == 'bool_money':
            config['onDemandCap']['val'] = False
        result = {'config': config, 'subscription_tier': 'SuperGrok'}
    elif method == '_x.ai/auto-topup-rule':
        if scenario == 'topup_error':
            send({'id': req['id'], 'error': {'code': -1, 'message': 'PRIVATE ERROR'}})
            continue
        if scenario == 'topup':
            result = {'rule': {'enabled': True}}
    elif method == 'session/prompt':
        pid = req['params']['_meta']['promptId']
        if scenario == 'timeout':
            child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
            Path(log_path + '.child').write_text(str(child.pid))
            time.sleep(120)
        if scenario == 'tool_event':
            event('tool_call', title='PRIVATE TOOL')
        if scenario == 'server_request':
            send({'id': 999, 'method': 'session/request_permission', 'params': {'secret': 'PRIVATE'}})
        event('agent_thought_chunk', content={'type': 'text', 'text': 'PRIVATE REASONING'})
        event('agent_message_chunk', content={'type': 'text', 'text': '{"ok":true}'})
        inter = {'input_tokens': 8, 'output_tokens': 2, 'cache_read_input_tokens': 2,
                 'cache_creation_input_tokens': 0, 'reasoning_tokens': 0}
        event('response_completed', stop_reason='end_turn', usage=inter)
        usage = {'inputTokens': 10, 'outputTokens': 2, 'totalTokens': 12,
                 'cachedReadTokens': 2, 'cacheCreationTokens': 0, 'reasoningTokens': 0,
                 'modelCalls': 1, 'apiDurationMs': 20, 'costUsdTicks': 123}
        usage = {**usage, 'numTurns': 1, 'modelUsage': {'grok-4.6-build': dict(usage)}}
        if scenario == 'unknown_cost':
            usage.pop('costUsdTicks'); usage['modelUsage']['grok-4.6-build'].pop('costUsdTicks')
        if scenario == 'partial':
            usage['costIsPartial'] = True
        if scenario == 'incomplete':
            usage['usageIsIncomplete'] = True
        if scenario == 'multi_call':
            usage['modelCalls'] = 2
        if scenario == 'tokens':
            usage['outputTokens'] = 129; usage['totalTokens'] = 139
        event('turn_completed', prompt_id=pid, stop_reason='end_turn', usage=usage)
        meta = {'sessionId': sid, 'promptId': pid, 'requestId': pid, 'modelId': 'grok-4.6',
                'usage': usage, 'structuredOutput': {'ok': True}, 'totalTokens': 12}
        if scenario == 'prompt_binding':
            meta['promptId'] = 'PRIVATE WRONG'
        if scenario == 'result_session':
            meta['sessionId'] = 'PRIVATE WRONG'
        if scenario == 'extra_work':
            meta['toolOverrides'] = {}
        if scenario == 'schema':
            meta['structuredOutput'] = {'ok': False}
        result = {'stopReason': 'end_turn', '_meta': meta}
    else:
        raise AssertionError(method)
    send({'id': req['id'], 'result': result})
