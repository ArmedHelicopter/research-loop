"""Current producer/reader contract using synthetic native/account processes."""
import pytest
import sys
import json
import hashlib
from datetime import timedelta
from pathlib import Path

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


def test_opt_in_postflight_account_read_retry_keeps_one_main_and_reader_binds_attempts(tmp_path, monkeypatch):
    entry, kwargs, spec, directory, calls, gets = prepared(tmp_path, monkeypatch)
    recovery={'schema':'headless-account-read-recovery-v1','max_attempts':2}
    kwargs['account_read_recovery']=recovery; spec['account_read_recovery']=recovery
    spec['native_context']=dict(spec['native_context'], account_read_recovery=recovery)
    original=transport.urllib.request.build_opener; count={'n':0}
    class FailOnce:
        def open(self, request, timeout):
            count['n'] += 1
            # preflight consumes three GETs; fail first postflight route once.
            if count['n'] == 4: raise transport.urllib.error.URLError('synthetic')
            return original().open(request, timeout)
    monkeypatch.setattr(transport.urllib.request, 'build_opener', lambda *args: FailOnce())
    result=transport.run_headless_diagnostic(**kwargs)
    binding=transport.verify_headless_request_binding(result, entry, directory, spec, kwargs['frozen_files']).data()
    assert result.receipt.data()['accepted'] and binding['accepted'] and len(calls)==1
    manifest=json.loads((directory/'native/billing-after/attempts.json').read_bytes())
    assert manifest['winning_attempt']==1 and len(manifest['attempts'])==2


def test_opt_in_account_policy_error_does_not_retry(tmp_path, monkeypatch):
    _, kwargs, _, directory, calls, _ = prepared(tmp_path, monkeypatch)
    kwargs['account_read_recovery']={'schema':'headless-account-read-recovery-v1','max_attempts':2}
    class Unauthorized:
        def open(self, request, timeout):
            raise transport.urllib.error.HTTPError(request.full_url, 401, 'x', None, None)
    monkeypatch.setattr(transport.urllib.request, 'build_opener', lambda *args: Unauthorized())
    result=transport.run_headless_diagnostic(**kwargs)
    assert not result.receipt.data()['accepted'] and not calls
    assert not (directory/'native/billing-before/attempt-001').exists()


def test_opt_in_reader_rejects_winner_or_partial_tamper(tmp_path, monkeypatch):
    entry, kwargs, spec, directory, _, _ = prepared(tmp_path, monkeypatch)
    recovery={'schema':'headless-account-read-recovery-v1','max_attempts':2}; kwargs['account_read_recovery']=recovery; spec['account_read_recovery']=recovery
    spec['native_context']=dict(spec['native_context'], account_read_recovery=recovery)
    result=transport.run_headless_diagnostic(**kwargs)
    attempts=directory/'native/billing-before/attempts.json'; body=json.loads(attempts.read_bytes()); body['winning_attempt']=1; transport._write(attempts,body)
    with pytest.raises(transport.ContractError): transport.verify_headless_request_binding(result,entry,directory,spec,kwargs['frozen_files'])


def test_opt_in_exhausts_two_transient_account_attempts_without_main(tmp_path, monkeypatch):
    _, kwargs, _, directory, calls, _ = prepared(tmp_path, monkeypatch)
    kwargs['account_read_recovery']={'schema':'headless-account-read-recovery-v1','max_attempts':2}
    class Down:
        def open(self, request, timeout): raise transport.urllib.error.URLError('synthetic')
    monkeypatch.setattr(transport.urllib.request, 'build_opener', lambda *args: Down())
    result=transport.run_headless_diagnostic(**kwargs)
    assert not result.receipt.data()['accepted'] and not calls
    attempts=json.loads((directory/'native/billing-before/attempts.json').read_bytes())
    assert [a['status'] for a in attempts['attempts']] == ['transient_failed','transient_failed']
    assert result.receipt.data()['account_preflight_attempts_sha256'] == hashlib.sha256((directory/'native/billing-before/attempts.json').read_bytes()).hexdigest()


def test_opt_in_reader_rejects_failed_partial_raw_tamper(tmp_path, monkeypatch):
    entry, kwargs, spec, directory, _, _ = prepared(tmp_path, monkeypatch)
    recovery={'schema':'headless-account-read-recovery-v1','max_attempts':2}; kwargs['account_read_recovery']=recovery; spec['account_read_recovery']=recovery
    spec['native_context']=dict(spec['native_context'],account_read_recovery=recovery)
    original=transport.urllib.request.build_opener; count={'n':0}
    class FailTopup:
        def open(self, request, timeout):
            count['n']+=1
            if count['n']==5: raise transport.urllib.error.URLError('synthetic')
            return original().open(request,timeout)
    monkeypatch.setattr(transport.urllib.request,'build_opener',lambda *args: FailTopup())
    result=transport.run_headless_diagnostic(**kwargs)
    (directory/'native/billing-after/attempt-000/credits.private.json').write_bytes(b'{}')
    with pytest.raises(transport.ContractError): transport.verify_headless_request_binding(result,entry,directory,spec,kwargs['frozen_files'])


