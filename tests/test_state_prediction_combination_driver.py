"""Functional synthetic checks for the bounded M2/M3-to-M4 driver seam."""
from pathlib import Path

from research_loop.modular.combination_panels import CombinationPanel
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.panel_receipts import PanelCell
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.state_prediction_combination_driver import (
    DESIGNS, registered_design, run_state_prediction_combination_cell,
    verify_state_prediction_combination_cell,
)
from test_lineage_combination_controller import _fixture, _sources
from test_modular_combination_benchmark_driver import _model, IMAGE


def _panel(root, obligation):
    sources = _sources([]); _, _, packets, config, _, _ = _fixture(root, sources)
    design = registered_design(obligation, config.data()['baseline_digest'])
    legacy_packages = config.data()['packages_by_arm']; materials = config.data()['materials_by_task']
    cells, scenarios = [], {}
    arms = {r['id']: FrozenRecord.from_dict(r['arm']) for r in design.data()['cells'] if r['status'] == 'executable'}
    for packet in packets:
        for arm_id, arm in arms.items():
            scenario = FrozenRecord.from_dict({'schema':'state-prediction-combination-scenario-v1',
                'obligation_id':obligation, 'design_digest':design.content_hash, 'task_digest':packet.task.content_hash,
                'replicate':'r1', 'material_digest':FrozenRecord.from_dict(materials[packet.task.content_hash]).content_hash})
            cell = PanelCell(obligation, packet.task.identity, 'r1', 'combination', arm_id, arm, packet.task.content_hash,
                scenario.content_hash, FrozenRecord.from_dict(next(iter(legacy_packages.values()))).content_hash,
                FrozenRecord.from_dict(config.data()['scorer']).content_hash)
            cells.append(cell); scenarios[cell.key] = scenario
    packages = {arm.content_hash: next(iter(legacy_packages.values())) for arm in arms.values()}
    panel = CombinationPanel('synthetic-state-prediction', 'train', packets[0].task.identity.split_id, obligation,
        'interaction_on_scale', design, FrozenRecord.from_dict({'schema':'combination-package-bundle-v1','packages':packages}),
        FrozenRecord.from_dict(config.data()['acceptance_criteria']), tuple(cells))
    return panel, packets, packages, materials, sources, scenarios


def test_registered_scope_and_m3_fixed_background():
    assert set(DESIGNS) == {'pair:M1+M4','pair:M2+M4','pair:M3+M4'}
    cells = registered_design('pair:M3+M4', 'a'*64).data()['cells']
    assert all('M2' in row['arm']['enabled'] for row in cells if row['status'] == 'executable')


def test_m2_m4_and_m3_m4_use_actual_registry_then_shared_docker(tmp_path):
    for obligation in ('pair:M2+M4', 'pair:M3+M4'):
        panel, packets, packages, materials, sources, scenarios = _panel(tmp_path/obligation.replace(':', '_'), obligation)
        # Exercise one M4-on and one M4-off cell on the same public task.
        for arm_id in ('00', '01'):
            cell = next(c for c in panel.cells if c.identity.benchmark == 'blade' and c.arm_id == arm_id)
            packet = next(p for p in packets if p.task.content_hash == cell.task_digest)
            root = tmp_path/obligation.replace(':', '_')/arm_id
            result = run_state_prediction_combination_cell(panel=panel, cell=cell, task=packet.task,
                scenario=scenarios[cell.key], package=__import__('research_loop.modular.modules.improvement', fromlist=['CandidatePackage']).CandidatePackage(FrozenRecord.from_dict(packages[cell.runtime_arm.content_hash])),
                material=__import__('research_loop.modular.lineage_combination_material', fromlist=['FrozenLineageMaterial']).FrozenLineageMaterial(FrozenRecord.from_dict(materials[cell.task_digest])),
                source_verifier=sources, objective=FrozenRecord.from_dict({'scope':'synthetic state prediction'}), sidecar=root,
                public_inputs={'public_csv':packet.csv_path}, image=IMAGE, broker=DockerExecutionBroker([tmp_path]), model=_model([]),
                audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}))
            assert result.runtime.status == 'succeeded'
            verified = verify_state_prediction_combination_cell(result, panel=panel, task=packet.task,
                scenario=scenarios[cell.key], package=__import__('research_loop.modular.modules.improvement', fromlist=['CandidatePackage']).CandidatePackage(FrozenRecord.from_dict(packages[cell.runtime_arm.content_hash])),
                material=__import__('research_loop.modular.lineage_combination_material', fromlist=['FrozenLineageMaterial']).FrozenLineageMaterial(FrozenRecord.from_dict(materials[cell.task_digest])),
                source_verifier=sources, public_inputs={'public_csv':packet.csv_path}, broker=DockerExecutionBroker([tmp_path]))
            assert verified.data()['scientific_effect'] == 'not_measured'
            logs = result.runtime.trace_path.parent
            assert bool((logs/'predictions.jsonl').read_text(encoding='utf-8').strip()) == ('M4' in cell.runtime_arm.data()['enabled'])
