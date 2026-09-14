"""Bounded actual-Docker M7/M8 artifact bridge checks."""
from pathlib import Path

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
    for name in ('invocation', 'selection', 'source'):
        descriptor = catalogue.append(kind='bound_phase_' + name, module=None, coverage='uncovered',
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
