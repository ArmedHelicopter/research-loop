import json
import hashlib
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.lineage_combination_material import FrozenLineageMaterial
from research_loop.modular import material_qualification_artifacts as artifacts_module
from research_loop.modular.material_qualification_artifacts import MaterialQualificationArtifacts
from research_loop.ontology import ContractError
from test_lineage_combination_controller import _fixture, _sources


def _subject(tmp_path, fault=None):
    calls = []
    verifier = _sources(calls, fault=fault)
    _, _, packets, config, _, _ = _fixture(tmp_path, verifier)
    material = FrozenLineageMaterial(FrozenRecord.from_dict(
        config.data()['materials_by_task'][packets[0].task.content_hash]))
    cell = FrozenRecord.from_dict({'cell_digest': 'a' * 64, 'scenario_digest': 'b' * 64})
    (tmp_path/'preproducer-inputs.json').write_bytes(FrozenRecord.from_dict({
        'material': material.record.data(), 'binding': verifier.binding().data(),
        'cell_binding': cell.data(), 'request': verifier.request(material, cell).data()}).encoded.encode())
    return verifier, material, cell, calls


def test_real_qualify_captures_overwritten_receipts_and_replay_never_calls_back(tmp_path):
    verifier, material, cell, calls = _subject(tmp_path)
    receipt = tmp_path / 'cell' / 'source-verification.json'
    digest = verifier.qualify(material, receipt, cell_binding=cell)
    assert len(calls) == 2 and digest
    root = receipt.with_name(receipt.name + '.artifacts')
    rows = [json.loads(line) for line in (root / 'journal.jsonl').read_text(encoding='utf-8').splitlines()]
    assert [row['kind'] for row in rows].count('reserved') == 2
    assert [row['kind'] for row in rows].count('sidecar_snapshot') == 4
    assert rows[0]['kind'] == 'begin' and rows[-1]['kind'] == 'terminal'
    assert verifier.replay(material, receipt, cell_binding=cell) == digest
    assert len(calls) == 2


def test_failed_callback_has_two_attempts_and_a_sealed_failure_record(tmp_path):
    verifier, material, cell, calls = _subject(tmp_path, 'exception')
    receipt = tmp_path / 'cell' / 'source-verification.json'
    with pytest.raises(ContractError):
        verifier.qualify(material, receipt, cell_binding=cell)
    assert len(calls) == 2
    rows = [json.loads(line) for line in receipt.with_name(receipt.name + '.artifacts').joinpath('journal.jsonl').read_text(encoding='utf-8').splitlines()]
    checked = [r['data'] for r in rows if r['kind'] == 'checked']
    assert checked[0]['status'] == 'failed' and checked[0]['error_chain'] == ['RuntimeError']
    assert (receipt.with_name(receipt.name + '.artifacts') / 'seal.json').is_file()


@pytest.mark.parametrize('target', ['receipt', 'snapshot', 'begin', 'seal'])
def test_independent_reader_rejects_tampering_without_rerunning_callbacks(tmp_path, target):
    verifier, material, cell, calls = _subject(tmp_path)
    receipt = tmp_path / 'cell' / 'source-verification.json'
    verifier.qualify(material, receipt, cell_binding=cell)
    root = receipt.with_name(receipt.name + '.artifacts')
    if target == 'receipt':
        receipt.write_bytes(receipt.read_bytes() + b' ')
    elif target == 'seal':
        (root / 'seal.json').write_text('{}\n', encoding='utf-8')
    else:
        row = json.loads((root / 'journal.jsonl').read_text(encoding='utf-8').splitlines()[0])
        ref = row['data']['request'] if target == 'begin' else next(json.loads(line)['data']['snapshot'] for line in (root / 'journal.jsonl').read_text(encoding='utf-8').splitlines() if json.loads(line)['kind'] == 'sidecar_snapshot')
        blob = root / 'blobs' / ref['sha256']; blob.write_bytes(b'tampered')
    with pytest.raises(ContractError, match='material artifact'):
        verifier.replay(material, receipt, cell_binding=cell)
    assert len(calls) == 2


def _original_and_attack(tmp_path):
    verifier, material, cell, calls = _subject(tmp_path)
    original = tmp_path/'original/source.json'
    verifier.qualify(material, original, cell_binding=cell)
    shutil.copytree(original.parent, tmp_path/'attack')
    return verifier, material, cell, calls, original, tmp_path/'attack/source.json'


def _reseal(root, rows):
    raw = b''.join((FrozenRecord.from_dict(row).encoded+'\n').encode() for row in rows)
    (root/'journal.jsonl').write_bytes(raw)
    seal = json.loads((root/'seal.json').read_bytes())
    seal['journal_sha256'] = hashlib.sha256(raw).hexdigest()
    (root/'seal.json').write_bytes((FrozenRecord.from_dict(seal).encoded+'\n').encode())


def _replace_blob(root, row, key, raw, rows):
    old = row[key]['sha256']; digest = hashlib.sha256(raw).hexdigest()
    (root/'blobs'/digest).write_bytes(raw)
    row[key] = {'sha256': digest, 'bytes': len(raw)}
    # Remove only an unreferenced leaf in this separate attack directory.
    if old not in json.dumps(rows): (root/'blobs'/old).unlink()


