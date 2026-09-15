import hashlib
import json
import shutil
from base64 import b64decode
from decimal import Context, localcontext

import pytest

from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from research_loop.modular.admission_combination import FrozenAdmissionMaterial
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.csv_measurement_authorities import (
    CsvMeasurementDataset, CsvMeasurementSpec, build_csv_measurement_admission_verifier,
)
from research_loop.ontology import ContractError


def _material(csv_bytes, sum_expected):
    identity = {'benchmark': 'blade', 'task_id': 'csv-scope', 'group_id': 'g', 'dataset_version': 'v1', 'split_id': 'train-r1', 'domain': 'train'}
    originals = [
        {'key': 'sum', 'root_material': {'kind': 'public-csv-amount'}, 'content': {'measurement': {'operation': 'decimal_sum', 'column': 'amount', 'expected': sum_expected}}, 'subject_bindings': {'task': 'csv-scope'}},
        {'key': 'count', 'root_material': {'kind': 'public-csv-name'}, 'content': {'measurement': {'operation': 'nonempty_count', 'column': 'name', 'expected': '1'}}, 'subject_bindings': {'task': 'csv-scope'}},
    ]
    body = {'schema': 'admission-combination-material-v1', 'identity': identity, 'task_digest': 'a' * 64,
        'public_artifacts': [{'artifact': {'artifact_id': 'public_csv', 'sha256': hashlib.sha256(csv_bytes).hexdigest(), 'byte_count': len(csv_bytes)}, 'container_path': '/input/public_csv'}],
        'question': 'What do the public CSV measurements report?', 'context_budget_bytes': 1024,
        'ordinary_summary': 'A public descriptive measurement is available.', 'originals': originals, 'representations': [],
        'claims': [{'key': 'claim', 'statement': 'The public measurement is recorded.', 'subject_bindings': {'task': 'csv-scope'},
                    'supports': ['sum'], 'refutes': [], 'depends_on': []}], 'withdrawals': [],
        'qualification_observations': {'before': {'sum': {'source': 'public'}, 'count': {'source': 'public'}},
                                       'after': {'sum': {'source': 'public'}, 'count': {'source': 'public'}}}}
    return FrozenAdmissionMaterial(FrozenRecord.from_dict(body))


def _spec(row, operation, column, expected):
    return CsvMeasurementSpec(FrozenRecord.from_dict({'schema': 'admission-csv-measurement-spec-v2', 'original_key': row['key'],
        'original_observation_digest': FrozenRecord.from_dict(row).content_hash, 'operation': operation, 'column': column, 'expected': expected}))


def _verifier(tmp_path, *, expected='3.5'):
    csv_path = tmp_path / 'public.csv'
    csv_path.write_text('amount,name\n1.20,a\n2.30,\n', encoding='utf-8')
    material = _material(csv_path.read_bytes(), expected)
    rows = material.data()['originals']
    dataset = CsvMeasurementDataset(csv_path, {'sum': _spec(rows[0], 'decimal_sum', 'amount', expected),
                                                'count': _spec(rows[1], 'nonempty_count', 'name', '1')})
    verifier = build_csv_measurement_admission_verifier(
        authorities=(LinkedExecutionAuthority('csv-a', b'a' * 32), LinkedExecutionAuthority('csv-b', b'b' * 32)),
        datasets={'a' * 64: dataset}, receipt_root=tmp_path / 'receipts')
    return material, csv_path, verifier


def _binding():
    return FrozenRecord.from_dict({'cell_digest': 'c' * 64, 'scenario_digest': 'd' * 64})


def test_real_two_worker_consumer_replay_accepts_scoped_agreement(tmp_path):
    material, _, verifier = _verifier(tmp_path)
    sidecar = tmp_path / 'cell' / 'source-verification.json'
    verifier.qualify(material, sidecar, cell_binding=_binding())
    assessments = verifier.assessments(material, sidecar, cell_binding=_binding())
    assert all(row['state']['validity'] == 'valid' for phase in assessments.values() for row in phase.values())
    assert len(list((tmp_path / 'receipts' / ('c' * 64)).glob('*.json'))) == 2


def test_completed_but_wrong_measurement_is_a_legitimate_m1_rejection(tmp_path):
    material, _, verifier = _verifier(tmp_path, expected='999')
    sidecar = tmp_path / 'cell' / 'source-verification.json'
    verifier.qualify(material, sidecar, cell_binding=_binding())
    assessments = verifier.assessments(material, sidecar, cell_binding=_binding())
    assert all(phase['sum']['state']['validity'] == 'unknown' and phase['sum']['execution_success'] is True
               and phase['count']['state']['validity'] == 'valid' for phase in assessments.values())


def test_source_failure_is_retained_as_unknown_not_promoted(tmp_path, monkeypatch):
    material, _, verifier = _verifier(tmp_path)
    import research_loop.modular.csv_measurement_authorities as module
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *args, **kwargs: (_ for _ in ()).throw(OSError('offline')))
    sidecar = tmp_path / 'cell' / 'source-verification.json'
    with pytest.raises(ContractError):
        verifier.qualify(material, sidecar, cell_binding=_binding())
    raw = next((tmp_path / 'receipts' / ('c' * 64)).glob('*.json'))
    assert FrozenRecord(raw.read_text(encoding='utf-8')).data()['executions'][0]['outcome'] == 'unknown'


