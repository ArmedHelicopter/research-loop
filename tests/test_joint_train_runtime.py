"""Complete formal catalogue, bounded real stage pipeline checks; no model calls."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.full_loo_modules import model_schemas, MEASUREMENT
from research_loop.modular.full_loo_composition import derive_allocation
from research_loop.modular.joint_train_protocol import FrozenJointTrainProtocol, common_recipes, OBLIGATION
from research_loop.modular.joint_train_runtime import (FrozenJointTrainRuntimePlan, JointTrainStageExecutor,
    JointTrainBarrier, component_templates, runtime_sources)
from research_loop.modular.phase_provider import provider_configuration
from research_loop.modular.train_selection import FrozenTrainSelectionRule
from research_loop.ontology import ContractError
from evaluation.modular.scoring_service import ScorerConfig
from test_full_loo_runtime import prepare as old_prepare, AUDIT, Provider
from test_modular_combination_benchmark_driver import _plan
from helpers.native_phase_provider import native_phase_provider

R=FrozenRecord.from_dict


def prepare(root, patch, fault_at=None):
    # Set the synthetic history's real original identity before executing it.
    # The older C4 fixture used a distinct placeholder split, which C5 rejects.
    import test_execution_improvement_train_controller as history_fixture
    original_primary=history_fixture.prepared_primary; identity_type=history_fixture.DataIdentity; split=[]
    def primary(path):
        prepared=original_primary(path);split.append(prepared[3][0].task.identity.split_id);return prepared
    def identity(benchmark,task,group,version,old_split,domain):
        return identity_type(benchmark,task,group,version,split[0] if task=='closed-history' else old_split,domain)
    patch.setattr(history_fixture,'prepared_primary',primary)
    patch.setattr(history_fixture,'DataIdentity',identity)
    setup=old_prepare(root,patch);old=setup['plan'];history=old.history;seen=[]
    def response(request):
        b=request.data();seen.append(b);m=b['module_context'];slot=b['slot']
        assert all(x not in request.encoded for x in ('PRIVATE-REFERENCE-SENTINEL','"arm_id"','"enabled"'))
        if b['task']==history.task.data():
            assert all(p.task.content_hash not in request.encoded for p in setup['packets'])
        if slot=='m4_plan':
            value=_plan()
            for branch in value['branches']:
                for prediction in branch['predictions']:prediction.update(observable=MEASUREMENT['observable'],discriminator_id=MEASUREMENT['discriminator_id'])
            return value
        if slot.startswith('review_'):
            return {'assessment':'concern','evidence_refs':['public statistic'],'counterexamples':['Check range'],'uncertainty':'Check outlier'}
        if slot=='bounded_choice':return {'job_id':m['alternative_checks'][-1]['id'],'rationale':'Check range after forecasts and reviews.'}
        if slot in ('builder_proposal','ordinary_revision'):
            value='Use public statistic '+str(sum(json.loads(r['stdout'])['statistic'] for r in m['execution_observations']))
            return {'entrypoint':'emit_literal_change_v1','surface':'prompt','key':'instructions','value':value} if slot=='builder_proposal' else {'instructions':value}
        if slot=='analysis_program':
            assert m['joint_mechanism']['candidate_context']['instructions'].startswith('Use public statistic')
            return {'analysis':'Check current public mean using built guidance.',
                'program':"import csv,json\nwith open('/input/public_csv') as f: xs=[float(r['x']) for r in csv.DictReader(f)]\nprint(json.dumps({'statistic':sum(xs)/len(xs)}))"}
        return {'objective_digest':m['required_objective_digest'],'outcome':'unknown','evidence_ids':[],
                'conclusion':'Synthetic observed '+b['execution_feedback'][0]['stdout'],'programme_complete':False}
    recipes=[r['recipe'] for r in common_recipes(baseline_digest='a'*64,history_binding_digest=history.binding.content_hash,
        builder_digest=old.fixed_builder.digest,context_bytes=24000).data()['recipes']]
    provider,logs=native_phase_provider(root/'common-provider',patch,schemas=model_schemas(),
        max_calls=derive_allocation(recipes,target_count=len(setup['packets']))['model_calls'],response=response,fault_at=fault_at,
        slot_output_caps={s:8192 if s=='analysis_program' else 2048 for s in model_schemas()},
        slot_input_byte_caps={s:262144 for s in model_schemas()},observed_main_token_cap=131072)
    csv={p.task.content_hash:p.csv_path for p in setup['packets']};csv[history.task.content_hash]=old.history_inputs[0][1]
    templates=component_templates(history=history,parent=old.parent,fixed_builder=old.fixed_builder,
                                 history_material=old.material(history.task.content_hash))
    protocol=FrozenJointTrainProtocol.freeze(baseline_digest='a'*64,p0_digest='d'*64,runtime_sources=runtime_sources(),
        history=history.task,targets=[p.task for p in setup['packets']],public_csv=csv,
        builder_digest=old.fixed_builder.digest,history_binding_digest=history.binding.content_hash,component_templates=templates,
        context_bytes=24000,provider_config=provider_configuration(provider),scorer=ScorerConfig(R(old.data()['scorer'])),
        selection_rule=FrozenTrainSelectionRule.create(coverage_id=OBLIGATION,baseline_arm='ordinary-control',
            tie_break_order=[r['id'] for r in recipes if r['id']!='B0']))
    b=old.data();fields=('stage','domain','export_mode','item_ids','task_bindings','history_binding','parent','fixed_builder',
        'materials','phase_materials','source_verifier_binding','corpus_verifier_binding','scorer_handle_bindings','objective','image','timeout_seconds')
    plan=FrozenJointTrainRuntimePlan(R({**{k:b[k] for k in fields},'schema':'c5-common-train-runtime-plan-v1',
        'protocol_digest':protocol.digest}),protocol,history,old.history_inputs,tuple(setup['packets']))
    setup.update(common_plan=plan,common_provider=provider,common_logs=logs,common_seen=seen)
    return setup


def executor(setup):
    p=setup['common_plan']
    return JointTrainStageExecutor(p,root=setup['root']/'common-run',provider=setup['common_provider'],
        source_verifier=setup['source'],corpus_verifier=setup['corpus'],retrieval_provider=Provider(setup['retrieval_calls']),
        audit_verifier=AUDIT,scorer_handle_bindings=p.data()['scorer_handle_bindings'])


def full_recipe(plan):return next(r for r in plan.recipes if all(r['arm_bits'].values()))


def test_actual_history_target_pipeline_with_full_catalogue(tmp_path,monkeypatch):
    setup=prepare(tmp_path,monkeypatch);runner=executor(setup);plan=setup['common_plan'];recipe=full_recipe(plan)
    assert len(plan.recipes)>11 and plan.protocol.record.data()['allocation']['target_cells']>22
    history=runner.execute(recipe_id=recipe['id'],stage='history_build')
    assert history.record.data()['status']=='succeeded',history.inner.record.data()
    runner.verify(history)
    with pytest.raises(ContractError,match='complete canonical'):JointTrainBarrier.seal(runner)
    target=runner.execute(recipe_id=recipe['id'],stage='target',target_digest=plan.packets[0].task.content_hash,build=history)
    assert target.record.data()['status']=='succeeded',target.inner.record.data()
    runner.verify(target);runner.verify(history)
    assert len(setup['common_logs'])==11
    assert target.inner.solver.execution.record.data()['argv'][:4]==['docker','run','--pull','never']
    checkpoint=json.loads((runner.root/'checkpoint.json').read_bytes())
    assert len(checkpoint['rows'])==len(plan.builds)+len(plan.recipes)*len(plan.packets)
    assert sum(r['status']=='succeeded' for r in checkpoint['rows'])==2
    assert checkpoint['score_eligible'] is checkpoint['complete_grid_executed'] is False
    assert all(r['status'] in ('succeeded','not_executed') for r in checkpoint['rows'])
    assert history.record.data()['original_experiments_completed'] is False
    # A coherent rewritten outer file and matching in-memory record must still
    # fail against actual inner/plan/ledger evidence, not merely file equality.
    path=runner.root/(history.record.data()['trial_id']+'-stage.json');original=path.read_bytes()
    replacements={key:'0'*64 for key in ('plan_digest','protocol_digest','trial_id','build_id',
        'scope_id','recipe_id','inner_pipeline_receipt_digest','provider_seal_digest')}
    replacements.update(schema='other',stage='target',status='failed',score_eligible=True,
        original_experiments_completed=True,target_binding_mode='common_panel',history_barrier_digest='0'*64,
        component_digests={k:'0'*64 for k in history.record.data()['component_digests']})
    for key,value in replacements.items():
        changed=R({**history.record.data(),key:value});forged=replace(history,record=changed)
        path.write_bytes(changed.encoded.encode());runner.stages[0]=forged
        try:
            with pytest.raises(ContractError,match='cross-binding'):runner.verify(forged)
        finally:
            runner.stages[0]=history;path.write_bytes(original)
    from research_loop.modular.joint_train_runtime import _barrier_record
    partial=_barrier_record(plan,(history,));barrier_path=runner.root/'common-history-barrier.json'
    barrier_path.write_bytes(partial.encoded.encode())
    incomplete=JointTrainBarrier(partial,runner,(history,))
    with pytest.raises(ContractError,match='complete original history'):incomplete.verify()
    for key,value in {'schema':'other','runtime_plan_digest':'0'*64,'protocol_digest':'0'*64,
            'component_digests':{},'original_experiments_completed':True,'score_eligible':True}.items():
        changed=R({**partial.data(),key:value});barrier_path.write_bytes(changed.encoded.encode())
        with pytest.raises(ContractError,match='header.*cross-binding'):replace(incomplete,record=changed).verify()
    barrier_path.write_bytes(partial.encoded.encode())
    with pytest.raises(ContractError):
        runner.execute(recipe_id=recipe['id'],stage='target',target_digest=plan.packets[1].task.content_hash,
            build=history,barrier=JointTrainBarrier(R({'schema':'invented'}),runner,(history,)))
    assert len(setup['common_logs'])==11


@pytest.mark.parametrize('fault',['handles','template','parent','csv','material'])
def test_preflight_drift_blocks_all_native_calls(tmp_path,monkeypatch,fault):
    setup=prepare(tmp_path,monkeypatch);plan=setup['common_plan'];b=plan.data();p=plan.protocol.record.data()
    if fault=='handles':
        handles=dict(b['scorer_handle_bindings']);handles[next(iter(handles))]='0'*64
        with pytest.raises(ContractError):plan.verify_dependencies(provider=setup['common_provider'],source_verifier=setup['source'],
            corpus_verifier=setup['corpus'],scorer_handle_bindings=handles)
    elif fault=='csv':
        plan.packets[0].csv_path.write_bytes(b'x\n999\n')
        with pytest.raises(ContractError):executor(setup)
    else:
        if fault=='template':
            p['component_templates']['M4']['config']['consumer']='unconsumed'
            changed=FrozenJointTrainProtocol(R(p));b['protocol_digest']=changed.digest
        else:
            changed=plan.protocol
            if fault=='parent':b['parent']['changes']['prompt']['instructions']='changed'
            else:b['materials'][plan.history.task.content_hash]['context_budget_bytes']=1
        with pytest.raises((ContractError,KeyError)):replace(plan,record=R(b),protocol=changed)
    assert not setup['common_logs']


def test_unknown_main_keeps_complete_denominator_and_stops(tmp_path,monkeypatch):
    setup=prepare(tmp_path,monkeypatch,fault_at=1);runner=executor(setup);recipe=full_recipe(runner.plan)
    result=runner.execute(recipe_id=recipe['id'],stage='history_build')
    assert result.record.data()['status']=='failed' and runner.poisoned
    with pytest.raises(ContractError):runner.execute(recipe_id=recipe['id'],stage='history_build')
    body=json.loads((runner.root/'checkpoint.json').read_bytes())
    assert len(body['rows'])==len(runner.plan.builds)+runner.plan.protocol.record.data()['allocation']['target_cells']
    assert all(r['status'] in ('failed','blocked') for r in body['rows']) and len(setup['common_logs'])==1
    assert body['provider_usage']['unknown_main_opportunities']==1


def test_completed_history_provenance_drift_blocks_target(tmp_path,monkeypatch):
    setup=prepare(tmp_path,monkeypatch);runner=executor(setup);recipe=full_recipe(runner.plan)
    build=runner.execute(recipe_id=recipe['id'],stage='history_build');assert build.record.data()['status']=='succeeded'
    (build.inner.root/'candidate.json').write_bytes(b'{}')
    with pytest.raises(ContractError):runner.execute(recipe_id=recipe['id'],stage='target',
        target_digest=runner.plan.packets[0].task.content_hash,build=build)
    body=json.loads((runner.root/'checkpoint.json').read_bytes())
    assert len(setup['common_logs'])==5 and runner.poisoned
    assert body['provider_usage']['known_reported_tokens']==60
    assert body['score_eligible'] is False and all(r['status'] in ('succeeded','blocked') for r in body['rows'])
