"""Complete formal catalogue, bounded real stage pipeline checks; no model calls."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.full_loo_modules import model_schemas, MEASUREMENT
from research_loop.modular.full_loo_composition import derive_allocation
from research_loop.modular.joint_train_protocol import FrozenJointTrainProtocol, common_recipes, OBLIGATION
from research_loop.modular.joint_train_panel import history_build_id
from research_loop.modular.joint_train_runtime import (FrozenJointTrainRuntimePlan, JointTrainStageExecutor,
    JointTrainBarrier, _barrier_record, _barrier_validation_scope, compile_panel, component_templates, runtime_sources)
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
    assert history.inner.record.data()['artifact_catalogue_seal']['binding']['run_id']!=target.inner.record.data()['artifact_catalogue_seal']['binding']['run_id']
    for stage in (history, target):
        receipt=stage.inner.record.data();seal=receipt['artifact_catalogue_seal']
        assert seal['binding']['experiment_id']==plan.record.content_hash
        assert (stage.inner.root/'runtime'/'artifacts.jsonl.seal.json').is_file()
        journal=stage.inner.root/'runtime'/'artifacts.jsonl'
        rows=[json.loads(line)['descriptor'] for line in journal.read_text(encoding='utf-8').splitlines()]
        assert seal['count']==len(rows) and seal['head'] is not None
        assert all(row['scientific_validated'] is False for row in rows)
        trace=[json.loads(line) for line in (stage.inner.root/'runtime'/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
        catalogue_trace=[row['payload']['canonical'] for row in rows if row['kind']=='trace_event']
        assert catalogue_trace==trace
        kinds = [row['kind'] for row in rows]
        assert {'model_context', 'journal_event', 'reveal_output', 'retrieval_event'} <= set(kinds)
        assert kinds.count('phase_program') == kinds.count('phase_return') == 2
        assert kinds.count('phase_allocation') == kinds.count('phase_receipt') == 1
        assert kinds.count('phase_scheduler_event') == len((stage.inner.root/'phase/events.jsonl').read_bytes().splitlines())
        assert kinds.count('phase_scheduler_sqlite') == int('M8' in stage.inner.cell.runtime_arm.data()['enabled'])
        if stage is history:
            assert {'m9_builder_selection', 'm9_builder_subjects', 'm9_builder_return', 'm9_builder_receipt',
                    'm9_candidate', 'm9_build_terminal'} <= set(kinds)
            assert json.loads((stage.inner.root/'m9-build-terminal.json').read_bytes())['status'] == 'succeeded'
    covered={row['module'] for row in [json.loads(line)['descriptor'] for line in (history.inner.root/'runtime'/'artifacts.jsonl').read_text(encoding='utf-8').splitlines()]
             + [json.loads(line)['descriptor'] for line in (target.inner.root/'runtime'/'artifacts.jsonl').read_text(encoding='utf-8').splitlines()] if row['coverage']=='covered' and row['status']=='produced'}
    assert covered >= {f'M{i}' for i in range(1,10)}
    # A coherently sealed failed builder is valid audit evidence, but cannot
    # support a successful enclosing history stage. Rehash both receipt levels
    # so rejection must come from this state mismatch, not stale checksums.
    from types import SimpleNamespace
    from research_loop.modular import builder_artifacts
    from research_loop.modular.artifact_catalogue import ArtifactCatalogue
    from research_loop.modular.joint_train_runtime import _stage_record
    from research_loop.modular.full_loo_driver import files
    from test_builder_artifacts import rewrite_catalogue
    stage_root = history.inner.root
    outer_path = runner.root/(history.record.data()['trial_id']+'-stage.json')
    changed_paths = [stage_root/'m9-build-terminal.json', stage_root/'runtime/artifacts.jsonl',
        stage_root/'runtime/artifacts.jsonl.seal.json', stage_root/'receipt.json', outer_path]
    originals = {path: path.read_bytes() for path in changed_paths}
    binding = history.inner.record.data()['artifact_catalogue_seal']['binding']
    catalogue = ArtifactCatalogue(stage_root/'runtime/artifacts.jsonl', identity=plan.history.task.identity,
        run_id=binding['run_id'], experiment_id=binding['experiment_id'], lock_digest=binding['lock_digest'])
    terminal = json.loads(changed_paths[0].read_bytes())
    terminal.update(status='failed', error_type='OSError', error='terminal publication failed')
    changed_paths[0].write_bytes((R(terminal).encoded+'\n').encode())
    def change_terminal(body):
        if body['kind'] == 'm9_build_terminal':
            body['status'] = 'failed'
            body['payload']['canonical'] = builder_artifacts._snapshot(stage_root, 'm9-build-terminal.json')
    try:
        rewrite_catalogue(SimpleNamespace(artifacts=catalogue), change_terminal)
        inner_record = R({**history.inner.record.data(), 'files': files(stage_root),
            'artifact_catalogue_seal': json.loads(changed_paths[2].read_bytes())})
        changed_paths[3].write_bytes(inner_record.encoded.encode())
        inner = replace(history.inner, record=inner_record)
        forged = replace(history, inner=inner, record=_stage_record(plan, inner, history.ledger, history.barrier, status='succeeded'))
        outer_path.write_bytes(forged.record.encoded.encode())
        runner.stages[0] = forged
        with pytest.raises(ContractError, match='successful C4 history requires a successful M9 build'):
            runner.verify(forged)
    finally:
        for path, original in originals.items(): path.write_bytes(original)
        runner.stages[0] = history
    runner.verify(history)
    receipt_path=history.inner.root/'receipt.json';original_receipt=receipt_path.read_bytes();changed=history.inner.record.data()
    changed['artifact_catalogue_seal']={**changed['artifact_catalogue_seal'],'head':'0'*64}
    receipt_path.write_bytes(R(changed).encoded.encode())
    try:
        with pytest.raises(ContractError):runner.verify(history)
    finally:
        receipt_path.write_bytes(original_receipt)
    runner.verify(history)
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


def test_actual_ordinary_control_preserves_module_disabled_artifact_status(tmp_path, monkeypatch):
    setup = prepare(tmp_path, monkeypatch)
    runner = executor(setup)
    recipe = next(recipe for recipe in runner.plan.recipes if recipe['id'] == 'ordinary-control')
    history = runner.execute(recipe_id=recipe['id'], stage='history_build')
    assert history.record.data()['status'] == 'succeeded', history.inner.record.data()
    runner.verify(history)
    target = runner.execute(recipe_id=recipe['id'], stage='target',
        target_digest=runner.plan.packets[0].task.content_hash, build=history)
    assert target.record.data()['status'] == 'succeeded', target.inner.record.data()
    runner.verify(target)
    for stage in (history, target):
        rows = [json.loads(line)['descriptor'] for line in (stage.inner.root/'runtime/artifacts.jsonl').read_bytes().splitlines()]
        for row in rows:
            if (row['kind'] in {'model_context', 'retrieval_event'} or row['kind'].startswith(('phase_', 'm9_'))):
                assert row['status'] == 'not_applied'
        assert not any(row['kind'] == 'reveal_output' for row in rows)
        assert not (stage.inner.root/'phase/queue.sqlite').exists()
        assert sum(row['kind'] == 'phase_program' for row in rows) == 2
    terminal = json.loads((history.inner.root/'m9-build-terminal.json').read_bytes())
    assert terminal['status'] == 'succeeded' and terminal['activation'] == 'not_applied'
    assert len(setup['common_logs']) == 11


def test_checkpoint_rows_are_frozen_at_executor_construction(tmp_path, monkeypatch):
    setup = prepare(tmp_path, monkeypatch)
    runner = executor(setup)
    original = json.loads((runner.root / 'checkpoint.json').read_bytes())
    def forbidden(*args, **kwargs):
        raise AssertionError('checkpoint persistence recomputed a frozen trial binding')
    monkeypatch.setattr(FrozenJointTrainProtocol, 'trial_binding', forbidden)
    first_stage, first_trial = runner._planned_checkpoint_rows[0]
    runner.attempts[(first_stage, first_trial)] = {'status': 'reserved'}
    runner._persist()
    reserved = json.loads((runner.root / 'checkpoint.json').read_bytes())
    assert reserved['allocation'] == original['allocation']
    assert reserved['provider_usage'] == original['provider_usage']
    assert [(row['stage'], row['trial_id']) for row in reserved['rows']] == list(runner._planned_checkpoint_rows)
    assert reserved['rows'][0]['status'] == 'reserved'
    runner.attempts[(first_stage, first_trial)] = {'status': 'failed'}
    runner.poisoned = True
    runner._persist()
    poisoned = json.loads((runner.root / 'checkpoint.json').read_bytes())
    assert poisoned['allocation'] == original['allocation']
    assert poisoned['provider_usage'] == original['provider_usage']
    assert [(row['stage'], row['trial_id']) for row in poisoned['rows']] == list(runner._planned_checkpoint_rows)
    assert poisoned['rows'][0]['status'] == 'failed'
    assert all(row['status'] == 'blocked' for row in poisoned['rows'][1:])


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
    journal=result.inner.root/'runtime'/'artifacts.jsonl'
    assert journal.exists()
    rows=[json.loads(line)['descriptor'] for line in journal.read_text(encoding='utf-8').splitlines()]
    assert any(row['kind']=='trace_event' and row['coverage']=='uncovered' for row in rows)


def test_artifact_writer_failure_retains_independent_failed_stage_receipt(tmp_path,monkeypatch):
    from research_loop.modular.artifact_catalogue import ArtifactCatalogue
    setup=prepare(tmp_path,monkeypatch);runner=executor(setup);recipe=full_recipe(runner.plan)
    append=ArtifactCatalogue.append
    def failed_append(self,**kwargs):
        if kwargs['kind']=='trace_event' and kwargs['payload'].data()['stage']!='objective_lock':
            raise OSError('synthetic artifact writer failure')
        return append(self,**kwargs)
    monkeypatch.setattr(ArtifactCatalogue,'append',failed_append)
    try:
        result=runner.execute(recipe_id=recipe['id'],stage='history_build')
    except ContractError:
        result=None
    assert result is None or result.record.data()['status']=='failed'
    assert runner.poisoned and not setup['common_logs']
    stage_root=runner.root/'stages'/history_build_id(runner.plan.protocol,recipe)
    failure=json.loads((stage_root/'runtime'/'audit-failure.json').read_bytes())
    receipt=json.loads((stage_root/'receipt.json').read_bytes())
    assert failure['schema']=='runtime-audit-failure-v1'
    assert failure['terminal'] is True and failure['audit_complete'] is False
    assert failure['scientific_validated'] is False
    assert receipt['status']=='failed' and receipt['candidate_digest'] is None
    assert receipt['reason']=='OSError: synthetic artifact writer failure'
    journal=stage_root/'runtime'/'artifacts.jsonl'
    assert journal.exists()
    rows=[json.loads(line)['descriptor'] for line in journal.read_text(encoding='utf-8').splitlines()]
    trace=[json.loads(line) for line in (stage_root/'runtime'/'trace.jsonl').read_bytes().splitlines()]
    covered_trace=[row['payload']['canonical'] for row in rows if row['kind']=='trace_event']
    assert covered_trace==trace[:-1] and trace[-1]['stage']=='c4_state'
    assert rows[0]['module']=='P0'
    # M2 wrote real lineage events before the failed c4_state trace. Retain all
    # of them instead of expecting the old one-descriptor-only directory.
    ledger_rows=[row['payload']['canonical'] for row in rows if row['kind']=='ledger_event']
    for journal_name in ('evidence','claims'):
        original=[json.loads(line) for line in (stage_root/'runtime'/(journal_name+'.jsonl')).read_bytes().splitlines()]
        assert [row['event'] for row in ledger_rows if row['journal']==journal_name]==original
    assert len(rows)==1+len(ledger_rows) and ledger_rows
    assert receipt['artifact_catalogue_seal']['count']==len(rows)
    assert failure['lock_digest']==receipt['artifact_catalogue_seal']['binding']['lock_digest']
    assert receipt['files']['runtime/audit-failure.json']
    checkpoint=json.loads((runner.root/'checkpoint.json').read_bytes())
    assert checkpoint['score_eligible'] is False
    assert all(row['status'] in ('failed','blocked') for row in checkpoint['rows'])


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


def test_verified_barrier_lease_is_fresh_revoked_and_not_publicly_injectable(tmp_path,monkeypatch):
    setup=prepare(tmp_path,monkeypatch);runner=executor(setup);recipe=full_recipe(runner.plan)
    history=runner.execute(recipe_id=recipe['id'],stage='history_build')
    partial=JointTrainBarrier(_barrier_record(runner.plan,(history,)),runner,(history,))
    calls=[]
    def replay(self): calls.append(self)
    monkeypatch.setattr(JointTrainBarrier,'verify',replay)
    with _barrier_validation_scope(partial) as first:
        first.require(partial)
        (history.inner.root/'candidate.json').write_bytes(b'{}')
    with pytest.raises(ContractError,match='context differs'):
        first.require(partial)
    with _barrier_validation_scope(partial) as second:
        assert first is not second
    assert calls==[partial,partial]
    with pytest.raises(TypeError): runner.verify(history,first)
    with pytest.raises(TypeError): compile_panel(partial,first)


def test_original_protocol_file_whitespace_drift_blocks_dispatch(tmp_path,monkeypatch):
    setup=prepare(tmp_path,monkeypatch);runner=executor(setup);path=runner.root/'protocol.json'
    original=path.read_bytes();assert original==(runner.plan.protocol.record.encoded+'\n').encode()
    # Same decoded record, different original bytes: a normalized digest cannot hide it.
    path.write_bytes(original+b'\n')
    with pytest.raises(ContractError,match='protocol bytes'):
        runner.execute(recipe_id=full_recipe(runner.plan)['id'],stage='history_build')
    assert not setup['common_logs'] and runner.poisoned
    body=json.loads((runner.root/'checkpoint.json').read_bytes())
    assert all(r['status']=='blocked' for r in body['rows']) and not body['score_eligible']
