"""Actual synthetic train jobs; no paid or validation access."""
def test_registered_exploration_scheduler_design_is_complete_without_background():
    from research_loop.modular.exploration_scheduler_combination import registered_design
    design=registered_design('a'*64).data()
    rows=[r for r in design['cells'] if r['status']=='executable']
    assert len(rows)==4
    assert {tuple(r['arm']['enabled']) for r in rows}=={(),('M7',),('M8',),('M7','M8')}
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from dataclasses import replace
import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.exploration_scheduler_combination import (SLOTS,FrozenExplorationSchedulerMaterial,
    registered_design,verify_exploration_scheduler_cell,run_phase,verify_phase,selection)
from research_loop.modular.exploration_scheduler_controller import (FrozenExplorationSchedulerTrainConfig,
    compile_exploration_scheduler_train_panel,run_exploration_scheduler_train_panel)
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError,canonical
from evaluation.modular.scorer_process import CombinationScorerProcessClient,serialize_combination_panel
from evaluation.modular.scoring_service import ScorerConfig,FrozenBenchmarkRubricEndpoint
from test_lineage_combination_controller import _fixture as old_fixture,_sources,EXECUTION,SCORER
from test_modular_train_controller import model_port,FINAL
from test_modular_combination_train_controller import ANALYSIS
from test_scorer_process import _store,_command

SCHEMAS={'analysis_program':ANALYSIS,'final_answer':FINAL}


def fixture(root,job_fault=None,scorer_fault=None):
    snapshot,custody,packets,old,_,_=old_fixture(root,_sources([]))
    body=old.data();body.pop('source_verifier_binding');body.update(schema='exploration-scheduler-train-controller-config-v1',
        stage='synthetic-exploration-scheduling',max_calls=16,schemas=SCHEMAS)
    package=next(iter(body['packages_by_arm'].values()))
    body['packages_by_arm']={row['arm_digest']:package for row in registered_design('a'*64).data()['cells'] if row['status']=='executable'}
    body['allocation']={'model_slots_per_cell':list(SLOTS),'docker_attempts_per_cell':3,'auxiliary_docker_attempts_per_cell':2,
        'scorer_calls_per_cell':1,'scorer_call_limit':8,'scorer_token_accounting':'transport_not_provided'}
    for packet in packets:
        old_m=body['materials_by_task'][packet.task.content_hash]
        jobs=[]
        for i in range(3):
            program="import csv,time\ntime.sleep(0.15)\nwith open('/input/public_csv',newline='') as f:\n rows=list(csv.DictReader(f))\nprint(sum(float(r['x']) for r in rows)+"+str(i)+")"
            if job_fault=='docker_failed':program="raise ValueError('public fixture failure')"
            jobs.append({'id':hashlib.sha256(('public-job-'+str(i)).encode()).hexdigest(),'purpose':'probe' if i==2 else 'main',
                'program':program,'dependencies':[],'resources':[hashlib.sha256(('resource-'+str(i)).encode()).hexdigest()],'cost_units':1})
        body['materials_by_task'][packet.task.content_hash]={'schema':'exploration-scheduler-material-v1','identity':packet.task.identity.data(),
            'task_digest':packet.task.content_hash,'public_artifacts':old_m['public_artifacts'],'context_budget_bytes':16000,'jobs':jobs}
    rubric=ScorerConfig.create(benchmark='core_pair',evaluator_id='synthetic-primary',version='v1',rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest())
    body['scorer']=rubric.record.data()
    store,handles,sha=_store(root,{'tasks':{p.task.content_hash:p.task for p in packets}})
    body['scorer_handle_bindings']={k:hashlib.sha256(v.encode()).hexdigest() for k,v in handles.items()}
    config=FrozenExplorationSchedulerTrainConfig(FrozenRecord.from_dict(body));compiled=compile_exploration_scheduler_train_panel(config,packets)
    (root/'frozen-config.json').write_text(config.record.encoded,encoding='utf-8')
    (root/'execution.key').write_bytes(EXECUTION.key);(root/'score.key').write_bytes(SCORER.key)
    server={'schema':'exploration-scheduler-scorer-process-config-v1','panel':serialize_combination_panel(compiled.panel,exploration_scheduler=True),
        'scorer_config':rubric.record.data(),'scorer_config_digest':rubric.digest,
        'train_reference_store':{'root':str(store.resolve()),'manifest_sha256':sha,'inventory_digest':packets[0].task.identity.dataset_version,'split_digest':compiled.panel.split_digest},
        'task_handles':handles,'execution_authority_key_files':{EXECUTION.authority_id:str((root/'execution.key').resolve())},
        'scorer_authority':{'id':SCORER.authority_id,'key_file':str((root/'score.key').resolve())},'evaluator':{'synthetic_mode':'fail' if scorer_fault else 'normal'}}
    path=root/'server.json';path.write_text(canonical(server),encoding='utf-8');command=_command(path,root/'worker.jsonl')
    command[1]=str((Path(__file__).parent/'helpers/admission_scorer_process_helper.py').resolve())
    service=CombinationScorerProcessClient(panel=compiled.panel,config=rubric,exploration_scheduler=True,
        command=command,journal_path=root/'client.jsonl',task_handle_bindings=body['scorer_handle_bindings'],
        execution_authority_keys={EXECUTION.authority_id:EXECUTION.key},scorer_authority_keys={SCORER.authority_id:SCORER.key},environment={**os.environ,'PYTHONIOENCODING':'gbk'})
    return snapshot,custody,config,compiled,service


