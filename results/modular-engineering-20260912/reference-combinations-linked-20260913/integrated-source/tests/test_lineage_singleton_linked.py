"""Public synthetic lineage mechanisms must reach the shared benchmark solver."""
import pytest
from evaluation.modular.train_io import TrainPacketExporter
from evaluation.modular.scoring_service import ScorerConfig, FrozenBenchmarkRubricEndpoint
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.history_panel_drivers import freeze_history_bundle
from research_loop.modular.support_panel_drivers import freeze_support_bundle
from research_loop.modular.panel_plan import obligation_grids, executable_arms
from research_loop.modular.panel_runner import DRIVERS
from research_loop.modular.train_controller import FrozenTrainControllerConfig
from test_modular_train_controller import config, snapshot_and_custody, REVIEW, FINAL
from test_modular_linked_train_controller import ANALYSIS


def _history(task):
    def row(withdrawal, dependency):
        return {'pre_transition_summary':'An earlier observation measured x as 8.',
            'post_transition_summary':'The currently published observation measures x as 1.',
            'upstream_claim':'The earlier observation supports x=8.',
            'downstream_claim':'The interpretation relies on the earlier observation.',
            'withdrawal':withdrawal,'dependency':dependency}
    return freeze_history_bundle(task,before_evidence={'observation_id':'public-record-0','x':8,'mode':'instrument-setting','ephemeral':False},
        current_evidence={'observation_id':'public-record-1','x':1,'mode':'instrument-setting','ephemeral':False},
        transition={'action':'replace_public_measurement','reason':'The source superseded its earlier observation.'},
        q11={'correct':{'historical_summary':'The present observation measures x as 1.'},
             'wrong':{'historical_summary':'The present observation measures x as 8.'},
             'neutral':{'historical_summary':'Inspect the current public observation.'}},
        q12={'summary_only':row(False,False),'registered':row(False,True),'withdraw':row(True,True)})


def _support(task):
    def source(index,value):
        return {'root_material':{'source_id':'public-origin-'+str(index)},'public_evidence':{'x':value,'mode':'instrument-setting','ephemeral':False}}
    a,b=source(0,1),source(1,2)
    def row(sources,actions):
        return {'sources':sources,'withdraw_actions':[{'source_key':k,'reason':'The source withdrew this observation.'} for k in actions],
            'claim_statement':'The supplied observations support an estimate of x.'}
    return freeze_support_bundle(task,
        q13={variant:{'source':a,'representation':rep,'claim_statement':'The observation supports x=1.'}
            for variant,rep in [('log','raw'),('report','report'),('summary','summary'),('memory','summary')]},
        q14={'one_withdrawn':row({'public-record-0':a,'public-record-1':a,'public-record-2':b},['public-record-0']),
             'all_withdrawn':row({'public-record-0':a,'public-record-1':b},['public-record-0','public-record-1']),
             'copies':row({'public-record-0':a,'public-record-1':a},[])})


def _config(root, group):
    snapshot,custody=snapshot_and_custody(root)
    base=config(custody,snapshot,root).data()
    packets=TrainPacketExporter(custody,snapshot,root/'material').export(base['item_ids'])
    scope=('Q1.1','Q1.2') if group=='history' else ('Q1.3','Q1.4')
    count=30 if group=='history' else 28
    grids=obligation_grids(scope,baseline_digest=base['baseline_digest'],p0_control=FrozenRecord.from_dict(base['p0_control']))
    package=next(iter(base['packages_by_arm'].values()))
    slots={slot for q in scope for slot in DRIVERS[q].slots}
    body={**base,'schema':'train-panel-controller-v1','engineering_scope':'train_only_panel_engineering',
        'stage':'public-train-'+group,'scope_ids':list(scope),'execution_mode':'linked_benchmark_solve',
        'evidence_by_task':{p.task.content_hash:(_history if group=='history' else _support)(p.task).data() for p in packets},
        'packages_by_arm':{a.content_hash:package for g in grids.values() for a in executable_arms(g).values()},
        'budget':{'model_calls':3,'execution_limit':0},'max_calls':count*5,'max_tokens':count*20,
        'schemas':{**{s:FINAL if s=='final' else REVIEW for s in slots},'analysis_program':ANALYSIS,'final_answer':FINAL},
        'scorer':ScorerConfig.create(benchmark='core_pair',evaluator_id='synthetic-primary',version='v1',
            rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest()).record.data()}
    return snapshot,custody,FrozenTrainControllerConfig(FrozenRecord.from_dict(body)),packets


