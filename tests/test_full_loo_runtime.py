"""Synthetic model/qualification; actual restricted builders, Docker and scorer process."""
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
import hashlib
import json
import os
import pytest
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.full_loo_composition import freeze_full_loo, candidate_build_key
from research_loop.modular.full_loo_controller import FrozenFullLooRuntimePlan, run_full_loo_train, verify_full_loo_cell
from research_loop.modular.full_loo_modules import model_schemas, MEASUREMENT
from research_loop.modular.metaprogram_training import model_configuration
from research_loop.modular.state_retrieval_combination_driver import freeze_material
from research_loop.modular.admission_combination import FrozenAdmissionMaterial
from research_loop.modular.modules.improvement import FrozenBuilderVersion, RestrictedBuilderPort
from research_loop.modular.runtime import verify_trace
from evaluation.modular.scorer_process import serialize_combination_panel, parse_combination_panel, CombinationScorerProcessClient
from evaluation.modular.scoring_service import ScorerConfig
from research_loop.ontology import ContractError, canonical
from test_execution_improvement_train_controller import prepare as prepare_history, phase_material, provenance, AUDIT
from test_state_retrieval_combination_driver import state_material, Provider
from test_admission_combination import sources
from test_modular_train_controller import model_port
from test_lineage_combination_controller import EXECUTION, SCORER
from test_scorer_process import _command
from test_modular_combination_benchmark_driver import _plan, _rewrite_trace