def run(root,patch,fault=None):
    snapshot,custody,config,compiled,service=fixture(root,job_fault=fault,scorer_fault=fault=='scorer_failed');seen=[]
    def respond(request):
        b=request.data();seen.append(b)
        assert not any(v in request.encoded for v in ('"arm_id"','"enabled"','"control"','"purpose"','"selection"','"argv"','"worker"','PRIVATE-REFERENCE-SENTINEL'))
        if b['slot']=='analysis_program':
            if fault=='model_unknown':raise RuntimeError('synthetic unknown provider cost')
            observations=b['module_context']['joint_mechanism']['material']['observations']
            assert len(observations)==2 and all(o['status']=='succeeded' for o in observations)
            values=[float(o['stdout']) for o in observations]
            return FrozenRecord.from_dict({'analysis':'' if fault=='analysis_invalid' else 'Calculate from actual public job returns.',
                'program':"import csv\nwith open('/input/public_csv',newline='') as f:\n rows=list(csv.DictReader(f))\nprint("+repr(sum(values))+")"})
        return FrozenRecord.from_dict({'objective_digest':b['module_context']['required_objective_digest'],'outcome':'unknown','evidence_ids':[],
            'conclusion':'' if fault=='answer_invalid' else 'Actual observation '+b['execution_feedback'][0]['stdout'],'programme_complete':False})
    port=model_port(root/'port',patch,max_calls=16,max_tokens=1000,schemas=SCHEMAS,response_factory=respond)
    try:
        result=run_exploration_scheduler_train_panel(config,custody=custody,snapshot_root=snapshot,export_root=root/'export',run_root=root/'run',
            model=port,audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),execution_authority=EXECUTION,scoring_service=service,scorer_authority_keys={SCORER.authority_id:SCORER.key})
    finally:service.close()
    return result,port,seen,config,root


@pytest.fixture(scope='module')
def grid(tmp_path_factory):
    with pytest.MonkeyPatch.context() as patch:yield run(tmp_path_factory.mktemp('actual-grid'),patch)


def args(grid,executed):
    result,_,_,config,_=grid;packet=next(p for p in result.compiled.packets if p.task.content_hash==executed.cell.task_digest)
    return dict(panel=result.compiled.panel,task=packet.task,scenario=result.compiled.scenarios[executed.cell.key],
        package=result.compiled.packages[executed.cell.runtime_arm.content_hash],
        material=FrozenExplorationSchedulerMaterial(FrozenRecord.from_dict(config.data()['materials_by_task'][executed.cell.task_digest])),
        public_inputs={'public_csv':packet.csv_path},broker=DockerExecutionBroker([packet.csv_path.parent,executed.runtime.trace_path.parent.parent]),
        image=config.data()['image'],timeout_seconds=config.data()['timeout_seconds'])


def test_full_8_actual_cells_24_docker_16_model_and_8_independent_scores(grid):
    result,port,seen,config,root=grid
    assert len(result.results)==len(result.scores)==8,[a.data() for a in result.attempts]
    assert len(seen)==len(port.ledger['calls'])==16
    assert result.receipt.data()['actual_docker_attempts']==24 and result.contrast.data()['status']=='estimated'
    for executed in result.results:
        b=executed.phase.data();enabled=executed.cell.runtime_arm.data()['enabled']
        assert b['actual_docker_attempts']==b['execution_units_reserved']==2 and b['remaining_leases']==b['residual_containers']==[]
        assert b['peak_dispatches']==(2 if 'M8' in enabled else 1)
        assert b['peak_leases']==(2 if 'M8' in enabled else 0)
        assert b['overlap_ns']>0 if 'M8' in enabled else b['overlap_ns']==0
        assert b['selection']['permit'] is not None if 'M7' in enabled else b['selection']['permit'] is None
        assert float(executed.solver.execution.record.data()['stdout'])==sum(float(o['stdout']) for o in b['public']['observations'])
        verify_exploration_scheduler_cell(executed,**args(grid,executed))
    for benchmark in ('blade','discoverybench'):
        outputs={tuple(r.cell.runtime_arm.data()['enabled']):r.solver.execution.record.data()['stdout'] for r in result.results if r.cell.identity.benchmark==benchmark}
        assert outputs[()]==outputs[('M8',)] and outputs[('M7',)]==outputs[('M7','M8')] and outputs[()]!=outputs[('M7',)]
    for name in ('client','worker'):
        rows=[json.loads(x) for x in (root/(name+'.jsonl')).read_text(encoding='utf-8').splitlines()]
        assert [r['status'] for r in rows]==['reserved','succeeded']*8
    assert result.receipt.data()['scientific_effectiveness_proven'] is False


