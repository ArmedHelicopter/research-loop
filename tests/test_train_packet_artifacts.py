"""Actual primary and extended public exporters; no model or network calls."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from evaluation.modular.fresh_airs_custodian import CustodyError
from evaluation.modular.train_packet_artifacts import verify_train_export_artifacts
from research_loop.modular.artifact_catalogue import ArtifactCatalogue
from research_loop.modular.contracts import FrozenRecord, PublicTask
from research_loop.ontology import ContractError
from test_primary_prospective_exporter import setup_export as primary_setup
from test_prospective_train_exporter import setup_export as extended_setup
from test_primary_reference_bridge import material as reference_material

R = FrozenRecord.from_dict


def fixture(root, patch, kind):
    if kind == 'primary':
        exporter, items, _, _ = primary_setup(root)
    else:
        _, exporter, items, _, _ = extended_setup(root,patch)
    result = exporter.export(items)
    return exporter, items, result


@pytest.mark.parametrize('kind',['primary','extended'])
def test_real_export_files_and_batch_anchor_are_read_without_private_sources(tmp_path,monkeypatch,kind):
    exporter, items, result = fixture(tmp_path,monkeypatch,kind)
    assert result.receipt.data()['schema'] == 'prospective-train-export-receipt-v2'
    def forbid(*args,**kwargs): raise AssertionError('public provenance reader touched private I/O or wrote')
    for name in ('_allocation','_verify_audit_inputs','_verify_source_receipts','_read_selected'):
        monkeypatch.setattr(exporter,name,forbid)
    monkeypatch.setattr(ArtifactCatalogue,'append',forbid); monkeypatch.setattr(ArtifactCatalogue,'seal',forbid)
    opened = Path.open
    private = [exporter.sealed_root,Path(exporter._private_root()).resolve()]
    def public_read(self,mode='r',*args,**kwargs):
        if any(flag in mode for flag in ('w','a','x','+')): forbid()
        assert not any(self.absolute().is_relative_to(root) for root in private)
        return opened(self,mode,*args,**kwargs)
    monkeypatch.setattr(Path,'open',public_read)
    checked = verify_train_export_artifacts(exporter.output_root,result.receipt,result.tasks).data()
    assert len(checked['packets']) == 2 and checked['private_sources_read'] is False
    assert checked['scientific_validated'] is checked['validation_access_authorized'] is False
    assert len(checked['observed_public_files']) == (10 if kind == 'primary' else 8)
    anchors = result.receipt.data()['artifact_catalogues']
    assert [a['token'] for a in anchors] == [i.token for i in items]
    assert all('groups' not in a['binding'] and 'member_tokens' not in a['binding'] for a in anchors)
    assert all(a['binding']['validation_index_included'] is False for a in anchors)


def test_validation_task_is_rejected_before_any_file_read(tmp_path,monkeypatch):
    exporter,_,result=fixture(tmp_path,monkeypatch,'primary')
    invalid=PublicTask(replace(result.tasks[0].identity,domain='validation'),result.tasks[0].payload)
    def forbid(*args,**kwargs): raise AssertionError('VAL denial must precede reads')
    monkeypatch.setattr(Path,'read_bytes',forbid)
    with pytest.raises(ContractError,match='training provenance'):
        verify_train_export_artifacts(exporter.output_root,result.receipt,(invalid,result.tasks[1]))


@pytest.mark.parametrize('file',['public.json','data.csv','artifacts.jsonl','artifacts.jsonl.seal.json'])
def test_actual_output_tamper_is_refused_against_original_batch(tmp_path,monkeypatch,file):
    exporter,items,result=fixture(tmp_path,monkeypatch,'primary')
    path=exporter.output_root/items[0].token/file
    path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ContractError):
        verify_train_export_artifacts(exporter.output_root,result.receipt,result.tasks)


def test_actual_partial_write_failure_retains_files_and_redacted_P0_terminal(tmp_path,monkeypatch):
    exporter,items,_,_=primary_setup(tmp_path)
    original=exporter._write_public_packet
    def failing(*args):
        original(*args)
        raise OSError('PRIVATE_DYNAMIC_ERROR_GOLD')
    monkeypatch.setattr(exporter,'_write_public_packet',failing)
    with pytest.raises(CustodyError): exporter.export(items)
    assert not exporter.output_root.exists()
    root=next(exporter.audit_root.glob('attempt-*/staging'))/items[0].token
    rows=[json.loads(line)['descriptor'] for line in (root/'artifacts.jsonl').read_bytes().splitlines()]
    assert rows[-1]['status']=='failed'
    terminal=rows[-1]['payload']['canonical']
    assert set(terminal['files'])=={'public.json','data.csv'} and terminal['metadata'] is None
    assert 'PRIVATE_DYNAMIC' not in json.dumps(rows)
    assert (root/'artifacts.jsonl.seal.json').is_file()
    assert json.loads((exporter.audit_root/'exports.jsonl').read_bytes().splitlines()[-1])['event']=='export_failed'


def test_audit_writer_failure_preserves_exposure_and_unsealed_prefix(tmp_path,monkeypatch):
    exporter,items,_,_=primary_setup(tmp_path)
    append=ArtifactCatalogue.append
    def fail_file(self,**kwargs):
        if kwargs['kind']=='p0_public_export_file': raise OSError('PRIVATE_AUDIT_FAILURE')
        return append(self,**kwargs)
    monkeypatch.setattr(ArtifactCatalogue,'append',fail_file)
    with pytest.raises(CustodyError): exporter.export(items)
    assert not exporter.output_root.exists()
    root=next(exporter.audit_root.glob('attempt-*/staging'))/items[0].token
    assert (root/'public.json').is_file() and (root/'data.csv').is_file()
    assert len((root/'artifacts.jsonl').read_bytes().splitlines())==1
    assert not (root/'artifacts.jsonl.seal.json').exists()
    rows=[json.loads(line) for line in (exporter.audit_root/'exports.jsonl').read_bytes().splitlines()]
    assert rows[-1]['event']=='export_failed' and rows[-1]['possibly_exposed_tokens']==[items[0].token]


def test_reference_bridge_rechecks_catalogue_after_private_reference_reader_returns(tmp_path,monkeypatch):
    bridge,requests,packets,_=reference_material(tmp_path)
    original=bridge._reference_reader; changed=[]
    def mutate_after_read(*args):
        value=original(*args)
        if not changed:
            path=packets[0].packet_path.parent/'artifacts.jsonl'
            path.write_bytes(path.read_bytes()+b' '); changed.append(True)
        return value
    monkeypatch.setattr(bridge,'_reference_reader',mutate_after_read)
    with pytest.raises(CustodyError): bridge.prepare(requests,packets)
    assert changed and not bridge.store_root.exists()
