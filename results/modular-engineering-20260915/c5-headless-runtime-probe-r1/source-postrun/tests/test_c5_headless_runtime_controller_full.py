"""Prepared, review-gated full C5 controller invocation using both headless ports.

This file is intentionally skipped.  Removing the marker spends the frozen
930 solver and 118 independent-evaluator synthetic opportunities exactly once;
it must follow profiling and review of the bounded probe.
"""
from pathlib import Path
import hashlib
import json

import pytest

from evaluation.modular.scorer_process import headless_evaluator_descriptor
from evaluation.modular.scoring_service import ScorerConfig
from research_loop.modular.c5_selected_artifact_registration import register_authenticated_selected_run, verify_registration
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.joint_deployment import JointComponentVersion, JointDeploymentBundle
from research_loop.modular.joint_train_controller import run_joint_common_train
from research_loop.modular.modules.improvement import TrainingManifest
from test_train_adapted_selection import EXEC, SCORER

from test_c5_headless_runtime_integration import executor, prepare_headless_runtime
from test_headless_c5_evaluator_stdio import _client, _server
from test_joint_train_panel import panel_fixture
from test_scorer_process import _store


def _preflight_headless_scorer_inputs(root, plan, evaluator):
    """Check frozen descriptor and handles before the controller spends its grid."""
    root = Path(root)
    root.mkdir(parents=True)
    store, handles, manifest = _store(root, {'tasks': {packet.task.content_hash: packet.task for packet in plan.packets}})
    expected = {token: hashlib.sha256(value.encode()).hexdigest() for token, value in handles.items()}
    assert expected == plan.data()['scorer_handle_bindings']
    descriptor = headless_evaluator_descriptor(evaluator)
    assert descriptor['configuration_digest'] == plan.headless_evaluator_binding['evaluator_provider']['configuration_digest']
    return store, expected, manifest


def _headless_scorer_factory(root, plan, evaluator):
    """Lazily build the production C5 stdio client only after the full barrier."""
    scorer = ScorerConfig(FrozenRecord.from_dict(plan.protocol.record.data()['scorer']))
    args = {'targets': [packet.task for packet in plan.packets], 'scorer': scorer}
    provider = plan.headless_evaluator_binding['evaluator_provider']
    factory_root = Path(root) / 'headless-full-scorer'
    factory_root.mkdir()
    _preflight_headless_scorer_inputs(factory_root / 'preflight', plan, evaluator)

    def create(panel):
        config, handles = _server(factory_root, panel, args, evaluator)
        return _client(root=factory_root, panel=panel, scorer=scorer, server_path=config, handles=handles, provider=provider)
    return create


def test_headless_full_controller_factory_preflight_has_no_grid_dispatch(tmp_path, monkeypatch):
    """Server serialization, descriptor and exact handles are checked without C5 execution."""
    setup = prepare_headless_runtime(tmp_path, monkeypatch)
    plan = setup['common_plan']
    _, expected_handles, _ = _preflight_headless_scorer_inputs(tmp_path / 'preflight', plan, setup['evaluator'])
    panel_root = tmp_path / 'panel'; panel_root.mkdir()
    panel, args, _, _ = panel_fixture(panel_root, monkeypatch)
    evaluator = dict(setup['evaluator'])
    scorer_body = args['scorer'].record.data()
    evaluator.update(evaluator_id=scorer_body['evaluator_id'], evaluator_version=scorer_body['version'])
    server_root = tmp_path / 'server'; server_root.mkdir()
    server, handles = _server(server_root, panel, args, evaluator)
    server_body = json.loads(server.read_text(encoding='utf-8'))
    # This synthetic 177-cell panel is deliberately separate from the frozen
    # 118-cell C5 plan; it checks serializer shape without spending that plan.
    assert handles and server_body['task_handles'] == handles
    assert expected_handles == plan.data()['scorer_handle_bindings']
    assert server_body['evaluator']['provider_kind'] == 'grok-headless-frozen-evaluator-v1'
    assert 'PRIVATE-REFERENCE-SENTINEL' not in server.read_text(encoding='utf-8')
    assert not setup['common_calls'] and not setup['evaluator_prompts'] and not setup['evaluator_gets']


@pytest.mark.skip(reason='review-gated: do not launch 930 solver + 118 evaluator full grid without root profiling plan')
def test_full_headless_c5_controller_then_registers_selected_bundle(tmp_path, monkeypatch):
    """Future single-run path: controller, closure, verifier, selector, registration."""
    setup = prepare_headless_runtime(tmp_path, monkeypatch)
    runner = executor(setup)
    plan = runner.plan
    allocation = plan.protocol.record.data()['allocation']
    assert allocation['model_calls'] == 930 and allocation['target_cells'] == allocation['scorer_calls'] == 118
    run = run_joint_common_train(runner, scorer_factory=_headless_scorer_factory(tmp_path, plan, setup['evaluator']),
                                 execution_authority=EXEC, scorer_authority_keys={SCORER.authority_id: SCORER.key})
    receipt = run.receipt.data()
    assert len(run.builds) == 46 and len(run.targets) == len(run.scores) == len(run.panel.cells) == 118
    assert len(run.score_inputs) == 118 and all(row['status'] == 'scored' for row in receipt['targets'])
    assert receipt['actual']['model_calls'] == 930 and receipt['actual']['scorer_calls'] == 118
    assert receipt['status'] == 'complete_train_engineering' and receipt['final_provider_eligible'] is True
    assert receipt['evaluator_final_verification']['score_eligible'] is True

    protocol = plan.protocol.record.data()
    parent = JointDeploymentBundle.create(parent_digest=None, baseline_digest=protocol['baseline_digest'],
        p0_digest=protocol['p0_digest'], resource_schedule=FrozenRecord.from_dict({'stage': 'synthetic_preceding_snapshot'}),
        components={name: JointComponentVersion(FrozenRecord.from_dict(value))
                    for name, value in protocol['component_templates'].items()})
    path = tmp_path / 'registered-selected-bundle.json'
    registered = register_authenticated_selected_run(path, run, parent=parent,
        execution_authority_keys={EXEC.authority_id: EXEC.key}, scorer_authority_keys={SCORER.authority_id: SCORER.key})
    assert verify_registration(path, run, parent=parent, execution_authority_keys={EXEC.authority_id: EXEC.key},
                               scorer_authority_keys={SCORER.authority_id: SCORER.key}) == registered
    selected = JointDeploymentBundle(FrozenRecord.from_dict(registered.record.data()['snapshot']['bundle']))
    frozen = registered.record.data()['snapshot']
    choice = frozen['selection']
    assert selected.digest == frozen['bundle_digest'] and selected.parent_digest == parent.digest
    assert len(selected.components()) == 9
    assert choice['expected_cells'] == choice['scored_cells'] == 118
    assert len(choice['combination_candidates_retained']) == 58 and len(choice['b0_reference']) == 2
    assert choice['selected_arm'] != 'B0' and choice['b0_used_for_selection'] is False
    assert choice['selected_subject']['recipe']['id'] == choice['selected_arm']
    assert len(choice['selected_subject']['component_templates']) == 9
    assert choice['selected_subject']['package_digest'] == choice['selected_package_digest']
    assert choice['validation_access_authorized'] is choice['deployment_authorized'] is False
    assert frozen['validation_access_authorized'] is frozen['deployment_authorized'] is False
    for component in selected.components().values():
        assert set(TrainingManifest(FrozenRecord.from_dict(component.record.data()['training_manifest'])).identities()) == {
            plan.history.task.identity, *[packet.task.identity for packet in plan.packets]}
