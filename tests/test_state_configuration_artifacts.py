"""Actual 11-build/22-target graph, using synthetic peers and real Docker."""
from pathlib import Path
import json

import pytest

from research_loop.modular.artifact_catalogue import ArtifactCatalogue
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.modules.improvement import RestrictedBuilderPort
from research_loop.modular.state_configuration_artifacts import verify_state_configuration
from research_loop.ontology import ContractError
from test_state_improvement_train_controller import grid

R = FrozenRecord.from_dict


def args_for(run, result):
    return dict(trace_path=result.runtime.trace_path, barrier=run.barrier, cell=result.cell,
        package=run.barrier.package(result.cell.coverage_id, result.cell.arm_id))


def test_real_grid_binds_all_22_targets_to_their_exact_11_original_builds(grid, monkeypatch):
    setup, run = grid
    body = run.receipt.data()
    assert body['status'] == 'complete_train_engineering', body
    assert len(run.builds) == 11 and len(run.results) == len(run.scores) == 22
    assert len(setup['seen']) == 55 and body['actual_docker_attempts'] == body['actual_scorer_calls'] == 22
    assert len(body['structural_exclusions']) == 2 and body['pruned_cells'] == []
    assert body['scientific_effectiveness_proven'] is body['validation_opened'] is False
    before = {p: p.read_bytes() for result in run.results for p in result.runtime.trace_path.parent.iterdir() if p.is_file()}
    def forbidden(*args, **kwargs):
        raise AssertionError('graph readback must not execute or write')
    monkeypatch.setattr(RestrictedBuilderPort, 'execute', forbidden)
    monkeypatch.setattr(ArtifactCatalogue, 'append', forbidden)
    monkeypatch.setattr(ArtifactCatalogue, 'seal', forbidden)
    opened = Path.open
    def read_only(self, mode='r', *args, **kwargs):
        if any(flag in mode for flag in ('w', 'a', 'x', '+')): forbidden()
        return opened(self, mode, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', read_only)
    sources = set(); inactive = 0
    for result in run.results:
        checked = verify_state_configuration(**args_for(run, result))
        assert checked.data()['relation'] == 'configured_by'
        assert checked.data()['scientific_validated'] is checked.data()['task_evidence_support'] is False
        row = json.loads((result.runtime.trace_path.parent/'artifacts.jsonl').read_bytes().splitlines()[1])['descriptor']
        source = row['payload']['canonical']['source']; sources.add(source['path'])
        assert source['identity'] == run.barrier.plan.history.task.identity.data()
        assert source['identity'] != result.cell.identity.data()
        assert source['recipe']['pair'] == result.cell.coverage_id and source['recipe']['arm_id'] == result.cell.arm_id
        assert source['candidate_digest'] == result.cell.package_digest
        if 'M9' not in result.cell.runtime_arm.data()['enabled']:
            inactive += 1
            assert row['status'] == 'not_applied'
        else:
            assert row['status'] == 'produced'
    assert len(sources) == 11 and inactive == 10
    assert all(p.read_bytes() == raw for p, raw in before.items())


def _rehash(path, mutate):
    rows = [json.loads(line) for line in path.read_bytes().splitlines()]
    previous = None; remap = {}; rewritten = []
    for row in rows:
        body = row['descriptor']; old = row['descriptor_digest']
        if body['kind'] == 'state_train_configuration_use':
            mutate(body['payload']['canonical'])
            payload = R(body['payload']['canonical'])
            body['payload'] = {'digest': payload.content_hash, 'canonical': payload.data(),
                'encoding': 'canonical_json', 'bytes': len(payload.encoded.encode('utf-8'))}
        body['parents'] = [remap.get(parent, parent) for parent in body['parents']]
        row['descriptor_digest'] = R(body).content_hash; remap[old] = row['descriptor_digest']
        row['previous'] = previous; record = R(row); rewritten.append(record.encoded+'\n'); previous = record.content_hash
    path.write_bytes(''.join(rewritten).encode('utf-8'))
    sealpath = path.with_name(path.name+'.seal.json')
    seal = json.loads(sealpath.read_bytes()); seal['head'] = previous
    sealpath.write_bytes((R(seal).encoded+'\n').encode('utf-8'))


@pytest.mark.parametrize('fault', ['evidence_relation', 'foreign_path', 'validation_identity', 'recipe'])
def test_coherently_resealed_cross_task_or_configuration_substitution_is_rejected(grid, fault, monkeypatch):
    _, run = grid; result = run.results[0]
    path = result.runtime.trace_path.parent/'artifacts.jsonl'; seal = path.with_name(path.name+'.seal.json')
    original = path.read_bytes(), seal.read_bytes()
    def change(body):
        if fault == 'evidence_relation': body['relation'] = 'supports'
        elif fault == 'foreign_path': body['source']['path'] = str(run.root/'validation-must-never-be-opened.jsonl')
        elif fault == 'validation_identity': body['source']['identity']['domain'] = 'validation'
        else: body['source']['recipe']['arm_id'] = 'another-build-with-identical-package'
    try:
        _rehash(path, change)
        read = Path.read_bytes
        def observed_read(self):
            assert self.name != 'validation-must-never-be-opened.jsonl'
            return read(self)
        monkeypatch.setattr(Path, 'read_bytes', observed_read)
        with pytest.raises(ContractError, match='configuration edge differs'):
            verify_state_configuration(**args_for(run, result))
    finally:
        path.write_bytes(original[0]); seal.write_bytes(original[1])


@pytest.mark.parametrize('end', ['source', 'target'])
def test_deleted_external_or_target_seal_cannot_be_recreated_by_readback(grid, end):
    _, run = grid; result = run.results[0]
    target = result.runtime.trace_path.parent/'artifacts.jsonl'
    row = json.loads(target.read_bytes().splitlines()[1])['descriptor']['payload']['canonical']
    path = Path(row['source']['path']) if end == 'source' else target
    seal = path.with_name(path.name+'.seal.json'); original = seal.read_bytes()
    # Move the exact existing seal aside; never delete a whole runtime directory.
    backup = seal.with_name(seal.name+'.test-preserved')
    assert not backup.exists()
    seal.rename(backup)
    try:
        with pytest.raises(ContractError, match='sealed catalogue'):
            verify_state_configuration(**args_for(run, result))
        assert not seal.exists()
    finally:
        backup.rename(seal)
    assert seal.read_bytes() == original
