"""Real custody/controller/model-port/host-Docker feasibility seam."""
from copy import deepcopy
import json

import pytest

from evaluation.modular.train_io import TrainPacketExporter
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.feasibility_panel_drivers import freeze_feasibility_panel_bundle
from research_loop.modular.panel_plan import obligation_grids, executable_arms
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.train_controller import FrozenTrainControllerConfig, run_train_panel
from research_loop.ontology import ContractError
from test_modular_feasibility_panel_drivers import _Authority, _item, _branches, _model
from test_modular_semantic_train_controller import _closed_shape
from test_modular_train_controller import config, snapshot_and_custody, model_port, FINAL


@pytest.mark.parametrize('coverage,expected_cells', [('Q5.1', 20), ('Q5.2', 16)])
def test_feasibility_full_grid_uses_only_exported_train_csv_and_real_port(tmp_path, monkeypatch, coverage, expected_cells):
    snapshot, custody = snapshot_and_custody(tmp_path)
    base = config(custody, snapshot, tmp_path).data()
    material = TrainPacketExporter(custody, snapshot, tmp_path/'material').export(base['item_ids'])
    authority = _Authority()
    bundles = {}
    for packet in material:
        task, csv = packet.task, packet.csv_path
        bundles[task.content_hash] = freeze_feasibility_panel_bundle(task,
            q51={name: _item(task, csv, authority, level=i) for i,name in enumerate(
                ('subjective', 'data', 'minimal_run', 'measurement', 'independent'))},
            q52={'zero_exit_same_prediction': _item(task, csv, authority, branches=_branches(False)),
                 'negative_control': _item(task, csv, authority, branches=_branches(True))}).data()
    grid = obligation_grids((coverage,), baseline_digest=base['baseline_digest'],
                            p0_control=FrozenRecord.from_dict(base['p0_control']))[coverage]
    package = next(iter(base['packages_by_arm'].values()))
    final_schema = deepcopy(FINAL)
    final_schema['properties']['outcome']['enum'] = ['unknown', 'invalid']
    schemas = {'subjective': _closed_shape({'feasibility': 'feasible', 'rationale': 'assessment'}),
               'diagnostic': _closed_shape({'decision': 'continue', 'rationale': 'observations'}),
               'final': final_schema}
    frozen = FrozenTrainControllerConfig(FrozenRecord.from_dict({**base,
        'schema': 'train-panel-controller-v1', 'engineering_scope': 'train_only_panel_engineering',
        'stage': 'feasibility-controller', 'scope_ids': [coverage], 'evidence_by_task': bundles,
        'packages_by_arm': {arm.content_hash: package for arm in executable_arms(grid).values()},
        'budget': {'model_calls': 3, 'execution_limit': 1}, 'max_calls': expected_cells*3, 'schemas': schemas}))
    seen = []
    port = model_port(tmp_path, monkeypatch, max_calls=expected_cells*3, schemas=schemas, response_factory=_model(seen))
    verifier = AuditVerifier({'a': b'a'*32, 'b': b'b'*32})
    with pytest.raises(ContractError, match='verification ports before export'):
        run_train_panel(frozen, custody=custody, snapshot_root=snapshot, export_root=tmp_path/'rejected-export',
            run_root=tmp_path/'rejected-run', model=port, audit_verifier=verifier)
    assert not (tmp_path/'rejected-export').exists() and not (tmp_path/'rejected-run').exists()
    assert len(port.ledger['calls']) == 0
    result = run_train_panel(frozen, custody=custody, snapshot_root=snapshot, export_root=tmp_path/'export',
        run_root=tmp_path/'run', model=port, audit_verifier=verifier, feasibility_authority=authority)
    assert len(result.runtimes) == expected_cells
    assert all(runtime.status == 'succeeded' for runtime in result.runtimes)
    assert len(seen) == len(port.ledger['calls']) == expected_cells*3
    assert len(authority.calls) == expected_cells*(4 if coverage == 'Q5.1' else 5)
    for runtime in result.runtimes:
        events = [json.loads(line) for line in runtime.trace_path.read_text().splitlines()]
        execution = next(e['data']['record'] for e in events if e['stage']=='execution_result')
        assert execution['status'] == 'succeeded'
        assert set(execution['input_artifacts']) == {'data_csv'}
        assert events[-1]['data']['scientific_validated'] is False
    assert result.receipt.data()['execution_status'] == 'engineering_complete'
    assert result.verdict.scientific_verified is False
