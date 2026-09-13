"""Synthetic TRAIN only; exercise renderer/worker/native ACP/budget/result seam."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from evaluation.modular.calibration_pilot import validate_manifest as validate_http, verify, runtime_code_paths
from evaluation.modular.diagnostic_subscription import (
    CONFIG_SCHEMA, OBSERVATION_SCHEMA, SCHEMA, compile_inventory, own_sources,
    policy, run_private, sha, validate_manifest,
)
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError, digest
from tests.helpers.calibration_pilot_fixture import build_fixture, record, write
from tests.helpers.subscription_worker import fixture_factory


def setup_subscription(root, *, all_ready=False, byte_cap=100000, ready_kind='valid_positive', main_cap=180,
                       reference_bytes=0):
    old, materials, authorities, config = build_fixture(root)
    b, c = old.data(), config.data()
    if reference_bytes:
        store_path = Path(c['reference_store']['root']) / 'manifest.json'
        store = json.loads(store_path.read_text())
        for row in store['rows']:
            path = store_path.parent / row['file']
            ref = json.loads(path.read_text())
            ref['references'][0]['hypothesis'] = 'SYNTHETIC_COMPLETE_REFERENCE_' + ('X' * reference_bytes)
            desc = write(path, ref)
            row['reference_sha256'] = desc['sha256']
            next(t for t in b['tasks'] if t['task_handle'] == row['task_handle'])['reference_digest'] = record(ref).content_hash
        c['reference_store']['manifest_sha256'] = write(store_path, store)['sha256']
    if not all_ready:
        kept = set()
        tasks = {digest(t['identity']): t for t in b['tasks']}
        for slot in b['slots']:
            benchmark = tasks[slot['identity_digest']]['identity']['benchmark']
            if benchmark not in kept and slot['kind'] == ready_kind:
                kept.add(benchmark)
                continue
            material = authorities['material'].issue('material', slot['slot_id'], {
                'status': 'unresolved_material', 'candidate': None,
                'expected': {'state': 'unknown', 'dimensions': None}, 'support_digest': digest({'fixture': slot['slot_id']})})
            slot.update(status='unresolved_material', candidate_digest=None, material_digest=material.content_hash)
            materials[slot['slot_id']] = material.data()
    b['schema'] = SCHEMA; b['policy'] = policy(input_byte_cap=byte_cap, main_opportunities=main_cap,
        main_output_cap=512, observed_main_token_cap=262144)
    for name, path in own_sources().items():
        b['input_pins'][name] = sha(path); c['input_files'][name] = str(path.absolute())
    c['schema'] = CONFIG_SCHEMA
    c['manifest'] = write(root / 'subscription-manifest.json', b)
    c['materials'] = write(root / 'subscription-materials.json', materials)
    c['request_inventory'] = None; c['native_deployment'] = None
    before = write(root / 'subscription-uncompiled-config.json', c)
    inventory = compile_inventory(before, root / 'request-inventory.json')
    c['request_inventory'] = inventory
    desc = write(root / 'subscription-config.json', c)
    return desc, record(b), authorities, old


def unpack(result, manifest, authorities):
    return verify(result, role='diagnostic', subject=manifest.content_hash,
        authority_id=authorities['diagnostic'].authority_id, key=authorities['diagnostic'].key)


def test_new_manifest_never_weakens_old_monetary_contract(tmp_path):
    _, new, _, old = setup_subscription(tmp_path)
    validate_manifest(new); validate_http(old)
    with pytest.raises(ContractError): validate_http(new)
    with pytest.raises(ContractError): validate_manifest(old)
    b = old.data(); b['policy']['max_microusd'] = 0
    with pytest.raises(ContractError): validate_http(record(b))
    b = new.data(); b['policy']['max_total_opportunities'] = 180
    with pytest.raises(ContractError): validate_manifest(record(b))


@pytest.mark.parametrize('mode,expected_calls,scored', [('diagnostic', 8, 4), ('diagnostic_unknown_main', 1, 0)])
def test_real_worker_renderer_native_ledger_and_fixed_denominators(tmp_path, mode, expected_calls, scored):
    desc, manifest, authorities, _ = setup_subscription(tmp_path)
    worker = Path(__file__).parent / 'helpers' / 'subscription_worker.py'
    result_path = tmp_path / 'result.json'
    proc = subprocess.run([sys.executable, str(worker), '--config', desc['path'], '--sha256', desc['sha256'],
        '--output', str(result_path), '--mode', mode], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=60, env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1])))
    assert proc.returncode == 0, proc.stderr.decode()
    assert b'PRIVATE' not in proc.stdout + proc.stderr
    result = unpack(FrozenRecord(result_path.read_text()), manifest, authorities)
    assert result['schema'] == OBSERVATION_SCHEMA
    assert result['material_availability'] == {'ready': 2, 'unresolved_material': 34, 'not_applicable': 0}
    assert len(result['observations']) == 72 and result['slot_count'] == 36
    assert sum(o['status'] == 'scored_diagnostic' for o in result['observations']) == scored
    budget = result['budget']
    assert budget['reserved_main_opportunities'] == expected_calls
    assert budget['reserved_possible_title_opportunities'] == expected_calls
    assert budget['all_opportunity_tokens'] is None and budget['settled_additional_charge_usd'] is None
    assert result['calibration_eligible'] is False and result['validation_eligible'] is False
    logs = list((tmp_path / 'private-journal.jsonl.acp').glob('*/peer.private.jsonl'))
    assert len(logs) == expected_calls
    for path in logs:
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        prompts = [r for r in rows if r['method'] == 'session/prompt']
        assert len(prompts) == 1
        text = prompts[0]['params']['prompt'][0]['text']
        assert 'PRIVATE_SYNTHETIC_REFERENCE_SENTINEL' in text
        assert '"expected"' not in text and 'support_digest' not in text
        assert [r['method'] for r in rows[:5]] == ['initialize', 'session/new', '_x.ai/billing', '_x.ai/auto-topup-rule', 'session/prompt']
    journal = [json.loads(line) for line in (tmp_path / 'private-journal.jsonl').read_text().splitlines()]
    frozen = next(i for i, row in enumerate(journal) if row['event'] == 'reviews_frozen')
    assert all(i > frozen for i, row in enumerate(journal) if row['event'] == 'subscription_reserved' and row['data']['role'] == 'evaluator')
    if mode == 'diagnostic_unknown_main':
        assert budget['further_io_blocked']
        assert budget['records'][0]['known_main_usage']['totalTokens'] == 12
        assert budget['records'][0]['known_response_usage'][0]['output_tokens'] == 2


def test_complete_reference_byte_cap_rejects_before_any_transport(tmp_path):
    with pytest.raises(ContractError, match='byte cap'):
        setup_subscription(tmp_path, byte_cap=1)
    assert not list(tmp_path.glob('**/native-reservation.json'))


def test_changed_request_inventory_rejected_before_io(tmp_path):
    desc, _, _, _ = setup_subscription(tmp_path)
    c = json.loads(Path(desc['path']).read_text())
    inv = json.loads(Path(c['request_inventory']['path']).read_text())
    inv['entries'][0]['prompt_sha256'] = '0' * 64
    c['request_inventory'] = write(tmp_path / 'changed-inventory.json', inv)
    desc = write(tmp_path / 'changed-config.json', c)
    calls = []
    with pytest.raises(ContractError, match='frozen inventory'):
        run_private(desc, fixture_factory=lambda *args: calls.append(args))
    assert calls == []


def test_source_drift_after_main_retains_receipt_and_blocks_later_io(tmp_path):
    desc, manifest, authorities, _ = setup_subscription(tmp_path)
    original = fixture_factory(); calls = []
    def drift(*args):
        result = original(*args); calls.append(result)
        (tmp_path / 'source-pin.json').write_text('drift')
        return result
    result = unpack(run_private(desc, fixture_factory=drift), manifest, authorities)
    assert len(calls) == 1 and result['budget']['further_io_blocked']
    assert result['budget']['records'][0]['known_main_usage']['totalTokens'] == 12


def test_unknown_title_does_not_invent_zero_or_block_known_main(tmp_path):
    desc, manifest, authorities, _ = setup_subscription(tmp_path, ready_kind='uncertain')
    result = unpack(run_private(desc, fixture_factory=fixture_factory()), manifest, authorities)
    assert result['budget']['reserved_main_opportunities'] == 8
    assert all(r['status'] == 'known_main_expected_unknown_title' and r['title_usage'] is None
               for r in result['budget']['records'])
    assert result['material_expected_states']['unknown'] == 36


def test_duplicate_native_identity_retained_and_halts(tmp_path):
    from research_loop.modular.grok_acp_transport import AcpResult
    desc, manifest, authorities, _ = setup_subscription(tmp_path)
    original = fixture_factory(); first = []
    def duplicate(*args):
        result = original(*args)
        if not first: first.append(result.receipt.data()['session_id'])
        receipt = result.receipt.data(); receipt['session_id'] = first[0]
        return AcpResult(record(receipt), result.response)
    result = unpack(run_private(desc, fixture_factory=duplicate), manifest, authorities)
    assert result['budget']['reserved_main_opportunities'] == 2
    assert result['budget']['further_io_blocked']
    assert len(result['budget']['records']) == 2


def test_all_materials_frozen_and_opportunity_budget_stops_before_second_call(tmp_path):
    desc, manifest, authorities, _ = setup_subscription(tmp_path, all_ready=True, main_cap=1)
    config = json.loads(Path(desc['path']).read_text())
    inventory = json.loads(Path(config['request_inventory']['path']).read_text())
    assert len(inventory['entries']) == 180
    assert len({row['opportunity_id'] for row in inventory['entries']}) == 180
    result = unpack(run_private(desc, fixture_factory=fixture_factory()), manifest, authorities)
    assert result['material_availability']['ready'] == 36
    assert len(result['observations']) == 72
    assert result['budget']['reserved_main_opportunities'] == 1
    assert result['budget']['reserved_possible_title_opportunities'] == 1
    assert result['budget']['unused_main_opportunities'] == 0
    assert len(list(tmp_path.glob('**/native-reservation.json'))) == 1


@pytest.mark.parametrize('mode', ['paid', 'tools', 'malformed', 'tool_event', 'optional_stop_bad_terminal'])
def test_native_fault_at_provider_seam_never_permits_later_request(tmp_path, mode):
    desc, manifest, authorities, _ = setup_subscription(tmp_path)
    result = unpack(run_private(desc, fixture_factory=fixture_factory(mode)), manifest, authorities)
    assert result['budget']['reserved_main_opportunities'] == 1
    assert result['budget']['further_io_blocked']
    assert len(list(tmp_path.glob('**/peer.private.jsonl'))) == 1
    if mode in ('paid', 'tools', 'malformed'):
        assert not list(tmp_path.glob('**/native-reservation.json'))


def test_invalid_review_keeps_accepted_native_main_receipt(tmp_path):
    from research_loop.modular.grok_acp_transport import AcpResult
    desc, manifest, authorities, _ = setup_subscription(tmp_path)
    native = fixture_factory()
    def invalid(*args):
        result = native(*args)
        return AcpResult(result.receipt, record({'state': 'known', 'dimensions': {'cvars': .3, 'transform': 1, 'model': 1}}))
    result = unpack(run_private(desc, fixture_factory=invalid), manifest, authorities)
    row = result['budget']['records'][0]
    assert row['known_main_usage']['totalTokens'] == 12
    assert row['native_accepted'] and result['budget']['further_io_blocked']


def test_native_execution_cannot_use_unprovisioned_profile_or_fixture_fallback(tmp_path):
    desc, _, _, _ = setup_subscription(tmp_path)
    with pytest.raises(ContractError): run_private(desc)
    assert not list(tmp_path.glob('**/native-reservation.json'))


@pytest.mark.parametrize('swap', ['valid_response', 'prompt', 'schema', 'reservation', 'source'])
def test_coherent_native_binding_swaps_keep_main_usage_but_stop_io(tmp_path, swap):
    from research_loop.modular.grok_acp_transport import AcpResult
    desc, manifest, authorities, _ = setup_subscription(tmp_path)
    native = fixture_factory()
    def swapped(entry, prompt, schema, directory, frozen_files, spec):
        actual_prompt = prompt
        if swap == 'prompt':
            messages = json.loads(prompt)
            messages['messages'][0]['content'] += ' Synthetic changed instruction.'
            actual_prompt = json.dumps(messages)
        # Keep a coherent native schema/answer, but make it differ from frozen schema.
        actual_schema = copy.deepcopy(schema)
        if swap == 'schema':
            actual_schema['properties']['state']['enum'] = ['known']
        actual_files = frozen_files | {str(Path(__file__).absolute()): sha(__file__)} if swap == 'source' else frozen_files
        result = native(entry, actual_prompt, actual_schema, directory, actual_files, spec)
        assert result.receipt.data()['accepted']
        if swap == 'valid_response':
            replacement = result.response.data()
            replacement['dimensions'] = {name: 0 for name in replacement['dimensions']}
            return AcpResult(result.receipt, record(replacement))
        if swap == 'reservation':
            path = directory / 'native-reservation.json'
            reservation = json.loads(path.read_text()); reservation['prompt_id'] = 'different-synthetic-prompt'
            path.write_text(json.dumps(reservation))
        return result
    result = unpack(run_private(desc, fixture_factory=swapped), manifest, authorities)
    assert result['budget']['reserved_main_opportunities'] == 1
    assert result['budget']['further_io_blocked']
    row = result['budget']['records'][0]
    assert row['known_main_usage']['totalTokens'] == 12 and row['native_accepted']
    assert row['status'] == 'rejected_with_known_usage_preserved'
    assert not any(o['status'] == 'scored_diagnostic' for o in result['observations'])


def test_large_synthetic_reference_compiles_complete_with_explicit_byte_limit(tmp_path):
    desc, _, _, _ = setup_subscription(tmp_path, reference_bytes=180000, byte_cap=200000)
    config = json.loads(Path(desc['path']).read_text())
    inventory = json.loads(Path(config['request_inventory']['path']).read_text())
    assert all(180000 < e['input_bytes'] < 200000 for e in inventory['entries'])
    assert not list(tmp_path.glob('**/native-reservation.json'))