@pytest.mark.parametrize('group,count',[('history',30),('support',28)])
def test_all_four_questions_have_frozen_linked_solver_configuration(tmp_path,group,count):
    _,_,frozen,_=_config(tmp_path,group)
    assert frozen.data()['max_calls']==count*5

import json
import hashlib
from research_loop.modular.runtime import AuditAuthority, AuditVerifier
from research_loop.modular.modules.admission import ScientificState, AuditItem
from research_loop.modular.train_controller import run_train_panel
from research_loop.modular.linked_public_projection import project_linked_public_context
from research_loop.ontology import ContractError
from test_modular_train_controller import model_port

KEYS={'source-a':b'a'*32,'source-b':b'b'*32}


def _admit(task,record):
    # This is explicit synthetic host qualification, never scientific calibration.
    audits=[AuditAuthority(name,key).issue_material(identity=task.identity,subject_digest=record.content_hash,
        execution_success=True,state=ScientificState('valid','supported','known','explore'),outcome='positive',
        audit=[AuditItem('measurement',True,True)]) for name,key in KEYS.items()]
    verified=AuditVerifier(KEYS).verify_material(audits,identity=task.identity,subject_digest=record.content_hash,required_audit=('measurement',))
    assert verified.data()['subject_digest']==record.content_hash
    return {'record_digest':record.content_hash,'trusted_validator':'+'.join(sorted(KEYS)),
        'validator_verified':True,'admitted':True}


def _response(request):
    body=request.data();context=body['module_context'];slot=body['slot']
    if slot=='analysis_program':
        material=context['predecessor_context']['mechanism_material']
        entries=material['context']['entries']['entries']
        roots=sorted({entry['root_id'] for entry in entries if entry['kind']=='evidence'})
        # Actual public state changes the executed program and stdout.
        return FrozenRecord.from_dict({'analysis':'Read the public CSV and report the supplied context.',
            'program':"import csv,json\nwith open('/input/public_csv', newline='') as f:\n rows=list(csv.DictReader(f))\nprint(json.dumps({'mean':sum(float(r['x']) for r in rows)/len(rows),'visible_roots':"+repr(roots)+"}))"})
    if slot in {'final','final_answer'}:
        return FrozenRecord.from_dict({'objective_digest':context['required_objective_digest'],'outcome':'unknown',
            'evidence_ids':[],'programme_complete':False,
            'conclusion':('Actual observed output: '+str(context.get('execution_feedback',[]))) if slot=='final_answer' else 'The supplied public context was assessed.'})
    return FrozenRecord.from_dict({'assessment':'unknown','evidence_refs':[],'counterexamples':[],
        'uncertainty':'Public source context requires independent scientific assessment.'})


@pytest.fixture(scope='module',params=['history','support'])
def linked_grid(request,tmp_path_factory):
    root=tmp_path_factory.mktemp('lineage-'+request.param)
    monkeypatch=pytest.MonkeyPatch()
    try:
        snapshot,custody,frozen,_=_config(root,request.param)
        port=model_port(root/'port',monkeypatch,max_calls=frozen.data()['max_calls'],max_tokens=frozen.data()['max_tokens'],
            schemas=frozen.data()['schemas'],response_factory=_response)
        result=run_train_panel(frozen,custody=custody,snapshot_root=snapshot,export_root=root/'export',run_root=root/'run',
            model=port,audit_verifier=AuditVerifier(KEYS),history_admission_port=_admit)
        yield result,port,root,request.param
    finally:
        monkeypatch.undo()


