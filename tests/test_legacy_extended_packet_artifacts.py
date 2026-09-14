"""Synthetic public-only checks for the legacy extended packet seam."""
from dataclasses import replace
from pathlib import Path

import pytest

import evaluation.modular.legacy_extended_packet_artifacts as artifacts
from evaluation.modular.custody import CustodyStore, InventoryItem
from evaluation.modular.extended_ingestion import ExtendedInventoryImporter, ExtendedTrainProjectionExporter
from research_loop.ontology import ContractError, digest
from research_loop.modular.contracts import FrozenRecord


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