def prepare(root, patch, fault=None):
    setup=prepare_history(root,patch);old=setup['plan'];history=old.history
    state_calls=[];corpus_calls=[];retrieval_calls=[];seen=[]
    source=sources(state_calls,'unknown_cost' if fault=='source_unknown' else 'source_cell_drift' if fault=='source_drift' else None)
    corpus=provenance(corpus_calls,corpus=True)
    hcsv=dict(old.history_inputs)['public_csv'];items=[(history.task,hcsv)]+[(p.task,p.csv_path) for p in setup['packets']]
    materials={};phases={}
    for task,csv in items:
        b=state_material(task,csv,True).data()
        if task==history.task:
            for r in b['originals']:r['root_material']={'history_digest':history.binding.content_hash,'observation_key':r['key']}
        material=FrozenAdmissionMaterial(FrozenRecord.from_dict(b))
        docs=[{'source_id':'origin-'+str(i),'root_source_id':'root-'+str(i),'lane':lane,'text':text} for i,(lane,text) in enumerate([
            ('support','Use the current public mean.'),('counter','Check public outliers using a robust median.'),('method','Read the named CSV and calculate spread.')])]
        materials[task.content_hash]=freeze_material(task,material,docs,'Which current public measurement is informative?').data()
        phases[task.content_hash]=phase_material(task,csv,'auxiliary_failed' if fault=='auxiliary_failed' else None).data()
    fixed=FrozenBuilderVersion(FrozenRecord.from_dict({'entrypoint':'emit_literal_change_v1','surface':'prompt','key':'instructions','value':'Use a public numerical check.'}))
    from research_loop.modular.experiments import registry
    composition=freeze_full_loo(baseline_digest='a'*64,train_task_digests=[p.task.content_hash for p in setup['packets']],
        issue_contract_ids=list(registry()),history_binding_digest=history.binding.content_hash,
        builder_digest=fixed.digest,history_input_budget=24000)
    def respond(request):
        b=request.data();seen.append(b);slot=b['slot'];m=b['module_context']
        if b['task']==history.task.data():
            assert not (root/'run/candidate-barrier.json').exists()
            for p in setup['packets']:assert p.task.content_hash not in request.encoded and p.task.identity.task_id not in request.encoded
        else:assert (root/'run/candidate-barrier.json').exists()
        assert all(x not in request.encoded for x in ('PRIVATE-REFERENCE-SENTINEL','"arm_id"','"enabled"','"qualification_observations"'))
        if fault=='model_unknown':raise RuntimeError('synthetic model outage')
        if slot=='m4_plan':
            b=_plan();b['question']='What will the fresh public statistic show?'
            for branch in b['branches']:
                for prediction in branch['predictions']:prediction.update(observable=MEASUREMENT['observable'],discriminator_id=MEASUREMENT['discriminator_id'])
            return FrozenRecord.from_dict(b)
        if slot.startswith('review_'):
            return FrozenRecord.from_dict({'assessment':'concern','evidence_refs':['current public evidence'],
                'counterexamples':['Check the range'] if not m['prior_responses'] else ['Reconsider previous range critique'],
                'uncertainty':'Use an outlier check' if not m['prior_responses'] else 'Use ordinary sequential revision'})
        if slot=='bounded_choice':
            # Consume forecasts, both critiques, and retrieval in an actual
            # procedure choice, using a main check for the sequential control.
            probe=all('outlier' in r['uncertainty'] for r in m['reviews']) and bool(m['retrieval']['by_lane']['counter'])
            chosen=m['alternative_checks'][int(probe)]
            return FrozenRecord.from_dict({'job_id':chosen['id'],'rationale':'Check the spread after the forecast and two critiques.'})
        if slot in ('builder_proposal','ordinary_revision'):
            values=[json.loads(r['stdout'])['statistic'] for r in m['execution_observations']]
            count=len(m['state_projection']['observations'])+len(m['retrieval']['by_lane']['counter'])-sum(r.get('needs_review') is True for r in m['state_projection']['memory'])
            value='Apply public adjustment='+str(sum(values)+count)
            return FrozenRecord.from_dict({'entrypoint':'emit_literal_change_v1','surface':'prompt','key':'instructions','value':value}
                if slot=='builder_proposal' else {'instructions':value+'; check arithmetic directly.'})
        joint=m['joint_mechanism']
        if slot=='analysis_program':
            adjustment=float(joint['candidate_context']['instructions'].split('=')[1].split(';')[0])
            values=[json.loads(r['stdout'])['statistic'] for r in joint.get('execution_observations',[])]
            state=[next(iter(v['content'].values())) for v in joint.get('state_projection',{}).get('observations',[])]
            reviews=joint.get('reviews',[]);branches=joint.get('prediction_proposal',{}).get('branches',[])
            counter=len(joint.get('retrieval',{}).get('by_lane',{}).get('counter',[]))
            memory_checks=sum(r.get('needs_review') is True for r in joint.get('state_projection',{}).get('memory',[]))
            observed={'candidate':adjustment,'auxiliary':values,'state':state,'review_checks':[r['counterexamples'] for r in reviews],
                'directions':[r['predictions'][0]['direction'] for r in branches],'counter_count':counter,'choice':joint.get('choice'),'memory_checks':memory_checks}
            program="import csv,json\nwith open('/input/public_csv') as f: xs=[float(r['x']) for r in csv.DictReader(f)]\nresult="+repr(observed)+"\nresult['statistic']=sum(xs)/len(xs)+sum(result['auxiliary'])+sum(result['state'])+result['candidate']-result['counter_count']-result['memory_checks']\nprint(json.dumps(result))"
            if fault=='solver_failed':program="raise RuntimeError('synthetic solver failure')"
            return FrozenRecord.from_dict({'analysis':'Execute the candidate, qualified state, forecast checks, critiques, retrieved counter-source and selected measurements.','program':program})
        return FrozenRecord.from_dict({'objective_digest':m['required_objective_digest'],'outcome':'unknown','evidence_ids':[],
            'conclusion':'Synthetic observation: '+b['execution_feedback'][0]['stdout'],'programme_complete':False})
    port=model_port(root/'c4-port',patch,max_calls=169,max_tokens=2000,schemas=model_schemas(),response_factory=respond)
    b=old.data()
    body={k:b[k] for k in ('export_mode','stage','domain','item_ids','task_bindings','history_binding','history_inputs','parent','scorer','scorer_handle_bindings','objective','image','timeout_seconds')}
    body.update(schema='c4-full-loo-runtime-plan-v1',composition=composition.data(),fixed_builder=fixed.record.data(),materials=materials,
        phase_materials=phases,source_verifier_binding=source.binding().data(),corpus_verifier_binding=corpus.binding().data(),model_config=model_configuration(port).data())
    setup.update(plan=FrozenFullLooRuntimePlan(FrozenRecord.from_dict(body),history,old.history_inputs),port=port,seen=seen,source=source,corpus=corpus,
        state_calls=state_calls,corpus_calls=corpus_calls,retrieval_calls=retrieval_calls)
    return setup


