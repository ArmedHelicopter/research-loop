"""Real qualifier failures preserve bytes, budgets and rejection semantics."""
import json

import pytest

from research_loop.modular import lineage_combination_material as lineage
from research_loop.modular.admission_combination import FrozenAdmissionMaterial
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.material_qualification_artifacts import MaterialQualificationArtifacts
from research_loop.ontology import ContractError
from test_admission_combination import sources
from test_material_qualification_artifacts import _subject


R = FrozenRecord.from_dict


def _retain(root, verifier, material, cell):
    (root/'independent-qualification-inputs.json').write_bytes(R({
        'material': material.record.data(), 'binding': verifier.binding().data(),
        'cell_binding': cell.data(), 'request': verifier.request(material, cell).data()
    }).encoded.encode())


@pytest.mark.parametrize('write_number,callback_count', [(1, 0), (2, 1), (3, 1), (4, 2)])
def test_partial_sidecar_failure_retains_bytes_without_extra_authority_call(tmp_path, monkeypatch, write_number, callback_count):
    verifier, material, cell, calls = _subject(tmp_path)
    _retain(tmp_path, verifier, material, cell)
    receipt = tmp_path/'attempt'/'source.json'
    original_write = lineage._write
    writes = []
    failure = OSError('PRIVATE-FILESYSTEM-MESSAGE')

    def fail_write(path, body):
        writes.append(body)
        if len(writes) == write_number:
            path.write_bytes(b'{"partial":')
            raise failure
        return original_write(path, body)

    monkeypatch.setattr(lineage, '_write', fail_write)
    with pytest.raises(ContractError, match='retained evidence is non-accepted') as caught:
        verifier.qualify(material, receipt, cell_binding=cell)
    assert caught.value.__cause__ is failure
    assert 'PRIVATE-' not in str(caught.value)
    assert len(calls) == callback_count and len(writes) == write_number
    assert receipt.read_bytes() == b'{"partial":'
    MaterialQualificationArtifacts.inspect(receipt)  # storage only, never a qualification
    with pytest.raises(ContractError):
        verifier.replay(material, receipt, cell_binding=cell)
    with pytest.raises(ContractError, match='already used'):
        verifier.qualify(material, receipt, cell_binding=cell)
    assert len(calls) == callback_count and len(writes) == write_number
    assert all(b'PRIVATE-FILESYSTEM-MESSAGE' not in p.read_bytes()
               for p in receipt.parent.rglob('*') if p.is_file())


def test_secondary_failure_does_not_replace_original_cause(tmp_path, monkeypatch):
    verifier, material, cell, calls = _subject(tmp_path)
    _retain(tmp_path, verifier, material, cell)
    receipt = tmp_path/'attempt'/'source.json'
    original = OSError('PRIVATE-ORIGINAL')

    def fail_write(path, body):
        path.write_bytes(b'{"partial":')
        raise original

    def fail_abort(self, exc):
        assert exc is original
        raise RuntimeError('PRIVATE-SECONDARY')

    monkeypatch.setattr(lineage, '_write', fail_write)
    monkeypatch.setattr(MaterialQualificationArtifacts, 'abort', fail_abort)
    with pytest.raises(ContractError) as caught:
        verifier.qualify(material, receipt, cell_binding=cell)
    assert caught.value.__cause__ is original and calls == []
    assert original.__notes__ == ['material failure storage incomplete: RuntimeError']
    assert 'PRIVATE-' not in str(caught.value)
    assert receipt.read_bytes() == b'{"partial":'
    with pytest.raises(ContractError):
        MaterialQualificationArtifacts.inspect(receipt)


def test_post_return_custody_failure_preserves_return_and_stops_before_next_call(tmp_path, monkeypatch):
    verifier, material, cell, calls = _subject(tmp_path)
    _retain(tmp_path, verifier, material, cell)
    receipt = tmp_path/'attempt'/'source.json'
    original_returned = MaterialQualificationArtifacts.returned
    failure = OSError('PRIVATE-POST-RETURN')

    def fail_after_return(self, authority, value):
        original_returned(self, authority, value)
        raise failure

    monkeypatch.setattr(MaterialQualificationArtifacts, 'returned', fail_after_return)
    with pytest.raises(ContractError) as caught:
        verifier.qualify(material, receipt, cell_binding=cell)
    assert caught.value.__cause__ is failure and len(calls) == 1
    _, rows, _, raw = MaterialQualificationArtifacts.inspect(receipt)
    returned = [row['data'] for row in rows if row['kind'] == 'returned']
    assert len(returned) == 1
    response = json.loads(raw(returned[0]['return']))
    assert response['body']['request_digest'] == verifier.request(material, cell).content_hash
    with pytest.raises(ContractError):
        verifier.replay(material, receipt, cell_binding=cell)
    assert len(calls) == 1


@pytest.mark.parametrize('fault', ['source_disagree', 'source_unknown', 'source_foreign', 'source_bool', 'source_exception'])
def test_admission_rejection_is_sealed_as_rejected_before_return(tmp_path, fault):
    _, state, cell, _ = _subject(tmp_path)
    body = state.data()
    body['schema'] = 'admission-combination-material-v1'
    body['withdrawals'] = []
    body['qualification_observations'] = {
        phase: {row['key']: {'effect': 1, 'calibration_error': 0} for row in body['originals']}
        for phase in ('before', 'after')}
    material = FrozenAdmissionMaterial(R(body))
    calls = []
    verifier = sources(calls, fault)
    _retain(tmp_path, verifier, material, cell)
    receipt = tmp_path/'attempt'/'source.json'
    with pytest.raises(ContractError):
        verifier.qualify(material, receipt, cell_binding=cell)
    _, rows, seal, _ = MaterialQualificationArtifacts.inspect(receipt)
    assert seal is not None and rows[-1]['kind'] == 'terminal'
    assert rows[-1]['data']['outcome'] == 'rejected'
    assert len(calls) == 2
    with pytest.raises(ContractError):
        verifier.replay(material, receipt, cell_binding=cell)
    assert len(calls) == 2
