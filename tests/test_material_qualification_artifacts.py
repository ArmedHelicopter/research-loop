import json

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.lineage_combination_material import FrozenLineageMaterial
from research_loop.ontology import ContractError
from test_lineage_combination_controller import _fixture, _sources


def _subject(tmp_path, fault=None):
    calls = []
    verifier = _sources(calls, fault=fault)
    _, _, packets, config, _, _ = _fixture(tmp_path, verifier)
    material = FrozenLineageMaterial(FrozenRecord.from_dict(
        config.data()['materials_by_task'][packets[0].task.content_hash]))
    cell = FrozenRecord.from_dict({'cell_digest': 'a' * 64, 'scenario_digest': 'b' * 64})
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
