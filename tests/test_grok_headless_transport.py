"""Current producer/reader contract using synthetic native/account processes."""
import pytest
import sys
import json
import hashlib
from datetime import timedelta

import research_loop.modular.grok_headless_transport as transport
from evaluation.modular.calibration_pilot_process import load_record
from tests.helpers.headless_authoring_fixture import install_synthetic_native
from tests.test_headless_material_authoring import prepare_headless


def prepared(tmp_path, monkeypatch):
    metadata = prepare_headless(tmp_path, monkeypatch)
    envelope = load_record(metadata['envelope']).data(); entry = envelope['entries'][0]
    calls, gets = install_synthetic_native(monkeypatch, envelope)
    slot = envelope['native_deployment']['slots'][entry['opportunity_id']]
    request = load_record(entry['private_request']).data(); directory = tmp_path/'run'
    context = slot | {'executable': envelope['native_deployment']['executable']}
    kwargs = dict(executable=context['executable'], cwd=context['cwd'], private_home=context['private_home'], private_profile=context['private_profile'], private_dir=directory/'native', reservation=directory/'native-reservation.json', frozen_files=envelope['frozen_files'], prompt=request['prompt'], schema=request['output_schema'], main_output_cap=8192, observed_main_token_cap=131072, input_byte_cap=262144, timeout=240)
    spec = {'main_output_cap':8192, 'observed_main_token_cap':131072, 'max_input_bytes':262144, 'timeout_seconds':240, 'native_context':context}
    return entry, kwargs, spec, directory, calls, gets


def test_actual_producer_reader_and_unknown_totals(tmp_path, monkeypatch):
    entry, kwargs, spec, directory, calls, gets = prepared(tmp_path, monkeypatch)
    result = transport.run_headless_diagnostic(**kwargs)
    binding = transport.verify_headless_request_binding(result, entry, directory, spec, kwargs['frozen_files']).data()
    assert binding['accepted'] and binding['usage']['main']['total_tokens'] == 10
    assert binding['usage']['initial_title'] is None and binding['usage']['all_opportunities'] is None
    assert len(calls) == 1 and len(gets) == 6


@pytest.mark.parametrize('path', ['command.json', 'process.json', 'billing-after/credits.private.json'])
def test_reader_rejects_artifact_swaps(tmp_path, monkeypatch, path):
    entry, kwargs, spec, directory, _, _ = prepared(tmp_path, monkeypatch)
    result = transport.run_headless_diagnostic(**kwargs)
    (directory/'native'/path).write_text('{}', encoding='utf-8')
    with pytest.raises(transport.ContractError): transport.verify_headless_request_binding(result, entry, directory, spec, kwargs['frozen_files'])


def test_context_binding_rejects_swap(tmp_path, monkeypatch):
    entry, kwargs, spec, directory, _, _ = prepared(tmp_path, monkeypatch)
    result = transport.run_headless_diagnostic(**kwargs)
    spec['native_context'] = dict(spec['native_context'], cwd=str(tmp_path/'foreign'))
    with pytest.raises(transport.ContractError): transport.verify_headless_request_binding(result, entry, directory, spec, kwargs['frozen_files'])


def test_reasoning_effort_is_frozen_in_command_reservation_and_reader(tmp_path, monkeypatch):
    entry, kwargs, spec, directory, calls, _ = prepared(tmp_path, monkeypatch)
    kwargs['reasoning_effort'] = 'low'; spec['reasoning_effort'] = 'low'
    spec['native_context'] = dict(spec['native_context'], reasoning_effort='low')
    result = transport.run_headless_diagnostic(**kwargs)
    assert calls[0][calls[0].index('--reasoning-effort') + 1] == 'low'
    binding = transport.verify_headless_request_binding(result, entry, directory, spec, kwargs['frozen_files']).data()
    assert binding['identity']['requested_reasoning_effort'] == 'low'
    spec['reasoning_effort'] = 'high'
    spec['native_context']['reasoning_effort'] = 'high'
    with pytest.raises(transport.ContractError, match='reasoning effort'):
        transport.verify_headless_request_binding(result, entry, directory, spec, kwargs['frozen_files'])


def test_reasoning_effort_rejects_values_outside_frozen_model_contract(tmp_path, monkeypatch):
    _, kwargs, _, _, _, _ = prepared(tmp_path, monkeypatch)
    kwargs['reasoning_effort'] = 'maximum'
    with pytest.raises(transport.ContractError):
        transport.run_headless_diagnostic(**kwargs)