@pytest.mark.parametrize('fault', ['event_extra', 'data_extra', 'sequence_bool', 'missing_return',
    'untyped_return', 'authority', 'cost_bool', 'error_chain', 'terminal', 'attempt', 'sources_missing',
    'source_path', 'source_bytes', 'extra_blob', 'snapshot_whitespace', 'snapshot_order', 'snapshot_prior_row'])
def test_coherent_attacks_reject_and_leave_original_usable(tmp_path, fault):
    verifier, material, cell, calls, original, receipt = _original_and_attack(tmp_path)
    root = receipt.with_name(receipt.name+'.artifacts')
    rows = [json.loads(line) for line in (root/'journal.jsonl').read_bytes().splitlines()]
    if fault == 'event_extra': rows[4]['invented'] = True
    elif fault == 'data_extra': rows[4]['data']['invented'] = True
    elif fault == 'sequence_bool': rows[1]['sequence'] = True
    elif fault == 'missing_return':
        rows.pop(3)
        for n,row in enumerate(rows): row['sequence'] = n
    elif fault == 'untyped_return':
        data = rows[3]['data']; data.update(typed=False, return_type='FrozenRecord', capture='bounded_json')
    elif fault == 'authority': rows[4]['data']['authority'] = 'other'
    elif fault == 'cost_bool': rows[4]['data']['cost_units'] = True
    elif fault == 'error_chain': rows[4]['data']['error_chain'] = ['RuntimeError']
    elif fault == 'terminal': rows[-1]['data']['outcome'] = 'rejected'
    elif fault == 'attempt':
        rows[0]['data']['attempt_id'] = 'f'*32
        seal = json.loads((root/'seal.json').read_bytes()); seal['attempt_id'] = 'f'*32
        (root/'seal.json').write_bytes(FrozenRecord.from_dict(seal).encoded.encode())
    elif fault == 'sources_missing': rows[0]['data']['producer_sources'] = []
    elif fault == 'source_path': rows[0]['data']['producer_sources'][0]['path'] = 'elsewhere/material_qualification_artifacts.py'
    elif fault == 'source_bytes':
        _replace_blob(root, rows[0]['data']['producer_sources'][0], 'snapshot', b'# forged producer\n', rows)
    elif fault == 'extra_blob': (root/'blobs'/('0'*64)).write_bytes(b'orphan')
    elif fault == 'snapshot_whitespace':
        data = rows[1]['data']; old = (root/'blobs'/data['snapshot']['sha256']).read_bytes()
        _replace_blob(root, data, 'snapshot', old+b' ', rows)
    elif fault == 'snapshot_order': rows[1]['data'], rows[5]['data'] = rows[5]['data'], rows[1]['data']
    elif fault == 'snapshot_prior_row':
        data=rows[6]['data']; snap=json.loads((root/'blobs'/data['snapshot']['sha256']).read_bytes())
        snap['calls'][0]['cost_units']=0
        _replace_blob(root, data, 'snapshot', FrozenRecord.from_dict(snap).encoded.encode(), rows)
    _reseal(root, rows)
    with pytest.raises(ContractError, match='material artifact'):
        verifier.replay(material, receipt, cell_binding=cell)
    verifier.replay(material, original, cell_binding=cell)
    assert len(calls) == 2


@pytest.mark.parametrize('malformed', [None, [], 'bad', {'authority':'source-0'}])
def test_malformed_reader_fields_use_stable_contract_error(tmp_path, malformed):
    verifier, material, cell, calls, original, receipt = _original_and_attack(tmp_path)
    root=receipt.with_name(receipt.name+'.artifacts')
    rows=[json.loads(line) for line in (root/'journal.jsonl').read_bytes().splitlines()]
    rows[4]['data']=malformed; _reseal(root, rows)
    with pytest.raises(ContractError, match='non-accepted'): verifier.replay(material, receipt, cell_binding=cell)
    assert len(calls)==2


@pytest.mark.parametrize('target', ['receipt','journal.jsonl','seal.json','attempt.json','blob','blobs'])
def test_link_rejection_precedes_all_content_io(tmp_path, monkeypatch, target):
    verifier, material, cell, calls, original, receipt = _original_and_attack(tmp_path)
    root=receipt.with_name(receipt.name+'.artifacts')
    if target=='receipt': path=receipt
    elif target=='blob': path=next((root/'blobs').iterdir())
    else: path=root/target
    destination=tmp_path/'link-target'
    if path.is_dir():
        path.rename(destination)
    else:
        destination.write_bytes(path.read_bytes()); path.unlink()
    try: path.symlink_to(destination, target_is_directory=destination.is_dir())
    except OSError as exc: pytest.skip('symlink creation unavailable: '+type(exc).__name__)
    def forbidden_read(self): raise AssertionError('content read before link rejection')
    monkeypatch.setattr(Path, 'read_bytes', forbidden_read)
    with pytest.raises(ContractError, match='material artifact'): verifier.replay(material, receipt, cell_binding=cell)
    assert len(calls)==2


