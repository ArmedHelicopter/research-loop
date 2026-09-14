"""Versioned authoring bindings use synthetic TRAIN sources and no real login."""
import json
from pathlib import Path

import pytest

import evaluation.modular.diagnostic_material_authoring as authoring
from evaluation.modular.calibration_pilot_process import load_record
from evaluation.modular.calibration_pilot import verify
from evaluation.modular.diagnostic_subscription import sha
from research_loop.ontology import ContractError
from tests.helpers.calibration_pilot_fixture import write
from tests.helpers.material_authoring_fixture import prepare_fixture


def prepare_headless(root, monkeypatch, reference_bytes=0):
    source = load_record(prepare_fixture(root / 'source', reference_bytes)).data()
    executable = root / 'synthetic-executable'; executable.write_bytes(b'synthetic executable, never launched')
    auth = root / 'synthetic-auth'; auth.write_bytes(b'PRIVATE_SYNTHETIC_AUTH_OPAQUE')
    monkeypatch.setattr(authoring, 'EXECUTABLE_SHA256', sha(executable))
    return authoring.provision_native(source['publication'], source['export_result'], root / 'prepared',
        executable=executable, existing_auth=auth, transport='headless')


def test_headless_freeze_has_distinct_schema_complete_inputs_and_runtime_pins(tmp_path, monkeypatch):
    metadata = prepare_headless(tmp_path, monkeypatch, reference_bytes=173399)
    envelope = load_record(metadata['envelope']).data()
    assert metadata['schema'] == 'four-task-authoring-freeze-metadata-v3'
    assert envelope['schema'] == authoring.SCHEMA_V3
    assert envelope['native_deployment']['schema'] == 'four-task-native-authoring-deployment-v3'
    assert 'native' not in envelope['native_deployment']
    assert envelope['limits'] == authoring.HEADLESS_LIMITS
    assert envelope['limits']['timeout_seconds'] == 240 and authoring.LIMITS['timeout_seconds'] == 60
    assert envelope['limits']['reasoning_effort'] == 'low'
    assert envelope['prospective_review_limits'] == authoring.REVIEW_LIMITS
    assert envelope['separate_review_evaluator_main_allocation'] == 180
    assert envelope['validation_eligible'] is False
    for entry in envelope['entries']:
        request = load_record(entry['private_request']).data()
        assert 'X' * 173399 in request['prompt']
        assert entry['input_bytes'] == len(request['prompt'].encode())
    for name in ('headless_transport_code', 'headless_stream_protocol_code'):
        path = authoring.own_sources()[name]
        assert envelope['frozen_files'][str(path)] == sha(path)
    assert not any('auth.json' in path for path in envelope['frozen_files'])
    assert 'PRIVATE_SYNTHETIC_AUTH' not in json.dumps(metadata)


@pytest.mark.parametrize('mutation', ['last_request', 'last_context', 'limits', 'schema', 'deployment'])
def test_all_headless_entries_preflight_before_any_dispatch(tmp_path, monkeypatch, mutation):
    metadata = prepare_headless(tmp_path, monkeypatch)
    desc = metadata['envelope']; envelope = load_record(desc).data()
    if mutation == 'last_request':
        envelope['entries'][3]['prompt_sha256'] = '0' * 64
    elif mutation == 'last_context':
        slot = list(envelope['native_deployment']['slots'].values())[-1]
        (Path(slot['cwd']) / 'unfrozen.md').write_text('unexpected context')
    elif mutation == 'limits':
        envelope['limits']['timeout_seconds'] = 60
    elif mutation == 'schema':
        envelope['schema'] = authoring.SCHEMA_V2
    else:
        envelope['native_deployment']['schema'] = 'four-task-native-authoring-deployment-v1'
    changed = write(tmp_path / 'changed-envelope.json', envelope)
    with pytest.raises(ContractError):
        authoring.run_authoring(changed, tmp_path / 'out',
            fixture_factory=lambda *args: pytest.fail('invalid frozen envelope dispatched'))
    assert not list(tmp_path.glob('**/native-reservation.json'))


def test_headless_requires_explicit_deployment_and_no_acp_native_record(tmp_path, monkeypatch):
    metadata = prepare_headless(tmp_path, monkeypatch)
    envelope = load_record(metadata['envelope']).data()
    config = load_record(envelope['config_descriptor']).data()
    config['native_deployment'] = None
    changed = write(tmp_path / 'missing-deployment.json', config)
    with pytest.raises(ContractError, match='exact native deployment'):
        authoring.compile_authoring(changed, tmp_path / 'missing-freeze')
    with pytest.raises(ContractError, match='transport or deployment'):
        authoring.provision_native(config['publication'], config['export_result'], tmp_path / 'invalid',
            executable=tmp_path / 'unused', existing_auth=tmp_path / 'unused-auth',
            transport='headless', deployment=object())


