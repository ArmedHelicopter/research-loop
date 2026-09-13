"""Custody export through production exploration registration, without registry patches."""
from copy import deepcopy
import json

import pytest

from evaluation.modular.train_io import TrainPacketExporter
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.exploration_panel_drivers import BUDGET, Q72_VARIANTS, freeze_exploration_panel_bundle
from research_loop.modular.panel_plan import obligation_grids, executable_arms
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.train_controller import FrozenTrainControllerConfig, run_train_panel
from research_loop.ontology import ContractError
from test_modular_exploration_panel_drivers import Authority, _item, _model
from test_modular_semantic_train_controller import _closed_shape
from test_modular_train_controller import config, snapshot_and_custody, model_port, FINAL


def _frozen(root):
    snapshot, custody = snapshot_and_custody(root, csv_text='x\n-2\n0\n')
    base = config(custody, snapshot, root).data()
    packets = TrainPacketExporter(custody, snapshot, root/'material').export(base['item_ids'])
    authority, bundles = Authority(), {}
    for packet in packets:
        task, csv = packet.task, packet.csv_path
        q71 = {'low_cost': _item(task, csv, authority),
               'data_unknown': _item(task, csv, authority, data_known=False),
               'measurement_repair': _item(task, csv, authority, repair=True),
               'valid_negative': _item(task, csv, authority, qualified=True),
               'conflict': _item(task, csv, authority, conflict=True)}
        q72 = {name: _item(task, csv, authority, kind=kind, repair=name != 'value',
                          hard='contract' if name == 'deterministic' else 'none')
               for name, kind in zip(Q72_VARIANTS, ('deterministic_block', 'evidence_insufficient', 'value_doubt'))}
        bundles[task.content_hash] = freeze_exploration_panel_bundle(
            task, q71=q71, q72=q72, budget=FrozenRecord.from_dict(BUDGET)).data()
    grids = obligation_grids(('Q7.1', 'Q7.2'), baseline_digest=base['baseline_digest'],
                            p0_control=FrozenRecord.from_dict(base['p0_control']))
    package = next(iter(base['packages_by_arm'].values()))
    final = deepcopy(FINAL)
    final['properties']['outcome']['enum'] = ['unknown', 'invalid', 'positive', 'negative']
    common = {'decision': 'explore', 'exploration_allowed': True, 'evidence_qualified': False, 'rationale': 'public'}
    schemas = {'prospective': _closed_shape({'diagnostic_id': 'small_probe', **common}),
               'diagnostic': _closed_shape(common), 'final': final}
    frozen = FrozenTrainControllerConfig(FrozenRecord.from_dict({**base,
        'schema': 'train-panel-controller-v1', 'engineering_scope': 'train_only_panel_engineering',
        'stage': 'exploration-custody-controller', 'scope_ids': ['Q7.1', 'Q7.2'],
        'evidence_by_task': bundles, 'budget': BUDGET, 'schemas': schemas, 'max_calls': 156, 'max_tokens': 400,
        'packages_by_arm': {arm.content_hash: package for grid in grids.values() for arm in executable_arms(grid).values()}}))
    return snapshot, custody, frozen, authority


def test_complete_exploration_grid_uses_real_export_ports_and_fixed_p0(tmp_path, monkeypatch):
    snapshot, custody, frozen, authority = _frozen(tmp_path)
    seen = []
    port = model_port(tmp_path, monkeypatch, max_calls=156, max_tokens=400,
                      schemas=frozen.data()['schemas'], response_factory=_model(seen))
    verifier = AuditVerifier({'a': b'a'*32, 'b': b'b'*32})
    with pytest.raises(ContractError, match='verification ports before export'):
        run_train_panel(frozen, custody=custody, snapshot_root=snapshot, export_root=tmp_path/'rejected-export',
                        run_root=tmp_path/'rejected-run', model=port, audit_verifier=verifier)
    assert not (tmp_path/'rejected-export').exists() and not (tmp_path/'rejected-run').exists()
    assert port.ledger['calls'] == [] and authority.calls == []
    result = run_train_panel(frozen, custody=custody, snapshot_root=snapshot, export_root=tmp_path/'export',
                            run_root=tmp_path/'run', model=port, audit_verifier=verifier, exploration_authority=authority)
    assert len(result.runtimes) == len(result.compiled.panel.cells) == 52
    assert len(seen) == len(port.ledger['calls']) == 156
    assert len(authority.calls) == 104
    assert all(runtime.status == 'succeeded' for runtime in result.runtimes)
    assert result.receipt.data()['execution_status'] == 'engineering_complete'
    assert result.verdict.scientific_verified is False
    for runtime in result.runtimes:
        events = [json.loads(line) for line in runtime.trace_path.read_text().splitlines()]
        execution = next(e['data']['record'] for e in events if e['stage'] == 'execution_result')
        assert execution['status'] == 'succeeded' and set(execution['input_artifacts']) == {'data_csv'}
        assert sum(e['stage'] == 'exploration_verifier_request' for e in events) == 2


def test_foreign_input_declaration_rejected_before_any_panel_call(tmp_path, monkeypatch):
    snapshot, custody, frozen, authority = _frozen(tmp_path)
    data = frozen.data()
    bundle = next(iter(data['evidence_by_task'].values()))
    bundle['q72']['value']['diagnostics'][1]['inputs']['data_csv']['sha256'] = '0'*64
    frozen = FrozenTrainControllerConfig(FrozenRecord.from_dict(data))
    port = model_port(tmp_path, monkeypatch, max_calls=156, max_tokens=400, schemas=data['schemas'])
    with pytest.raises(ContractError, match='differs from exported train CSV bytes'):
        run_train_panel(frozen, custody=custody, snapshot_root=snapshot, export_root=tmp_path/'export',
                        run_root=tmp_path/'run', model=port, audit_verifier=AuditVerifier({'a': b'a'*32, 'b': b'b'*32}),
                        exploration_authority=authority)
    assert port.ledger['calls'] == [] and authority.calls == []
    assert json.loads((tmp_path/'run/controller-attempt.json').read_text())['status'] == 'execution_interrupted'
