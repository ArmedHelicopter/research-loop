"""Bounded C5 native-headless runtime probe; it deliberately does not run C5's full grid.

The test exercises one real history build and one real target through the
production stage executor, using the synthetic native peers.  The frozen plan
still contains the complete 46-build/59-recipe/two-target C5 allocation so a
future controller invocation cannot silently shrink the denominator.
"""
import json

import pytest

from evaluation.modular.scorer_process import headless_evaluator_descriptor
from evaluation.modular.scoring_service import ScorerConfig
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.full_loo_composition import derive_allocation
from research_loop.modular.full_loo_modules import MEASUREMENT, model_schemas
from research_loop.modular.joint_train_protocol import (
    FrozenJointTrainProtocol, HEADLESS_OBLIGATION, OBLIGATION, common_recipes,
)
from research_loop.modular.joint_train_runtime import FrozenJointTrainRuntimePlan, component_templates, runtime_sources
from research_loop.modular.phase_provider import provider_configuration
from research_loop.modular.train_provider import GrokHeadlessTrainProvider
from research_loop.modular.train_selection import FrozenTrainSelectionRule
from research_loop.ontology import ContractError
from test_full_loo_runtime import AUDIT, Provider
from test_headless_evaluator_factory import native_spec
from test_joint_train_runtime import full_recipe
from test_modular_combination_benchmark_driver import _plan
from tests.helpers.headless_train_provider import headless_train_provider


R = FrozenRecord.from_dict


def _response(setup, history, seen):
    def respond(request):
        body = request.data()
        seen.append(body)
        context, slot = body['module_context'], body['slot']
        assert all(value not in request.encoded for value in ('PRIVATE-REFERENCE-SENTINEL', '"arm_id"', '"enabled"'))
        if body['task'] == history.task.data():
            assert all(packet.task.content_hash not in request.encoded for packet in setup['packets'])
        if slot == 'm4_plan':
            value = _plan()
            for branch in value['branches']:
                for prediction in branch['predictions']:
                    prediction.update(observable=MEASUREMENT['observable'], discriminator_id=MEASUREMENT['discriminator_id'])
            return value
        if slot.startswith('review_'):
            return {'assessment': 'concern', 'evidence_refs': ['public statistic'],
                    'counterexamples': ['Check range'], 'uncertainty': 'Check outlier'}
        if slot == 'bounded_choice':
            return {'job_id': context['alternative_checks'][-1]['id'],
                    'rationale': 'Check range after forecasts and reviews.'}
        if slot in ('builder_proposal', 'ordinary_revision'):
            value = 'Use public statistic ' + str(sum(json.loads(row['stdout'])['statistic']
                                                       for row in context['execution_observations']))
            return ({'entrypoint': 'emit_literal_change_v1', 'surface': 'prompt', 'key': 'instructions', 'value': value}
                    if slot == 'builder_proposal' else {'instructions': value})
        if slot == 'analysis_program':
            assert context['joint_mechanism']['candidate_context']['instructions'].startswith('Use public statistic')
            return {'analysis': 'Check current public mean using built guidance.',
                    'program': "import csv,json\nwith open('/input/public_csv') as f: xs=[float(r['x']) for r in csv.DictReader(f)]\nprint(json.dumps({'statistic':sum(xs)/len(xs)}))"}
        return {'objective_digest': context['required_objective_digest'], 'outcome': 'unknown', 'evidence_ids': [],
                'conclusion': 'Synthetic observed ' + body['execution_feedback'][0]['stdout'], 'programme_complete': False}
    return respond


