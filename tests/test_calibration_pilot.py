"""Synthetic diagnostic calibration only; no real benchmark reference access."""
import json
from pathlib import Path
import sys

import pytest

from evaluation.modular.calibration import verify_calibration_receipt
from evaluation.modular.calibration_pilot import (
    PILOT_SCHEMA, OPPORTUNITIES, DiagnosticPilot, PilotTransportError, PortResult,
    validate_manifest, verify, DIMENSIONS,
)
from evaluation.modular.calibration_pilot_process import run_config, launch_once
from evaluation.modular.reference_store import FrozenTrainReferenceResolver
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError, digest
from tests.helpers.calibration_pilot_fixture import build_fixture, FixturePorts, record, write, hash_file


def test_contract_is_diagnostic_and_complete():
    assert PILOT_SCHEMA == 'four-train-diagnostic-calibration-v1'
    assert OPPORTUNITIES == 72


def setup_pilot(tmp_path, *, change=None):
    manifest, materials, authorities, config = build_fixture(tmp_path)
    if change:
        manifest, materials = change(manifest, materials, authorities)
    ports = FixturePorts(manifest, authorities)
    store = config.data()['reference_store']
    resolver = FrozenTrainReferenceResolver(Path(store['root']), manifest_sha256=store['manifest_sha256'],
        inventory_digest=store['inventory_digest'], split_digest=store['split_digest'])
    kwargs = {'manifest': manifest, 'materials': {k: record(v) for k, v in materials.items()}, 'resolver': resolver,
        'keys': {k: a.key for k, a in authorities.items()}, 'authority': authorities['diagnostic'],
        'journal_path': tmp_path / 'pilot.jsonl'} | ports.kwargs()
    return kwargs, ports, config


