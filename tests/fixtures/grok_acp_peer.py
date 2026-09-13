"""Synthetic ACP subprocess; never imports a provider or contacts a network."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

scenario, log_path = sys.argv[1:]
sid = '00000000-0000-4000-8000-000000000001'
if scenario.startswith(('diagnostic', 'authoring', 'train_')):
    sid = str(uuid.uuid5(uuid.NAMESPACE_URL, log_path))
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
        answer = {'ok': True}
        if scenario.startswith('authoring'):
            from tests.helpers.material_authoring_fixture import authored_answer
            answer = authored_answer(json.loads(req['params']['prompt'][0]['text'])['references'])
        if scenario.startswith(('diagnostic','train_')):
            from tests.helpers.calibration_pilot_fixture import fixture_target
            messages = json.loads(req['params']['prompt'][0]['text'])['messages']
            schema_fields = req['params']['_meta']['outputSchema']['properties']
            if 'state' in schema_fields:
                material = json.loads(messages[1]['content'])
                benchmark = 'blade' if 'cvars' in material['dimensions'] else 'discoverybench'
                answer = fixture_target(material['candidate']['answer'], benchmark)
            else:
                candidate = json.loads(messages[1]['content'].rsplit('\nANONYMOUS_CANDIDATE=', 1)[1])
                benchmark = 'blade' if 'cvars' in schema_fields else 'discoverybench'
                target = fixture_target(candidate['answer'], benchmark)
                dims = target['dimensions'] or {k: 1 for k in schema_fields if k != 'reason'}
                answer = {k: v * (2 if benchmark == 'blade' else 1) for k, v in dims.items()}
                answer['reason'] = 'synthetic fixture'
        if scenario.startswith('train_'):
            request = json.loads(req['params']['prompt'][0]['text'].split('\n', 1)[1])
            slot = request['slot']
            if slot == 'm4_plan':
                answer = {'question': 'Which public mechanism explains x?', 'budget_units': 3, 'branches': [
                    {'hypothesis_id':'h1','mechanism_key':'m1','mechanism':'public mechanism one','intervention':'public','elimination_condition':'x does not increase','predictions':[{'prediction_id':'p1','discriminator_id':'d','observable':'x','direction':'increase','value_range':None,'failure_condition':'not increase'}]},
                    {'hypothesis_id':'h2','mechanism_key':'m2','mechanism':'public mechanism two','intervention':'public','elimination_condition':'x does increase','predictions':[{'prediction_id':'p2','discriminator_id':'d','observable':'x','direction':'decrease','value_range':None,'failure_condition':'not decrease'}]},
                    {'hypothesis_id':'h3','mechanism_key':'m3','mechanism':'public mechanism three','intervention':'public','elimination_condition':'x is unchanged','predictions':[{'prediction_id':'p3','discriminator_id':'d','observable':'x','direction':'unchanged','value_range':None,'failure_condition':'not unchanged'}]}]}
            elif slot in ('m5_mechanism', 'm5_measurement'):
                answer = {'assessment': 'concern', 'evidence_refs': [], 'counterexamples': [], 'uncertainty': 'synthetic'}
            elif slot == 'analysis_program':
                answer = {'analysis': 'mean public x', 'program': "import csv\nwith open('/input/public_csv', newline='') as f:\n rows=list(csv.DictReader(f))\nprint(sum(float(r['x']) for r in rows)/len(rows))"}
            else:
                answer = {'objective_digest': request['module_context']['required_objective_digest'], 'outcome': 'unknown',
                    'evidence_ids': [], 'conclusion': 'The public mean is 2.0.', 'programme_complete': False}
        if scenario in ('queue', 'queue_wrong', 'queue_extra', 'queue_unknown'):
            send({'method': '_x.ai/queue/changed', 'params': {'sessionId': sid, 'entries': [
                {'id': pid, 'version': 1, 'kind': 'prompt', 'text': 'PRIVATE PROMPT DISPLAY', 'position': 0}]}})
            params = {'sessionId': sid, 'entries': [], 'runningPromptId': pid,
                      'runningText': 'PRIVATE PROMPT DISPLAY', 'runningKind': 'prompt'}
            if scenario == 'queue_wrong':
                params['runningPromptId'] = 'other-prompt'
            if scenario == 'queue_extra':
                params['entries'] = [{'id': 'another'}, {'id': 'another2'}]
            if scenario == 'queue_unknown':
                params['launchNewAgent'] = True
            send({'method': '_x.ai/queue/changed', 'params': params})
        if scenario == 'timeout':
            child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
            Path(log_path + '.child').write_text(str(child.pid))
            time.sleep(120)
        if scenario == 'tool_event':
            event('tool_call', title='PRIVATE TOOL')
        if scenario == 'server_request':
            send({'id': 999, 'method': 'session/request_permission', 'params': {'secret': 'PRIVATE'}})
        event('agent_thought_chunk', content={'type': 'text', 'text': 'PRIVATE REASONING'})
        event('agent_message_chunk', content={'type': 'text', 'text': json.dumps(answer)})
        inter = {'input_tokens': 8, 'output_tokens': 2, 'cache_read_input_tokens': 2,
                 'cache_creation_input_tokens': 0, 'reasoning_tokens': 0}
        if scenario == 'optional_usage':
            event('response_completed')
        elif scenario in ('optional_stop', 'optional_stop_bad_terminal'):
            event('response_completed', usage=inter)
        else:
            event('response_completed', stop_reason='end_turn', usage=inter)
        usage = {'inputTokens': 10, 'outputTokens': 2, 'totalTokens': 12,
                 'cachedReadTokens': 2, 'cacheCreationTokens': 0, 'reasoningTokens': 0,
                 'modelCalls': 1, 'apiDurationMs': 20, 'costUsdTicks': 123}
        usage = {**usage, 'numTurns': 1, 'modelUsage': {'grok-4.6-build': dict(usage)}}
<<<<<<< HEAD
        if scenario in ('diagnostic_unknown_main', 'authoring_unknown_main'):
=======
        if scenario in ('diagnostic_unknown_main','train_unknown_main'):
>>>>>>> 9ad2fd9 (Repair native TRAIN startup and terminal provenance replay)
            usage['usageIsIncomplete'] = True
        if scenario == 'rpc_error_usage':
            usage['usageIsIncomplete'] = True
            send({'id': req['id'], 'error': {'code': -32000, 'message': 'PRIVATE ERROR',
                  'data': {'promptUsage': usage}}})
            continue
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
                'usage': usage, 'structuredOutput': answer, 'totalTokens': 12}
        if scenario == 'prompt_binding':
            meta['promptId'] = 'PRIVATE WRONG'
        if scenario == 'result_session':
            meta['sessionId'] = 'PRIVATE WRONG'
        if scenario == 'extra_work':
            meta['toolOverrides'] = {}
        if scenario == 'schema':
            meta['structuredOutput'] = {'ok': False}
        if scenario == 'context_count':
            meta['totalTokens'] = True
        if scenario in ('prompt_complete', 'prompt_complete_wrong'):
            send({'method': '_x.ai/session/prompt_complete', 'params': {'sessionId': sid,
                  'promptId': 'other' if scenario == 'prompt_complete_wrong' else pid,
                  'stopReason': 'end_turn', 'agentResult': None}})
        result = {'stopReason': 'max_tokens' if scenario == 'optional_stop_bad_terminal' else 'end_turn', '_meta': meta}
    else:
        raise AssertionError(method)
    send({'id': req['id'], 'result': result})
