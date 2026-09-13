"""Actual subprocess boundaries, with no model or network access."""
import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import time

import pytest

from research_loop.modular.grok_acp_transport import (
    Rejected, SinglePromptACP, billing_gate, digest, known_usage, profile, run_native,
)

PEER = Path(__file__).parent / 'fixtures' / 'grok_acp_peer.py'
SCHEMA = {'type': 'object', 'properties': {'ok': {'type': 'boolean', 'enum': [True]}},
          'required': ['ok'], 'additionalProperties': False}


def invoke(tmp_path, scenario='ok', timeout=5):
    log = tmp_path / 'peer.jsonl'
    client = SinglePromptACP([sys.executable, str(PEER), scenario, str(log)],
        cwd=tmp_path, env=dict(os.environ), private_dir=tmp_path / 'private',
        reservation=tmp_path / 'reserved.json', frozen_files={str(PEER): digest(PEER.read_bytes())},
        timeout=timeout)
    result = client.invoke('PRIVATE PROMPT REFERENCE KEY', SCHEMA)
    requests = [json.loads(line) for line in log.read_text().splitlines()]
    return client, result, requests


def test_native_acp_binding_and_preflight_order(tmp_path):
    client, result, requests = invoke(tmp_path)
    receipt = result.receipt.data()
    assert receipt['accepted'], receipt
    assert result.response.data() == {'ok': True}
    assert [r['method'] for r in requests] == ['initialize', 'session/new', '_x.ai/billing',
        '_x.ai/auto-topup-rule', 'session/prompt', '_x.ai/billing', '_x.ai/auto-topup-rule']
    assert requests[1]['params']['_meta']['agentProfile'] == profile()
    assert requests[4]['params']['sessionId'] == receipt['session_id']
    assert requests[4]['params']['_meta']['promptId'] == receipt['prompt_id']
    assert receipt['known_usage']['totalTokens'] == 12
    assert receipt['settled_additional_charge_usd'] is None
    assert receipt['billing_before']['remaining_percentage'] is None
    assert 'PRIVATE' not in result.receipt.encoded
    assert b'PRIVATE REASONING' in (tmp_path / 'private' / 'stdout.private.jsonl').read_bytes()
    assert b'PRIVATE PROMPT' in (tmp_path / 'private' / 'requests.private.jsonl').read_bytes()
    assert (tmp_path / 'reserved.json').exists()
    with pytest.raises(Rejected, match='single_invoke_only'):
        client.invoke('retry', SCHEMA)


@pytest.mark.parametrize('scenario,fault', [
    ('tools', 'runtime_tools_not_empty'), ('paid', 'paid_fallback_available'),
    ('bool_money', 'billing_money_shape'), ('topup', 'auto_topup_present_or_unknown'),
    ('topup_error', 'rpc_error'), ('malformed', 'malformed_json'),
    ('unknown', 'unknown_notification'), ('new_binding', 'session_binding'),
    ('model', 'selected_model_mismatch')])
def test_gate_rejection_cannot_dispatch(tmp_path, scenario, fault):
    _, result, requests = invoke(tmp_path, scenario)
    receipt = result.receipt.data()
    assert not receipt['accepted'] and fault in receipt['faults']
    assert not receipt['prompt_may_have_been_dispatched']
    assert all(r['method'] != 'session/prompt' for r in requests)
    assert not (tmp_path / 'reserved.json').exists()


@pytest.mark.parametrize('scenario,fault', [
    ('prompt_binding', 'result_binding'), ('result_session', 'result_binding'),
    ('extra_work', 'result_extra_work_or_failure'), ('schema', 'structured_text_disagreement'),
    ('multi_call', 'usage_incomplete_or_extra_calls'), ('incomplete', 'usage_incomplete_or_extra_calls'),
    ('tokens', 'observed_token_limit'), ('post_paid', 'paid_fallback_available'),
    ('tool_event', 'tool_activity'), ('server_request', 'server_request_disallowed')])
def test_dispatched_failure_is_terminal(tmp_path, scenario, fault):
    _, result, requests = invoke(tmp_path, scenario)
    receipt = result.receipt.data()
    assert not receipt['accepted'] and fault in receipt['faults'], receipt
    assert receipt['prompt_may_have_been_dispatched']
    assert sum(r['method'] == 'session/prompt' for r in requests) == 1
    assert result.response is None and (tmp_path / 'reserved.json').exists()
    if scenario not in ('tool_event', 'server_request'):
        assert receipt['known_usage'] is not None
    assert 'PRIVATE' not in result.receipt.encoded