def test_full_grid_uses_actual_context_in_solver_and_docker(linked_grid):
    result,port,root,group=linked_grid
    count=30 if group=='history' else 28
    assert len(result.linked_results)==len(result.runtimes)==count
    assert result.receipt.data()['linked_statuses']==['linked_succeeded']*count
    assert len(port.ledger['calls'])==count*5
    assert not result.verdict.scientific_verified
    for row in result.linked_results:
        assert row.solver.execution.status=='succeeded'
        task=result.compiled.tasks[row.cell.task_digest];scenario=result.compiled.scenarios[row.cell.key]
        projection=project_linked_public_context(provenance=row.provenance,cell=row.cell,task=task,scenario=scenario)
        material=projection.data()['mechanism_material'];entries=material['context']['entries']['entries']
        roots=sorted({item['root_id'] for item in entries if item['kind']=='evidence'})
        actual=json.loads(row.solver.execution.record.data()['stdout'])
        assert actual=={'mean':1.0,'visible_roots':roots}
        events=[json.loads(line) for line in row.mechanism.runtime.trace_path.read_text(encoding='utf-8').splitlines()]
        solver=[json.loads(line) for line in (row.solver.session.sidecar/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
        for event in events+solver:
            if event['stage']!='model_request':continue
            public=FrozenRecord.from_dict(event['data']['request']).encoded
            assert not any(label in public for label in ('Q1.1','Q1.2','Q1.3','Q1.4','q11-','q12-','q13-','q14-','arm_id','expected_correctness'))
        final_request=next(event['data']['request'] for event in events if event['stage']=='model_request' and event['data']['request']['slot']=='final')['module_context']
        assert material['source_material']==final_request.get('history_material',final_request.get('public_support_state'))
        solver_requests=[event['data']['request'] for event in solver if event['stage']=='model_request']
        assert len(solver_requests)==2
        assert all(item['module_context']['predecessor_context']==projection.data() for item in solver_requests)
        enabled=row.cell.runtime_arm.data()['enabled']
        if row.cell.coverage_id=='Q1.3' and 'M2' in enabled: assert len(roots)==1
        if row.cell.coverage_id=='Q1.4' and 'M2' in enabled:
            assert len(roots)=={'copies':1,'one_withdrawn':1,'all_withdrawn':0}[row.cell.variant]
        if row.cell.coverage_id=='Q1.1' and 'M3' in enabled:
            assert len(roots)==1
            assert next(item for item in entries if item['kind']=='evidence')['payload']['content']['x']==1
        if row.cell.coverage_id=='Q1.2' and 'M3' in enabled and row.cell.variant=='withdraw': assert roots==[]


def test_every_actual_solver_result_reaches_independent_primary_process(linked_grid):
    from evaluation.modular.linked_scoring import issue_linked_score_input,verify_linked_adapted_receipt
    from evaluation.modular.scorer_process import LinkedScorerProcessClient
    from test_scorer_process import _config as process_config,_command
    from test_train_adapted_selection import EXEC,SCORER
    from research_loop.ontology import canonical
    result,_,root,_=linked_grid
    args={'panel':result.compiled.panel,'tasks':result.compiled.tasks,
        'config':ScorerConfig.create(benchmark='core_pair',evaluator_id='synthetic-primary',version='v1',
            rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest())}
    private=root/'independent-fixture';private.mkdir()
    cfg=process_config(private,args);path=private/'worker.json';path.write_text(canonical(cfg),encoding='utf-8')
    client=LinkedScorerProcessClient(panel=args['panel'],command=_command(path,private/'worker.jsonl'),journal_path=private/'client.jsonl')
    scores=[]
    try:
        for row in result.linked_results:
            source=issue_linked_score_input(panel=args['panel'],result=row,task=args['tasks'][row.cell.task_digest],
                scenario=result.compiled.scenarios[row.cell.key],package=result.compiled.packages[row.cell.runtime_arm.content_hash],authority=EXEC)
            score=client.submit(cell_key=row.cell.key,linked_input=source)
            verified=verify_linked_adapted_receipt(score,authority_keys={SCORER.authority_id:SCORER.key},config=args['config'],
                panel=args['panel'],cell=row.cell,linked_input=source,execution_authority_keys={EXEC.authority_id:EXEC.key})
            assert verified.data()['scientific_validity']=='not_measured'
            scores.append(score.receipt.data())
    finally:client.close()
    assert len(scores)==len(result.linked_results)
    (private/'verified-scores.json').write_text(json.dumps(scores),encoding='utf-8')
    assert 'PRIVATE-REFERENCE-SENTINEL' not in (private/'client.jsonl').read_text(encoding='utf-8')
    assert 'PRIVATE-REFERENCE-SENTINEL' not in (private/'worker.jsonl').read_text(encoding='utf-8')


@pytest.mark.parametrize('fault',['stage','root','context','admission_subject','missing_admission','failed_source','malformed','output_digest'])
def test_replay_rejects_mutated_actual_lineage(linked_grid,fault):
    result,*_=linked_grid
    row=next(item for item in result.linked_results if 'M2' in item.cell.runtime_arm.data()['enabled'])
    body=row.provenance.data();proof=body['lineage_replay'];events=proof['events']
    if fault=='stage':
        event=next(e for e in events if e['stage']=='modular_workflow' and e['data']['stage'] not in {'operation_public_material_admission','operation_public_material_admission_attempt'})
        event['data']['status']='failed'
    elif fault=='root':proof['evidence_events'][0]['root_id']='f'*64
    elif fault=='context':
        event=next(e for e in events if e['stage']=='model_request')
        event['data']['request']['module_context']['context_material' if 'context_material' in event['data']['request']['module_context'] else 'claim_context']['entries']={'entries':[]}
        event['data']['request_digest']=FrozenRecord.from_dict(event['data']['request']).content_hash
    elif fault=='admission_subject':
        event=next(e for e in events if e['stage']=='modular_workflow' and e['data']['stage']=='operation_public_material_admission')
        event['data']['receipt']['record_digest']='0'*64
    elif fault=='missing_admission':
        events[:]=[e for e in events if not(e['stage']=='modular_workflow' and e['data']['stage']=='operation_public_material_admission')]
    elif fault=='malformed':proof['claim_events']=None
    elif fault=='output_digest':body['runtime_output_digest']='f'*64
    else:events[-1]['data']['decision']='blocked'
    # A newly self-consistent hash chain is insufficient to pass operation replay.
    previous=None
    for index,event in enumerate(events):
        event['sequence']=index;event['previous']=previous;previous=FrozenRecord.from_dict(event).content_hash
    body['runtime_trace_digest']=previous
    body['mechanism_stages']=[{'stage':e['data']['stage'],'data':e['data']} for e in events if e['stage']=='modular_workflow']
    with pytest.raises(ContractError):
        project_linked_public_context(provenance=FrozenRecord.from_dict(body),cell=row.cell,
            task=result.compiled.tasks[row.cell.task_digest],scenario=result.compiled.scenarios[row.cell.key])


def test_fixed_actual_ledger_file_is_required_and_cannot_be_substituted(linked_grid,tmp_path):
    import shutil
    from dataclasses import replace
    from research_loop.modular.benchmark_cell import verified_mechanism_provenance
    result,*_=linked_grid
    row=next(item for item in result.linked_results if 'M2' in item.cell.runtime_arm.data()['enabled'])
    sidecar=tmp_path/'copied-sidecar';shutil.copytree(row.mechanism.runtime.trace_path.parent,sidecar)
    target=sidecar/'evidence.jsonl';target.write_text('',encoding='utf-8')
    mechanism=replace(row.mechanism,runtime=replace(row.mechanism.runtime,trace_path=sidecar/'trace.jsonl'))
    with pytest.raises(ContractError,match='ledger'):
        verified_mechanism_provenance(cell=row.cell,task=result.compiled.tasks[row.cell.task_digest],
            scenario=result.compiled.scenarios[row.cell.key],package=result.compiled.packages[row.cell.runtime_arm.content_hash],mechanism=mechanism)


@pytest.mark.parametrize('group,count,successes',[('history',30,6),('support',28,14)])
def test_admission_failure_keeps_every_cell_and_actual_cost(tmp_path,monkeypatch,group,count,successes):
    snapshot,custody,frozen,_=_config(tmp_path,group)
    port=model_port(tmp_path/'port',monkeypatch,max_calls=frozen.data()['max_calls'],max_tokens=frozen.data()['max_tokens'],
        schemas=frozen.data()['schemas'],response_factory=_response)
    attempts=[]
    def refused(task,record):
        attempts.append(record.content_hash)
        receipt=_admit(task,record);receipt['record_digest']='f'*64
        return receipt
    result=run_train_panel(frozen,custody=custody,snapshot_root=snapshot,export_root=tmp_path/'export',run_root=tmp_path/'run',
        model=port,audit_verifier=AuditVerifier(KEYS),history_admission_port=refused)
    assert len(result.linked_results)==count
    assert sum(row.status=='linked_succeeded' for row in result.linked_results)==successes
    assert sum(row.status=='mechanism_failed' for row in result.linked_results)==count-successes
    assert len(attempts)==count-successes
    assert sum(row.mechanism.call_plan.data()['source_admission_attempts'] for row in result.linked_results)==len(attempts)
    assert all(row.mechanism.call_plan.data()['source_admission_cost']=='not_provided_by_caller_port' for row in result.linked_results if row.status=='mechanism_failed')
    assert len(port.ledger['calls'])==successes*5
    assert sum(row.solver is not None and row.solver.execution is not None for row in result.linked_results)==successes
    assert result.receipt.data()['execution_status']=='execution_incomplete'
    assert result.verdict.decision=='engineering_verified' and not result.verdict.scientific_verified


@pytest.mark.parametrize('fault',['label','bad_bundle','missing_port'])
def test_preflight_rejects_before_model(tmp_path,monkeypatch,fault):
    snapshot,custody,frozen,_=_config(tmp_path,'history');body=frozen.data()
    if fault=='label':
        for bundle in body['evidence_by_task'].values():bundle['q11']['wrong']['historical_summary']='Q1.1 wrong arm expected_correctness'
    if fault=='bad_bundle':
        for bundle in body['evidence_by_task'].values():bundle['q12']['withdraw']['withdrawal']='true'
    frozen=FrozenTrainControllerConfig(FrozenRecord.from_dict(body))
    port=model_port(tmp_path/'port',monkeypatch,max_calls=frozen.data()['max_calls'],max_tokens=frozen.data()['max_tokens'],
        schemas=frozen.data()['schemas'],response_factory=_response)
    with pytest.raises(ContractError):
        run_train_panel(frozen,custody=custody,snapshot_root=snapshot,export_root=tmp_path/'export',run_root=tmp_path/'run',
            model=port,audit_verifier=AuditVerifier(KEYS),history_admission_port=None if fault=='missing_port' else _admit)
    assert port.ledger['calls']==[]


@pytest.mark.parametrize("group",["history","support"])
def test_source_authority_labels_stay_out_of_actual_mechanism_requests(tmp_path,group):
    from test_modular_history_panel_drivers import _rows,_model
    from research_loop.modular.panel_runner import run_train_cell
    compiled,tasks,_=_rows('Q1.1')
    cell=next(item for item in compiled.panel.cells if 'M3' in item.runtime_arm.data()['enabled'])
    if group=='support':
        from test_modular_support_panel_drivers import _q13_cell
        task,_,compiled,cell,_=_q13_cell();tasks={task.identity.benchmark:task}
    seen=[];private_name='Q1.1-arm_id-correct-source-authority'
    def labelled(task,record):
        receipt=_admit(task,record);receipt['trusted_validator']=private_name;return receipt
    result=run_train_cell(cell,task=tasks[cell.identity.benchmark],scenario=compiled.scenarios[cell.key],
        package=compiled.packages[cell.runtime_arm.content_hash],objective=FrozenRecord.from_dict({'purpose':'public training'}),
        sidecar=tmp_path/'cell',model=_model(seen),audit_verifier=AuditVerifier(KEYS),history_admission_port=labelled)
    assert result.runtime.status=='succeeded'
    assert len(seen)==3
    assert private_name not in FrozenRecord.from_dict({'requests':seen}).encoded
    assert private_name in result.runtime.trace_path.read_text(encoding='utf-8')


def test_late_source_failure_preserves_already_spent_model_slot(tmp_path):
    from test_modular_history_panel_drivers import _rows,_model
    from research_loop.modular.benchmark_cell import run_benchmark_cell,verify_linked_benchmark_cell
    from research_loop.modular.benchmarks.execution import DockerExecutionBroker
    from test_modular_linked_train_controller import IMAGE
    compiled,tasks,_=_rows('Q1.1');cell=compiled.panel.cells[0];seen=[];attempts=[]
    def port(task,record):
        attempts.append(record.content_hash)
        if len(attempts)==2: raise RuntimeError('private upstream error must not enter public context')
        return _admit(task,record)
    csv=tmp_path/'public.csv';csv.write_text('x\n1\n',encoding='utf-8')
    result=run_benchmark_cell(cell=cell,task=tasks[cell.identity.benchmark],scenario=compiled.scenarios[cell.key],
        package=compiled.packages[cell.runtime_arm.content_hash],objective=FrozenRecord.from_dict({'purpose':'public training'}),
        mechanism_sidecar=tmp_path/'mechanism',solver_sidecar=tmp_path/'solver',public_inputs={'public_csv':csv},image=IMAGE,
        broker=DockerExecutionBroker([tmp_path]),model=_model(seen),audit_verifier=AuditVerifier(KEYS),history_admission_port=port)
    assert result.status=='mechanism_failed' and result.solver is None
    assert len(seen)==1 and len(attempts)==2
    assert result.mechanism.call_plan.data()['model_calls']==1
    assert result.mechanism.call_plan.data()['source_admission_attempts']==2
    events=result.mechanism.runtime.trace_path.read_text(encoding='utf-8')
    assert 'operation_public_material_admission_failure' in events and 'private upstream error' not in events
    verified=verify_linked_benchmark_cell(result,task=tasks[cell.identity.benchmark],scenario=compiled.scenarios[cell.key],
        package=compiled.packages[cell.runtime_arm.content_hash])
    assert verified.data()['engineering_verified'] is True


def test_public_projection_preserves_scientific_fields_named_like_metadata():
    from research_loop.modular.lineage_singleton_replay import _public
    material={'source_material':{'public_record':{'evidence':{'mode':'instrument-setting','ephemeral':False}}},
        'context':{'entries':{'entries':[{'kind':'evidence','payload':{
            'trusted_validator':'private-id','validator_verified':True,
            'content':{'mode':'instrument-setting','ephemeral':False}}}]}}}
    result=_public(material)
    assert result['source_material']==material['source_material']
    payload=result['context']['entries']['entries'][0]['payload']
    assert payload=={'content':{'mode':'instrument-setting','ephemeral':False}}
