import hashlib
import json

import pytest

from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from research_loop.modular.admission_combination import FrozenAdmissionMaterial
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.csv_measurement_authorities import CsvMeasurementDataset, CsvMeasurementSpec
from research_loop.modular.exploration_scheduler_combination import FrozenExplorationSchedulerMaterial, run_phase
from research_loop.modular.panel_receipts import PanelCell
from research_loop.modular.validation_bundle_material import (
    ValidationAdmissionMaterial, ValidationPhaseMaterial, ValidationBundleMaterial,
    build_validation_csv_verifier, freeze_validation_retrieval, run_validation_phase,
)
from research_loop.ontology import ContractError, digest
from test_modular_benchmark_solver import IMAGE

R = FrozenRecord.from_dict


def materials(root, task=None, csv_bytes=b'x\n1\n3\n'):
    root.mkdir(parents=True, exist_ok=True)
    csv = root / 'public.csv'; csv.write_bytes(csv_bytes)
    if task is None:
        task = PublicTask.create(DataIdentity('blade', 'held-opaque', 'held-family', 'fixture', 'a'*64, 'validation'),
                                 {'question': 'Compute the public mean.'})
    bindings = {'task': task.identity.task_id}
    original = {'key': 'rows', 'root_material': {'kind': 'public-csv-count'},
        'content': {'measurement': {'operation': 'row_count', 'column': None, 'expected': str(len(csv_bytes.splitlines())-1)}},
        'subject_bindings': bindings}
    public = [{'artifact': {'artifact_id': 'public_csv', 'sha256': hashlib.sha256(csv_bytes).hexdigest(),
                           'byte_count': len(csv_bytes)}, 'container_path': '/input/public_csv'}]
    admission = ValidationAdmissionMaterial(R({'schema': 'validation-admission-material-v1', 'identity': task.identity.data(),
        'task_digest': task.content_hash, 'public_artifacts': public, 'question': 'Compute the public mean.',
        'context_budget_bytes': 16000, 'ordinary_summary': 'A public descriptive measurement is available.',
        'originals': [original], 'representations': [{'key': 'copy', 'root': 'rows', 'representation': 'summary', 'content': {'reported': 'row count'}}],
        'claims': [{'key': 'count', 'statement': 'The public row count is known.', 'subject_bindings': bindings,
                    'supports': ['rows'], 'refutes': [], 'depends_on': []}], 'withdrawals': [],
        'qualification_observations': {'before': {'rows': {'source': 'public CSV'}}, 'after': {'rows': {'source': 'public CSV'}}}}))
    jobs = [{'id': digest({'job': i}), 'purpose': 'probe' if i == 2 else 'main',
        'program': "import csv,json,time\ntime.sleep(0.05)\nwith open('/input/public_csv') as f: xs=[float(r['x']) for r in csv.DictReader(f)]\nprint(json.dumps({'statistic':sum(xs)/len(xs)}))",
        'dependencies': [], 'resources': [digest({'resource': i})], 'cost_units': 1} for i in range(3)]
    phase = ValidationPhaseMaterial(R({'schema': 'validation-phase-material-v1', 'identity': task.identity.data(),
        'task_digest': task.content_hash, 'public_artifacts': public, 'context_budget_bytes': 16000, 'jobs': jobs}))
    sources = [{'source_id': lane, 'root_source_id': lane, 'lane': lane,
                'text': {'text': 'Check the arithmetic mean against the public rows.'}} for lane in ('support', 'counter', 'method')]
    retrieval = freeze_validation_retrieval(task, sources, 'Compute the public mean.')
    material = ValidationBundleMaterial(admission, phase, retrieval)
    spec = CsvMeasurementSpec(R({'schema': 'admission-csv-measurement-spec-v2', 'original_key': 'rows',
        'original_observation_digest': R(original).content_hash, 'operation': 'row_count', 'column': None,
        'expected': str(len(csv_bytes.splitlines())-1)}))
    verifier = build_validation_csv_verifier(
        authorities=(LinkedExecutionAuthority('val-csv-a', b'a'*32), LinkedExecutionAuthority('val-csv-b', b'b'*32)),
        datasets={task.content_hash: CsvMeasurementDataset(csv, {'rows': spec})}, receipt_root=root / 'authority')
    return task, csv, material, verifier


def test_validation_material_has_real_two_process_source_measurements_and_replay(tmp_path):
    task, csv, material, verifier = materials(tmp_path)
    binding = R({'cell_digest': 'c'*64, 'scenario_digest': 'd'*64})
    source = tmp_path / 'cell' / 'source.json'
    verifier.qualify(material.admission, source, cell_binding=binding)
    assessments = verifier.assessments(material.admission, source, cell_binding=binding)
    assert assessments['before']['rows']['state']['validity'] == 'valid'
    assert source.is_file()
    raw = [json.loads(path.read_bytes()) for path in (tmp_path / 'authority' / ('c'*64)).glob('*.json')]
    assert len(raw) == 2 and len({row['process']['pid'] for row in raw}) == 2
    assert all(row['process']['exit_code'] == 0 and row['process']['outcome'] == 'completed' for row in raw)
    assert all(row['process']['stdout_sha256'] for row in raw)
    csv.write_bytes(b'x\n100\n')
    with pytest.raises(ContractError):
        verifier.assessments(material.admission, source, cell_binding=binding)


def test_validation_material_does_not_enter_existing_train_contracts(tmp_path):
    task, csv, material, verifier = materials(tmp_path)
    # Even an unchanged legacy schema cannot reclassify a held-out identity.
    state = material.admission.data(); state['schema'] = 'admission-combination-material-v1'
    phase = material.phase.data(); phase['schema'] = 'exploration-scheduler-material-v1'
    with pytest.raises(ContractError): FrozenAdmissionMaterial(R(state))
    with pytest.raises(ContractError): FrozenExplorationSchedulerMaterial(R(phase))
    state = material.admission.data(); state['identity']['domain'] = 'train'
    with pytest.raises(ContractError): ValidationAdmissionMaterial(R(state))


def test_validation_phase_runs_real_fifo_and_two_restricted_docker_jobs(tmp_path):
    task, csv, material, _ = materials(tmp_path)
    cell = PanelCell('C5-selected-bundle', task.identity, 'r1', 'fixed_acceptance', 'candidate',
        default_compatibility('a'*64).arm(('M7', 'M8')), task.content_hash, material.record.content_hash, 'b'*64, 'c'*64)
    args = dict(material=material.phase, cell=cell, objective=R({'question': 'Compute the mean.'}),
        root=tmp_path / 'phase', broker=DockerExecutionBroker([tmp_path]), inputs={'public_csv': csv},
        image=IMAGE, timeout_seconds=20, selected_job_id=material.phase.data()['jobs'][2]['id'])
    with pytest.raises(ContractError): run_phase(**args)
    result = run_validation_phase(**args).data()
    assert result['status'] == 'succeeded' and result['actual_docker_attempts'] == 2
    assert result['remaining_leases'] == [] and result['peak_leases'] == 2
    assert (tmp_path / 'phase' / 'queue.sqlite').is_file()
    assert all(json.loads(o['stdout'])['statistic'] == 2 for o in result['public']['observations'])
