"""Synthetic authoring -> signed materials -> complete private renderer inventory."""
import copy
import json
from pathlib import Path
import sys

import pytest

from evaluation.modular.calibration_pilot import verify
from evaluation.modular.calibration_pilot_process import load_record
from evaluation.modular.diagnostic_material_authoring import (
    LIMITS, REVIEW_LIMITS, compile_authoring, load_config, run_authoring, validate_authored,
)
from research_loop.modular.grok_acp_transport import AcpResult
from research_loop.ontology import ContractError
from tests.helpers.calibration_pilot_fixture import record, write
from tests.helpers.material_authoring_fixture import authored_answer, fixture_factory, prepare_fixture
from tests.helpers.subscription_worker import run_fixture_worker


def prepare(root, reference_bytes=0):
    descriptor = prepare_fixture(root, reference_bytes)
    metadata = compile_authoring(descriptor, root / 'freeze')
    return descriptor, metadata['envelope']


def test_worker_authoring_material_signatures_and_ready_renderer_inventory(tmp_path, monkeypatch):
    config, envelope = prepare(tmp_path)
    monkeypatch.delenv('PYTHONPATH', raising=False)
    checkout = Path(__file__).resolve().parents[1]
    worker = checkout / 'tests/helpers/material_authoring_worker.py'
    # Parent orchestration has its own 180s deadline, separate from each native
    # synthetic session's 10s and the real transport's unchanged 60s limit.
    proc = run_fixture_worker([sys.executable, str(worker), '--input', envelope['path'],
        '--sha256', envelope['sha256'], '--output', str(tmp_path / 'out')],
        stream_root=tmp_path, timeout=180)
    stdout, stderr = proc.stdout, proc.stderr
    assert proc.returncode == 0, stderr.decode()
    assert b'PRIVATE' not in stdout + stderr
    outcome = json.loads((tmp_path / 'out/public-outcome.json').read_text())
    assert outcome['material_availability'] == {'ready': 28, 'unresolved_material': 8, 'not_applicable': 0}
    assert outcome['slot_count'] == 36 and outcome['evaluator_opportunity_count'] == 72
    assert outcome['review_evaluator_main_allocation'] == 180
    assert not outcome['authoring_included_in_review_allocation']
    assert not outcome['source_or_compilation_fault']
    assert all(s['status'] == 'accepted_provisional_authoring' for s in outcome['authoring_outcomes'])
    assert all(s['known_main_usage']['totalTokens'] == 12 for s in outcome['authoring_outcomes'])
    assert outcome['title_usage'] is None and outcome['settled_additional_charge_usd'] is None
    _, authorities = load_config(config)
    materials = load_record(outcome['materials']).data()
    for sid, material in materials.items():
        body = verify(record(material), role='material', subject=sid,
            authority_id=authorities['material'].authority_id, key=authorities['material'].key)
        assert body['expected'] == {'state': 'unknown', 'dimensions': None}
        if body['candidate'] is not None:
            assert set(body['candidate']) == {'answer'}
    inventory = load_record(outcome['ready_review_inventory']).data()
    assert len(inventory['entries']) == 140  # 28 * (three review roles + two evaluators)
    logs = list((tmp_path / 'out').glob('*/peer.private.jsonl'))
    assert len(logs) == 4
    for log in logs:
        requests = [json.loads(line) for line in log.read_text().splitlines()]
        prompts = [r for r in requests if r['method'] == 'session/prompt']
        assert len(prompts) == 1
        assert 'PRIVATE_SYNTHETIC_REFERENCE_SENTINEL' in prompts[0]['params']['prompt'][0]['text']
    assert 'PRIVATE_SYNTHETIC' not in json.dumps(outcome)


@pytest.mark.parametrize('mode,usage', [('authoring_unknown_main', 12), ('paid', None), ('tools', None)])
def test_fault_preserves_four_states_and_denominators_without_retry(tmp_path, mode, usage, monkeypatch):
    _, envelope = prepare(tmp_path)
    monkeypatch.delenv('PYTHONPATH', raising=False)
    result = run_authoring(envelope, tmp_path / 'out', fixture_factory=fixture_factory(mode))
    assert result['further_authoring_io_blocked']
    assert result['material_availability']['unresolved_material'] == 36
    assert len(result['authoring_outcomes']) == 4 and result['evaluator_opportunity_count'] == 72
    first = result['authoring_outcomes'][0]
    assert (first['known_main_usage']['totalTokens'] if first['known_main_usage'] else None) == usage
    assert all(s['status'] == 'blocked_prior_authoring' for s in result['authoring_outcomes'][1:])
    with pytest.raises(FileExistsError):
        run_authoring(envelope, tmp_path / 'retry', fixture_factory=lambda *args: pytest.fail('retried'))


