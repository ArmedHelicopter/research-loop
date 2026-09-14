"""Bounded actual-Docker M7/M8 artifact bridge checks."""
from pathlib import Path
from dataclasses import replace

import pytest

from research_loop.ontology import ContractError
from research_loop.modular.artifact_catalogue import ArtifactCatalogue, source_snapshot
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.phase_artifacts import (PhaseArtifactBridge, PhaseArtifactContext,
    verify_phase_artifacts, verify_phase_artifact_prefix)
from research_loop.modular.exploration_scheduler_combination import FrozenExplorationSchedulerMaterial, run_phase
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from test_exploration_scheduler_combination import fixture


def _bridge(tmp_path, supplied):
    catalogue = ArtifactCatalogue(tmp_path / 'catalogue.jsonl', identity=supplied['cell'].identity,
        run_id='phase-run', experiment_id='phase-experiment', lock_digest='f' * 64,
        producer_source=source_snapshot(Path(__file__)))
    parents = {}
    kinds = {'invocation': ('model_context','M3'), 'selection': ('c4_choice_frozen','M7'), 'source': ('retrieval_result','M6')}
    for name, (kind, module) in kinds.items():
        descriptor = catalogue.append(kind=kind, module=module,
            payload={'schema': 'phase-parent-v1', 'name': name}, producer_source=source_snapshot(Path(__file__)),
            cost={'known': True, 'units': 0})
        parents[name] = descriptor.content_hash
    context = PhaseArtifactContext(catalogue, tmp_path / 'phase-artifacts', parents)
    return PhaseArtifactBridge(context, phase_root=supplied['root'], enabled=set(supplied['cell'].runtime_arm.data()['enabled']))


def _verify(supplied, bridge):
    return verify_phase_artifacts(bridge=bridge, **{key: value for key, value in supplied.items() if key != 'broker'})


def _for_arm(tmp_path, enabled):
    """Compile the real synthetic panel but dispatch only this two-job phase."""
    snapshot, custody, config, compiled, service = fixture(tmp_path)
    service.close()
    cell = next(item for item in compiled.panel.cells if item.runtime_arm.data()['enabled'] == enabled)
    packet = next(item for item in compiled.packets if item.task.content_hash == cell.task_digest)
    material = FrozenExplorationSchedulerMaterial(FrozenRecord.from_dict(config.data()['materials_by_task'][cell.task_digest]))
    objective = FrozenRecord.from_dict({'identity': cell.identity.data(), 'objective': 'bounded phase artifact fixture'})
    inputs = {'public_csv': packet.csv_path}
    return dict(material=material, cell=cell, objective=objective, root=tmp_path / 'phase',
        broker=DockerExecutionBroker([packet.csv_path.parent, tmp_path]), inputs=inputs,
        image=config.data()['image'], timeout_seconds=config.data()['timeout_seconds'])


@pytest.mark.parametrize('enabled', [['M7', 'M8'], []])
def test_actual_phase_artifacts_cover_parallel_and_serial_sources(tmp_path, enabled):
    supplied = _for_arm(tmp_path, enabled)
    bridge = _bridge(tmp_path, supplied)
    report = run_phase(**supplied, artifact_bridge=bridge)
    assert _verify(supplied, bridge) == report
    bridge.context.catalogue.seal()
    assert _verify(supplied, bridge) == report
    records = [record.data() for record in bridge.context.catalogue.records() if record.data()['kind'].startswith('phase_')]
    m8 = [record for record in records if record['module'] == 'M8']
    assert {record['status'] for record in m8} == ({'produced'} if 'M8' in enabled else {'not_applied'})
    assert (supplied['root'] / 'queue.sqlite').exists() is ('M8' in enabled)


def test_actual_failed_job_keeps_prefix_witnesses_and_rehash_rejects(tmp_path):
    supplied = _for_arm(tmp_path, ['M7', 'M8'])
    body = supplied['material'].data()
    for job in body['jobs']:
        job['program'] = "raise RuntimeError('synthetic phase failure')"
    supplied['material'] = FrozenExplorationSchedulerMaterial(FrozenRecord.from_dict(body))
    bridge = _bridge(tmp_path, supplied)
    report = run_phase(**supplied, artifact_bridge=bridge)
    assert report.data()['status'] == 'failed'
    verify_phase_artifact_prefix(bridge=bridge)
    assert _verify(supplied, bridge) == report
    job = report.data()['fifo_order'][0]
    (supplied['root'] / (job + '.json')).write_bytes(b'{}')
    with pytest.raises(ContractError):
        _verify(supplied, bridge)