def prepare_headless_runtime(root, patch, *, response_factory=None):
    """Reuse the actual C5 fixture originals, then replace only the provider ports."""
    import test_execution_improvement_train_controller as history_fixture
    from test_full_loo_runtime import prepare as old_prepare

    original_primary, identity_type, split = history_fixture.prepared_primary, history_fixture.DataIdentity, []

    def primary(path):
        prepared = original_primary(path)
        split.append(prepared[3][0].task.identity.split_id)
        return prepared

    def identity(benchmark, task, group, version, old_split, domain):
        return identity_type(benchmark, task, group, version,
                             split[0] if task == 'closed-history' else old_split, domain)

    patch.setattr(history_fixture, 'prepared_primary', primary)
    patch.setattr(history_fixture, 'DataIdentity', identity)
    setup = old_prepare(root, patch)
    old, history, seen = setup['plan'], setup['plan'].history, []
    recipes = [row['recipe'] for row in common_recipes(
        baseline_digest='a' * 64, history_binding_digest=history.binding.content_hash,
        builder_digest=old.fixed_builder.digest, context_bytes=24000).data()['recipes']]
    allocation = derive_allocation(recipes, target_count=len(setup['packets']))
    respond = _response(setup, history, seen)
    if response_factory is not None:
        respond = response_factory(setup, history, seen, respond)
    provider, calls, gets = headless_train_provider(
        root / 'headless-solver', patch, schemas=model_schemas(), max_calls=allocation['model_calls'],
        response=respond, wrapped=True)

    # This descriptor is pure: it freezes the production evaluator configuration
    # without starting an evaluator worker or exposing any private reference bytes.
    with patch.context() as evaluator_patch:
        evaluator, prompts, evaluator_gets = native_spec(root / 'headless-evaluator', evaluator_patch)
    evaluator.update(max_calls=allocation['target_cells'], max_tokens=allocation['target_cells'] * 100,
                     evaluator_id=old.data()['scorer']['evaluator_id'],
                     evaluator_version=old.data()['scorer']['version'])
    descriptor = headless_evaluator_descriptor(evaluator)
    evaluator_provider = {'kind': 'grok-headless-frozen-evaluator-v1',
                          'configuration_digest': descriptor['configuration_digest']}
    evaluator_usage = {'schema': 'c5-headless-evaluator-usage-declaration-v1',
                       'provider_kind': evaluator_provider['kind'], 'usage_contract': 'grok-headless-c5-usage-v1',
                       'evaluator_config_digest': evaluator_provider['configuration_digest']}

    csv = {packet.task.content_hash: packet.csv_path for packet in setup['packets']}
    csv[history.task.content_hash] = old.history_inputs[0][1]
    templates = component_templates(history=history, parent=old.parent, fixed_builder=old.fixed_builder,
                                    history_material=old.material(history.task.content_hash))
    protocol = FrozenJointTrainProtocol.freeze(
        baseline_digest='a' * 64, p0_digest='d' * 64, runtime_sources=runtime_sources(), history=history.task,
        targets=[packet.task for packet in setup['packets']], public_csv=csv, builder_digest=old.fixed_builder.digest,
        history_binding_digest=history.binding.content_hash, component_templates=templates, context_bytes=24000,
        provider_config=provider_configuration(provider), scorer=ScorerConfig(R(old.data()['scorer'])),
        selection_rule=FrozenTrainSelectionRule.create(coverage_id=OBLIGATION, baseline_arm='ordinary-control',
            tie_break_order=[recipe['id'] for recipe in recipes if recipe['id'] != 'B0']),
        evaluator_usage=evaluator_usage, evaluator_provider=evaluator_provider)
    body = old.data()
    fields = ('stage', 'domain', 'export_mode', 'item_ids', 'task_bindings', 'history_binding', 'parent', 'fixed_builder',
              'materials', 'phase_materials', 'source_verifier_binding', 'corpus_verifier_binding',
              'scorer_handle_bindings', 'objective', 'image', 'timeout_seconds')
    plan = FrozenJointTrainRuntimePlan(R({**{key: body[key] for key in fields},
                                         'schema': 'c5-common-train-runtime-plan-v1', 'protocol_digest': protocol.digest}),
                                       protocol, history, old.history_inputs, tuple(setup['packets']))
    setup.update(common_plan=plan, common_provider=provider, common_calls=calls, common_gets=gets,
                 common_seen=seen, evaluator=evaluator, evaluator_prompts=prompts,
                 evaluator_gets=evaluator_gets, evaluator_descriptor=descriptor)
    return setup


def executor(setup):
    from research_loop.modular.joint_train_runtime import JointTrainStageExecutor
    plan = setup['common_plan']
    return JointTrainStageExecutor(plan, root=setup['root'] / 'headless-common-run', provider=setup['common_provider'],
        source_verifier=setup['source'], corpus_verifier=setup['corpus'], retrieval_provider=Provider(setup['retrieval_calls']),
        audit_verifier=AUDIT, scorer_handle_bindings=plan.data()['scorer_handle_bindings'])


def test_c5_headless_runtime_probe_freezes_full_controller_denominator(tmp_path, monkeypatch):
    """One full history and one target are an engineering probe, not C5 qualification."""
    setup = prepare_headless_runtime(tmp_path, monkeypatch)
    plan, runner, recipe = setup['common_plan'], executor(setup), full_recipe(setup['common_plan'])
    allocation = plan.protocol.record.data()['allocation']
    assert plan.protocol.record.data()['schema'] == HEADLESS_OBLIGATION
    assert len(plan.recipes) == 59 and len(plan.builds) == 46 and len(plan.packets) == 2
    assert allocation['model_calls'] == 930 and allocation['target_cells'] == 118 and allocation['scorer_calls'] == 118
    assert set(plan.protocol.record.data()['component_templates']) == {f'M{index}' for index in range(1, 10)}
    assert plan.headless_evaluator_binding == {
        'evaluator_usage': plan.protocol.record.data()['evaluator_usage'],
        'evaluator_provider': plan.protocol.record.data()['evaluator_provider'],
    }
    assert type(setup['common_provider']) is GrokHeadlessTrainProvider
    config = setup['common_provider'].configuration().data()
    assert config['provider_kind'] == 'grok-headless-public-train-v1'
    assert config['native_config']['schema'] == 'grok-headless-train-solver-port-v1'
    assert config['limits']['main_opportunities'] == 930
    assert not setup['evaluator_prompts'] and not setup['evaluator_gets']

    history = runner.execute(recipe_id=recipe['id'], stage='history_build')
    assert history.record.data()['status'] == 'succeeded', history.inner.record.data()
    runner.verify(history)
    with pytest.raises(ContractError, match='complete canonical'):
        from research_loop.modular.joint_train_runtime import JointTrainBarrier
        JointTrainBarrier.seal(runner)
    target = runner.execute(recipe_id=recipe['id'], stage='target', target_digest=plan.packets[0].task.content_hash,
                            build=history)
    assert target.record.data()['status'] == 'succeeded', target.inner.record.data()
    runner.verify(history)
    runner.verify(target)
    assert len(setup['common_calls']) == 11
    assert not setup['evaluator_prompts'] and not setup['evaluator_gets']
    for stage in (history, target):
        receipt, outer = stage.inner.record.data(), stage.record.data()
        assert receipt['artifact_catalogue_seal']['binding']['experiment_id'] == plan.record.content_hash
        assert receipt['artifact_catalogue_seal']['count'] > 0
        assert set(outer['component_digests']) == {f'M{index}' for index in range(1, 10)}
    assert target.inner.solver.execution.record.data()['argv'][:4] == ['docker', 'run', '--pull', 'never']
