"""Full C5 controller integration using both synthetic headless ports.

The full test is opt-in because it executes 46 builds and 118 targets before
independent scoring and selection. The ordinary preparation test has no calls.
"""
from pathlib import Path
import hashlib
import json
import os

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


def test_headless_history_contract_failure_returns_closed_inconclusive_receipt(tmp_path, monkeypatch):
    """A failed history stage closes the full denominator without scorer use."""
    def malformed_first_plan(_setup, _history, _seen, fallback):
        def respond(request):
            if request.data()['slot'] == 'm4_plan':
                return {}
            return fallback(request)
        return respond

    setup = prepare_headless_runtime(tmp_path, monkeypatch, response_factory=malformed_first_plan)
    runner = executor(setup)
    plan = runner.plan

    def scorer_factory(_panel):
        raise AssertionError('scorer factory must not start without a complete history barrier')

    run = run_joint_common_train(runner, scorer_factory=scorer_factory,
                                 execution_authority=EXEC, scorer_authority_keys={SCORER.authority_id: SCORER.key})
    receipt = run.receipt.data()
    allocation = plan.protocol.record.data()['allocation']
    assert run.barrier is None and run.panel is None
    assert len(run.builds) == 1 and run.builds[0].record.data()['status'] == 'failed'
    assert len(run.targets) == allocation['target_cells'] == 118 and all(target is None for target in run.targets)
    assert len(run.scores) == len(run.score_inputs) == 0
    assert len(receipt['builds']) == allocation['unique_canonical_builds'] == 46
    assert receipt['builds'][0]['status'] == 'failed' and receipt['builds'][0]['reason'] == 'history_stage_failed'
    assert all(row['status'] == 'blocked' and row['reason'] == 'prior_history_failure_or_terminal'
               for row in receipt['builds'][1:])
    assert len(receipt['targets']) == 118
    assert all(row['status'] == 'blocked' and row['reason'] == 'complete_history_barrier_unavailable'
               for row in receipt['targets'])
    assert receipt['allocation'] == allocation and receipt['actual']['scorer_calls'] == 0
    assert receipt['final_provider_eligible'] is False and receipt['status'] == 'inconclusive'
    assert receipt['scorer_process']['startup_attempts'] == 0
    assert len(setup['common_calls']) == 1
    assert not setup['evaluator_prompts'] and not setup['evaluator_gets']


@pytest.mark.skipif(os.environ.get('RESEARCH_LOOP_RUN_FULL_C5_HEADLESS') != '1',
                    reason='set RESEARCH_LOOP_RUN_FULL_C5_HEADLESS=1 for the complete synthetic integration')
def test_full_headless_c5_controller_then_registers_selected_bundle(tmp_path, monkeypatch):
    """One full run: controller, closure, verifier, selector and registration."""
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