def test_phase_artifact_context_rejects_unbound_parent(tmp_path):
    identity = DataIdentity('synthetic', 'phase-task', 'group', 'dataset-v1', 'split-v1', 'train')
    catalogue = ArtifactCatalogue(tmp_path / 'catalogue.jsonl', identity=identity,
        run_id='phase-run', experiment_id='phase-experiment', lock_digest='f' * 64,
        producer_source=source_snapshot(Path(__file__)))
    with pytest.raises(ContractError, match='parent'):
        PhaseArtifactContext(catalogue, tmp_path / 'artifact-root', {'invocation': 'a' * 64,
            'selection': 'b' * 64, 'source': 'c' * 64})


def test_actual_full_c4_arm_only_uses_m7_m8_phase_bridge(tmp_path):
    supplied = _for_arm(tmp_path, ['M7', 'M8'])
    arm = supplied['cell'].runtime_arm.data(); arm['enabled'] = [f'M{i}' for i in range(1, 10)]
    supplied['cell'] = replace(supplied['cell'], runtime_arm=FrozenRecord.from_dict(arm))
    bridge = _bridge(tmp_path, supplied)
    report = run_phase(**supplied, artifact_bridge=bridge)
    assert bridge.enabled == frozenset({'M7','M8'})
    assert _verify(supplied, bridge) == report


def test_sealed_catalogue_rejects_coherent_duplicate_program_witness(tmp_path):
    supplied = _for_arm(tmp_path, ['M7', 'M8'])
    bridge = _bridge(tmp_path, supplied)
    report = run_phase(**supplied, artifact_bridge=bridge)
    records = {record.content_hash: record.data() for record in bridge.context.catalogue.records()}
    allocation = next(digest for digest, body in records.items() if body['kind'] == 'phase_allocation')
    job = report.data()['fifo_order'][1]
    raw = (supplied['root'] / (job + '.py')).read_bytes()
    blob = {'schema':'phase-artifact-bytes-v1','relative_path':job + '.py','sha256':__import__('hashlib').sha256(raw).hexdigest(),'byte_count':len(raw)}
    bridge.context.catalogue.append(kind='phase_program', module='M7', status='produced', parents=(allocation,),
        payload={'schema':'phase-artifact-witness-v1','kind':'phase_program','bytes':blob,
                 'extra':{'job':report.data()['fifo_order'][0]}}, producer_source=bridge.source,
        config_refs=(bridge.bridge_source_ref,))
    bridge.context.catalogue.seal()
    with pytest.raises(ContractError, match='bijection|job binding'):
        _verify(supplied, bridge)


def test_sealed_catalogue_rejects_misordered_event_witness(tmp_path):
    supplied = _for_arm(tmp_path, ['M7', 'M8'])
    bridge = _bridge(tmp_path, supplied)
    run_phase(**supplied, artifact_bridge=bridge)
    records = {record.content_hash: record.data() for record in bridge.context.catalogue.records()}
    allocation = next(digest for digest, body in records.items() if body['kind'] == 'phase_allocation')
    line = (supplied['root'] / 'events.jsonl').read_bytes().splitlines(keepends=True)[1]
    event = FrozenRecord(line.decode().rstrip('\n')).data()
    blob = {'schema':'phase-artifact-bytes-v1','relative_path':'events.jsonl#1',
        'sha256':__import__('hashlib').sha256(line).hexdigest(),'byte_count':len(line)}
    bridge.context.catalogue.append(kind='phase_scheduler_event', module='M8', status='produced', parents=(allocation,),
        payload={'schema':'phase-artifact-witness-v1','kind':'phase_scheduler_event','bytes':blob,
                 'extra':{'sequence':1,'event':event}}, producer_source=bridge.source,
        config_refs=(bridge.bridge_source_ref,))
    bridge.context.catalogue.seal()
    with pytest.raises(ContractError, match='unordered|chronology'):
        _verify(supplied, bridge)


def test_context_rejects_known_parent_with_forged_semantic_role(tmp_path):
    identity = DataIdentity('synthetic', 'phase-task', 'group', 'dataset-v1', 'split-v1', 'train')
    catalogue = ArtifactCatalogue(tmp_path / 'catalogue.jsonl', identity=identity,
        run_id='phase-run', experiment_id='phase-experiment', lock_digest='f' * 64,
        producer_source=source_snapshot(Path(__file__)))
    descriptors = [catalogue.append(kind=kind, module=module, payload={'schema':'phase-parent-v1','name':name},
        producer_source=source_snapshot(Path(__file__))) for name, kind, module in (
            ('invocation','model_context','M3'), ('selection','c4_choice_frozen','M7'), ('not-source','c4_choice_frozen','M7'))]
    with pytest.raises(ContractError, match='semantic role'):
        PhaseArtifactContext(catalogue, tmp_path / 'artifact-root', {'invocation':descriptors[0].content_hash,
            'selection':descriptors[1].content_hash, 'source':descriptors[2].content_hash})
