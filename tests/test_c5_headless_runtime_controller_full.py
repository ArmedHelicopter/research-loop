"""Prepared, review-gated full C5 controller invocation using both headless ports.

This file is intentionally skipped.  Removing the marker spends the frozen
930 solver and 118 independent-evaluator synthetic opportunities exactly once;
it must follow profiling and review of the bounded probe.
"""
from pathlib import Path

import pytest

from evaluation.modular.scoring_service import ScorerConfig
from research_loop.modular.c5_selected_artifact_registration import register_authenticated_selected_run, verify_registration
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.joint_deployment import JointComponentVersion, JointDeploymentBundle
from research_loop.modular.joint_train_controller import run_joint_common_train, verify_joint_common_train_run
from research_loop.modular.modules.improvement import TrainingManifest
from test_train_adapted_selection import EXEC, SCORER

from test_c5_headless_runtime_integration import executor, prepare_headless_runtime
from test_headless_c5_evaluator_stdio import _client, _server


def _headless_scorer_factory(root, plan, evaluator):
    """Lazily build the production C5 stdio client only after the full barrier."""
    scorer = ScorerConfig(FrozenRecord.from_dict(plan.protocol.record.data()['scorer']))
    args = {'targets': [packet.task for packet in plan.packets], 'scorer': scorer}
    provider = plan.headless_evaluator_binding['evaluator_provider']
    factory_root = Path(root) / 'headless-full-scorer'
    factory_root.mkdir()

    def create(panel):
        config, handles = _server(factory_root, panel, args, evaluator)
        return _client(root=factory_root, panel=panel, scorer=scorer, server_path=config, handles=handles, provider=provider)
    return create


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
    assert receipt['actual']['model_calls'] == 930 and receipt['actual']['scorer_calls'] == 118
    assert receipt['evaluator_final_verification']['score_eligible'] is True
    assert verify_joint_common_train_run(run, execution_authority_keys={EXEC.authority_id: EXEC.key},
                                         scorer_authority_keys={SCORER.authority_id: SCORER.key}).data()['status'] == 'eligible'

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
    assert len(selected.components()) == 9
    for component in selected.components().values():
        assert set(TrainingManifest(FrozenRecord.from_dict(component.record.data()['training_manifest'])).identities()) == {
            plan.history.task.identity, *[packet.task.identity for packet in plan.packets]}
