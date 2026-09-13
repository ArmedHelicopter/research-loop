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
    native_launch, SAFE_CONFIG,
)

PEER = Path(__file__).parent / 'fixtures' / 'grok_acp_peer.py'
SCHEMA = {'type': 'object', 'properties': {'ok': {'type': 'boolean', 'enum': [True]}},
          'required': ['ok'], 'additionalProperties': False}


def test_diagnostic_entry_uses_separate_explicit_caps_without_changing_smoke(tmp_path, monkeypatch):
    import research_loop.modular.grok_acp_transport as module
    configs = []
    def launch(**kwargs):
        configs.append(kwargs['expected_config'])
        return [sys.executable, str(PEER), 'ok', str(tmp_path / 'peer.jsonl')], dict(os.environ)
    monkeypatch.setattr(module, 'native_launch', launch)
    result = module.run_native_diagnostic(opportunity_contract=module.DIAGNOSTIC_OPPORTUNITY_CONTRACT,
        executable='synthetic', cwd=tmp_path, private_home=tmp_path / 'home',
        private_profile=tmp_path / 'profile', private_dir=tmp_path / 'private',
        reservation=tmp_path / 'reservation.json', frozen_files={str(PEER): digest(PEER.read_bytes())},
        prompt='synthetic prompt', schema=SCHEMA, main_output_cap=512,
        observed_main_token_cap=262144, input_byte_cap=200000)
    assert result.receipt.data()['accepted']
    assert result.receipt.data()['requested_max_completion_tokens'] == 512
    assert configs == [module.diagnostic_config(512)]
    assert module.SAFE_CONFIG.count('max_completion_tokens = 128') == 2
    assert configs[0].count('max_completion_tokens = 512') == 2


def test_native_nullable_diagnostic_dimensions_leave_legacy_schema_unchanged():
    from research_loop.modular.grok_acp_transport import validate_acp_schema
    from research_loop.modular.model_port import _validate_schema
    from research_loop.ontology import ContractError
    schema = {'type': 'object', 'properties': {'dimensions': {'type': ['object', 'null'],
        'properties': {'value': {'type': 'number', 'minimum': 0, 'maximum': 1}},
        'required': ['value'], 'additionalProperties': False}},
        'required': ['dimensions'], 'additionalProperties': False}
    validate_acp_schema(schema, {'dimensions': None})
    validate_acp_schema(schema, {'dimensions': {'value': .5}})
    with pytest.raises(ContractError): _validate_schema(schema, {'dimensions': None})
    with pytest.raises(ContractError): validate_acp_schema(schema, {'dimensions': {'value': 2}})


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


def test_native_entry_point_requires_explicit_revised_contract(monkeypatch):
    import research_loop.modular.grok_acp_transport as transport
    def forbidden(*args, **kwargs):
        pytest.fail('native process must not start without initial-title contract')
    monkeypatch.setattr(transport.subprocess, 'Popen', forbidden)
    with pytest.raises(Rejected, match='opportunity_contract_unapproved'):
        run_native(opportunity_contract='one-total-model-call', executable='', cwd='',
            private_home='', private_profile='', private_dir='', reservation='',
            frozen_files={}, prompt='synthetic', schema=SCHEMA)


def test_receipt_cannot_claim_main_usage_is_total(tmp_path):
    _, result, _ = invoke(tmp_path)
    r = result.receipt.data()
    assert r['known_usage']['modelCalls'] == 1
    assert r['max_initial_title_opportunities'] == 1
    assert r['requested_initial_title_output_cap'] == 100
    assert r['initial_title_internal_function'] == 'session_title'
    for key in ('initial_title_usage', 'initial_title_cost_usd', 'total_model_call_count',
                'total_tokens_all_opportunities', 'total_cost_usd_all_opportunities'):
        assert r[key] is None


