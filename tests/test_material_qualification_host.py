"""Actual C5 -> C4 consumer seams; synthetic TRAIN model, real Docker."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.full_loo_driver import files
from research_loop.modular.joint_train_runtime import _stage_record
from research_loop.modular.lineage_combination_driver import _source_binding
from research_loop.modular.material_qualification_artifacts import MaterialQualificationArtifacts
from research_loop.ontology import ContractError
from test_joint_train_runtime import prepare, executor, full_recipe


R = FrozenRecord.from_dict


def _companion(receipt):
    return receipt.with_name(receipt.name + '.artifacts')


def _independent_inputs(setup):
    # Retain frozen inputs before either actual producer runs. The archive
    # reader must not invent expected subjects from the output being checked.
    plan = setup['common_plan']
    value = {'plan': plan.record.data(), 'protocol': plan.protocol.record.data(),
        'source_binding': setup['source'].binding().data(),
        'corpus_binding': setup['corpus'].binding().data()}
    (setup['root']/'qualification-host-inputs.json').write_bytes(R(value).encoded.encode())


def _tree_bytes(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_actual_history_target_consumers_reject_rehashed_qualification_history(tmp_path, monkeypatch):
    setup = prepare(tmp_path, monkeypatch)
    _independent_inputs(setup)
    runner = executor(setup)
    plan = setup['common_plan']
    recipe = full_recipe(plan)
    history = runner.execute(recipe_id=recipe['id'], stage='history_build')
    assert history.record.data()['status'] == 'succeeded', history.inner.record.data()
    runner.verify(history)
    target = runner.execute(recipe_id=recipe['id'], stage='target',
        target_digest=plan.packets[0].task.content_hash, build=history)
    assert target.record.data()['status'] == 'succeeded', target.inner.record.data()
    runner.verify(target)
    assert len(setup['common_logs']) == 11
    assert len(setup['state_calls']) == len(setup['corpus_calls']) == 4
    assert target.inner.solver.execution.record.data()['argv'][:4] == ['docker', 'run', '--pull', 'never']

    attempts = set()
    for stage in (history, target):
        material = plan.material(stage.inner.cell.task_digest)
        for role, subject, verifier in (('source', material.state(), setup['source']),
                                        ('corpus', material, setup['corpus'])):
            receipt = stage.inner.root/role/'source.json'
            companion = _companion(receipt)
            seal = json.loads((companion/'seal.json').read_bytes())
            attempts.add(seal['attempt_id'])
            assert verifier.replay(subject, receipt, cell_binding=_source_binding(stage.inner.cell)) == hashlib.sha256(receipt.read_bytes()).hexdigest()
            assert stage.inner.record.data()['files'][
                (companion/'seal.json').relative_to(stage.inner.root).as_posix()
            ] == hashlib.sha256((companion/'seal.json').read_bytes()).hexdigest()
    assert len(attempts) == 4

    original_tree = _tree_bytes(runner.root)
    # Recompute BOTH outer receipt levels so failure cannot be attributed to
    # a stale generic file hash. Preserve attacked copies and restore originals.
    for role in ('source', 'corpus'):
        for fault in ('attempt', 'missing_seal'):
            receipt = history.inner.root/role/'source.json'
            seal_path = _companion(receipt)/'seal.json'
            outer_path = runner.root/(history.record.data()['trial_id']+'-stage.json')
            inner_path = history.inner.root/'receipt.json'
            originals = {p: p.read_bytes() for p in (seal_path, inner_path, outer_path)}
            try:
                if fault == 'attempt':
                    seal = json.loads(originals[seal_path])
                    seal['attempt_id'] = '0'*32 if seal['attempt_id'] != '0'*32 else '1'*32
                    seal_path.write_bytes((R(seal).encoded+'\n').encode())
                else:
                    seal_path.unlink()
                inner_record = R({**history.inner.record.data(), 'files': files(history.inner.root)})
                inner_path.write_bytes(inner_record.encoded.encode())
                inner = replace(history.inner, record=inner_record)
                forged = replace(history, inner=inner,
                    record=_stage_record(plan, inner, history.ledger, history.barrier, status='succeeded'))
                outer_path.write_bytes(forged.record.encoded.encode())
                runner.stages[0] = forged
                replica = tmp_path/'attack-replicas'/(role+'-'+fault)
                replica.mkdir(parents=True)
                shutil.copy2(receipt, replica/receipt.name)
                shutil.copytree(_companion(receipt), replica/_companion(receipt).name)
                (replica/'attack.json').write_bytes(R({'role': role, 'fault': fault,
                    'cell_binding': _source_binding(history.inner.cell).data(),
                    'task_digest': history.inner.cell.task_digest,
                    'inner_receipt': inner_record.data(), 'outer_receipt': forged.record.data()}).encoded.encode())
                with pytest.raises(ContractError, match='material artifact'):
                    runner.verify(forged)
            finally:
                for path, raw in originals.items():
                    path.write_bytes(raw)
                runner.stages[0] = history
    runner.verify(history)
    runner.verify(target)
    assert _tree_bytes(runner.root) == original_tree
    assert len(setup['common_logs']) == 11
    assert len(setup['state_calls']) == len(setup['corpus_calls']) == 4
    checkpoint = json.loads((runner.root/'checkpoint.json').read_bytes())
    assert checkpoint['complete_grid_executed'] is checkpoint['score_eligible'] is False
    assert sum(r['status'] == 'succeeded' for r in checkpoint['rows']) == 2


@pytest.mark.parametrize('role', ['source', 'corpus'])
def test_missing_qualification_seal_blocks_actual_host_before_model(tmp_path, monkeypatch, role):
    setup = prepare(tmp_path, monkeypatch)
    _independent_inputs(setup)
    runner = executor(setup)
    # This shared qualifier also runs with M1 disabled. Failure is still a P0
    # custody failure; it must not be credited as enabled M1 behavior.
    recipe = next(r for r in runner.plan.recipes if r['id'] == 'ordinary-control')
    original_verify = MaterialQualificationArtifacts.verify
    withheld = []

    def missing_seal(receipt, **kwargs):
        receipt = Path(receipt)
        if receipt.parent.name == role and not withheld:
            seal_path = _companion(receipt)/'seal.json'
            raw = seal_path.read_bytes()
            preserved = tmp_path/'withheld-seals'/role/'seal.json'
            preserved.parent.mkdir(parents=True)
            preserved.write_bytes(raw)
            seal_path.unlink()
            withheld.append(str(seal_path))
        return original_verify(receipt, **kwargs)

    monkeypatch.setattr(MaterialQualificationArtifacts, 'verify', staticmethod(missing_seal))
    result = runner.execute(recipe_id=recipe['id'], stage='history_build')
    assert result.record.data()['status'] == 'failed'
    assert 'material artifact' in result.inner.record.data()['reason']
    assert runner.poisoned is True and not setup['common_logs']
    assert len(setup['state_calls']) == 2
    assert len(setup['corpus_calls']) == (2 if role == 'corpus' else 0)
    assert withheld and not (result.inner.root/'runtime').exists()
    with pytest.raises(ContractError, match='terminal'):
        runner.execute(recipe_id=recipe['id'], stage='history_build')
    assert not setup['common_logs']
