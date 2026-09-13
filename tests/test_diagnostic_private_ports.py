"""Real local HTTP transport, synthetic private references only."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import pytest

from evaluation.modular.diagnostic_private_ports import (
    PrivateRequestRenderer, FrozenHTTPDeployment, PrivateHTTPPorts,
    context_digest, API_SCHEMA,
)
from evaluation.modular.calibration_pilot import blind_request, ROLES, PortBudget, PrivateJournal, PilotTransportError, verify
from evaluation.modular.calibration_pilot_process import run_config, launch_once
from evaluation.modular.reference_store import FrozenTrainReferenceResolver, _read_bound
from research_loop.ontology import ContractError, digest
from tests.helpers.calibration_pilot_fixture import build_fixture, record, write, hash_file
from tests.helpers.private_http_fixture import LocalProvider


def setup_renderer(tmp_path):
    manifest, materials, authorities, config = build_fixture(tmp_path)
    store = config.data()['reference_store']
    resolver = FrozenTrainReferenceResolver(Path(store['root']), manifest_sha256=store['manifest_sha256'],
        inventory_digest=store['inventory_digest'], split_digest=store['split_digest'])
    return PrivateRequestRenderer(manifest, resolver), manifest, materials, authorities, config


def test_renderer_resolves_train_reference_and_blinds_labels(tmp_path):
    renderer, manifest, materials, _, _ = setup_renderer(tmp_path)
    slot = manifest.data()['slots'][0]
    task = manifest.data()['tasks'][0]
    request = blind_request(manifest, slot, task, materials[slot['slot_id']]['body']['payload'])
    rendered = renderer.render('reviewer1', request)
    assert 'PRIVATE_SYNTHETIC_REFERENCE_SENTINEL' in rendered.encoded
    assert 'support_digest' not in rendered.encoded and '"expected"' not in rendered.encoded
    public = json.loads(rendered.data()['messages'][1]['content'])
    assert set(public) == {'task', 'reference', 'candidate', 'dimensions', 'rubric', 'normalization'}
    assert set(public['dimensions']) == {'cvars', 'transform', 'model'}


def test_foreign_handle_rejected_before_resolver_payload_read(tmp_path, monkeypatch):
    renderer, manifest, materials, _, _ = setup_renderer(tmp_path)
    slot = manifest.data()['slots'][0]; task = manifest.data()['tasks'][0]
    request = blind_request(manifest, slot, task, materials[slot['slot_id']]['body']['payload']).data()
    request['task_handle'] = 'f' * 64
    calls = []
    monkeypatch.setattr(FrozenTrainReferenceResolver, '__call__', lambda *args: calls.append(args))
    with pytest.raises(ContractError):
        renderer.render('reviewer1', record(request))
    assert calls == []


def setup_http(root, provider):
    manifest, materials, authorities, config = build_fixture(root)
    evidence = {name: write(root / (name + '-evidence.json'), {'scope': 'loopback_fixture',
        'contract': name, 'synthetic_only': True}) for name in ('api', 'model_context', 'tokenizer', 'pricing')}
    deployments = {}
    b = manifest.data(); c = config.data()
    for role in ROLES:
        spec = record({'schema': API_SCHEMA, 'scope': 'loopback_fixture', 'endpoint': provider.endpoint,
            'model': 'synthetic-' + role, 'context_window': 100000, 'completion_cap': 512,
            'tokenizer': {'algorithm': 'utf8_wire_bytes_upper_v1', 'provider_overhead_upper': 100},
            'pricing': {'currency': 'USD', 'billing_rule': 'flat_all_prompt_and_completion_tokens',
                'input_microusd_per_million': 1000000, 'output_microusd_per_million': 2000000,
                'per_request_microusd': 1}, 'evidence': evidence, 'timeout_seconds': 1,
            'max_response_bytes': 100000})
        deployments[role] = FrozenHTTPDeployment(spec)
        b['policy']['ports'][role].update({'model': spec.data()['model'], 'context_digest': context_digest(role),
            'tokenizer_digest': deployments[role].tokenizer_digest, 'pricing_digest': deployments[role].pricing_digest,
            'max_output_tokens': 512, 'max_microusd_per_call': 100000})
    b['policy']['max_microusd'] = 18000000
    manifest = record(b); c['manifest'] = write(root / 'manifest.json', b)
    config = record(c)
    store = c['reference_store']
    resolver = FrozenTrainReferenceResolver(Path(store['root']), manifest_sha256=store['manifest_sha256'],
        inventory_digest=store['inventory_digest'], split_digest=store['split_digest'])
    def guard():
        for name, path in c['input_files'].items():
            _read_bound(Path(path), {b['input_pins'][name]})
    ports = PrivateHTTPPorts(manifest=manifest, resolver=resolver, deployments=deployments,
        authorities=authorities, credentials={r:'synthetic-local-credential' for r in ROLES},
        root=root / 'transport', source_guard=guard)
    slot = b['slots'][0]; task = next(t for t in b['tasks'] if digest(t['identity']) == slot['identity_digest'])
    request = blind_request(manifest, slot, task, materials[slot['slot_id']]['body']['payload'])
    budget = PortBudget(manifest, PrivateJournal(root / 'outer-budget.jsonl'), capacity_port=ports.capacity,
        capacity_key=authorities['capacity'].key, source_guard=guard)
    return ports, budget, request, config, manifest, authorities


def test_real_http_serialization_reservation_usage_and_blinding(tmp_path):
    with LocalProvider() as server:
        ports, budget, request, _, manifest, authorities = setup_http(tmp_path, server)
        output, status = budget.call('reviewer1', request, ports.kwargs()['reviewer1'])
        assert status == 'received' and len(server.calls) == server.cap_checks == 1
        assert verify(output, role='reviewer1', subject=request.content_hash,
            authority_id=authorities['reviewer1'].authority_id, key=authorities['reviewer1'].key)['state'] == 'known'
        sent = server.calls[0]
        assert sent['max_completion_tokens'] == manifest.data()['policy']['ports']['reviewer1']['max_output_tokens']
        assert 'PRIVATE_SYNTHETIC_REFERENCE_SENTINEL' in json.dumps(sent)
        assert 'expected' not in json.dumps(sent) and 'support_digest' not in json.dumps(sent)
        rows = [json.loads(s) for s in ports.journal.path.read_text().splitlines()]
        assert [r['event'] for r in rows] == ['transport_opened', 'http_reserved', 'http_raw', 'usage_verified', 'http_completed']
        usage = json.loads((ports.root/'0001/usage.json').read_bytes())
        assert usage['response_sha256'] == hash_file(ports.root/'0001/response.bin')
        assert usage['request_digest'] == request.content_hash
        assert 'synthetic-local-credential' not in ports.journal.path.read_text()


@pytest.mark.parametrize('mode', ['timeout', 'http_error', 'missing_usage', 'invalid_content', 'cap_breach'])
def test_http_failure_keeps_partial_usage_and_stops(tmp_path, mode):
    with LocalProvider(mode) as server:
        ports, budget, request, _, _, _ = setup_http(tmp_path, server)
        output, status = budget.call('reviewer1', request, ports.kwargs()['reviewer1'])
        assert output is None and ports.halted
        assert len(server.calls) == 1
        raw = (ports.root/'0001/response.bin').read_bytes()
        assert raw
        if mode == 'timeout':
            assert raw == b'{"PRIVATE_TIMEOUT_PARTIAL":'
            assert json.loads((ports.root/'0001/response-status.json').read_bytes())['complete'] is False
        if mode in ('invalid_content', 'cap_breach'):
            assert (ports.root/'0001/usage.json').exists()
        else:
            assert not (ports.root/'0001/usage.json').exists()
        budget.call('reviewer1', request, ports.kwargs()['reviewer1'])
        assert len(server.calls) == 1


def test_reused_provider_usage_across_roles_is_unknown_not_new_receipt(tmp_path):
    with LocalProvider('duplicate') as server:
        ports, budget, request, _, _, _ = setup_http(tmp_path, server)
        assert budget.call('reviewer1', request, ports.kwargs()['reviewer1'])[1] == 'received'
        assert budget.call('reviewer2', request, ports.kwargs()['reviewer2'])[0] is None
        assert len(server.calls) == 2 and ports.halted and budget.halted
        assert not (ports.root/'0002/usage.json').exists()


def test_source_drift_after_response_preserves_paid_usage_but_no_review(tmp_path):
    with LocalProvider(on_request=lambda _: (tmp_path/'source-pin.json').write_text('drift')) as server:
        ports, budget, request, _, _, _ = setup_http(tmp_path, server)
        assert budget.call('reviewer1', request, ports.kwargs()['reviewer1'])[0] is None
        assert (ports.root/'0001/usage.json').exists() and ports.halted
        (tmp_path/'source-pin.json').write_text('{"synthetic":true}')
        budget.call('reviewer1', request, ports.kwargs()['reviewer1'])
        assert len(server.calls) == 1


def test_evidence_drift_or_foreign_request_has_zero_http_calls(tmp_path):
    with LocalProvider() as server:
        ports, budget, request, _, _, _ = setup_http(tmp_path, server)
        bad = request.data(); bad['reference_digest'] = 'f' * 64
        assert budget.call('reviewer1', record(bad), ports.kwargs()['reviewer1'])[0] is None
        assert server.calls == []
        (tmp_path/'pricing-evidence.json').write_text('drift')
        assert budget.call('reviewer1', request, ports.kwargs()['reviewer1'])[0] is None
        assert ports.halted and server.calls == []


@pytest.mark.parametrize('disagree', [False, True])
def test_full_36_slot_real_http_grid_and_optional_arbitration(tmp_path, disagree):
    with LocalProvider('disagree' if disagree else 'normal') as server:
        ports, _, _, config, manifest, authorities = setup_http(tmp_path, server)
        receipt = run_config(config, **ports.kwargs())
        result = verify(receipt, role='diagnostic', subject=manifest.content_hash,
            authority_id=authorities['diagnostic'].authority_id, key=authorities['diagnostic'].key)
        assert len(result['observations']) == 72
        assert sum(o['status']=='scored_diagnostic' for o in result['observations']) == 72
        # Four unknown-target slots agree in both reviewers; disagreement elsewhere uses 28 arbiters.
        expected_arbitration = 28 if disagree else 0
        assert len(server.calls) == 144 + expected_arbitration
        assert result['budget']['calls']['arbitrator'] == expected_arbitration
        assert result['calibration_eligible'] is False and result['validation_eligible'] is False
        assert result['source_task_count'] == 4
        (tmp_path/'http-grid-result.json').write_text(receipt.encoded)