def test_actual_headless_authoring_dispatch_to_signed_material_and_review_inventory(tmp_path, monkeypatch):
    from tests.helpers.headless_authoring_fixture import install_synthetic_native
    from evaluation.modular.diagnostic_subscription import record
    metadata = prepare_headless(tmp_path, monkeypatch)
    envelope = load_record(metadata['envelope']).data()
    calls, gets = install_synthetic_native(monkeypatch, envelope)
    monkeypatch.setattr(authoring, 'verify_native_request_binding',
        lambda *a, **k: pytest.fail('headless result was routed through ACP verifier'))
    result = authoring.run_authoring(metadata['envelope'], tmp_path / 'out')
    assert len(calls) == 4 and len(gets) == 24
    assert all(command[command.index('--reasoning-effort') + 1] == 'low' for command in calls)
    assert result['schema'] == 'four-task-private-authoring-outcome-v3'
    assert result['material_availability'] == {'ready': 28, 'unresolved_material': 8, 'not_applicable': 0}
    assert result['slot_count'] == 36 and result['evaluator_opportunity_count'] == 72
    assert result['review_evaluator_main_allocation'] == 180
    assert not result['source_or_compilation_fault'] and not result['review_dispatch_blocked']
    for state in result['authoring_outcomes']:
        assert state['status'] == 'accepted_provisional_authoring'
        assert state['known_headless_main_usage']['total_tokens'] == 10
        assert state['known_main_usage'] is None and state['known_response_usage'] == []
        assert state['native_prompt_may_have_been_dispatched'] is True
        assert state['headless_request_binding_digest']
        assert state['title_usage'] is None and state['all_opportunity_tokens'] is None
        assert state['settled_additional_charge_usd'] is None
    _, authorities = authoring.load_config(envelope['config_descriptor'])
    for sid, signed in load_record(result['materials']).data().items():
        body = verify(record(signed), role='material', subject=sid,
            authority_id=authorities['material'].authority_id, key=authorities['material'].key)
        assert body['expected'] == {'state': 'unknown', 'dimensions': None}
    assert len(load_record(result['ready_review_inventory']).data()['entries']) == 140
    assert 'PRIVATE_SYNTHETIC' not in json.dumps(result)


@pytest.mark.parametrize('mutation', ['response', 'stream', 'private_request'])
def test_headless_mismatch_retains_observed_usage_and_unexecuted_denominators(tmp_path, monkeypatch, mutation):
    import research_loop.modular.grok_headless_transport as transport
    from tests.helpers.headless_authoring_fixture import install_synthetic_native
    from evaluation.modular.diagnostic_subscription import record
    metadata = prepare_headless(tmp_path, monkeypatch)
    envelope = load_record(metadata['envelope']).data()
    calls, gets = install_synthetic_native(monkeypatch, envelope)
    invoke = transport.run_headless_diagnostic
    def changed(**kwargs):
        native = invoke(**kwargs)
        assert native.receipt.data()['accepted'], native.receipt.data()['faults']
        if mutation == 'response':
            response = native.response.data()
            response['slots'][0]['support']['rationale'] += ' substituted'
            return transport.HeadlessResult(native.receipt, record(response))
        if mutation == 'stream':
            (Path(kwargs['private_dir']) / 'stdout.private.jsonl').write_text('tampered')
        else:
            Path(envelope['entries'][0]['private_request']['path']).write_text('tampered')
        return native
    monkeypatch.setattr(transport, 'run_headless_diagnostic', changed)
    result = authoring.run_authoring(metadata['envelope'], tmp_path / 'out')
    assert len(calls) == 1 and len(gets) == 6
    assert result['further_authoring_io_blocked'] and result['review_dispatch_blocked']
    assert result['material_availability']['unresolved_material'] == 36
    assert result['evaluator_opportunity_count'] == 72
    first, *rest = result['authoring_outcomes']
    assert first['status'] == 'rejected_authoring'
    assert first['known_headless_main_usage']['total_tokens'] == 10
    assert first['known_main_usage'] is None
    assert first['native_prompt_may_have_been_dispatched'] is True
    assert all(row['status'] == 'blocked_prior_authoring' and row['known_headless_main_usage'] is None
        and row['native_prompt_may_have_been_dispatched'] is False for row in rest)
    reservation = Path(metadata['envelope']['path']).with_suffix('.run-reservation.json')
    reserved = reservation.read_bytes()
    with pytest.raises((FileExistsError, ContractError)):
        authoring.run_authoring(metadata['envelope'], tmp_path / 'retry')
    assert reservation.read_bytes() == reserved and len(calls) == 1 and len(gets) == 6