def journal(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_full_grid_blind_reviews_before_evaluation_and_statistics(tmp_path):
    args, ports, _ = setup_pilot(tmp_path)
    pilot = DiagnosticPilot(**args)
    receipt = pilot.run()
    result = verify(receipt, role='diagnostic', subject=args['manifest'].content_hash,
        authority_id=args['authority'].authority_id, key=args['authority'].key)
    assert result['validation_eligible'] is False and result['calibration_eligible'] is False
    assert result['slot_count'] == 36 and len(result['observations']) == 72
    assert result['budget']['calls'] == {'reviewer1': 36, 'reviewer2': 36, 'arbitrator': 0, 'evaluator': 72}
    assert result['source_task_count'] == 4 and result['independent_sample_count_claimed'] is None
    for bench, stats in result['per_benchmark'].items():
        assert stats['opportunities'] == 36 and stats['source_tasks'] == 2
        assert all(v['n'] == 36 and v['mean'] == 0 for v in stats['absolute_error'].values())
        assert all(v['pairs'] == 18 and v['mean'] == 0 for v in stats['repeat_absolute_difference'].values())
    rows = journal(args['journal_path'])
    frozen_index = next(i for i, r in enumerate(rows) if r['event'] == 'reviews_frozen')
    first_evaluator = next(i for i, r in enumerate(rows) if r['event'] == 'port_reserved' and r['data']['role'] == 'evaluator')
    assert frozen_index < first_evaluator
    assert 'PRIVATE_SYNTHETIC_REFERENCE_SENTINEL' not in receipt.encoded
    assert 'Synthetic anonymous candidate' not in receipt.encoded
    with pytest.raises(ContractError):
        verify_calibration_receipt(receipt, {args['authority'].authority_id: args['authority'].key},
            panel_digest=args['manifest'].content_hash, scorer_digest='a'*64, protocol_digest='b'*64)
    with pytest.raises(ContractError):
        pilot.run()


@pytest.mark.parametrize('mutation', ['validation', 'missing_slot', 'duplicate_slot', 'foreign_benchmark', 'duplicate_authority', 'missing_price', 'oversize_calls'])
def test_malformed_or_foreign_grid_refused_before_references(tmp_path, mutation):
    manifest, materials, authorities, config = build_fixture(tmp_path)
    body = manifest.data()
    if mutation == 'validation': body['tasks'][0]['identity']['domain'] = 'validation'
    if mutation == 'missing_slot': body['slots'].pop()
    if mutation == 'duplicate_slot': body['slots'][0] = body['slots'][1]
    if mutation == 'foreign_benchmark': body['tasks'][0]['identity']['benchmark'] = 'foreign'
    if mutation == 'duplicate_authority': body['authorities']['reviewer2'] = body['authorities']['reviewer1']
    if mutation == 'missing_price': del body['policy']['ports']['evaluator']['pricing_digest']
    if mutation == 'oversize_calls': body['policy']['max_calls'] = 181
    with pytest.raises(ContractError): validate_manifest(record(body))
    assert not (tmp_path/'pilot.jsonl').exists()


def test_candidate_drift_rejected_before_resolver_or_ports(tmp_path):
    args, ports, _ = setup_pilot(tmp_path)
    sid = next(iter(args['materials']))
    body = args['materials'][sid].data()
    body['body']['payload']['candidate']['answer'] = 'DRIFT'
    args['materials'][sid] = record(body)
    with pytest.raises(ContractError): DiagnosticPilot(**args)
    assert not args['journal_path'].exists()
    assert sum(map(len, ports.calls.values())) == 0


def test_reference_drift_keeps_reservation_and_zero_ports(tmp_path):
    args, ports, config = setup_pilot(tmp_path)
    handle = args['manifest'].data()['tasks'][0]['task_handle']
    (Path(config.data()['reference_store']['root'])/(handle+'.json')).write_text('{}')
    with pytest.raises(ContractError, match='source preflight'):
        DiagnosticPilot(**args)
    assert [r['event'] for r in journal(args['journal_path'])] == ['pilot_reserved','pilot_source_rejected']
    assert sum(map(len, ports.calls.values())) == 0


def test_review_disagreement_calls_one_fixed_arbitration(tmp_path):
    args, ports, _ = setup_pilot(tmp_path)
    def disagree(request):
        result = ports.review('reviewer2', request)
        body = result.output.data()['body']['payload']
        body['dimensions'] = {name: 0 for name in body['dimensions']}
        return PortResult(ports.authorities['reviewer2'].issue('reviewer2', request.content_hash, body), result.cost)
    args['reviewer2'] = disagree
    result = DiagnosticPilot(**args).run().data()['body']['payload']
    assert result['budget']['calls'] == {'reviewer1':36,'reviewer2':36,'arbitrator':36,'evaluator':72}
    assert set(result['review_states'].values()) == {'arbitrated'}
    assert len(ports.calls['arbitrator']) == 36


def test_unresolved_and_not_applicable_keep_both_opportunities(tmp_path):
    def change(manifest, materials, authorities):
        body = manifest.data()
        for slot, status in zip(body['slots'][:2], ('unresolved_material','not_applicable')):
            sid = slot['slot_id']
            payload = materials[sid]['body']['payload']
            payload.update(status=status, candidate=None, expected={'state':'unknown','dimensions':None})
            receipt = authorities['material'].issue('material', sid, payload)
            materials[sid] = receipt.data()
            slot.update(status=status,candidate_digest=None,material_digest=receipt.content_hash)
        return record(body), materials
    args, _, _ = setup_pilot(tmp_path, change=change)
    result = DiagnosticPilot(**args).run().data()['body']['payload']
    assert len(result['observations']) == 72
    assert result['budget']['calls']['evaluator'] == 68
    assert sum(o['status']=='not_applicable' for o in result['observations']) == 2
    assert sum(o['status']=='unresolved_material' for o in result['observations']) == 2


@pytest.mark.parametrize('failure', ['unreliable','capacity','wrong_quote','budget'])
def test_capacity_or_budget_never_calls_billable_ports(tmp_path, failure):
    args, ports, _ = setup_pilot(tmp_path)
    def quote(request):
        q = ports.capacity(request).data()['body']['payload']
        if failure == 'unreliable': q['reliable'] = False
        if failure == 'capacity': q['input_tokens_upper'] = 100001
        if failure == 'budget': q['cost_microusd_upper'] = 180001
        return ports.authorities['capacity'].issue('capacity', '0'*64 if failure=='wrong_quote' else request.content_hash, q)
    args['capacity_port'] = quote
    result = DiagnosticPilot(**args).run().data()['body']['payload']
    assert sum(result['budget']['calls'].values()) == 0
    assert len(result['observations']) == 72


def test_unknown_reviewer_cost_blocks_entire_global_budget(tmp_path):
    args, ports, _ = setup_pilot(tmp_path)
    def partial(request):
        raise PilotTransportError(partial_response=record({'private_partial':'SENTINEL_PARTIAL'}),
            reported_cost=record({'microusd':'INVALID_REPORTED_COST'}))
    args['reviewer1'] = partial
    result = DiagnosticPilot(**args).run().data()['body']['payload']
    assert result['budget']['calls'] == {'reviewer1':1,'reviewer2':0,'arbitrator':0,'evaluator':0}
    assert result['budget']['unknown_cost_calls']['reviewer1'] == 1
    assert result['budget']['known_or_reserved_microusd']['reviewer1'] == 1000
    assert len(result['observations']) == 72
    raw = next(r['data'] for r in journal(args['journal_path']) if r['event']=='port_raw')
    assert raw['reported_cost']['microusd'] == 'INVALID_REPORTED_COST'
    assert raw['output']['private_partial'] == 'SENTINEL_PARTIAL'
    assert 'SENTINEL_PARTIAL' not in json.dumps(result)


def test_invalid_judge_output_retained_before_validation(tmp_path):
    args, ports, _ = setup_pilot(tmp_path)
    def bad(request):
        ports.calls['evaluator'].append(request)
        return PortResult(record({'bad_private_key':'SENTINEL'}),ports.cost('evaluator',request))
    args['evaluator'] = bad
    result = DiagnosticPilot(**args).run().data()['body']['payload']
    assert result['budget']['calls']['evaluator'] == 72
    assert all(o['status']=='invalid_evaluator_output' for o in result['observations'])
    assert 'bad_private_key' not in json.dumps(result)
    assert 'bad_private_key' in args['journal_path'].read_text()


def test_real_subprocess_36_slot_standard_resolver_endpoint(tmp_path):
    manifest, _, authorities, config = build_fixture(tmp_path)
    config_desc = write(tmp_path/'config.json',config.data())
    output = tmp_path/'diagnostic-result.json'
    helper = Path(__file__).parent/'helpers/calibration_pilot_worker.py'
    receipt = launch_once(command=[sys.executable,str(helper),'--config',config_desc['path'],
        '--sha256',config_desc['sha256'],'--output',str(output)], executable_sha256=hash_file(Path(sys.executable)),
        config_descriptor=config_desc,result_path=output,parent_journal_path=tmp_path/'parent.jsonl',timeout_seconds=60)
    payload = verify(receipt,role='diagnostic',subject=manifest.content_hash,
        authority_id=authorities['diagnostic'].authority_id,key=authorities['diagnostic'].key)
    assert len(payload['observations']) == 72 and payload['budget']['calls']['evaluator'] == 72
    assert payload['budget']['calls']['reviewer1'] == payload['budget']['calls']['reviewer2'] == 36
    assert 'PRIVATE_SYNTHETIC_REFERENCE_SENTINEL' not in output.read_text()


def test_worker_source_pin_drift_zero_ports(tmp_path):
    manifest, _, authorities, config = build_fixture(tmp_path)
    ports = FixturePorts(manifest, authorities)
    Path(config.data()['input_files']['source']).write_text('changed')
    with pytest.raises(ContractError): run_config(config,**ports.kwargs())
    assert sum(map(len,ports.calls.values())) == 0