@pytest.mark.parametrize('fault', ['first_blob','producer_source','seal'])
def test_writer_failure_preserves_first_inputs_and_partial_storage(tmp_path, monkeypatch, fault):
    verifier, material, cell, calls = _subject(tmp_path)
    receipt=tmp_path/'attempt/source.json'; failure=OSError('PRIVATE-FAILURE-CONTENT')
    if fault=='first_blob':
        def fail_blob(self, raw):
            (self.blobs/('0'*64)).write_bytes(b'partial-blob')
            raise failure
        monkeypatch.setattr(MaterialQualificationArtifacts, '_put', fail_blob)
    elif fault=='producer_source':
        read=artifacts_module._read
        def fail_source(path):
            if path.name=='material_qualification_artifacts.py': raise failure
            return read(path)
        monkeypatch.setattr(artifacts_module, '_read', fail_source)
    else:
        def fail_seal(self, status):
            (self.root/'seal.json').write_bytes(b'{"partial":')
            raise failure
        monkeypatch.setattr(MaterialQualificationArtifacts, 'terminal', fail_seal)
    with pytest.raises(ContractError) as caught: verifier.qualify(material, receipt, cell_binding=cell)
    assert 'PRIVATE-' not in str(caught.value)
    attempt=json.loads((receipt.with_name(receipt.name+'.artifacts')/'attempt.json').read_bytes())
    assert attempt['material']==material.record.data() and attempt['request']==verifier.request(material,cell).data()
    root, rows, seal, raw=MaterialQualificationArtifacts.inspect(receipt)
    assert seal is None and (root/'failure.json').is_file()
    assert len(calls)==(2 if fault=='seal' else 0)
    with pytest.raises(ContractError): verifier.replay(material,receipt,cell_binding=cell)


def test_untyped_json_returns_retain_contents_and_arbitrary_objects_mark_type_only(tmp_path):
    verifier, material, cell, calls = _subject(tmp_path)
    class Unserializable:
        def __str__(self): raise AssertionError('must not stringify arbitrary returns')
        def __repr__(self): raise AssertionError('must not represent arbitrary returns')
    values=[{'malformed':['literal', 7]},Unserializable()]
    authorities=[]
    for authority,value in zip(verifier.authorities,values):
        def returned(request,value=value): calls.append(request); return value
        authorities.append(replace(authority,verify=returned))
    verifier=replace(verifier,authorities=tuple(authorities)); receipt=tmp_path/'attempt/source.json'
    with pytest.raises(ContractError): verifier.qualify(material,receipt,cell_binding=cell)
    root,rows,seal,raw=MaterialQualificationArtifacts.inspect(receipt)
    returns=[r['data'] for r in rows if r['kind']=='returned']
    assert returns[0]['capture']=='bounded_json' and json.loads(raw(returns[0]['return']))=={'value':values[0]}
    assert returns[1]['capture']=='type_only' and returns[1]['return'] is None
    assert len(calls)==2 and rows[-1]['data']['outcome']=='rejected'


def test_verified_unknown_cost_remains_unknown_without_replay_callbacks(tmp_path):
    verifier, material, cell, calls = _subject(tmp_path)
    authorities=[]
    for authority in verifier.authorities:
        def unknown(request, authority=authority):
            body=authority.verify(request).data()['body']; body['cost_units']=None
            return authority.authority.issue({k:v for k,v in body.items() if k!='authority'})
        authorities.append(replace(authority,verify=unknown))
    verifier=replace(verifier,authorities=tuple(authorities)); receipt=tmp_path/'attempt/source.json'
    digest=verifier.qualify(material,receipt,cell_binding=cell)
    assert all(row['cost_units'] is None and row['cost_unknown'] is True for row in json.loads(receipt.read_bytes())['calls'])
    assert verifier.replay(material,receipt,cell_binding=cell)==digest and len(calls)==2


@pytest.mark.parametrize('fault', ['attempt_id','whitespace'])
def test_failed_storage_marker_binds_original_attempt_and_exact_bytes(tmp_path,monkeypatch,fault):
    verifier,material,cell,calls=_subject(tmp_path); receipt=tmp_path/'original/source.json'
    from research_loop.modular import lineage_combination_material
    def fail_write(path,body): path.write_bytes(b'partial'); raise OSError('private synthetic marker')
    monkeypatch.setattr(lineage_combination_material,'_write',fail_write)
    with pytest.raises(ContractError): verifier.qualify(material,receipt,cell_binding=cell)
    MaterialQualificationArtifacts.inspect(receipt)
    shutil.copytree(receipt.parent,tmp_path/'attack'); attacked=tmp_path/'attack/source.json'
    path=attacked.with_name(attacked.name+'.artifacts')/'failure.json'
    if fault=='attempt_id':
        body=json.loads(path.read_bytes()); body['attempt_id']='f'*32
        path.write_bytes((FrozenRecord.from_dict(body).encoded+'\n').encode())
    else: path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ContractError): MaterialQualificationArtifacts.inspect(attacked)
    MaterialQualificationArtifacts.inspect(receipt)
    assert calls==[]