def service(setup,stack,panel,fault=None):
    setup['scorer_factory_calls']=setup.get('scorer_factory_calls',0)+1
    if fault=='scorer_startup':raise OSError('synthetic scorer factory startup outage')
    root=setup['root'];b=setup['plan'].data();rubric=ScorerConfig(FrozenRecord.from_dict(b['scorer']))
    (root/'execution.key').write_bytes(EXECUTION.key);(root/'score.key').write_bytes(SCORER.key)
    server={'schema':'c4-full-loo-scorer-process-config-v1','panel':serialize_combination_panel(panel,full_loo=True),
        'scorer_config':rubric.record.data(),'scorer_config_digest':rubric.digest,
        'train_reference_store':{'root':str(setup['store'].resolve()),'manifest_sha256':setup['manifest_sha'],
            'inventory_digest':panel.cells[0].identity.dataset_version,'split_digest':panel.split_digest},'task_handles':setup['handles'],
        'execution_authority_key_files':{EXECUTION.authority_id:str(root/'execution.key')},
        'scorer_authority':{'id':SCORER.authority_id,'key_file':str(root/'score.key')},'evaluator':{'synthetic_mode':'fail' if fault=='scorer_failed' else 'normal'}}
    path=root/'c4-server.json';path.write_text(canonical(server),encoding='utf-8')
    command=_command(path,root/'c4-worker.jsonl');command[1]=str((Path(__file__).parent/'helpers/full_loo_scorer_process_helper.py').resolve())
    client=CombinationScorerProcessClient(panel=panel,config=rubric,full_loo=True,command=command,journal_path=root/'c4-client.jsonl',
        task_handle_bindings=b['scorer_handle_bindings'],execution_authority_keys={EXECUTION.authority_id:EXECUTION.key},
        scorer_authority_keys={SCORER.authority_id:SCORER.key},environment={**os.environ,'PYTHONIOENCODING':'gbk'})
    setup.setdefault('clients',[]).append(client)
    if fault=='scorer_scope':client.full_loo=False
    return client


def invoke(setup,patch,fault=None):
    if fault=='builder_failed':
        def fail(*args,**kwargs):raise ContractError('synthetic builder outage')
        patch.setattr(RestrictedBuilderPort,'execute',fail)
    with ExitStack() as stack:
        exporter=setup['exporter']
        return run_full_loo_train(setup['plan'],prospective_exporter=exporter,snapshot_root=Path(exporter.config['snapshot_root']),
            export_root=exporter.output_root,run_root=setup['root']/'run',model=setup['port'],audit_verifier=AUDIT,
            source_verifier=setup['source'],corpus_verifier=setup['corpus'],provider=Provider(setup['retrieval_calls']),
            scorer_factory=lambda panel:service(setup,stack,panel,fault),execution_authority=EXECUTION,scorer_authority_keys={SCORER.authority_id:SCORER.key})


@pytest.fixture(scope='module')
def grid(tmp_path_factory):
    with pytest.MonkeyPatch.context() as patch:
        setup=prepare(tmp_path_factory.mktemp('full-loo'),patch);run=invoke(setup,patch)
    return setup,run


def test_actual_complete_22_cell_composition(grid):
    setup,run=grid;b=run.receipt.data()
    assert b['status']=='complete_train_engineering',b
    assert len(run.builds)==9 and len(run.results)==len(run.scores)==22 and len(b['structural'])==2
    assert b['actual']=={'model_calls':169,'builder_executions':9,'independent_source_qualification_calls':62,'corpus_qualification_calls':58,
        'retrieval_requests':87,'auxiliary_docker_attempts':58,'solver_docker_attempts':22,'docker_attempts':80,'scorer_calls':22}
    assert not any(b['unused'].values()) and len(setup['seen'])==169 and len(setup['state_calls'])==62 and len(setup['corpus_calls'])==58
    assert b['scorer_process']['closed'] is True and b['scorer_process']['close_attempts']==1
    assert all(c.process.poll() is not None for c in setup['clients'])
    assert b['p0']['required'] is True and b['p0']['scientific_execution_qualified'] is False
    assert len(setup['retrieval_calls'])==87
    assert b['unchanged_parent_package_digest']==setup['plan'].parent.digest and b['candidate_activation']=='none_offline_experiment'
    full_build=next(r for r in run.builds if r.cell.arm_id=='full')
    full_target=next(r for r in run.results if r is not None and r.cell.arm_id=='full')
    descriptors=[]
    for result in (full_build,full_target):
        descriptors.extend(json.loads(line)['descriptor'] for line in (result.root/'runtime/artifacts.jsonl').read_text(encoding='utf-8').splitlines())
    assert {d['module'] for d in descriptors if d['coverage']=='covered'} >= {f'M{i}' for i in range(1,10)}
    assert all(d['scientific_validated'] is False for d in descriptors)
    recipes=setup['plan'].composition.data()['cells'];by_id={r['id']:r for r in recipes}
    assert run.barrier.package(by_id['full'])==run.barrier.package(by_id['without-M8'])
    assert run.barrier.package(by_id['B0'])==run.barrier.package(by_id['ordinary-control'])
    for r in run.results:
        verify_full_loo_cell(r,barrier=run.barrier,panel=run.panel,ledger=run.ledger)
        out=json.loads(r.solver.execution.record.data()['stdout'])
        assert 'candidate' in out
        if r.cell.arm_id=='B0':assert out['auxiliary']==out['state']==out['review_checks']==[]
        else:
            assert len(out['auxiliary'])==2 and out['state'] and len(out['review_checks'])==2 and len(out['directions'])==3
            assert out['choice']['job_id']==r.phase.data()['selection']['selected'][-1]
            assert not r.phase.data()['remaining_leases'] and not r.phase.data()['residual_containers']
            phase=r.phase.data();scheduled='M8' in r.cell.runtime_arm.data()['enabled']
            assert phase['peak_dispatches']==(2 if scheduled else 1)
            assert phase['peak_leases']==(2 if scheduled else 0)
            assert phase['actual_docker_attempts']==2
            # Short tasks can have zero overlap under host scheduling. Preserve
            # the observed interval without turning it into a throughput claim.
            assert 0<=phase['overlap_ns']<=phase['wall_ns']
            if not scheduled:assert phase['overlap_ns']==0
        enabled=set(r.cell.runtime_arm.data()['enabled'])
        events=[json.loads(x) for x in (r.root/'runtime/trace.jsonl').read_bytes().splitlines()]
        reviews=[e['data']['request']['module_context'] for e in events if e['stage']=='model_request' and e['data']['request']['slot'].startswith('review_')]
        if 'M5' in enabled:assert all(x['prior_responses']==[] for x in reviews)
        elif reviews:assert len(reviews[1]['prior_responses'])==1
    for contrast in b['contrasts']:assert contrast['confidence_interval'] is None and contrast['unrestricted_interactions']=='not_identified'