@pytest.mark.parametrize('mutation', ['answer', 'prompt', 'schema', 'reservation', 'source'])
def test_native_binding_swap_retains_main_accounting_and_stops(tmp_path, mutation):
    _, envelope = prepare(tmp_path)
    original = fixture_factory(); calls = []
    def swap(*args):
        native = original(*args); calls.append(native)
        entry, _, _, directory, _, _ = args
        if mutation == 'answer':
            response = native.response.data()
            response['slots'][1]['support']['rationale'] += ' Another coherent provisional rationale.'
            return AcpResult(native.receipt, record(response))
        if mutation in ('prompt', 'schema'):
            entry[mutation + ('_sha256' if mutation == 'prompt' else '_digest')] = '0' * 64
        elif mutation == 'reservation':
            (directory / 'native-reservation.json').write_text('{}')
        else:
            (tmp_path / 'synthetic-source.json').write_text('changed')
        return native
    result = run_authoring(envelope, tmp_path / 'out', fixture_factory=swap)
    assert len(calls) == 1 and result['further_authoring_io_blocked']
    assert result['authoring_outcomes'][0]['known_main_usage']['totalTokens'] == 12
    assert result['material_availability']['unresolved_material'] == 36


def test_late_entry_malformed_before_any_dispatch(tmp_path):
    _, desc = prepare(tmp_path)
    envelope = load_record(desc).data(); envelope['entries'][3]['prompt_sha256'] = '0' * 64
    changed = write(tmp_path / 'bad-envelope.json', envelope)
    with pytest.raises(ContractError, match='request inventory'):
        run_authoring(changed, tmp_path / 'out', fixture_factory=lambda *args: pytest.fail('dispatched'))
    assert not list(tmp_path.glob('**/native-reservation.json'))


def test_full_reference_in_all_four_requests_and_explicit_caps(tmp_path):
    _, desc = prepare(tmp_path, reference_bytes=173399)
    envelope = load_record(desc).data()
    assert envelope['limits'] == LIMITS and envelope['prospective_review_limits'] == REVIEW_LIMITS
    assert REVIEW_LIMITS['main_output_cap'] == 2048
    for entry in envelope['entries']:
        text = load_record(entry['private_request']).data()['prompt']
        assert 'X' * 173399 in text and entry['input_bytes'] == len(text.encode())
    with pytest.raises(ContractError, match='byte cap'):
        prepare(tmp_path / 'oversized', reference_bytes=262144)


def test_file_only_native_provision_freezes_all_slots_without_launch(tmp_path, monkeypatch):
    import evaluation.modular.diagnostic_material_authoring as module
    from evaluation.modular.diagnostic_subscription import sha
    source = tmp_path / 'source'; config = load_record(prepare_fixture(source)).data()
    executable = tmp_path / 'synthetic-executable'; executable.write_bytes(b'non-executable fixture')
    auth = tmp_path / 'synthetic-auth'; auth.write_bytes(b'PRIVATE_SYNTHETIC_AUTH_OPAQUE')
    monkeypatch.setattr(module, 'EXECUTABLE_SHA256', sha(executable))
    metadata = module.provision_native(config['publication'], config['export_result'], tmp_path / 'prepared',
        executable=executable, existing_auth=auth)
    assert metadata['native_deployment_frozen'] and metadata['real_generation_requests'] == 0
    envelope = load_record(metadata['envelope']).data()
    assert len(envelope['native_deployment']['slots']) == 4
    assert not any('auth.json' in key for key in envelope['frozen_files'])
    assert 'PRIVATE_SYNTHETIC_AUTH' not in json.dumps(metadata)
    last = list(envelope['native_deployment']['slots'].values())[-1]
    (Path(last['cwd']) / 'unfrozen-instruction.txt').write_text('synthetic changed context')
    with pytest.raises(ContractError, match='not fresh'):
        run_authoring(metadata['envelope'], tmp_path / 'out',
            fixture_factory=lambda *args: pytest.fail('launched with changed fourth context'))


def test_explicit_negative_support_still_remains_provisional():
    refs = [{'hypothesis': 'Explicit synthetic negative finding.'}]
    response = authored_answer(refs)
    row = response['slots'][1]
    row.update(status='ready', candidate={'answer': 'Explicit synthetic negative finding.'})
    row['support'] = copy.deepcopy(response['slots'][0]['support'])
    row['support']['negative_basis'] = 'explicit_supported_negative'
    assert validate_authored(response, refs)[1]['status'] == 'ready'
    assert 'expected' not in row  # Only the worker creates unknown expected targets.


@pytest.mark.parametrize('fault', ['order', 'empty', 'negative', 'alternative', 'excerpt', 'expected'])
def test_author_assertions_cannot_create_coverage_truth(fault):
    refs = [{'hypothesis': 'synthetic source'}]; answer = authored_answer(refs)
    if fault == 'order': answer['slots'].reverse()
    elif fault == 'empty': answer['slots'][8]['candidate']['answer'] = 'empty output'
    elif fault == 'negative':
        row = answer['slots'][1]; row.update(status='ready', candidate={'answer': 'not significant'})
        row['support'] = copy.deepcopy(answer['slots'][0]['support'])
        row['support']['negative_basis'] = 'nonsignificant_only'
    elif fault == 'alternative':
        row = answer['slots'][7]; row.update(status='ready', candidate={'answer': 'invented analysis'})
        row['support']['provenance'] = 'controlled_hypothetical'
    elif fault == 'excerpt': answer['slots'][0]['support']['evidence'][0]['excerpt'] = 'invented'
    else: answer['slots'][0]['expected'] = {'state': 'known'}
    with pytest.raises(ContractError): validate_authored(answer, refs)