@pytest.mark.parametrize('scenario', ['unknown_cost', 'partial'])
def test_unknown_cost_not_invented(tmp_path, scenario):
    _, result, _ = invoke(tmp_path, scenario)
    receipt = result.receipt.data()
    assert receipt['accepted']
    assert receipt['known_usage']['totalTokens'] == 12
    assert receipt['reported_cost_usd'] is None
    assert receipt['reported_cost_complete'] is False


@pytest.mark.parametrize('scenario,dispatched', [('pre_timeout', False), ('timeout', True)])
def test_timeout_kills_subprocess_tree_without_retry(tmp_path, scenario, dispatched):
    start = time.monotonic()
    _, result, requests = invoke(tmp_path, scenario, timeout=1.5)
    assert time.monotonic() - start < 8
    receipt = result.receipt.data()
    assert receipt['faults'] == ['timeout']
    assert receipt['prompt_may_have_been_dispatched'] is dispatched
    pid = int((tmp_path / 'peer.jsonl.child').read_text())
    if os.name == 'nt':
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(handle)
            assert code.value != 259
    else:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            pass
        else:
            assert Path(f'/proc/{pid}/stat').read_text().split()[2] == 'Z'
    assert sum(r['method'] == 'session/prompt' for r in requests) == int(dispatched)


def test_existing_reservation_blocks_new_peer(tmp_path):
    (tmp_path / 'reserved.json').write_text('previous attempt')
    client = SinglePromptACP([sys.executable, str(PEER), 'ok', str(tmp_path / 'log')],
        cwd=tmp_path, env=dict(os.environ), private_dir=tmp_path / 'private',
        reservation=tmp_path / 'reserved.json', frozen_files={str(PEER): digest(PEER.read_bytes())})
    result = client.invoke('private', SCHEMA)
    assert result.receipt.data()['faults'] == ['reservation_already_exists']
    assert not (tmp_path / 'log').exists()


def test_frozen_file_change_blocks_process(tmp_path):
    client = SinglePromptACP(['must-not-exist'], cwd=tmp_path, env={},
        private_dir=tmp_path / 'private', reservation=tmp_path / 'reserved.json',
        frozen_files={str(PEER): 'wrong'})
    assert client.invoke('private', SCHEMA).receipt.data()['faults'] == ['frozen_file_changed']


def test_billing_zero_is_typed_and_current():
    now = datetime.now(timezone.utc)
    b = {'subscription_tier': 'SuperGrok', 'config': {'isUnifiedBillingUser': True,
        'onDemandCap': {'val': 0}, 'onDemandUsed': {'val': 0}, 'prepaidBalance': {'val': 0},
        'currentPeriod': {'start': (now - timedelta(hours=1)).isoformat(),
                          'end': (now + timedelta(hours=1)).isoformat()}}}
    assert billing_gate(b, {})['remaining_percentage'] is None
    with pytest.raises(Rejected, match='billing_period_stale'):
        billing_gate(b, {}, now + timedelta(days=1))
    for field in ('onDemandCap', 'onDemandUsed', 'prepaidBalance'):
        modified = copy.deepcopy(b); modified['config'].pop(field)
        with pytest.raises(Rejected, match='billing_money_shape'):
            billing_gate(modified, {})


def test_acp_input_includes_cache_and_reasoning_is_subset():
    base = {'inputTokens': 10, 'outputTokens': 2, 'totalTokens': 12,
        'cachedReadTokens': 2, 'cacheCreationTokens': 3, 'reasoningTokens': 1,
        'modelCalls': 1, 'apiDurationMs': 1}
    assert known_usage(base)['totalTokens'] == 12
    for changed in ({'reasoningTokens': 3}, {'cachedReadTokens': 11}, {'inputTokens': True}):
        assert known_usage({**base, **changed}) is None


def test_native_entry_point_blocks_unbounded_initial_title_before_start(monkeypatch):
    import research_loop.modular.grok_acp_transport as transport
    def forbidden(*args, **kwargs):
        pytest.fail('native process must not start without initial-title contract')
    monkeypatch.setattr(transport.subprocess, 'Popen', forbidden)
    with pytest.raises(Rejected, match='initial_title_suppression_unverified'):
        run_native(prompt='synthetic')