def test_native_startup_pins_config_and_excludes_api_environment(tmp_path, monkeypatch):
    import research_loop.modular.grok_acp_transport as transport
    exe = tmp_path / 'fake-grok.exe'; exe.write_bytes(b'fixture only')
    home = tmp_path / 'home'; home.mkdir()
    user = tmp_path / 'user'; user.mkdir()
    cwd = tmp_path / 'cwd'; cwd.mkdir()
    config = home / 'config.toml'; config.write_text(SAFE_CONFIG)
    (home / 'auth.json').write_text('{}')  # Synthetic; no actual login involved.
    monkeypatch.setattr(transport, 'EXECUTABLE_SHA256', digest(exe.read_bytes()))
    monkeypatch.setenv('XAI_API_KEY', 'fixture-must-not-propagate')
    monkeypatch.setenv('GROK_CONFIG', 'fixture-must-not-propagate')
    files = {str(exe): digest(exe.read_bytes()), str(config): digest(config.read_bytes())}
    cmd, env = native_launch(executable=exe, cwd=cwd, private_home=home,
        private_profile=user, frozen_files=files)
    assert cmd[-2:] == ['agent', 'stdio']
    assert 'XAI_API_KEY' not in env and 'GROK_CONFIG' not in env
    assert env['GROK_HOME'] == str(home)
    assert env['GROK_TURN_SUMMARY'] == 'false'
    assert 'session_summary = "grok-4.6"' in SAFE_CONFIG
    assert 'max_retries = 0' in SAFE_CONFIG


def test_bound_native_queue_display_does_not_expose_prompt_or_add_dispatch(tmp_path):
    _, result, requests = invoke(tmp_path, 'queue')
    assert result.receipt.data()['accepted'], result.receipt.data()
    assert result.receipt.data()['event_counts']['queue_changed'] == 2
    assert sum(r['method'] == 'session/prompt' for r in requests) == 1
    assert 'PRIVATE PROMPT DISPLAY' not in result.receipt.encoded


@pytest.mark.parametrize('scenario,fault', [('queue_wrong', 'queue_prompt_binding'),
    ('queue_extra', 'extra_queued_work'), ('queue_unknown', 'unknown_queue_field')])
def test_queue_repair_still_rejects_other_work(tmp_path, scenario, fault):
    _, result, requests = invoke(tmp_path, scenario)
    assert fault in result.receipt.data()['faults']
    assert sum(r['method'] == 'session/prompt' for r in requests) == 1
    assert result.response is None


def test_optional_intermediate_stop_requires_bound_terminal_success(tmp_path):
    _, result, _ = invoke(tmp_path, 'optional_stop')
    assert result.receipt.data()['accepted'], result.receipt.data()
    assert result.receipt.data()['known_response_usage'][0]['output_tokens'] == 2


def test_missing_intermediate_stop_does_not_allow_bad_terminal(tmp_path):
    _, result, _ = invoke(tmp_path, 'optional_stop_bad_terminal')
    assert not result.receipt.data()['accepted']
    assert 'result_stop_or_model' in result.receipt.data()['faults']
    assert result.receipt.data()['known_response_usage'][0]['output_tokens'] == 2


@pytest.mark.parametrize('scenario', ['optional_usage', 'prompt_complete'])
def test_source_optional_metadata_and_terminal_notification(tmp_path, scenario):
    _, result, _ = invoke(tmp_path, scenario)
    assert result.receipt.data()['accepted'], result.receipt.data()
    assert result.receipt.data()['known_usage']['totalTokens'] == 12


@pytest.mark.parametrize('scenario,fault', [('prompt_complete_wrong', 'prompt_complete_binding'),
                                         ('context_count', 'terminal_context_count_shape')])
def test_source_optional_review_keeps_binding_and_types(tmp_path, scenario, fault):
    _, result, _ = invoke(tmp_path, scenario)
    assert fault in result.receipt.data()['faults']


def test_rejected_rpc_retains_already_received_partial_usage(tmp_path):
    _, result, requests = invoke(tmp_path, 'rpc_error_usage')
    r = result.receipt.data()
    assert r['faults'] == ['rpc_error']
    assert r['known_usage']['totalTokens'] == 12
    assert r['known_usage']['usageIsIncomplete'] is True
    assert r['known_usage_binding_verified'] is False
    assert r['reported_cost_usd'] is None
    assert r['known_response_usage'][0]['output_tokens'] == 2
    assert sum(x['method'] == 'session/prompt' for x in requests) == 1
