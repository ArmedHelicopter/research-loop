"""Inspect the pinned Grok headless protocol without calling a provider.

Reported service accounting is not an invoice or a subscription entitlement.
Even rejected replies retain independently parseable usage; callers must keep
their reservation terminal after any failure instead of retrying the prompt.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from typing import Mapping

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.model_port import _finite, _validate_schema
from research_loop.ontology import ContractError


MODEL = 'grok-4.6'
ACCOUNTING_MODELS = frozenset((MODEL, 'grok-4.6-build'))
TOKEN_FIELDS = ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens',
                'output_tokens', 'reasoning_tokens', 'total_tokens')
EVENT_TYPES = frozenset(('available_commands', 'thought', 'text', 'usage', 'end',
                         'error', 'tool_call', 'tool_call_update'))


@dataclass(frozen=True)
class GrokStreamInspection:
    receipt: FrozenRecord
    response: FrozenRecord | None


def _load(raw):
    def pairs(rows):
        out = {}
        for key, value in rows:
            if key in out:
                raise ValueError('duplicate JSON key')
            out[key] = value
        return out
    value = json.loads(raw, object_pairs_hook=pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    _finite(value)
    return value


def _integer(value):
    return type(value) is int and value >= 0


def _usage(end):
    usage = end.get('usage')
    if not isinstance(usage, dict) or set(usage) != set(TOKEN_FIELDS):
        return None
    if any(not _integer(v) for v in usage.values()):
        return None
    if usage['reasoning_tokens'] > usage['output_tokens']:
        return None
    total = sum(usage[k] for k in TOKEN_FIELDS[:4])
    if total != usage['total_tokens'] or end.get('usage_is_incomplete', False) is not False:
        return None
    return usage


def inspect_grok_stream(raw: bytes, *, schema: Mapping, session_id: str,
                        max_output_tokens: int, max_total_tokens: int,
                        process_exit_code: int) -> GrokStreamInspection:
    """Validate a single fresh-session response, retaining known failure cost.

    A successful result requires observed empty runtime tool inventories, no
    tool events, one completed turn/call, exact model accounting and matching
    textual/structured JSON. Output limits here are checked observations,
    not evidence that an unseen wire request enforced a cap.
    """
    if (not isinstance(raw, bytes) or not isinstance(schema, Mapping)
            or not isinstance(session_id, str) or not session_id
            or type(max_output_tokens) is not int or max_output_tokens < 1
            or type(max_total_tokens) is not int or max_total_tokens < max_output_tokens
            or type(process_exit_code) is not int):
        raise ContractError('invalid frozen Grok stream inspection contract')
    faults = []
    def fault(value):
        if value not in faults:
            faults.append(value)
    events = []
    try:
        lines = raw.decode('utf-8').splitlines()
    except UnicodeError:
        lines = []; fault('non_utf8_stream')
    for line in lines:
        if not line.strip():
            continue
        try:
            event = _load(line)
            if not isinstance(event, dict) or event.get('type') not in EVENT_TYPES:
                raise ValueError('unknown event')
            events.append(event)
        except (ValueError, TypeError, ContractError):
            fault('invalid_or_unknown_event')
    if any(event['type']=='thought' and (set(event)!={'type','data'}
            or not isinstance(event['data'],str)) for event in events):
        fault('invalid_thought_event')
    ends = [event for event in events if event['type'] == 'end']
    inventories = [event for event in events if event['type'] == 'available_commands']
    tool_events = sum(event['type'] in ('tool_call','tool_call_update') for event in events)
    if not inventories:
        fault('runtime_tools_unobserved')
    for event in inventories:
        if (set(event) != {'type','tools','commands'} or not isinstance(event['tools'], list)
                or not isinstance(event['commands'], list)
                or any(not isinstance(v, str) for v in event['tools']+event['commands'])):
            fault('invalid_runtime_inventory')
        elif event['tools']:
            fault('runtime_tools_available')
    if tool_events:
        fault('tool_activity')
    if any(event['type'] == 'error' for event in events):
        fault('provider_error')
    if process_exit_code != 0:
        fault('process_failed')
    usage = None; accounting_model = None; calls = None; cost = None; cost_ticks = None
    response = None
    if len(ends) != 1:
        fault('end_count')
    else:
        end = ends[0]
        end_fields = {'type','stopReason','sessionId','requestId','usage','num_turns',
                      'modelUsage','structuredOutput','total_cost_usd','total_cost_usd_ticks',
                      'cost_is_partial','usage_is_incomplete'}
        if set(end)-end_fields:
            fault('unknown_end_fields')
        if events[-1] is not end:
            fault('events_after_end')
        if end.get('sessionId') != session_id:
            fault('session_mismatch')
        if end.get('stopReason') != 'end_turn':
            fault('incomplete_stop')
        if not isinstance(end.get('requestId'), str) or not end['requestId']:
            fault('missing_request_id')
        if type(end.get('num_turns')) is not int or end['num_turns'] != 1:
            fault('turn_count')
        usage = _usage(end)
        if usage is None:
            fault('usage_incomplete_or_invalid')
        elif usage['output_tokens'] > max_output_tokens or usage['total_tokens'] > max_total_tokens:
            fault('observed_token_budget_breach')
        usage_events = [event for event in events if event['type']=='usage']
        if len(usage_events)!=1:
            fault('usage_event_count')
        else:
            event=usage_events[0]
            expected_fields=set(TOKEN_FIELDS)-{'total_tokens'}
            if (set(event)!={'type','usage','signature'} or not isinstance(event['signature'],str)
                    or not isinstance(event['usage'],dict) or set(event['usage'])!=expected_fields
                    or any(not _integer(v) for v in event['usage'].values())):
                fault('invalid_usage_event')
            elif usage is not None and any(event['usage'][k]!=usage[k] for k in expected_fields):
                fault('contradictory_usage_event')
        models = end.get('modelUsage')
        if not isinstance(models, dict) or len(models) != 1 or next(iter(models)) not in ACCOUNTING_MODELS:
            fault('model_accounting_mismatch')
        else:
            accounting_model, model = next(iter(models.items()))
            expected = {'inputTokens','outputTokens','cacheReadInputTokens','cacheCreationInputTokens','modelCalls'}
            if (not isinstance(model, dict) or set(model)-{'costUSD'} != expected
                    or any(not _integer(model.get(k)) for k in expected)):
                fault('model_accounting_invalid')
            else:
                calls = model['modelCalls']
                if calls != 1:
                    fault('model_call_count')
                mapping = {'inputTokens':'input_tokens','outputTokens':'output_tokens',
                           'cacheReadInputTokens':'cache_read_input_tokens',
                           'cacheCreationInputTokens':'cache_creation_input_tokens'}
                if usage is not None and any(model[k] != usage[v] for k,v in mapping.items()):
                    fault('contradictory_usage')
        # Cost is retained only with consistent full accounting. Absent or partial
        # cost remains unknown; it never becomes an inferred zero tariff.
        if end.get('cost_is_partial', False) is False:
            amount = end.get('total_cost_usd'); ticks = end.get('total_cost_usd_ticks')
            if type(amount) in (float,int) and math.isfinite(amount) and amount >= 0 and _integer(ticks):
                try:
                    if Decimal(str(amount))*10**10 == ticks:
                        cost, cost_ticks = amount, ticks
                    else:
                        fault('contradictory_cost')
                except InvalidOperation:
                    fault('invalid_cost')
            elif amount is not None or ticks is not None:
                fault('invalid_cost')
        if cost is not None and accounting_model is not None and isinstance(models.get(accounting_model), dict):
            reported = models[accounting_model].get('costUSD')
            if reported is not None and reported != cost:
                fault('contradictory_cost')
                cost = cost_ticks = None
        texts = [event for event in events if event['type'] == 'text']
        if any(set(event) != {'type','data'} or not isinstance(event['data'], str) for event in texts):
            fault('invalid_text_event')
        else:
            try:
                output = _load(''.join(event['data'] for event in texts))
                if output != end.get('structuredOutput'):
                    raise ValueError('structured output mismatch')
                _validate_schema(schema, output)
                response = FrozenRecord.from_dict(output)
            except (ValueError, TypeError, ContractError):
                fault('invalid_or_mismatched_response')
    receipt = FrozenRecord.from_dict({
        'schema':'grok-cli-stream-inspection-v1', 'events_sha256':hashlib.sha256(raw).hexdigest(),
        'requested_model':MODEL, 'accounting_model':accounting_model, 'session_id':session_id,
        'process_exit_code':process_exit_code, 'event_count':len(events), 'end_count':len(ends),
        'runtime_inventory_count':len(inventories), 'tool_event_count':tool_events,
        'usage':usage, 'reported_main_model_calls':calls,
        'server_reported_usd':cost, 'server_reported_usd_ticks':cost_ticks,
        'cost_status':'server_reported' if cost is not None else 'unknown',
        'billing_settlement':'not_established_by_stream', 'output_cap_wire_certified':False,
        'faults':faults, 'accepted':not faults,
        'response_digest':response.content_hash if response is not None else None,
        'requested_max_output_tokens':max_output_tokens, 'max_total_tokens':max_total_tokens})
    return GrokStreamInspection(receipt, response if not faults else None)