def test_preflight_denial_has_terminal_no_dispatch_receipt(tmp_path, monkeypatch):
    entry, kwargs, spec, directory, calls, _ = prepared(tmp_path, monkeypatch)
    monkeypatch.setattr(transport, '_account', lambda *args: (_ for _ in ()).throw(transport.ContractError('denied')))
    result = transport.run_headless_diagnostic(**kwargs)
    assert not result.receipt.data()['accepted'] and not result.receipt.data()['prompt_process_launched'] and not calls


def test_postflight_failure_preserves_observed_stream(tmp_path, monkeypatch):
    entry, kwargs, spec, directory, calls, _ = prepared(tmp_path, monkeypatch)
    original, count = transport._account, {'n': 0}
    def fail_after(*args):
        count['n'] += 1
        if count['n'] == 2: raise transport.ContractError('post failure')
        return original(*args)
    monkeypatch.setattr(transport, '_account', fail_after)
    result = transport.run_headless_diagnostic(**kwargs)
    assert not result.receipt.data()['accepted'] and result.receipt.data()['stream_inspection']['usage']['total_tokens'] == 10 and len(calls) == 1


def test_short_timeout_closes_owned_process_tree(tmp_path):
    raw, process = transport._child([sys.executable, '-c', 'import time; time.sleep(5)'],
        {'cwd': str(tmp_path)}, {}, tmp_path/'timeout', 0.05)
    assert process['timed_out'] and process['owned_tree_closed'] and process['process_exit_code'] is not None


def test_constructor_failure_does_not_claim_no_launch(tmp_path, monkeypatch):
    def failed(*args, **kwargs): raise OSError('synthetic constructor failure')
    monkeypatch.setattr(transport, 'ProcessTree', failed)
    _, process = transport._child(['synthetic'], {'cwd':str(tmp_path)}, {}, tmp_path/'failed', 1)
    assert process['launched'] is None and process['process_exit_code'] is None
    assert process['owned_tree_closed'] is None
    assert process['failure'] == 'process_launch_or_io_failed'


@pytest.mark.parametrize('change', ['command', 'environment', 'source_manifest'])
def test_rehashed_reservation_cannot_change_frozen_execution_contract(tmp_path, monkeypatch, change):
    entry, kwargs, spec, directory, _, _ = prepared(tmp_path, monkeypatch)
    result = transport.run_headless_diagnostic(**kwargs)
    path = directory/'native-reservation.json'; bound = json.loads(path.read_bytes())
    receipt = result.receipt.data()
    if change == 'command':
        bound['command'].remove('--no-subagents')
        transport._write(directory/'native/command.json', bound['command'])
    elif change == 'environment':
        bound['environment']['GROK_DISABLE_API_KEY_AUTH'] = '0'
    else:
        bound['frozen_files'] = {}
    transport._write(path, bound)
    receipt['reservation_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    transport._write(directory/'native/observer-receipt.json', receipt)
    swapped = transport.HeadlessResult(transport.FrozenRecord.from_dict(receipt), result.response)
    with pytest.raises(transport.ContractError):
        transport.verify_headless_request_binding(swapped, entry, directory, spec, kwargs['frozen_files'])


def test_raw_account_gate_rejects_paid_blocked_and_unordered_observations(tmp_path, monkeypatch):
    entry, kwargs, spec, directory, _, _ = prepared(tmp_path, monkeypatch)
    transport.run_headless_diagnostic(**kwargs)
    folder = directory/'native/billing-before'
    rows = json.loads((folder/'requests.json').read_bytes())
    original = {name:(folder/(name+'.private.json')).read_bytes() for name, _ in transport.ACCOUNT_ROUTES}
    observed = json.loads((folder/'observation.json').read_bytes())['observed_at']
    for change in ('paid', 'topup', 'blocked', 'no_balance', 'naive_time', 'unordered'):
        raws = dict(original); records = json.loads(json.dumps(rows)); when = observed
        if change in ('paid', 'no_balance'):
            credits = json.loads(raws['credits'])
            if change == 'paid': credits['config']['onDemandCap'] = {'val':1}
            else: credits['config']['creditUsagePercent'] = 100
            raws['credits'] = transport._canon(credits)
        elif change == 'topup': raws['topup'] = b'{"rule":{"enabled":true}}'
        elif change == 'blocked':
            user = json.loads(raws['user']); user['hasGrokCodeAccess'] = False
            raws['user'] = transport._canon(user)
        elif change == 'naive_time': when = transport._instant(when).replace(tzinfo=None).isoformat()
        else:
            records[1]['started_at'] = (transport._instant(records[0]['started_at'])-timedelta(seconds=1)).isoformat()
        for row in records:
            row.update(sha256=hashlib.sha256(raws[row['name']]).hexdigest(), bytes=len(raws[row['name']]))
        with pytest.raises(transport.ContractError): transport._project_account(raws, records, when)