def test_closed_scorer_scope_and_history_removal(grid):
    setup,run=grid;wire=serialize_combination_panel(run.panel,full_loo=True)
    assert parse_combination_panel(wire,full_loo=True)==run.panel
    for flags in ({},{'execution_improvement':True},{'mechanism_improvement':True},{'state_improvement':True},{'full_loo':1},{'full_loo':True,'execution_improvement':True}):
        with pytest.raises(ContractError):parse_combination_panel(wire,**flags)
    for family in ('lineage_retrieval_improvement','mechanism_exploration',
                   'mechanism_scheduling','admission_prediction_exploration'):
        with pytest.raises(ContractError):parse_combination_panel(wire,**{family:True})
        with pytest.raises(ContractError):parse_combination_panel(wire,full_loo=True,**{family:True})
    for build in run.builds:
        body=build.record.data();active=set(build.cell.runtime_arm.data()['enabled']);assert 'M8' not in active
        removed=body['recipe'].get('removed_module')
        if removed:assert removed not in active
        events=[json.loads(x) for x in (build.root/'runtime/trace.jsonl').read_bytes().splitlines()]
        assert len([e for e in events if e['stage']=='model_request'])==5
        prediction=next(e for e in events if e['stage']=='c4_prediction_frozen')
        assert (prediction['data']['registered'] is not None)==('M4' in active)
        assert bool((build.root/'runtime/reviews.jsonl').read_bytes())==('M5' in active)


@pytest.mark.parametrize('fault',['source_unknown','model_unknown','builder_failed','auxiliary_failed','source_drift'])
def test_failure_denominators_no_candidate_activation(tmp_path,monkeypatch,fault):
    setup=prepare(tmp_path,monkeypatch,fault);run=invoke(setup,monkeypatch,fault);b=run.receipt.data()
    assert b['status']=='inconclusive' and len(b['targets'])==22 and len(b['structural'])==2 and len(b['builds'])==9
    assert all(r['status']=='blocked' for r in b['targets']) and not run.scores
    assert b['unchanged_parent_package_digest']==setup['plan'].parent.digest and b['actual']['scorer_calls']==0
    assert all(v>=0 for v in b['unused'].values())
    if fault in ('source_unknown','model_unknown'):assert len(run.builds)==1


def test_coherently_rehashed_prediction_after_choice_rejected(grid):
    _,run=grid;r=run.results[0];path=r.root/'runtime/trace.jsonl';raw=path.read_bytes()
    try:
        rows=[json.loads(x) for x in raw.splitlines()]
        pred=next(e for e in rows if e['stage']=='c4_prediction_frozen');rows.remove(pred)
        rows.insert(next(i for i,e in enumerate(rows) if e['stage']=='c4_choice_frozen')+1,pred)
        _rewrite_trace(path,lambda existing:existing.__setitem__(slice(None),rows));verify_trace(path)
        # Generic hash replay passes; the C4 immutable original and causal
        # replay must still reject rehashed stage substitutions.
        with pytest.raises(ContractError):verify_full_loo_cell(r,barrier=run.barrier,panel=run.panel,ledger=run.ledger)
    finally:path.write_bytes(raw)