@pytest.mark.parametrize('fault',['docker_failed','analysis_invalid','answer_invalid','model_unknown','scorer_failed'])
def test_failures_preserve_every_planned_cell_and_cost(tmp_path,monkeypatch,fault):
    result,port,seen,_,_=run(tmp_path,monkeypatch,fault)
    assert len(result.results)==8 and not result.scores and result.contrast.data()['status']=='inconclusive'
    b=result.receipt.data();assert b['failed_cells']+b['blocked_cells']==8 and b['pruned_cells']==[]
    assert b['actual_docker_attempts']==({'docker_failed':16,'analysis_invalid':16,'answer_invalid':24,'model_unknown':2,'scorer_failed':24}[fault])
    assert len(seen)==({'docker_failed':0,'analysis_invalid':8,'answer_invalid':16,'model_unknown':1,'scorer_failed':16}[fault])
    if fault=='model_unknown':assert port.ledger['usage_incomplete'] is True and b['blocked_cells']==7
    if fault=='scorer_failed':assert b['actual_scorer_calls']==8


@pytest.mark.parametrize('fault',['bool_cost','foreign_task','missing_job','label','missing_arm','csv_size','rubric','dependency'])
def test_frozen_malformed_material_rejects_before_execution(grid,fault):
    b=grid[3].data();m=next(iter(b['materials_by_task'].values()))
    if fault=='bool_cost':m['jobs'][0]['cost_units']=True
    elif fault=='foreign_task':m['task_digest']='0'*64
    elif fault=='missing_job':m['jobs'].pop()
    elif fault=='label':m['jobs'][0]['program']="print('M7 on expected_correct')"
    elif fault=='missing_arm':b['packages_by_arm'].pop(next(iter(b['packages_by_arm'])))
    elif fault=='csv_size':next(iter(b['task_bindings'].values()))['csv_byte_count']+=1
    elif fault=='rubric':b['scorer']['rubric_digest']='0'*64
    else:m['jobs'][2]['dependencies']=[m['jobs'][1]['id']]
    with pytest.raises(ContractError):FrozenExplorationSchedulerTrainConfig(FrozenRecord.from_dict(b))


@pytest.mark.parametrize('flag',[False,1,None,'true'])
def test_scorer_scope_is_explicit_closed_strict_bool(grid,flag):
    with pytest.raises(ContractError):serialize_combination_panel(grid[0].compiled.panel,exploration_scheduler=flag)


@pytest.mark.parametrize('other',['lineage','retrieval_review','admission'])
def test_scorer_scopes_cannot_be_combined(grid,other):
    with pytest.raises(ContractError):serialize_combination_panel(grid[0].compiled.panel,exploration_scheduler=True,**{other:True})


def phase_args(grid,tmp_path,mode):
    executed=next(r for r in grid[0].results if r.cell.runtime_arm.data()['enabled']==['M7','M8'])
    supplied=args(grid,executed);m=supplied['material'].data()
    if mode=='dependency':
        for j in m['jobs'][1:]:j['dependencies']=[m['jobs'][0]['id']]
    if mode=='conflict':
        for j in m['jobs'][1:]:j['resources']=m['jobs'][0]['resources']
    if mode=='timeout':
        for j in m['jobs']:j['program']='import time\ntime.sleep(10)'
    if mode=='order':
        m['jobs'][0]['program']='import time\ntime.sleep(2)\nprint(11)'
        m['jobs'][2]['program']='print(22)'
    return dict(material=FrozenExplorationSchedulerMaterial(FrozenRecord.from_dict(m)),cell=executed.cell,
        objective=executed.solver.session.objective,root=tmp_path/'phase',
        broker=DockerExecutionBroker([next(iter(supplied['public_inputs'].values())).parent,tmp_path]),
        inputs=supplied['public_inputs'],image=supplied['image'],timeout_seconds=1 if mode=='timeout' else 20)