def test_replay_rejects_a_forged_but_authorized_assessment(tmp_path):
    material, _, verifier = _verifier(tmp_path)
    sidecar = tmp_path / 'cell' / 'source-verification.json'
    verifier.qualify(material, sidecar, cell_binding=_binding())
    body = json.loads(sidecar.read_text(encoding='utf-8'))
    for authority, call in zip(verifier.authorities, body['calls'], strict=True):
        forged = call['response']['body']
        forged['assessments']['before']['sum']['state']['validity'] = 'unknown'
        call['response'] = authority.authority.issue(forged).data()
    sidecar.write_text(json.dumps(body, sort_keys=True, separators=(',', ':')), encoding='utf-8')
    with pytest.raises(ContractError, match='semantic result or cost'):
        verifier._verify_receipt(material, sidecar, cell_binding=_binding())


def test_return_pin_absence_retains_streams_and_remains_unknown(tmp_path, monkeypatch):
    material, _, verifier = _verifier(tmp_path)
    import research_loop.modular.csv_measurement_authorities as module
    request = verifier.request(material, _binding())
    original_pins = module._read_worker_pins
    observed = 0

    def pins(dataset, source):
        nonlocal observed
        observed += 1
        if observed == 2:
            return None, None, 'FileNotFoundError'
        return original_pins(dataset, source)

    monkeypatch.setattr(module, '_read_worker_pins', pins)
    launch_csv, launch_worker, process, executions = module._run_worker(request, verifier.datasets['a' * 64], verifier.authorities[0])
    assert launch_csv is not None and launch_worker is not None
    assert process['outcome'] == 'unknown' and process['return_pin_error'] == 'FileNotFoundError'
    assert process['return_pins'] is None and all(row['outcome'] == 'unknown' for row in executions)
    assert b64decode(process['stdout_b64'], validate=True) and process['cleanup_status'] == 'not_required'


def test_dataset_requires_the_materials_unique_csv_byte_parent(tmp_path):
    material, _, verifier = _verifier(tmp_path)
    foreign = tmp_path / 'foreign.csv'
    foreign.write_text('amount,name\n1.20,a\n2.30,\nextra,z\n', encoding='utf-8')
    dataset = CsvMeasurementDataset(foreign, verifier.datasets['a' * 64].specs)
    foreign_verifier = build_csv_measurement_admission_verifier(
        authorities=(LinkedExecutionAuthority('foreign-a', b'f' * 32), LinkedExecutionAuthority('foreign-b', b'g' * 32)),
        datasets={'a' * 64: dataset}, receipt_root=tmp_path / 'foreign-receipts')
    with pytest.raises(ContractError, match='unique public CSV byte parent'):
        foreign_verifier.request(material, _binding())


@pytest.mark.parametrize('fault', ['csv', 'code', 'spec', 'raw_receipt'])
def test_actual_replay_rejects_csv_code_spec_and_raw_receipt_mutations(tmp_path, monkeypatch, fault):
    import research_loop.modular.csv_measurement_authorities as module
    pinned = tmp_path / 'pinned' / 'research_loop' / 'modular'
    pinned.mkdir(parents=True)
    for group, source_path in tuple(module._WORKERS.items()):
        copied = pinned / source_path.name
        shutil.copy2(source_path, copied)
        monkeypatch.setitem(module._WORKERS, group, copied)
    material, csv_path, verifier = _verifier(tmp_path)
    sidecar = tmp_path / 'cell' / 'source-verification.json'
    verifier.qualify(material, sidecar, cell_binding=_binding())
    raw = next((tmp_path / 'receipts' / ('c' * 64)).glob('*.json'))
    original_csv = csv_path.read_bytes()
    source = module._WORKERS['csv-reader-aggregate-v2']
    original_source = source.read_bytes()
    try:
        if fault == 'csv':
            csv_path.write_bytes(original_csv + b' ')
        elif fault == 'code':
            source.write_bytes(original_source + b'\n# mutation\n')
        else:
            receipt = FrozenRecord(raw.read_text(encoding='utf-8')).data()
            if fault == 'spec':
                receipt['executions'][0]['spec_digest'] = 'e' * 64
            else:
                receipt['process']['stdout_b64'] = 'e30='
            raw.write_text(FrozenRecord.from_dict(receipt).encoded, encoding='utf-8')
        with pytest.raises(ContractError):
            verifier.assessments(material, sidecar, cell_binding=_binding())
    finally:
        csv_path.write_bytes(original_csv)
        source.write_bytes(original_source)


def test_reader_and_dictreader_are_context_independent_and_reject_bad_csv(tmp_path):
    from research_loop.modular.csv_dictreader_measurement_worker import measure as dict_measure
    from research_loop.modular.csv_reader_measurement_worker import measure as reader_measure
    csv_path = tmp_path / 'numbers.csv'
    csv_path.write_text('amount\n123456789012345678901234567890.1\n0.2\n', encoding='utf-8')
    spec = FrozenRecord.from_dict({'schema': 'admission-csv-measurement-spec-v2', 'original_key': 'x',
        'original_observation_digest': 'f' * 64, 'operation': 'decimal_sum', 'column': 'amount', 'expected': '123456789012345678901234567890.3'})
    with localcontext(Context(prec=2)):
        assert reader_measure(csv_path, spec).data()['value'] == dict_measure(csv_path, spec).data()['value'] == spec.data()['expected']
    csv_path.write_text('amount,amount\n1,2\n', encoding='utf-8')
    with pytest.raises(ContractError):
        reader_measure(csv_path, spec)
    with pytest.raises(ContractError):
        dict_measure(csv_path, spec)
