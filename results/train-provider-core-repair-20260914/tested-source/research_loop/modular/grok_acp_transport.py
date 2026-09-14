"""One Grok native ACP prompt with an included-allowance preflight.

This is deliberately not a ModelPort adapter or a headless-event translator.
Raw ACP is private. A terminal reservation is never reused, even on timeout.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import threading
import time
import uuid

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.model_port import _validate_schema
from research_loop.ontology import ContractError

MODEL = 'grok-4.6'


def validate_acp_schema(schema, value):
    """Native-only nullable-object support for diagnostic unknown judgments.

    The legacy Codex schema validator and its admitted schema subset are unchanged.
    """
    if isinstance(schema, dict) and schema.get('type') == ['object', 'null']:
        if (set(schema) != {'type', 'properties', 'required', 'additionalProperties'}
                or not isinstance(schema['properties'], dict)
                or not isinstance(schema['required'], list)
                or set(schema['required']) != set(schema['properties'])
                or schema['additionalProperties'] is not False
                or any(child != {'type': 'number', 'minimum': 0, 'maximum': 1}
                       for child in schema['properties'].values())):
            raise ContractError('invalid nullable diagnostic dimensions schema')
        if value is None:
            return
        schema = dict(schema, type='object')
    if isinstance(schema, dict) and schema.get('type') == 'object' and isinstance(value, dict):
        properties = schema.get('properties', {})
        for key, child in properties.items():
            if isinstance(child, dict) and child.get('type') == ['object', 'null'] and key in value:
                validate_acp_schema(child, value[key])
                properties = dict(properties)
                properties[key] = {'type': 'null'} if value[key] is None else dict(child, type='object')
        schema = dict(schema, properties=properties)
    _validate_schema(schema, value)


EXECUTABLE_SHA256 = 'bf43dc75f5478a106eab1e86d422c963e4dbe9666cf14dab363733d27bf1e672'
DENIED_TOOLS = (
    'Agent', 'ask_user_question', 'enter_plan_mode', 'exit_plan_mode',
    'get_command_or_subagent_output', 'get_task_output', 'grep', 'image_edit',
    'image_gen', 'image_to_video', 'kill_command_or_subagent', 'kill_task',
    'list_dir', 'monitor', 'read_file', 'reference_to_video', 'run_terminal_cmd',
    'run_terminal_command', 'scheduler_create', 'scheduler_delete', 'scheduler_list',
    'search_replace', 'search_tool', 'send_feedback', 'spawn_subagent', 'task',
    'todo_write', 'update_goal', 'use_tool', 'wait_tasks', 'web_fetch', 'web_search', 'write',
)
SAFE_CONFIG = '''disable_web_search = true
[cli]
auto_update = false
[models]
default = "grok-4.6"
session_summary = "grok-4.6"
max_completion_tokens = 128
max_retries = 0
[model."grok-4.6"]
max_completion_tokens = 128
max_retries = 0
[features]
title_refresh = false
turn_summary = false
[skills]
disabled = []
[plugins]
enabled = []
disabled = []
[memory]
enabled = false
[workflows]
enabled = false
[managed_mcps]
enabled = false
gateway_tools_enabled = false
[subagents]
enabled = false
[goal]
enabled = false
[compat.claude]
agents = false
hooks = false
mcps = false
rules = false
skills = false
[compat.cursor]
agents = false
hooks = false
mcps = false
rules = false
skills = false
[marketplace]
default_skills_installs_purged = true
official_marketplace_auto_installed = true
[[marketplace.sources]]
name = "xAI Official"
git = "https://github.com/xai-org/plugin-marketplace.git"
'''
OPPORTUNITY_CONTRACT = 'main-and-initial-title-v2'
DIAGNOSTIC_OPPORTUNITY_CONTRACT = 'diagnostic-main-and-initial-title-v1'
TRAIN_OPPORTUNITY_CONTRACT = 'public-train-main-and-initial-title-v1'


def diagnostic_config(main_output_cap):
    require(type(main_output_cap) is int and main_output_cap > 0, 'diagnostic_output_cap')
    return SAFE_CONFIG.replace('max_completion_tokens = 128', f'max_completion_tokens = {main_output_cap}')


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')


def load_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))


def integer(value):
    return type(value) is int and value >= 0


class Rejected(Exception):
    """Only fixed, public reason codes enter receipts."""


def require(condition, code):
    if not condition:
        raise Rejected(code)


def profile():
    return {'name': 'transport-no-tools', 'description': 'Single bounded transport',
            'discoverSkills': False, 'agentsMd': False, 'permissionMode': 'dontAsk',
            'maxTurns': 1, 'disallowedTools': list(DENIED_TOOLS)}


def billing_gate(billing, topup, now=None):
    """Typed unified-pool gate. Missing remaining percentage is not zero quota.

    A successful empty top-up result means no rule; an RPC error is never empty.
    This is a fresh account snapshot, not an atomic per-request spending lock.
    """
    require(isinstance(billing, dict) and isinstance(topup, dict), 'billing_shape')
    config = billing.get('config')
    require(isinstance(config, dict), 'billing_config_missing')
    require(config.get('isUnifiedBillingUser') is True, 'billing_route_unverified')
    require(billing.get('subscription_tier') in ('SuperGrok', 'SuperGrokHeavy'),
            'included_subscription_unverified')
    for field in ('onDemandCap', 'onDemandUsed', 'prepaidBalance'):
        wrapped = config.get(field)
        require(isinstance(wrapped, dict) and set(wrapped) == {'val'}
                and integer(wrapped['val']), 'billing_money_shape')
        require(wrapped['val'] == 0, 'paid_fallback_available')
    require(topup == {} or topup == {'rule': None}, 'auto_topup_present_or_unknown')
    require(billing.get('on_demand_enabled', False) is False, 'on_demand_enabled')
    period = config.get('currentPeriod')
    require(isinstance(period, dict), 'billing_period_missing')
    try:
        start = datetime.fromisoformat(period['start'].replace('Z', '+00:00'))
        end = datetime.fromisoformat(period['end'].replace('Z', '+00:00'))
        current = now or datetime.now(timezone.utc)
        valid = start <= current < end
    except (KeyError, TypeError, ValueError):
        valid = False
    require(valid, 'billing_period_stale')
    percentage = config.get('creditUsagePercent')
    require(percentage is None or (type(percentage) in (int, float)
            and 0 <= percentage <= 100), 'billing_percentage_shape')
    return {'route': 'grok_com_unified_subscription', 'on_demand_cap': 0,
            'on_demand_used': 0, 'prepaid_balance': 0, 'auto_topup_rule_present': False,
            'remaining_percentage': None if percentage is None else 100 - percentage,
            'atomic_per_request_spending_lock': False}


TOKEN_KEYS = ('inputTokens', 'outputTokens', 'totalTokens', 'cachedReadTokens',
              'cacheCreationTokens', 'reasoningTokens')
COUNT_KEYS = TOKEN_KEYS + ('modelCalls', 'apiDurationMs')


def known_usage(value):
    """Return valid known accounting even when completeness/cost are unknown."""
    if not isinstance(value, dict) or any(not integer(value.get(k)) for k in COUNT_KEYS):
        return None
    if (value['totalTokens'] != value['inputTokens'] + value['outputTokens']
            or value['cachedReadTokens'] + value['cacheCreationTokens'] > value['inputTokens']
            or value['reasoningTokens'] > value['outputTokens']):
        return None
    out = {k: value[k] for k in COUNT_KEYS}
    for key in ('usageIsIncomplete', 'costIsPartial'):
        if type(value.get(key, False)) is not bool:
            return None
        out[key] = value.get(key, False)
    ticks = value.get('costUsdTicks')
    out['costUsdTicks'] = ticks if integer(ticks) else None
    out['numTurns'] = value.get('numTurns') if integer(value.get('numTurns')) else None
    models = value.get('modelUsage')
    out['modelUsage'] = {}
    if isinstance(models, dict):
        for model, usage in models.items():
            # Unknown model names must never carry private text into observer.
            if model not in (MODEL, MODEL + '-build') or not isinstance(usage, dict):
                continue
            parsed = known_usage({**usage, 'modelUsage': None})
            if parsed:
                parsed.pop('modelUsage'); parsed.pop('numTurns')
                out['modelUsage'][model] = parsed
    return out


@dataclass(frozen=True)
class AcpResult:
    receipt: FrozenRecord
    response: FrozenRecord | None


class ProcessTree:
    """Own the subprocess tree; Windows job closure also kills surviving children."""
    def __init__(self, command, cwd, env, stderr):
        self.job = None
        self.process = subprocess.Popen(command, cwd=cwd, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            start_new_session=os.name != 'nt')
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.CreateJobObjectW.restype = wintypes.HANDLE
            kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
            kernel.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int,
                                                       ctypes.c_void_p, wintypes.DWORD)
            kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
            kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            class Basic(ctypes.Structure):
                _fields_ = [('perProcess', ctypes.c_int64), ('perJob', ctypes.c_int64),
                    ('flags', wintypes.DWORD), ('minWorking', ctypes.c_size_t),
                    ('maxWorking', ctypes.c_size_t), ('active', wintypes.DWORD),
                    ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD),
                    ('scheduling', wintypes.DWORD)]
            class Info(ctypes.Structure):
                _fields_ = [('basic', Basic), ('io', ctypes.c_uint64 * 6),
                    ('processMemory', ctypes.c_size_t), ('jobMemory', ctypes.c_size_t),
                    ('peakProcess', ctypes.c_size_t), ('peakJob', ctypes.c_size_t)]
            info = Info(); info.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE
            handle = kernel.CreateJobObjectW(None, None)
            if not handle or not kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)) or not kernel.AssignProcessToJobObject(handle, int(self.process._handle)):
                if handle:
                    kernel.CloseHandle(handle)
                self.process.kill(); self.process.wait()
                raise Rejected('process_tree_guard_unavailable')
            self.job = (kernel, handle)

    def close(self):
        if self.job:
            kernel, handle = self.job
            kernel.CloseHandle(handle); self.job = None
        else:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.process.wait(timeout=5)
        self.process.stdin.close()
        self.process.stdout.close()


class SinglePromptACP:
    """Protocol engine; native callers must use run_native below.

    command injection is intentionally available for synthetic subprocess peers.
    This engine alone is not an authentication or executable provenance gate.
    """
    def __init__(self, command, *, cwd, env, private_dir, reservation, frozen_files,
                 timeout=60, max_total_tokens=20000, main_output_cap=128,
                 opportunity_contract=OPPORTUNITY_CONTRACT, input_byte_cap=None):
        require(0 < timeout <= 60, 'timeout_contract')
        require(type(main_output_cap) is int and main_output_cap > 0
                and type(max_total_tokens) is int and max_total_tokens > main_output_cap,
                'main_token_bounds')
        require(opportunity_contract in (OPPORTUNITY_CONTRACT, DIAGNOSTIC_OPPORTUNITY_CONTRACT, TRAIN_OPPORTUNITY_CONTRACT),
                'opportunity_contract_unapproved')
        require(opportunity_contract != OPPORTUNITY_CONTRACT or main_output_cap == 128,
                'smoke_output_cap_changed')
        require(opportunity_contract not in (DIAGNOSTIC_OPPORTUNITY_CONTRACT, TRAIN_OPPORTUNITY_CONTRACT)
                or (type(input_byte_cap) is int and input_byte_cap > 0), 'diagnostic_input_cap_missing')
        self.command = tuple(command); self.cwd = Path(cwd); self.env = dict(env)
        self.private = Path(private_dir); self.reservation = Path(reservation)
        self.frozen_files = dict(frozen_files)
        self.timeout = timeout; self.max_total_tokens = max_total_tokens
        self.main_output_cap = main_output_cap; self.opportunity_contract = opportunity_contract
        self.input_byte_cap = input_byte_cap
        self.called = False; self.sid = None; self.prompt_id = str(uuid.uuid4())
        self.inventory_sessions = []; self.seen_sessions = set(); self.text = []
        self.usage = None; self.response_usage = []; self.turns = 0
        self.usage_bound = False
        self.sent = False; self.event_counts = {}; self.pre = None; self.post = None
        self.raw_bytes = 0

    def verify_files(self):
        require(bool(self.frozen_files), 'source_manifest_empty')
        for path, expected in self.frozen_files.items():
            require(digest(Path(path).read_bytes()) == expected, 'frozen_file_changed')

    def notification(self, row):
        method = row.get('method'); params = row.get('params')
        require(isinstance(method, str) and isinstance(params, dict), 'notification_shape')
        if method in ('session/update', '_x.ai/session_notification'):
            sid = params.get('sessionId'); update = params.get('update')
            require(isinstance(sid, str) and sid and isinstance(update, dict), 'session_update_shape')
            self.seen_sessions.add(sid)
            require(self.sid is None or sid == self.sid, 'session_binding')
            kind = update.get('sessionUpdate')
            require(isinstance(kind, str), 'session_update_kind')
            meta = params.get('_meta', {})
            require(isinstance(meta, dict), 'notification_meta_shape')
            if 'promptId' in meta:
                require(self.sent and meta['promptId'] == self.prompt_id, 'prompt_binding')
            if kind == 'available_commands_update':
                require(isinstance(update.get('availableCommands'), list), 'command_inventory_shape')
                require(isinstance(update.get('_meta'), dict) and update['_meta'].get('tools') == [],
                        'runtime_tools_not_empty')
                self.inventory_sessions.append(sid)
            elif kind in ('agent_message_chunk', 'agent_thought_chunk', 'user_message_chunk'):
                require(self.sent, 'content_before_prompt')
                content = update.get('content')
                require(isinstance(content, dict) and content.get('type') == 'text'
                        and isinstance(content.get('text'), str), 'nontext_content')
                if kind == 'agent_message_chunk':
                    self.text.append(content['text'])
            elif kind == 'response_completed':
                require(self.sent, 'completion_before_prompt')
                self.response_usage.append(update.get('usage'))
                require(not set(update) - {'sessionUpdate', 'message_id', 'stop_reason',
                        'usage', 'signature', 'stop_sequence'}, 'unknown_response_field')
                # This intermediate wire field is optional. The bound prompt
                # result must still explicitly finish with end_turn below.
                require(len(self.response_usage) == 1
                        and update.get('stop_reason') in (None, 'end_turn', 'stop'),
                        'unexpected_response_completion')
            elif kind == 'turn_completed':
                # Capture independently parseable usage before rejecting bindings.
                self.usage = known_usage(update.get('usage')) or self.usage
                require(self.sent and update.get('prompt_id') == self.prompt_id, 'prompt_binding')
                require(update.get('error_kind') is None, 'terminal_error_kind')
                self.turns += 1
                require(self.turns == 1 and update.get('stop_reason') == 'end_turn', 'unexpected_turn')
            elif kind in ('tool_call', 'tool_call_update', 'tool_call_delta_chunk'):
                raise Rejected('tool_activity')
            elif kind == 'background_tasks':
                require(update.get('tasks') == [] and update.get('truncated', False) is False,
                        'background_activity')
            elif kind == 'model_changed':
                require(update.get('model_id') == MODEL, 'model_changed')
            elif kind == 'session_status':
                pass  # Source-defined display snapshot; values stay private.
            elif kind == 'session_summary_generated':
                require(self.sent and isinstance(update.get('session_summary'), str)
                        and self.event_counts.get(kind, 0) == 0, 'unexpected_title_update')
            elif kind == 'session_info_update':
                require(self.sent and isinstance(update.get('title'), str)
                        and self.event_counts.get(kind, 0) == 0, 'unexpected_title_update')
            elif kind == 'response_started':
                require(self.sent and update.get('model') in (None, MODEL, MODEL + '-build'),
                        'response_model')
                require(all(integer(update.get(k)) for k in ('input_tokens',
                    'cache_read_input_tokens', 'cache_creation_input_tokens')), 'response_start_shape')
                require(self.event_counts.get(kind, 0) == 0, 'extra_response_started')
            elif kind == 'reasoning_completed':
                require(self.sent and (update.get('signature') is None
                        or isinstance(update['signature'], str)),
                        'reasoning_complete_shape')
            else:
                raise Rejected('unknown_or_disallowed_session_update')
            self.event_counts[kind] = self.event_counts.get(kind, 0) + 1
        elif method == '_x.ai/mcp/servers_updated':
            require(params.get('mcpServers') == [], 'mcp_servers_present')
        elif method == '_x.ai/mcp_initialized':
            require(params.get('mcpToolCount') == 0, 'mcp_tools_present')
            sid = params.get('sessionId')
            require(isinstance(sid, str) and sid, 'mcp_session_shape')
            self.seen_sessions.add(sid)
            require(self.sid is None or self.sid == sid, 'session_binding')
        elif method == '_x.ai/models/update':
            require(params.get('currentModelId') == MODEL, 'model_changed')
        elif method == '_x.ai/session/prompt_complete':
            require(self.sent and params.get('sessionId') == self.sid
                    and params.get('promptId') == self.prompt_id, 'prompt_complete_binding')
            require(set(params) <= {'sessionId', 'promptId', 'stopReason', 'agentResult'}
                    and params.get('stopReason') == 'end_turn'
                    and (params.get('agentResult') is None or isinstance(params['agentResult'], str)),
                    'prompt_complete_failure')
            require(self.event_counts.get('prompt_complete', 0) == 0, 'duplicate_prompt_complete')
            self.event_counts['prompt_complete'] = 1
        elif method == '_x.ai/queue/changed':
            # Native prompt lifecycle display, not a new prompt request. Accept
            # only an empty queue or our one bound pending/running prompt.
            require(params.get('sessionId') == self.sid and self.sid is not None,
                    'queue_session_binding')
            require(not set(params) - {'sessionId', 'entries', 'runningPromptId',
                    'runningText', 'runningKind', 'runningCombinedTexts'}, 'unknown_queue_field')
            entries = params.get('entries')
            require(isinstance(entries, list) and len(entries) <= 1, 'extra_queued_work')
            running = params.get('runningPromptId')
            require(running is None or (self.sent and running == self.prompt_id), 'queue_prompt_binding')
            require(params.get('runningCombinedTexts') in (None, []), 'combined_prompt_work')
            if running is not None:
                require(not entries and isinstance(params.get('runningText'), str)
                        and params.get('runningKind') == 'prompt', 'queue_running_shape')
            else:
                require(params.get('runningText') is None and params.get('runningKind') is None,
                        'queue_running_shape')
            for entry in entries:
                require(isinstance(entry, dict) and not set(entry) - {'id', 'version', 'owner',
                        'lastEditor', 'kind', 'text', 'combinedTexts', 'position'}, 'queue_entry_shape')
                require(self.sent and entry.get('id') == self.prompt_id, 'queue_prompt_binding')
                require(entry.get('kind') == 'prompt' and isinstance(entry.get('text'), str)
                        and integer(entry.get('version')) and type(entry.get('position')) is int
                        and entry['position'] == 0 and entry.get('combinedTexts') in (None, []),
                        'queue_entry_shape')
            self.event_counts['queue_changed'] = self.event_counts.get('queue_changed', 0) + 1
        elif method in ('_x.ai/settings/update', '_x.ai/announcements/update'):
            pass  # Advisory startup metadata only; never copied to observer.
        else:
            raise Rejected('unknown_notification')

    def next_row(self):
        remaining = self.deadline - time.monotonic()
        require(remaining > 0, 'timeout')
        try:
            line = self.queue.get(timeout=remaining)
        except queue.Empty:
            raise Rejected('timeout') from None
        require(line is not None, 'unexpected_eof')
        require(len(line) <= 1024 * 1024, 'oversized_frame')
        try:
            row = load_json(line)
        except (ValueError, UnicodeError):
            raise Rejected('malformed_json') from None
        require(isinstance(row, dict) and row.get('jsonrpc') == '2.0', 'rpc_envelope')
        return row

    def rpc(self, method, params):
        self.request_id += 1
        row = {'jsonrpc': '2.0', 'id': self.request_id, 'method': method, 'params': params}
        data = encoded(row) + b'\n'
        self.requests.write(data); self.requests.flush(); os.fsync(self.requests.fileno())
        self.tree.process.stdin.write(data); self.tree.process.stdin.flush()
        while True:
            row = self.next_row()
            if 'id' in row:
                require('method' not in row, 'server_request_disallowed')
                require(type(row['id']) is int and row['id'] == self.request_id, 'rpc_binding')
                require('error' not in row and isinstance(row.get('result'), dict), 'rpc_error')
                return row['result']
            self.notification(row)

    def bill(self):
        billing = self.rpc('_x.ai/billing', {})
        topup = self.rpc('_x.ai/auto-topup-rule', {})
        result = billing_gate(billing, topup)
        result['observed_at'] = datetime.now(timezone.utc).isoformat()
        self.billing_monotonic = time.monotonic()
        return result

    def check_result(self, result, schema):
        meta = result.get('_meta')
        require(isinstance(meta, dict), 'result_meta_missing')
        previous = self.usage
        parsed_usage = known_usage(meta.get('usage'))
        self.usage = parsed_usage or previous
        require(set(result) == {'stopReason', '_meta'} and not set(meta) - {
            'sessionId', 'requestId', 'promptId', 'totalTokens', 'modelId', 'inputTokens',
            'outputTokens', 'cachedReadTokens', 'reasoningTokens', 'usage', 'structuredOutput',
            'completionKind', 'cancellationCategory', 'cancellationContext', 'cancelTrigger',
            'structuredOutputError', 'toolOverrides'}, 'unknown_result_field')
        require(parsed_usage is not None, 'result_usage_missing')
        require(previous is None or previous == parsed_usage, 'terminal_usage_disagreement')
        require(integer(meta.get('totalTokens')), 'terminal_context_count_shape')
        require(all(k not in meta or integer(meta[k]) for k in
                ('inputTokens', 'outputTokens', 'cachedReadTokens', 'reasoningTokens')),
                'terminal_last_call_count_shape')
        require(meta.get('sessionId') == self.sid and meta.get('promptId') == self.prompt_id
                and meta.get('requestId') == self.prompt_id, 'result_binding')
        self.usage_bound = True
        require(result.get('stopReason') == 'end_turn' and meta.get('modelId') == MODEL,
                'result_stop_or_model')
        require(not any(k in meta for k in ('completionKind', 'cancellationCategory',
                'cancelTrigger', 'cancellationContext', 'structuredOutputError', 'toolOverrides')),
                'result_extra_work_or_failure')
        usage = self.usage
        require(usage is not None and usage['numTurns'] == 1 and usage['modelCalls'] == 1
                and not usage['usageIsIncomplete'], 'usage_incomplete_or_extra_calls')
        require(usage['outputTokens'] <= self.main_output_cap and usage['totalTokens'] <= self.max_total_tokens,
                'observed_token_limit')
        models = usage['modelUsage']
        require(len(models) == 1, 'accounting_model')
        raw_usage = meta['usage']
        require(isinstance(raw_usage.get('modelUsage'), dict)
                and set(raw_usage['modelUsage']) == set(models), 'accounting_model')
        model_usage = next(iter(models.values()))
        require(all(model_usage[k] == usage[k] for k in COUNT_KEYS), 'accounting_disagreement')
        require(model_usage['costUsdTicks'] == usage['costUsdTicks'], 'cost_disagreement')
        require(len(self.response_usage) == 1, 'response_usage_missing')
        intermediate = self.response_usage[0]
        fields = ('input_tokens', 'output_tokens', 'cache_read_input_tokens',
                  'cache_creation_input_tokens', 'reasoning_tokens')
        if intermediate is not None:
            require(isinstance(intermediate, dict) and set(intermediate) == set(fields)
                    and all(integer(v) for v in intermediate.values()), 'response_usage_shape')
            expected = (usage['inputTokens'] - usage['cachedReadTokens'] - usage['cacheCreationTokens'],
                        usage['outputTokens'], usage['cachedReadTokens'],
                        usage['cacheCreationTokens'], usage['reasoningTokens'])
            require(tuple(intermediate[k] for k in fields) == expected, 'response_usage_disagreement')
        try:
            text = load_json(''.join(self.text))
            require(text == meta.get('structuredOutput'), 'structured_text_disagreement')
            validate_acp_schema(schema, text)
            require(isinstance(text, dict), 'structured_output_not_object')
        except (ValueError, ContractError, TypeError):
            raise Rejected('structured_output_invalid') from None
        return FrozenRecord.from_dict(text)

    def invoke(self, prompt, schema):
        require(not self.called, 'single_invoke_only'); self.called = True
        require(isinstance(prompt, str) and prompt and isinstance(schema, dict), 'prompt_contract')
        require(self.input_byte_cap is None or len(prompt.encode('utf-8')) <= self.input_byte_cap,
                'bounded_input_bytes')
        self.private.mkdir(parents=True, exist_ok=False)
        self.deadline = time.monotonic() + self.timeout
        self.request_id = 0; self.queue = queue.Queue(); faults = []; response = None
        self.tree = None; reader = None
        with (self.private / 'requests.private.jsonl').open('xb') as self.requests, \
             (self.private / 'stdout.private.jsonl').open('xb') as raw, \
             (self.private / 'stderr.private.txt').open('xb') as stderr:
            try:
                self.verify_files()
                require(not self.reservation.exists(), 'reservation_already_exists')
                self.tree = ProcessTree(self.command, self.cwd, self.env, stderr)
                def read():
                    try:
                        while True:
                            line = self.tree.process.stdout.readline(1024 * 1024 + 1)
                            if not line:
                                break
                            raw.write(line); raw.flush()
                            self.raw_bytes += len(line)
                            self.queue.put(line)
                            if len(line) > 1024 * 1024 or self.raw_bytes > 8 * 1024 * 1024:
                                break
                    finally:
                        self.queue.put(None)
                reader = threading.Thread(target=read, daemon=True); reader.start()
                init = self.rpc('initialize', {'protocolVersion': 1, 'clientCapabilities': {},
                    'clientInfo': {'name': 'research-loop-bounded-acp', 'version': '1'},
                    '_meta': {'startupHints': {'nonInteractive': True, 'skipGitStatus': True,
                                               'skipProjectLayout': True}}})
                require(type(init.get('protocolVersion')) is int and init['protocolVersion'] == 1,
                        'protocol_version')
                new = self.rpc('session/new', {'cwd': str(self.cwd), 'mcpServers': [],
                    '_meta': {'agentProfile': profile(), 'sessionKind': 'headless'}})
                sid = new.get('sessionId')
                try:
                    valid_sid = isinstance(sid, str) and str(uuid.UUID(sid)) == sid
                except ValueError:
                    valid_sid = False
                require(valid_sid, 'session_id_invalid')
                self.sid = sid
                require(isinstance(new.get('models'), dict)
                        and new['models'].get('currentModelId') == MODEL, 'selected_model_mismatch')
                require(self.seen_sessions <= {self.sid}, 'session_binding')
                require(self.sid in self.inventory_sessions, 'preprompt_inventory_missing')
                self.pre = self.bill()  # Same live process, after session setup, before prompt.
                while not self.queue.empty():
                    row = self.next_row()
                    require('id' not in row, 'unsolicited_response')
                    self.notification(row)
                self.verify_files()
                require(time.monotonic() - self.billing_monotonic <= 5, 'billing_snapshot_expired')
                require(time.monotonic() < self.deadline, 'timeout')
                reservation = {'schema': 'grok-acp-single-prompt-reservation-v1',
                    'session_id': self.sid, 'prompt_id': self.prompt_id, 'model': MODEL,
                    'prompt_sha256': digest(prompt.encode()), 'schema_sha256': digest(encoded(schema)),
                    'source_manifest_sha256': digest(encoded(self.frozen_files)),
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'terminal_after_possible_dispatch': True}
                with self.reservation.open('xb') as out:
                    out.write(encoded(reservation)); out.flush(); os.fsync(out.fileno())
                self.sent = True  # Before I/O: an uncertain write is still an attempt.
                result = self.rpc('session/prompt', {'sessionId': self.sid,
                    'prompt': [{'type': 'text', 'text': prompt}], '_meta': {'verbatim': True,
                    'outputSchema': schema, 'screenMode': 'headless', 'promptId': self.prompt_id}})
                try:
                    response = self.check_result(result, schema)
                except Rejected as exc:
                    faults.append(str(exc))
                self.post = self.bill()
                while not self.queue.empty():
                    row = self.next_row(); require('id' not in row, 'unsolicited_response')
                    self.notification(row)
            except Rejected as exc:
                faults.append(str(exc))
            except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError):
                faults.append('local_io_or_contract_failure')
            finally:
                if self.tree:
                    try:
                        self.tree.close()
                    except (OSError, subprocess.SubprocessError):
                        faults.append('process_tree_shutdown_failure')
                if reader:
                    reader.join(timeout=5)
                raw.flush(); os.fsync(raw.fileno())
        # Terminal raw streams may contain a usage frame already delivered when
        # an earlier tool/protocol fault stopped the client. Preserve it privately
        # and expose valid scalar accounting without accepting its binding.
        candidates = []
        for line in (self.private / 'stdout.private.jsonl').read_bytes().splitlines():
            try:
                row = load_json(line)
                possible = [row.get('result', {}).get('_meta', {}).get('usage'),
                    row.get('params', {}).get('update', {}).get('usage'),
                    row.get('error', {}).get('data', {}).get('promptUsage')]
                for item in possible:
                    candidate = known_usage(item)
                    if candidate and candidate not in candidates:
                        candidates.append(candidate)
            except (ValueError, UnicodeError, AttributeError):
                continue
        if self.usage is None and len(candidates) == 1:
            self.usage = candidates[0]
        usage = self.usage
        known_responses = []
        response_fields = {'input_tokens', 'output_tokens', 'cache_read_input_tokens',
                           'cache_creation_input_tokens', 'reasoning_tokens'}
        for item in self.response_usage:
            if (isinstance(item, dict) and set(item) == response_fields
                    and all(integer(v) for v in item.values())
                    and item['reasoning_tokens'] <= item['output_tokens']):
                known_responses.append(item)
        ticks = usage['costUsdTicks'] if usage else None
        cost_complete = bool(usage and ticks is not None and not usage['costIsPartial']
                             and not usage['usageIsIncomplete'])
        receipt = {'schema': 'grok-native-acp-receipt-v2', 'accepted': not faults,
            'faults': list(dict.fromkeys(faults)), 'prompt_may_have_been_dispatched': self.sent,
            'prompt_requests_reserved': int(self.sent), 'session_id': self.sid,
            'prompt_id': self.prompt_id, 'requested_model': MODEL,
            'requested_max_completion_tokens': self.main_output_cap, 'wire_output_cap_certified': False,
            'requested_max_retries': 0, 'requested_max_turns': 1,
            'opportunity_contract': self.opportunity_contract,
            'max_main_prompt_opportunities': 1, 'max_initial_title_opportunities': 1,
            'requested_initial_title_model': MODEL, 'requested_initial_title_output_cap': 100,
            'initial_title_internal_function': 'session_title',
            'initial_title_usage': None, 'initial_title_cost_usd': None,
            'total_model_call_count': None, 'total_tokens_all_opportunities': None,
            'total_cost_usd_all_opportunities': None,
            'side_call_completeness_certified': False,
            'reported_usage_scope': 'native_prompt_usage_ledger',
            'runtime_empty_inventory_count': len(self.inventory_sessions),
            'event_counts': self.event_counts, 'known_usage': usage,
            'known_usage_binding_verified': self.usage_bound,
            'known_response_usage': known_responses,
            'response_usage_scope': 'observed model responses; not all-opportunity totals',
            'known_terminal_usage_candidates': candidates,
            'reported_cost_usd': ticks / 10_000_000_000 if cost_complete else None,
            'reported_cost_complete': cost_complete, 'settled_additional_charge_usd': None,
            'billing_before': self.pre, 'billing_after': self.post,
            'private_stream_sha256': digest((self.private / 'stdout.private.jsonl').read_bytes()),
            'source_manifest_sha256': digest(encoded(self.frozen_files))}
        if self.opportunity_contract == DIAGNOSTIC_OPPORTUNITY_CONTRACT:
            receipt['schema'] = 'grok-native-acp-diagnostic-receipt-v1'
            receipt['diagnostic_binding'] = {
                'prompt_sha256': digest(prompt.encode('utf-8')),
                'schema_sha256': digest(encoded(schema)),
                'response_sha256': response.content_hash if response is not None else None,
                'reservation_sha256': digest(self.reservation.read_bytes()) if self.sent else None,
                'source_manifest_sha256': digest(encoded(self.frozen_files)),
                'input_byte_cap': self.input_byte_cap,
                'observed_main_token_cap': self.max_total_tokens}
        elif self.opportunity_contract == TRAIN_OPPORTUNITY_CONTRACT:
            receipt['schema'] = 'grok-native-acp-public-train-receipt-v1'
            receipt['public_train_binding'] = {
                'request_stream_sha256': digest((self.private / 'requests.private.jsonl').read_bytes()),
                'prompt_sha256': digest(prompt.encode('utf-8')), 'schema_sha256': digest(encoded(schema)),
                'response_sha256': response.content_hash if response is not None else None,
                'reservation_sha256': digest(self.reservation.read_bytes()) if self.sent else None,
                'source_manifest_sha256': digest(encoded(self.frozen_files)), 'input_byte_cap': self.input_byte_cap,
                'observed_main_token_cap': self.max_total_tokens,
                'title_usage_and_all_opportunity_totals': 'unknown'}
        (self.private / 'observer-receipt.json').write_bytes(encoded(receipt) + b'\n')
        return AcpResult(FrozenRecord.from_dict(receipt), response if not faults else None)


def native_launch(*, executable, cwd, private_home, private_profile, frozen_files, expected_config=SAFE_CONFIG):
    """Prepare pinned native startup for read-only ACP investigation.

    The caller provisions the already-authorized native auth file without reading
    it, freezes source/config hashes, and keeps all runtime directories private.
    This function never logs in, purchases credits or changes account settings.
    """
    executable = Path(executable).resolve(); cwd = Path(cwd).resolve()
    home = Path(private_home).resolve(); user = Path(private_profile).resolve()
    require(digest(executable.read_bytes()) == EXECUTABLE_SHA256, 'executable_pin')
    require((home / 'config.toml').read_text(encoding='utf-8') == expected_config, 'native_config_pin')
    require(set(p.name for p in home.iterdir()) == {'auth.json', 'config.toml'}, 'native_home_not_fresh')
    require(not any(cwd.iterdir()) and not any(user.iterdir()), 'native_context_not_empty')
    require(str(executable) in frozen_files and str(home / 'config.toml') in frozen_files,
            'native_manifest_missing')
    env = {k: v for k, v in os.environ.items() if k.upper() in
           {'SYSTEMROOT', 'WINDIR', 'SYSTEMDRIVE', 'COMSPEC', 'PATHEXT', 'PATH',
            'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'OS'}}
    env.update({'GROK_HOME': str(home), 'USERPROFILE': str(user), 'HOME': str(user),
        'HOMEDRIVE': user.drive, 'HOMEPATH': str(user)[len(user.drive):],
        'APPDATA': str(user / 'AppData' / 'Roaming'),
        'LOCALAPPDATA': str(user / 'AppData' / 'Local'), 'TEMP': str(user / 'temp'),
        'TMP': str(user / 'temp'), 'GROK_TITLE_REFRESH': 'false', 'GROK_TURN_SUMMARY': 'false',
        'GROK_MEMORY': 'false', 'GROK_WORKFLOWS': 'false', 'GROK_SUBAGENTS': 'false'})
    for key in ('APPDATA', 'LOCALAPPDATA', 'TEMP'):
        Path(env[key]).mkdir(parents=True, exist_ok=True)
    command = [str(executable), '--no-auto-update', '--cwd', str(cwd), 'agent', 'stdio']
    return command, env


def run_native(*, opportunity_contract, executable, cwd, private_home, private_profile,
               private_dir, reservation, frozen_files, prompt, schema, timeout=60):
    """Execute the explicit two-opportunity contract using existing native login.

    One main prompt plus at most one first-title opportunity, with title usage
    unknown, is a different contract from a single total model-call guarantee.
    No legacy ModelPort or Codex dispatch policy is changed by this entry point.
    """
    require(opportunity_contract == OPPORTUNITY_CONTRACT, 'opportunity_contract_unapproved')
    command, env = native_launch(executable=executable, cwd=cwd,
        private_home=private_home, private_profile=private_profile, frozen_files=frozen_files)
    return SinglePromptACP(command, cwd=cwd, env=env, private_dir=private_dir,
        reservation=reservation, frozen_files=frozen_files, timeout=timeout).invoke(prompt, schema)


def run_native_diagnostic(*, opportunity_contract, executable, cwd, private_home, private_profile,
                          private_dir, reservation, frozen_files, prompt, schema,
                          main_output_cap, observed_main_token_cap, input_byte_cap):
    """Separate diagnostic request bounds; no tokenizer or capacity claim."""
    require(opportunity_contract == DIAGNOSTIC_OPPORTUNITY_CONTRACT, 'diagnostic_contract_unapproved')
    require(type(input_byte_cap) is int and input_byte_cap > 0 and isinstance(prompt, str)
            and len(prompt.encode('utf-8')) <= input_byte_cap, 'diagnostic_input_bytes')
    config = diagnostic_config(main_output_cap)
    require(type(observed_main_token_cap) is int and observed_main_token_cap > main_output_cap,
            'diagnostic_observed_token_cap')
    command, env = native_launch(executable=executable, cwd=cwd, private_home=private_home,
        private_profile=private_profile, frozen_files=frozen_files, expected_config=config)
    return SinglePromptACP(command, cwd=cwd, env=env, private_dir=private_dir,
        reservation=reservation, frozen_files=frozen_files, timeout=60,
        main_output_cap=main_output_cap, max_total_tokens=observed_main_token_cap,
        opportunity_contract=opportunity_contract, input_byte_cap=input_byte_cap).invoke(prompt, schema)


def run_native_train(*, opportunity_contract, executable, cwd, private_home, private_profile,
                     private_dir, reservation, frozen_files, prompt, schema, main_output_cap,
                     observed_main_token_cap, input_byte_cap):
    """Native public-TRAIN request with explicit observed, not quoted, bounds."""
    require(opportunity_contract == TRAIN_OPPORTUNITY_CONTRACT, 'train_opportunity_contract_unapproved')
    require(type(input_byte_cap) is int and input_byte_cap > 0 and isinstance(prompt, str)
            and len(prompt.encode('utf-8')) <= input_byte_cap, 'train_input_bytes')
    require(type(observed_main_token_cap) is int and observed_main_token_cap > main_output_cap,
            'train_observed_token_cap')
    config = diagnostic_config(main_output_cap)
    command, env = native_launch(executable=executable, cwd=cwd, private_home=private_home,
        private_profile=private_profile, frozen_files=frozen_files, expected_config=config)
    return SinglePromptACP(command, cwd=cwd, env=env, private_dir=private_dir,
        reservation=reservation, frozen_files=frozen_files, timeout=60,
        main_output_cap=main_output_cap, max_total_tokens=observed_main_token_cap,
        opportunity_contract=TRAIN_OPPORTUNITY_CONTRACT,
        input_byte_cap=input_byte_cap).invoke(prompt, schema)
