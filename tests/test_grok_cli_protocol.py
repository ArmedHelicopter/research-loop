"""Protocol regressions; all streams are synthetic and issue no CLI calls."""
import copy
import json

import pytest

from research_loop.modular.grok_cli_protocol import inspect_grok_stream

SCHEMA={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}
SESSION='synthetic-single-session'


def stream():
    # Field forms and counting convention reproduce the authorized r5 receipt.
    return [
        {'type':'available_commands','tools':[],'commands':['context']},
        {'type':'text','data':'{"ok":true}'},
        {'type':'end','stopReason':'end_turn','sessionId':SESSION,'requestId':'synthetic-request',
         'usage':{'input_tokens':9335,'cache_read_input_tokens':0,'cache_creation_input_tokens':0,
                  'output_tokens':46,'reasoning_tokens':37,'total_tokens':9381},
         'num_turns':1,'total_cost_usd':.00644164,'total_cost_usd_ticks':64416400,
         'modelUsage':{'grok-4.6-build':{'inputTokens':9335,'outputTokens':46,'cacheReadInputTokens':0,
                       'cacheCreationInputTokens':0,'modelCalls':1,'costUSD':.00644164}},
         'structuredOutput':{'ok':True}}]


def inspect(events=None,raw=None,**kwargs):
    return inspect_grok_stream(raw if raw is not None else ('\n'.join(json.dumps(e) for e in events)+'\n').encode(),
        schema=SCHEMA,session_id=SESSION,max_output_tokens=128,max_total_tokens=20000,
        process_exit_code=kwargs.get('process_exit_code',0))


def test_observed_success_keeps_accounting_model_reasoning_and_settlement_separate():
    result=inspect(stream()); body=result.receipt.data()
    assert result.response.data()=={'ok':True} and body['accepted']
    assert body['accounting_model']=='grok-4.6-build'
    assert body['usage']['total_tokens']==9381  # reasoning is already in output.
    assert body['server_reported_usd']==.00644164
    assert body['billing_settlement']=='not_established_by_stream'
    assert body['output_cap_wire_certified'] is False


@pytest.mark.parametrize('fault',[
    'advertised_tools','tool_call','tool_update','missing_inventory','different_session','two_ends',
    'truncated_stop','two_model_calls','other_model','two_models','bool_tokens','usage_flag',
    'mismatched_total','mismatched_model_usage','budget_breach','response_mismatch','invalid_schema',
    'provider_error','after_end','unknown_event','malformed_inventory','duplicate_json_key'])
def test_protocol_failures_are_terminal_but_keep_available_usage(fault):
    rows=stream(); end=rows[-1]; model=end['modelUsage']['grok-4.6-build']; raw=None
    if fault=='advertised_tools':rows[0]['tools']=['run_terminal_command']
    elif fault=='tool_call':rows.insert(1,{'type':'tool_call','toolName':'read_file'})
    elif fault=='tool_update':rows.insert(1,{'type':'tool_call_update','toolCallId':'x'})
    elif fault=='missing_inventory':rows.pop(0)
    elif fault=='different_session':end['sessionId']='other-session'
    elif fault=='two_ends':rows.append(copy.deepcopy(end))
    elif fault=='truncated_stop':end['stopReason']='max_tokens'
    elif fault=='two_model_calls':model['modelCalls']=2
    elif fault=='other_model':end['modelUsage']={'other-model':model}
    elif fault=='two_models':end['modelUsage']['other-model']=copy.deepcopy(model)
    elif fault=='bool_tokens':end['usage']['output_tokens']=True
    elif fault=='usage_flag':end['usage_is_incomplete']=True
    elif fault=='mismatched_total':end['usage']['total_tokens']+=1
    elif fault=='mismatched_model_usage':model['inputTokens']+=1
    elif fault=='budget_breach':end['usage'].update(output_tokens=129,total_tokens=9464);model['outputTokens']=129
    elif fault=='response_mismatch':end['structuredOutput']={'ok':False}
    elif fault=='invalid_schema':end['structuredOutput']={'ok':1};rows[1]['data']='{"ok":1}'
    elif fault=='provider_error':rows.insert(1,{'type':'error','message':'synthetic quota exhausted'})
    elif fault=='after_end':rows.append({'type':'thought','data':'late'})
    elif fault=='unknown_event':rows.insert(1,{'type':'unexpected_session_resume'})
    elif fault=='malformed_inventory':rows[0]['tools']={}
    elif fault=='duplicate_json_key':raw=('\n'.join(json.dumps(e) for e in rows)+'\n{"type":"thought","type":"text","data":"extra"}\n').encode()
    result=inspect(rows,raw=raw); body=result.receipt.data()
    assert result.response is None and not body['accepted'] and body['faults']
    if fault not in {'two_ends','bool_tokens','usage_flag','mismatched_total'}:
        assert body['usage'] is not None
        assert body['server_reported_usd']==.00644164


@pytest.mark.parametrize('cost_form',['missing','partial','zero'])
def test_missing_or_partial_cost_is_unknown_and_reported_zero_is_explicit(cost_form):
    rows=stream();end=rows[-1]
    if cost_form in {'missing','partial'}:
        if cost_form=='partial':end['cost_is_partial']=True
        else:
            end.pop('total_cost_usd');end.pop('total_cost_usd_ticks')
            end['modelUsage']['grok-4.6-build'].pop('costUSD')
    else:
        end['total_cost_usd']=0;end['total_cost_usd_ticks']=0
        end['modelUsage']['grok-4.6-build']['costUSD']=0
    body=inspect(rows).receipt.data()
    assert body['accepted']
    assert body['server_reported_usd']==(0 if cost_form=='zero' else None)
    assert body['cost_status']==('server_reported' if cost_form=='zero' else 'unknown')
    assert body['billing_settlement']=='not_established_by_stream'


def test_failed_process_retains_complete_reported_usage_without_returning_response():
    result=inspect(stream(),process_exit_code=7)
    assert result.response is None
    assert result.receipt.data()['usage']['total_tokens']==9381
    assert result.receipt.data()['faults']==['process_failed']


def test_cached_tokens_are_counted_once_and_contradictory_cost_is_rejected():
    rows=stream();end=rows[-1]
    end['usage'].update(cache_read_input_tokens=100,cache_creation_input_tokens=200,total_tokens=9681)
    end['modelUsage']['grok-4.6-build'].update(cacheReadInputTokens=100,cacheCreationInputTokens=200)
    assert inspect(rows).receipt.data()['usage']['total_tokens']==9681
    end['total_cost_usd_ticks']+=1
    result=inspect(rows)
    assert result.response is None and 'contradictory_cost' in result.receipt.data()['faults']
    assert result.receipt.data()['server_reported_usd'] is None


def test_invalid_utf8_and_truncated_json_never_invent_complete_usage():
    for raw in (b'\xff',b'{"type":"end",'):
        result=inspect(raw=raw);body=result.receipt.data()
        assert result.response is None and body['usage'] is None
        assert body['server_reported_usd'] is None and body['cost_status']=='unknown'