def test_opt_in_reader_rejects_coherent_partial_raw_and_requests_rewrite(tmp_path, monkeypatch):
    entry, kwargs, spec, directory, _, _ = prepared(tmp_path, monkeypatch)
    recovery={'schema':'headless-account-read-recovery-v1','max_attempts':2}; kwargs['account_read_recovery']=recovery; spec['account_read_recovery']=recovery
    spec['native_context']=dict(spec['native_context'],account_read_recovery=recovery)
    original=transport.urllib.request.build_opener; count={'n':0}
    class FailTopup:
        def open(self, request, timeout):
            count['n']+=1
            if count['n']==5: raise transport.urllib.error.URLError('synthetic')
            return original().open(request,timeout)
    monkeypatch.setattr(transport.urllib.request,'build_opener',lambda *args: FailTopup())
    result=transport.run_headless_diagnostic(**kwargs); attempt=directory/'native/billing-after/attempt-000'
    raw=b'{}'; (attempt/'credits.private.json').write_bytes(raw); rows=json.loads((attempt/'requests.json').read_bytes()); rows[0].update(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw)); transport._write(attempt/'requests.json',rows)
    with pytest.raises(transport.ContractError): transport.verify_headless_request_binding(result,entry,directory,spec,kwargs['frozen_files'])


def _account_response(request, body, calls):
    calls.append(request.full_url)
    class Response:
        status=200
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def geturl(self): return request.full_url
        def read(self, maximum): return body
    return Response()


@pytest.mark.parametrize('kind', ['paid','malformed','period','percent'])
def test_recovered_account_received_credit_prefix_is_terminal_not_retried(tmp_path, monkeypatch, kind):
    _, kwargs, _, _, _, _ = prepared(tmp_path, monkeypatch)
    calls=[]; now=transport.datetime.now(transport.timezone.utc)
    config={'isUnifiedBillingUser':True,'onDemandCap':{},'onDemandUsed':{},'prepaidBalance':{},'on_demand_enabled':False,
            'creditUsagePercent':2,'currentPeriod':{'start':(now-timedelta(days=1)).isoformat(),'end':(now+timedelta(days=1)).isoformat()}}
    if kind=='paid': config['onDemandCap']={'val':1}
    if kind=='period': config['currentPeriod']['end']=(now-timedelta(seconds=1)).isoformat()
    if kind=='percent': config['creditUsagePercent']=100
    body=b'{' if kind=='malformed' else json.dumps({'config':config}).encode()
    class Opener:
        def open(self, request, timeout): return _account_response(request,body,calls)
    monkeypatch.setattr(transport.urllib.request,'build_opener',lambda *args: Opener())
    folder=tmp_path/'account'; recovery={'schema':'headless-account-read-recovery-v1','max_attempts':2}
    with pytest.raises(transport.ContractError): transport._account_recovered(Path(kwargs['private_home']),folder,recovery)
    manifest=json.loads((folder/'attempts.json').read_bytes())
    assert len(calls)==1 and manifest['attempts'][0]['status']=='terminal_failed'


@pytest.mark.parametrize('kind', ['identity','access'])
def test_recovered_account_received_user_prefix_is_terminal_not_retried(tmp_path, monkeypatch, kind):
    _, kwargs, _, _, _, _ = prepared(tmp_path, monkeypatch)
    calls=[]; now=transport.datetime.now(transport.timezone.utc)
    def body(url):
        if 'billing?format=credits' in url: return {'config':{'isUnifiedBillingUser':True,'onDemandCap':{},'onDemandUsed':{},'prepaidBalance':{},'on_demand_enabled':False,'creditUsagePercent':2,'currentPeriod':{'start':(now-timedelta(days=1)).isoformat(),'end':(now+timedelta(days=1)).isoformat()}}}
        if url.endswith('auto-topup-rule'): return {}
        return {'userId':'' if kind=='identity' else 'synthetic-account','hasGrokCodeAccess':False if kind=='access' else True,'userBlockedReason':None,'teamBlockedReasons':[]}
    class Opener:
        def open(self, request, timeout): return _account_response(request,json.dumps(body(request.full_url)).encode(),calls)
    monkeypatch.setattr(transport.urllib.request,'build_opener',lambda *args: Opener())
    folder=tmp_path/'account'; recovery={'schema':'headless-account-read-recovery-v1','max_attempts':2}
    with pytest.raises(transport.ContractError): transport._account_recovered(Path(kwargs['private_home']),folder,recovery)
    assert len(calls)==3 and json.loads((folder/'attempts.json').read_bytes())['attempts'][0]['status']=='terminal_failed'


def test_recovered_preflight_stale_snapshot_blocks_main_and_retains_attempt(tmp_path, monkeypatch):
    _, kwargs, _, directory, calls, _ = prepared(tmp_path, monkeypatch)
    recovery={'schema':'headless-account-read-recovery-v1','max_attempts':2}; kwargs['account_read_recovery']=recovery
    original=transport._account_recovered
    def stale(*args):
        result=original(*args); result['projection']=dict(result['projection'],oldest_observed_at=(transport.datetime.now(transport.timezone.utc)-timedelta(seconds=6)).isoformat()); return result
    monkeypatch.setattr(transport,'_account_recovered',stale)
    result=transport.run_headless_diagnostic(**kwargs)
    assert not result.receipt.data()['accepted'] and not calls and (directory/'native/billing-before/attempts.json').exists()


@pytest.mark.parametrize('value', [True, 2.0, 1, 3])
def test_opt_in_recovery_requires_exact_integer_bound(tmp_path, monkeypatch, value):
    _, kwargs, _, _, _, _ = prepared(tmp_path, monkeypatch)
    kwargs['account_read_recovery']={'schema':'headless-account-read-recovery-v1','max_attempts':value}
    with pytest.raises(transport.ContractError): transport.run_headless_diagnostic(**kwargs)


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