@pytest.mark.parametrize('fault',['solver_failed','scorer_failed'])
def test_target_and_independent_scorer_failures_remain_in_denominator(tmp_path,monkeypatch,fault):
    setup=prepare(tmp_path,monkeypatch,fault);run=invoke(setup,monkeypatch,fault);b=run.receipt.data()
    assert b['status']=='inconclusive' and len(run.builds)==9 and len(b['targets'])==22 and len(b['structural'])==2
    assert b['actual']['docker_attempts']==80 and len(run.scores)==0
    assert all(r['status']=='failed' for r in b['targets'])
    assert b['actual']['scorer_calls']==(22 if fault=='scorer_failed' else 0)
    assert all(p['difference'] is None for contrast in b['contrasts'] for p in contrast['paired_rows'])


def test_composed_candidate_whole_package_durable_rollback(grid,tmp_path):
    """Host authority fixture only: this is not C5 validation or acceptance."""
    from research_loop.modular.deployment import FileDeploymentPort
    from research_loop.modular.modules.improvement import ExecutionRuntime
    from test_modular_improvement import authority, signed_validation, candidate_box
    setup,run=grid;parent=setup['plan'].parent
    candidate=run.barrier.package(setup['plan'].composition.data()['cells'][0])
    deployment=FileDeploymentPort(tmp_path/'deployment.json',parent)
    candidate_box.update(candidate=candidate,active=parent.digest);auth=authority()
    runtime=ExecutionRuntime(tmp_path/'runtime.sqlite',deployment,auth,parent)
    try:
        initial=(tmp_path/'deployment.json').read_bytes()
        runtime.activate(auth.validate(candidate,parent.digest,signed_validation()),candidate)
        assert runtime.run_task(setup['plan'].history.task.identity,lambda _,p:p.record.data()).data()['result']==candidate.record.data()
        runtime.rollback(auth.authorize_rollback(candidate.digest,parent.digest,'synthetic whole-package recovery'))
        assert (tmp_path/'deployment.json').read_bytes()==initial
        assert runtime.active()==parent and deployment.current().active_digest==parent.digest
    finally:runtime.close()
    reopened=ExecutionRuntime(tmp_path/'runtime.sqlite',deployment,auth,parent)
    try:assert reopened.run_task(setup['plan'].history.task.identity,lambda _,p:p.record.data()).data()['result']==parent.record.data()
    finally:reopened.close()


def test_original_input_and_candidate_barrier_bytes_replayed(grid):
    _,run=grid;r=run.results[0];csv=run.barrier.packets[0].csv_path;raw=csv.read_bytes()
    try:
        csv.write_bytes(raw+b' ')
        with pytest.raises(ContractError):verify_full_loo_cell(r,barrier=run.barrier,panel=run.panel,ledger=run.ledger)
    finally:csv.write_bytes(raw)
    barrier=run.barrier.root/'candidate-barrier.json';raw=barrier.read_bytes()
    try:
        b=json.loads(raw);b['candidate_selections']['full']='0'*64;barrier.write_text(canonical(b)+'\n',encoding='utf-8')
        with pytest.raises(ContractError):verify_full_loo_cell(r,barrier=run.barrier,panel=run.panel,ledger=run.ledger)
    finally:barrier.write_bytes(raw)


@pytest.mark.parametrize('fault',['scorer_startup','scorer_scope'])
def test_scorer_startup_rejection_closes_22_executed_rows_without_rpc(tmp_path,monkeypatch,fault):
    setup=prepare(tmp_path,monkeypatch,fault);run=invoke(setup,monkeypatch,fault);b=run.receipt.data()
    assert len(run.results)==22 and all(r.record.data()['status']=='succeeded' for r in run.results)
    assert b['status']=='inconclusive' and all(r['status']=='scoring_blocked' for r in b['targets'])
    assert b['scorer_process']['startup_attempts']==1 and b['scorer_process']['startup_status']=='failed'
    assert b['actual']['scorer_calls']==0 and b['unused']['scorer_calls']==22 and not run.scores
    if fault=='scorer_scope':
        assert b['scorer_process']['closed'] is True
        assert all(c.process.poll() is not None and c.states=={} for c in setup['clients'])
