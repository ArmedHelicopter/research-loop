"""Synthetic public-only checks for the legacy extended packet seam."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

import evaluation.modular.legacy_extended_packet_artifacts as artifacts
from evaluation.modular.custody import CustodyStore, InventoryItem
from evaluation.modular.extended_ingestion import ExtendedInventoryImporter, ExtendedTrainProjectionExporter
from research_loop.ontology import ContractError, digest
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.artifact_catalogue import ArtifactCatalogue


@pytest.fixture
def synthetic_snapshots(monkeypatch):
    from test_modular_extended_ingestion import synthetic_snapshots as fixture
    return fixture.__wrapped__(monkeypatch)


def _export(tmp_path, snapshots, source_data):
    from test_modular_extended_ingestion import _sources
    private = _sources(tmp_path, snapshots, source_data)
    source = CustodyStore(tmp_path/'source.json'); ExtendedInventoryImporter(private).import_into(source)
    eligible = [replace(InventoryItem.parse(row), exposure='exposed') for row in source.state['inventory']]
    custody = CustodyStore(tmp_path/'train.json'); custody.inventory(eligible); custody.split(seed='frozen')
    exporter = ExtendedTrainProjectionExporter(custody, private, tmp_path/'public')
    item = f"{custody.state['inventory'][0]['benchmark']}:{custody.state['inventory'][0]['task_id']}"
    task = exporter.export([item])[0]
    directory = exporter.output_root/task.identity.benchmark/digest(task.identity.data())
    return exporter, task, directory


def _source(directory):
    return FrozenRecord((directory/'packet-seal.json').read_text(encoding='utf-8').strip()).data()['binding']['source_sha256']


def test_reader_rejects_tamper_omission_and_unregistered_paths(tmp_path, synthetic_snapshots):
    exporter, task, directory = _export(tmp_path, *synthetic_snapshots)
    source = _source(directory)
    for name, action in (
        ('public.json', lambda p: p.write_bytes(p.read_bytes()+b' ')),
        ('receipt.json', lambda p: p.unlink()),
        ('escape.txt', lambda p: p.write_bytes(b'outside manifest')),
    ):
        exporter, task, directory = _export(tmp_path/name, *synthetic_snapshots)
        action(directory/name)
        with pytest.raises(ContractError): artifacts.verify_packet(directory, task, source)


def test_validation_is_denied_before_packet_directory_mutation(tmp_path, synthetic_snapshots):
    exporter, task, _ = _export(tmp_path, *synthetic_snapshots)
    invalid = replace(task.identity, domain='validation')
    target = exporter.output_root/invalid.benchmark/digest(invalid.data())
    with pytest.raises(ContractError):
        exporter._write(type(task)(invalid, task.payload), '0'*64)
    assert not target.exists()


def test_partial_write_is_sealed_as_storage_only(tmp_path, synthetic_snapshots, monkeypatch):
    from test_modular_extended_ingestion import _sources
    private = _sources(tmp_path, *synthetic_snapshots)
    source = CustodyStore(tmp_path/'source.json'); ExtendedInventoryImporter(private).import_into(source)
    eligible = [replace(InventoryItem.parse(row), exposure='exposed') for row in source.state['inventory']]
    custody = CustodyStore(tmp_path/'train.json'); custody.inventory(eligible); custody.split(seed='frozen')
    exporter = ExtendedTrainProjectionExporter(custody, private, tmp_path/'public')
    item = f"{custody.state['inventory'][0]['benchmark']}:{custody.state['inventory'][0]['task_id']}"
    original = artifacts._new
    def fail_receipt(path, raw):
        if Path(path).name == 'receipt.json': raise OSError('synthetic write failure')
        original(path, raw)
    monkeypatch.setattr(artifacts, '_new', fail_receipt)
    with pytest.raises(OSError): exporter.export([item])
    directory = next((tmp_path/'public').glob('*/*'))
    task = exporter._material_by_key({item.split(':')[0]})[item]
    # The typed task is reconstructed only from the public material, never a private record.
    from evaluation.modular.extended_ingestion import prepare_extended_public_task
    public_task = prepare_extended_public_task(custody.export_train()[0], task[0])
    checked = artifacts.verify_packet(directory, public_task, _source(directory)).data()
    assert checked['storage_verified'] and not checked['operation_validated'] and not checked['engineering_verified']


def test_expected_source_hash_mismatch_is_rejected(tmp_path, synthetic_snapshots):
    _, task, directory = _export(tmp_path, *synthetic_snapshots)
    with pytest.raises(ContractError): artifacts.verify_packet(directory, task, 'f'*64)
    with pytest.raises(ContractError): artifacts.verify_packet(directory/'..', task)


def _rewrite_catalogue(directory, task, change):
    """Recompute every local hash/seal after a malicious metadata change."""
    path=directory/artifacts._CAT
    records=[json.loads(line)['descriptor'] for line in path.read_text().splitlines()]
    packet=json.loads((directory/artifacts._SEAL).read_bytes())
    bindings=dict(records[0]['binding']); change(records,bindings)
    path.unlink(); (directory/artifacts._CAT_SEAL).unlink()
    cat=ArtifactCatalogue(path,identity=task.identity,**bindings); previous=None
    for row in records:
        new=cat.append(**{k:row[k] for k in ('kind','module','status','coverage','producer_source','config_refs','cost','checks','optimizer_visible')},
            payload=row['payload']['canonical'],parents=[] if previous is None else [previous])
        previous=new.content_hash
    packet['catalogue_seal']=cat.seal().data()
    (directory/artifacts._SEAL).write_bytes((FrozenRecord.from_dict(packet).encoded+'\n').encode())


def _failed_packet(tmp_path, snapshots, monkeypatch):
    exporter,task,good=_export(tmp_path/'original',*snapshots); source=_source(good)
    directory=tmp_path/'failed'; original=artifacts._new
    def fail(path,raw):
        if path.name=='receipt.json': raise OSError('controlled public receipt write failure')
        return original(path,raw)
    with monkeypatch.context() as patch:
        patch.setattr(artifacts,'_new',fail)
        with pytest.raises(OSError):
            artifacts.seal_packet(directory,task,source,(good/'public.json').read_bytes(),(good/'receipt.json').read_bytes())
    return directory,task,source


@pytest.mark.parametrize('fault',['omitted_file','wrong_source','wrong_lock'])
def test_rehashed_failed_packet_metadata_cannot_claim_storage_integrity(tmp_path,synthetic_snapshots,monkeypatch,fault):
    directory,task,source=_failed_packet(tmp_path,synthetic_snapshots,monkeypatch)
    def change(rows,bindings):
        if fault=='omitted_file': rows.pop(1)
        elif fault=='wrong_source': rows[1]['producer_source']=artifacts._sources()['exporter']
        else: bindings['lock_digest']='0'*64
    _rewrite_catalogue(directory,task,change)
    with pytest.raises(ContractError): artifacts.verify_packet(directory,task,source)


@pytest.mark.parametrize('fault',['empty','false_flag','boolean_substitution'])
def test_rehashed_public_receipt_must_match_exact_original_projection(tmp_path,synthetic_snapshots,fault):
    _,task,directory=_export(tmp_path,*synthetic_snapshots); source=_source(directory)
    receipt=json.loads((directory/'receipt.json').read_bytes())
    if fault=='empty': receipt={}
    else: receipt['public_projection_written']=False if fault=='false_flag' else 1
    (directory/'receipt.json').write_bytes((FrozenRecord.from_dict(receipt).encoded+'\n').encode())
    files=artifacts._files(directory)
    def change(rows,bindings):
        for row in rows:
            if row['kind']=='p0_legacy_extended_file': row['payload']['canonical']=files[row['payload']['canonical']['file']]
            if row['kind']=='p0_legacy_extended_terminal': row['payload']['canonical']['files']=files
    _rewrite_catalogue(directory,task,change)
    with pytest.raises(ContractError,match='public output'): artifacts.verify_packet(directory,task,source)


def test_actual_export_gate_blocks_returned_storage_only_failure(tmp_path,synthetic_snapshots,monkeypatch):
    exporter,task,good=_export(tmp_path/'original',*synthetic_snapshots); source=_source(good)
    exporter.output_root=tmp_path/'attempt'
    def return_closed_failure(directory,task,source,public,receipt):
        writer=artifacts.LegacyExtendedPacketArtifacts(directory,task,source)
        writer.stage='public'; writer.fail(OSError('fixture failed before public write'))
    monkeypatch.setattr(artifacts,'seal_packet',return_closed_failure)
    with pytest.raises(ContractError,match='usable training task'): exporter._write(task,source)


def test_seal_failure_preserves_original_exception_and_incomplete_prefix(tmp_path,synthetic_snapshots,monkeypatch):
    _,task,good=_export(tmp_path/'original',*synthetic_snapshots); source=_source(good)
    root=tmp_path/'attempt'; original=artifacts._new; error=OSError('controlled packet seal failure')
    def fail(path,raw):
        if path.name==artifacts._SEAL: raise error
        return original(path,raw)
    monkeypatch.setattr(artifacts,'_new',fail)
    with pytest.raises(OSError) as caught:
        artifacts.seal_packet(root,task,source,(good/'public.json').read_bytes(),(good/'receipt.json').read_bytes())
    assert caught.value is error and error.__notes__
    assert (root/'public.json').is_file() and (root/artifacts._CAT).is_file()
    with pytest.raises(ContractError): artifacts.verify_packet(root,task,source)