@pytest.mark.parametrize('mode',['dependency','conflict','timeout','order'])
def test_actual_docker_dependency_resource_timeout_and_completion_mapping(grid,tmp_path,mode):
    supplied=phase_args(grid,tmp_path,mode);report=run_phase(**supplied);replay={k:v for k,v in supplied.items() if k!='broker'}
    assert verify_phase(**replay)==report
    b=report.data();assert b['actual_docker_attempts']==b['execution_units_reserved']==2 and b['remaining_leases']==[]
    if mode in {'dependency','conflict'}:assert b['peak_leases']==1 and b['overlap_ns']==0
    if mode=='timeout':
        assert b['status']=='failed' and b['residual_containers']==[]
        for path in supplied['root'].glob('*.json'):
            data=json.loads(path.read_bytes())
            if data.get('schema')=='exploration-scheduler-job-return-v1':
                assert data['execution']['status']=='timed_out' and data['execution']['record']['cleanup']['removed'] is True
    if mode=='order':
        assert b['completion_order']==list(reversed(b['fifo_order']))
        assert [o['stdout'].strip() for o in b['public']['observations']]==['11','22']
    with pytest.raises(ContractError,match='exclusive'):run_phase(**supplied)


def test_atomic_claims_from_independent_connections_never_duplicate(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from research_loop.modular.modules.scheduling import FifoScheduler
    path=tmp_path/'queue.sqlite';scheduler=FifoScheduler(path,max_concurrency=2,total_budget=2)
    for i in range(2):scheduler.enqueue(experiment_id='public',task_id=str(i),dependencies=[],resources=[],cost_units=1,snapshot={'evidence':'a','rules':'b','package':'c'})
    def claim(i):return FifoScheduler(path,max_concurrency=2,total_budget=2).claim_next(str(i),lease_seconds=10)
    with ThreadPoolExecutor(max_workers=8) as pool:claims=list(pool.map(claim,range(32)))
    actual=[c for c in claims if c is not None]
    assert len(actual)==2 and len({c.run_id for c in actual})==2 and scheduler.reserved_cost_units()==2
    with pytest.raises(ContractError):scheduler.merge('public')
    for c in actual:scheduler.complete(c.run_id,receipt_id=c.run_id,receipt={'returned':c.task_id},cost_units=1)
    assert len(scheduler.merge('public'))==2


@pytest.mark.parametrize('fault',['literal','input','limits','duplicate_claim','early_merge','snapshot','budget','return_subject'])
def test_replay_rejects_actual_artifact_and_operation_forgery(grid,tmp_path,fault):
    from shutil import copytree
    supplied=phase_args(grid,tmp_path,'normal');report=run_phase(**supplied)
    replay={k:v for k,v in supplied.items() if k!='broker'}
    assert verify_phase(**replay)==report
    root=supplied['root'];copytree(root,tmp_path/'original-phase') # Preserve original fixture evidence.
    job=report.data()['fifo_order'][0];path=root/(job+'.json');body=json.loads(path.read_bytes())
    if fault=='literal':(root/(job+'.py')).write_bytes(b'print(999)')
    elif fault=='input':body['execution']['record']['input_artifacts']['public_csv']['byte_count']+=1
    elif fault=='limits':body['execution']['record']['argv'][19]='4.0'
    elif fault=='return_subject':body['job']='0'*64
    elif fault in {'snapshot','budget'}:
        with sqlite3.connect(root/'queue.sqlite') as db:
            db.execute("UPDATE runs SET snapshot_hash=?" if fault=='snapshot' else 'UPDATE budget SET reserved=?',('0'*64 if fault=='snapshot' else 0,))
    else:
        events=[json.loads(x) for x in (root/'events.jsonl').read_text(encoding='utf-8').splitlines()]
        index=next(i for i,e in enumerate(events) if e['kind']=='claim')
        if fault=='duplicate_claim':events.insert(index+1,dict(events[index]))
        else:events.insert(index+1,{'kind':'merge','jobs':report.data()['fifo_order'],'time_ns':events[index]['time_ns']})
        for i,e in enumerate(events):e['sequence']=i
        (root/'events.jsonl').write_text(''.join(canonical(e)+'\n' for e in events),encoding='utf-8')
    if fault in {'input','limits','return_subject'}:path.write_text(canonical(body),encoding='utf-8')
    with pytest.raises(ContractError):verify_phase(**replay)


def test_missing_or_modified_export_bytes_reject_before_permit_and_jobs(grid,tmp_path):
    supplied=phase_args(grid,tmp_path,'normal')
    changed=tmp_path/'changed.csv';changed.write_bytes(b'x\n77\n');supplied['inputs']={'public_csv':changed}
    with pytest.raises(ContractError,match='actual public bytes'):run_phase(**supplied)
    assert not supplied['root'].exists()
