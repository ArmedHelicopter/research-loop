"""Exact prospective TRAIN state/scheduling controller and independent scorer checks.

All primary-like packets, qualifier observations and private scorer references
are synthetic fixtures. Model transport is mocked; Docker and child workers run.
"""
from contextlib import ExitStack
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path

import pytest

from evaluation.modular.fresh_airs_custodian import CustodyError
from evaluation.modular.scorer_process import CombinationScorerProcessClient, serialize_combination_panel, parse_combination_panel, parse_server_config
from evaluation.modular.scoring_service import ScorerConfig, FrozenBenchmarkRubricEndpoint
from evaluation.modular.train_io import TrainPacketExporter
from evaluation.modular.state_scheduling_scoring import issue_state_scheduling_score_input
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.state_scheduling_combination_controller import (
    FrozenStateSchedulingTrainConfig, compile_state_scheduling_train_panels, run_state_scheduling_train_panels, _arms)
from research_loop.modular.state_scheduling_combination_driver import DESIGNS, SLOTS, freeze_material, verify_state_scheduling_cell
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.combination_train_controller import _ANALYSIS
from research_loop.ontology import ContractError, canonical
from test_remaining_prospective_train_sources import prepared_primary, changed_source_config, corrupt_export
from test_primary_prospective_exporter import events
from test_lineage_combination_controller import EXECUTION, SCORER
from test_admission_combination import sources
from test_modular_train_controller import model_port, FINAL
from test_modular_combination_train_controller import ANALYSIS
from test_state_retrieval_combination_driver import state_material, provenance, IMAGE
from research_loop.modular.exploration_scheduler_combination import FrozenExplorationSchedulerMaterial
from test_modular_combination_benchmark_driver import _rewrite_trace
from test_scorer_process import _store, _command


def job_material(task, state, fault=None):
    header = "import csv,json,time\ntime.sleep(0.3)\nwith open('/input/public_csv',newline='') as f: xs=[float(r['x']) for r in csv.DictReader(f)]\n"
    # Both levels execute the same useful mean and dispersion jobs. The shared
    # three-slot phase contract freezes a dormant probe; M7 is never enabled.
    bodies = ["print(json.dumps({'mean':sum(xs)/len(xs)}))",
        "print(json.dumps({'variance':sum((x-sum(xs)/len(xs))**2 for x in xs)/len(xs)}))",
        "print(json.dumps({'range':max(xs)-min(xs)}))"]
    ids = [hashlib.sha256(('literal-public-analysis-'+str(i)).encode()).hexdigest() for i in range(3)]
    jobs = [{'id': ids[i], 'purpose': 'probe' if i == 2 else 'main',
        'program': ("raise RuntimeError('original phase failure')" if fault == 'phase' else
            'import time\ntime.sleep(3)' if fault == 'timeout' else
            header.replace('time.sleep(0.3)', 'started=time.monotonic_ns()\ntime.sleep(4)')+body.replace('}))', ", 'started_ns':started, 'finished_ns':time.monotonic_ns()}))") if fault == 'container_overlap' else
            header.replace('time.sleep(0.3)', 'time.sleep('+('1.5' if i == 0 else '0.05')+')')+body if fault == 'order' else header+body),
        'dependencies': [ids[0]] if fault == 'dependency' and i == 1 else [],
        'resources': [hashlib.sha256(('shared-public-csv' if fault == 'conflict' else 'resource-'+str(i)).encode()).hexdigest()],
        'cost_units': 1} for i,body in enumerate(bodies)]
    return FrozenExplorationSchedulerMaterial(FrozenRecord.from_dict({'schema':'exploration-scheduler-material-v1',
        'identity': task.identity.data(), 'task_digest': task.content_hash,
        'public_artifacts': state.data()['public_artifacts'], 'context_budget_bytes':state.data()['context_budget_bytes'], 'jobs':jobs}))


def model(seen):
    def respond(request):
        b=request.data();seen.append(b);joint=b['module_context']['joint_mechanism']
        assert all(marker not in request.encoded for marker in ('"enabled"','"arm_id"','"policy_digest"',
            'qualification_observations','pair:M1','pair:M2','pair:M3','PRIVATE-REFERENCE-SENTINEL'))
        if b['slot']=='analysis_program':
            observations=[next(iter(v['content'].values())) for v in joint['state_projection']['observations']]
            pending=sum(v.get('needs_review') is True for v in joint['state_projection']['memory'])
            phase_values=[json.loads(o['stdout']) for o in joint['scheduling']['observations']]
            program="import csv,json\nwith open('/input/public_csv',newline='') as f: xs=[float(r['x']) for r in csv.DictReader(f)]\nobservations="+repr(observations)+"\npending="+repr(pending)+"\nphase="+repr(phase_values)+"\nprint(json.dumps({'mean':sum(xs)/len(xs),'phase':phase,'observations':observations,'pending':pending,'adjusted':sum(observations)/len(observations)-pending-sum(next(iter(v.values())) for v in phase)},sort_keys=True))"
            return FrozenRecord.from_dict({'analysis':'Compute the current evidence summary with actual public dispersion observations.','program':program})
        return FrozenRecord.from_dict({'objective_digest':b['module_context']['required_objective_digest'],'outcome':'unknown',
            'evidence_ids':[],'conclusion':'Observed public synthetic execution: '+b['execution_feedback'][0]['stdout'],'programme_complete':False})
    return respond


def prepare(root, fault=None):
    import test_primary_process_qualification as fixture_source
    original_write = fixture_source.write
    def public_rows(path, value):
        if path.name == 'data.csv' and isinstance(value, bytes) and value.startswith(b'x\n'):
            x = float(value.decode().splitlines()[1])
            value = ('x\n'+str(x)+'\n'+str(x+1)+'\n'+str(x+3)+'\n').encode()
        return original_write(path, value)
    # Richer synthetic rows are generated before inventory hashing and sealing.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(fixture_source, 'write', public_rows)
        exporter, selected, all_items, packets = prepared_primary(root)
    calls=[]
    verifiers = {pair:(sources(calls, fault='source_exception' if fault=='source_exception' else fault)
        if pair=='pair:M1+M8' else provenance(calls,'unknown' if fault=='source_exception' else None)) for pair in DESIGNS}
    materials={}
    for pair in DESIGNS:
        materials[pair]={}
        for packet in packets:
            state=state_material(packet.task,packet.csv_path,pair=='pair:M1+M8')
            materials[pair][packet.task.content_hash]=freeze_material(packet.task,state,job_material(packet.task,state,fault)).data()
    package=CandidatePackage.create(parent_digest=None,manifest=TrainingManifest.freeze([p.task.identity for p in packets]),
        changes={'prompt':{'instructions':'Analyze the supplied public training observations.'}},search_cost=0)
    store,handles,manifest_sha=_store(root,{'tasks':{p.task.content_hash:p.task for p in packets}})
    b={'schema':'state-scheduling-combination-train-config-v2','export_mode':'primary_prospective','domain':'train',
        'stage':'synthetic-prospective-state-scheduling','item_ids':[i.token for i in selected],
        'task_bindings':{i.token:{'identity':p.task.identity.data(),'task_digest':p.task.content_hash,
            'csv_sha256':hashlib.sha256(p.csv_path.read_bytes()).hexdigest(),'csv_byte_count':p.csv_path.stat().st_size}
            for i,p in zip(selected,packets,strict=True)},'baseline_digest':'a'*64,
        'packages_by_arm':{a:package.record.data() for a in _arms('a'*64)},
        'scorer':ScorerConfig.create(benchmark='core_pair',evaluator_id='synthetic-primary',version='v1',
            rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest()).record.data(),
        'scorer_handle_bindings':{k:hashlib.sha256(v.encode()).hexdigest() for k,v in handles.items()},
        'acceptance_criteria':{'contrast_analysis':_ANALYSIS},'replicates':['r1'],'model':'gpt-5.6-luna','effort':'low',
        'materials_by_pair':materials,'source_verifier_bindings':{p:v.binding().data() for p,v in verifiers.items()},
        'objective':{'purpose':'Analyze public TRAIN measurements with frozen module context.'},
        'image':IMAGE,'timeout_seconds':1 if fault=='timeout' else 20,'max_calls':48,'max_tokens':1000,
        'schemas':{'analysis_program':ANALYSIS,'final_answer':FINAL},
        'allocation':{'model_slots_per_cell':list(SLOTS),'docker_attempts_per_cell':3,
            'auxiliary_docker_attempts_per_cell':2,'solver_docker_attempts_per_cell':1,
            'scorer_calls_per_cell':1,'scorer_call_limit':24,'scorer_token_accounting':'transport_not_provided',
            'source_calls_per_cell':2,'phase_cost_units_per_cell':2,'phase_job_limit':2,'phase_policy':'fifo','phase_max_concurrency':2,'context_budget_bytes':24000}}
    config=FrozenStateSchedulingTrainConfig(FrozenRecord.from_dict(b)); compiled=compile_state_scheduling_train_panels(config,packets)
    (root/'frozen-config.json').write_text(config.record.encoded+'\n',encoding='utf-8')
    return dict(root=root,exporter=exporter,selected=selected,all_items=all_items,packets=packets,
        config=config,compiled=compiled,verifiers=verifiers,calls=calls,
        store=store,handles=handles,manifest_sha=manifest_sha)


def services(setup, stack, scorer_fault=False):
    root=setup['root'];b=setup['config'].data();rubric=ScorerConfig(FrozenRecord.from_dict(b['scorer']))
    (root/'execution.key').write_bytes(EXECUTION.key);(root/'score.key').write_bytes(SCORER.key)
    clients={}
    for n,panel in enumerate(setup['compiled'].panels):
        server={'schema':'state-scheduling-scorer-process-config-v1',
            'panel':serialize_combination_panel(panel,state_scheduling=True),'scorer_config':rubric.record.data(),
            'scorer_config_digest':rubric.digest,'train_reference_store':{'root':str(setup['store'].resolve()),
                'manifest_sha256':setup['manifest_sha'],'inventory_digest':panel.cells[0].identity.dataset_version,'split_digest':panel.split_digest},
            'task_handles':setup['handles'],'execution_authority_key_files':{EXECUTION.authority_id:str(root/'execution.key')},
            'scorer_authority':{'id':SCORER.authority_id,'key_file':str(root/'score.key')},
            'evaluator':{'synthetic_mode':'fail' if scorer_fault else 'normal'}}
        path=root/f'server-{n}.json';path.write_text(canonical(server),encoding='utf-8')
        command=_command(path,root/f'worker-{n}.jsonl');command[1]=str((Path(__file__).parent/'helpers/state_scheduling_scorer_process_helper.py').resolve())
        client=CombinationScorerProcessClient(panel=panel,config=rubric,state_scheduling=True,command=command,
            journal_path=root/f'client-{n}.jsonl',task_handle_bindings=b['scorer_handle_bindings'],
            execution_authority_keys={EXECUTION.authority_id:EXECUTION.key},scorer_authority_keys={SCORER.authority_id:SCORER.key},
            environment={**os.environ,'PYTHONIOENCODING':'gbk'})
        stack.callback(client.close);clients[panel.obligation_id]=client
    return clients


def invoke(setup,monkeypatch,fault=None):
    root=setup['root'];config=setup['config'];b=config.data();seen=[];respond=model(seen)
    def response(request):
        # Synchronous callback sees the fully written catalogue, before the model result.
        frozen=json.loads((root/'run/controller-attempt.json').read_text(encoding='utf-8'))
        assert len(frozen['cells'])==24 and len(frozen['panels'])==3
        assert [(p['digest'],p['cells']) for p in frozen['panels']]==[(p.digest,[c.data() for c in p.cells]) for p in setup['compiled'].panels]
        assert 'PRIVATE-REFERENCE-SENTINEL' not in request.encoded
        if not seen and fault=='poison':
            seen.append(request.data());raise RuntimeError('synthetic unknown model usage')
        return respond(request)
    port=model_port(root/'port',monkeypatch,max_calls=b['max_calls'],max_tokens=b['max_tokens'],schemas=b['schemas'],response_factory=response)
    def forbidden(*args,**kwargs):raise AssertionError('legacy exporter was invoked')
    monkeypatch.setattr(TrainPacketExporter,'export',forbidden)
    exporter=setup['exporter']
    if fault=='unknown_phase':
        original_execute=DockerExecutionBroker.execute
        def unknown_phase(self,request):
            if request.program.parent.name=='phase':raise RuntimeError('synthetic unknown auxiliary provider usage')
            return original_execute(self,request)
        monkeypatch.setattr(DockerExecutionBroker,'execute',unknown_phase)
    kwargs=dict(custody=None,prospective_exporter=exporter,snapshot_root=Path(exporter.config['snapshot_root']),
        export_root=exporter.output_root,run_root=root/'run',model=port,audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),
        source_verifiers=setup['verifiers'],
        execution_authority=EXECUTION,scorer_authority_keys={SCORER.authority_id:SCORER.key})
    no_io={'both','wrong_port','roots','split','validation','swapped_tokens','export_receipt','completion_anchor','source','material'}
    if fault=='both':kwargs['custody']=object()
    if fault=='wrong_port':kwargs.update(custody=object(),prospective_exporter=None)
    if fault=='roots':kwargs['export_root']=root/'wrong-export'
    if fault=='split':exporter.expected_split_digest='f'*64
    if fault in ('validation','swapped_tokens'):config=changed_source_config(config,setup['all_items'],fault)
    if fault in ('export_receipt','completion_anchor'):corrupt_export(monkeypatch,exporter,fault)
    if fault=='source':
        path=Path(exporter.config['snapshot_root'])/'scienceagent/work/BLADE/blade_bench/datasets/case0/data.csv';path.write_bytes(path.read_bytes()+b' ')
    if fault=='material':
        original=exporter.export_controller_packets
        def drift(tokens):
            packets=original(tokens);packets[0].csv_path.write_bytes(b'drift');return packets
        monkeypatch.setattr(exporter,'export_controller_packets',drift)
    with ExitStack() as stack:
        kwargs['scoring_services']=services(setup,stack,scorer_fault=fault=='scorer')
        if fault in no_io:
            with pytest.raises((ContractError,CustodyError)):run_state_scheduling_train_panels(config,**kwargs)
            assert not seen and not setup['calls'] and not port.ledger['calls']
            assert not list((root/'run').glob('cells/*/runtime/analysis-1.py')) and not list(root.glob('worker-*.jsonl'))
            return
        result=run_state_scheduling_train_panels(config,**kwargs)
    return result,port,seen


@pytest.fixture(scope='module')
def grid(tmp_path_factory):
    setup=prepare(tmp_path_factory.mktemp('state-scheduling-controller'))
    with pytest.MonkeyPatch.context() as patch: result,port,seen=invoke(setup,patch)
    return setup,result,port,seen


def replay_args(setup,result,executed):
    panel=next(p for p in result.compiled.panels if executed.cell in p.cells)
    packet=next(p for p in result.compiled.packets if p.task.content_hash==executed.cell.task_digest)
    return dict(panel=panel,task=packet.task,scenario=result.compiled.scenarios[executed.cell.key],
        package=result.compiled.packages[executed.cell.runtime_arm.content_hash],material=result.compiled.materials[panel.obligation_id][executed.cell.task_digest],
        source_verifier=setup['verifiers'][panel.obligation_id],
        public_inputs={'public_csv':packet.csv_path},broker=DockerExecutionBroker([setup['root']/'export',setup['root']/'run']))


def test_full24_prospective_cells_docker_and_independent_primary_scores(grid):
    setup,result,port,seen=grid
    assert len(result.scores)==len(result.results)==len(result.attempts)==24,[a.data() for a in result.attempts if a.data()['status']!='succeeded']
    assert len(seen)==len(port.ledger['calls'])==48
    assert len(setup['calls'])==48
    b=result.receipt.data();assert b['status']=='complete_train_engineering'
    assert b['actual_docker_attempts']==72 and b['actual_scorer_calls']==24
    assert b['source_calls']==48 and b['auxiliary_docker_attempts']==48 and b['pruned_cells']==[]
    assert b['validation_opened'] is b['scientific_effectiveness_proven'] is False
    assert [e['event'] for e in events(setup['exporter'])]==['export_reserved','sources_verified','exposure_reserved','exposure_reserved','export_completed']
    for attempt,executed in zip(result.attempts,result.results,strict=True):
        row=attempt.data();assert row['status']=='succeeded'
        assert len(row['source_verification']['calls'])==2
        assert row['docker_attempts']==3 and row['scorer_calls']==1 and row['auxiliary_docker_attempts']==2
        assert row['execution_receipt']['record']['argv'][-3:]==[IMAGE,'python3','/task/analysis.py']
        phase=executed.phase.data()
        assert phase['actual_docker_attempts']==phase['execution_units_reserved']==2
        assert phase['peak_dispatches']==(2 if 'M8' in executed.cell.runtime_arm.data()['enabled'] else 1)
        assert phase['peak_leases']==(2 if 'M8' in executed.cell.runtime_arm.data()['enabled'] else 0) and phase['remaining_leases']==phase['residual_containers']==[]
        if 'M8' not in executed.cell.runtime_arm.data()['enabled']: assert phase['completion_order']==phase['fifo_order']
        assert phase['selection']['permit'] is None
        frozen_jobs=replay_args(setup,result,executed)['material'].scheduling().data()['jobs']
        assert phase['selection']['selected']==[job['id'] for job in frozen_jobs[:2]]
        assert 'M7' not in executed.cell.runtime_arm.data()['enabled']
        assert (phase['overlap_ns']>0)==('M8' in executed.cell.runtime_arm.data()['enabled'])
        assert len(phase['public']['observations'])==2 and all(o['status']=='succeeded' for o in phase['public']['observations'])
        verify_state_scheduling_cell(executed,**replay_args(setup,result,executed))
        if executed.cell.coverage_id=='pair:M3+M8':assert 'M2' in executed.cell.runtime_arm.data()['enabled']
    for pair in DESIGNS:
        for benchmark in ('blade','discoverybench'):
            values=[json.loads(r.solver.execution.record.data()['stdout'])['adjusted'] for r in result.results
                if r.cell.coverage_id==pair and r.cell.identity.benchmark==benchmark]
            assert len(set(values))==2
            outputs={r.cell.arm_id:r.solver.execution.record.data()['stdout'] for r in result.results if r.cell.coverage_id==pair and r.cell.identity.benchmark==benchmark}
            assert outputs['00']==outputs['01'] and outputs['10']==outputs['11']
    for n in range(3):
        rows=[json.loads(l) for l in (setup['root']/f'worker-{n}.jsonl').read_text(encoding='utf-8').splitlines()]
        assert [r['status'] for r in rows]==['reserved','succeeded']*8
        assert 'PRIVATE-REFERENCE-SENTINEL' not in (setup['root']/f'client-{n}.jsonl').read_text(encoding='utf-8')


@pytest.mark.parametrize('fault',['both','wrong_port','roots','split','validation','swapped_tokens','export_receipt','completion_anchor','source','material'])
def test_source_faults_precede_downstream_io(tmp_path,monkeypatch,fault):invoke(prepare(tmp_path),monkeypatch,fault)


def test_poisoned_ledger_preserves_all24_opportunities(tmp_path,monkeypatch):
    setup=prepare(tmp_path);result,port,seen=invoke(setup,monkeypatch,'poison');b=result.receipt.data()
    assert len(result.attempts)==24 and b['failed_cells']==1 and b['blocked_cells']==23
    assert len(seen)==len(port.ledger['calls'])==1 and port.ledger['usage_incomplete'] is True
    assert b['actual_docker_attempts']==2 and b['actual_scorer_calls']==0
    assert b['unused_model_opportunities']==47 and b['source_calls']==2 and b['auxiliary_docker_attempts']==2
    assert b['pruned_cells']==[] and all(c.data()['status']=='inconclusive' for c in result.contrasts)


@pytest.mark.parametrize('fault',['source_exception','phase','scorer','unknown_phase'])
def test_original_failures_keep_all24_denominators(tmp_path,monkeypatch,fault):
    setup=prepare(tmp_path,fault);result,port,seen=invoke(setup,monkeypatch,fault);b=result.receipt.data()
    assert len(result.attempts)==len(result.results)==24 and b['failed_cells']==24 and b['pruned_cells']==[]
    assert b['source_calls']==48 and b['actual_docker_attempts']=={'source_exception':0,'phase':48,'scorer':72,'unknown_phase':48}[fault]
    assert len(seen)==len(port.ledger['calls'])==({'scorer':48}.get(fault,0))
    assert b['actual_scorer_calls']==(24 if fault=='scorer' else 0)
    if fault=='unknown_phase':assert b['phase_unknown_cost_attempts']==48 and b['unused_model_opportunities']==48
    if fault in ('phase','unknown_phase'):
        for executed in result.results:verify_state_scheduling_cell(executed,**replay_args(setup,result,executed))
    assert all(c.data()['status']=='inconclusive' for c in result.contrasts)


def test_m1_semantic_drift_preserves_scores_but_blocks_contrast(tmp_path,monkeypatch):
    setup=prepare(tmp_path,'source_cell_drift');result,port,seen=invoke(setup,monkeypatch)
    assert len(result.scores)==len(result.attempts)==24 and len(seen)==48
    contrasts={p.obligation_id:c.data() for p,c in zip(result.compiled.panels,result.contrasts,strict=True)}
    assert contrasts['pair:M1+M8']['status']=='inconclusive'
    assert contrasts['pair:M1+M8']['reason']=='admission_qualification_semantic_drift'
    assert all(contrasts[p]['status']=='estimated' for p in DESIGNS if p!='pair:M1+M8')
    assert result.receipt.data()['status']=='inconclusive'


@pytest.mark.parametrize('fault',['state_journal','claims_journal','request_context','program','state_signature',
    'literal_job','phase_input','phase_budget','phase_permit','phase_return','phase_order','phase_binding','operation_order'])
def test_persistent_replay_and_score_issuance_reject_forgeries(grid,fault):
    setup,result,*_=grid;mutations=[]
    for executed in result.results:
        if executed.cell.identity.benchmark!='blade' or executed.cell.arm_id!='11':continue
        args=replay_args(setup,result,executed);path=executed.runtime.trace_path;before=path.read_bytes();extra=None;saved=None
        def mutate(rows):
            if fault=='request_context':
                request=next(e for e in rows if e['stage']=='model_request')['data'];old=request['request_digest']
                request['request']['module_context']['joint_mechanism']['state_projection']={}
                request['request_digest']=FrozenRecord.from_dict(request['request']).content_hash
                for row in rows:
                    if row['stage']=='model_response' and row['data']['request_digest']==old:row['data']['request_digest']=request['request_digest']
            elif fault=='phase_binding':next(e for e in rows if e['stage']=='state_scheduling_phase')['data']['phase_digest']='f'*64
            elif fault=='operation_order':
                first=next(e for e in rows if e['stage']=='state_scheduling_transition');rows.remove(first)
                rows.insert(next(i for i,e in enumerate(rows) if e['stage']=='state_scheduling_phase_start')+1,first)
        try:
            phase=path.parent.parent/'phase'
            if fault in ('request_context','phase_binding','operation_order'):
                tail=_rewrite_trace(path,mutate);forged=replace(executed,runtime=replace(executed.runtime,trace_digest=tail))
            else:
                if fault in ('state_journal','claims_journal','program','state_signature'):
                    extra={'state_journal':path.parent/'evidence.jsonl','claims_journal':path.parent/'claims.jsonl',
                        'program':path.parent/'analysis-1.py','state_signature':path.parent.parent/'source-verification.json'}[fault]
                    saved=extra.read_bytes();extra.write_bytes(saved+b'{}\n')
                elif fault=='literal_job':
                    extra=phase/(executed.phase.data()['selection']['selected'][0]+'.py');saved=extra.read_bytes();extra.write_bytes(saved+b'\nprint(123)')
                elif fault in ('phase_input','phase_budget','phase_permit'):
                    extra=phase/'allocation.json';saved=extra.read_bytes();body=json.loads(saved)
                    if fault=='phase_input':body['input_paths']['public_csv']='foreign.csv'
                    elif fault=='phase_budget':body['docker_limit']=3
                    else:body['selection']['permit']={'invented':True}
                    extra.write_text(canonical(body),encoding='utf-8')
                elif fault=='phase_return':
                    extra=next(p for p in phase.glob('*.json') if json.loads(p.read_bytes()).get('schema')=='exploration-scheduler-job-return-v1')
                    saved=extra.read_bytes();body=json.loads(saved);body['snapshot_digest']='e'*64;extra.write_text(canonical(body),encoding='utf-8')
                else:
                    extra=phase/'events.jsonl';saved=extra.read_bytes();body=[json.loads(x) for x in saved.decode().splitlines()]
                    next(e for e in body if e['kind']=='merge')['kind']='complete'
                    extra.write_text(''.join(canonical(e)+'\n' for e in body),encoding='utf-8')
                forged=executed
            with pytest.raises((ContractError,ValueError)):verify_state_scheduling_cell(forged,**args)
            with pytest.raises((ContractError,ValueError)):issue_state_scheduling_score_input(authority=EXECUTION,result=forged,**args)
            mutations.append({'pair':executed.cell.coverage_id,'fault':fault})
        finally:
            path.write_bytes(before)
            if extra is not None:extra.write_bytes(saved)
        verify_state_scheduling_cell(executed,**args)
    assert {m['pair'] for m in mutations}==set(DESIGNS)
    (setup['root']/('replay-'+fault+'.json')).write_text(canonical(mutations),encoding='utf-8')


@pytest.mark.parametrize('flags',[{}, {'state_scheduling':1},{'state_scheduling':'true'},
    {'state_scheduling':True,'state_prediction':True},{'state_scheduling':True,'state_exploration':True},{'state_scheduling':True,'state_retrieval':True},{'state_scheduling':True,'lineage':True},
    {'state_scheduling':True,'retrieval_review':True},{'state_scheduling':True,'admission':True},
    {'state_scheduling':True,'exploration_scheduler':True}])
def test_strict_scorer_family_scope_no_default_relaxation(grid,flags):
    setup,*_=grid
    with pytest.raises(ContractError):serialize_combination_panel(setup['compiled'].panels[0],**flags)


def test_roundtrip_each_pair_and_reject_schema_substitution(grid):
    setup,*_=grid
    for n,panel in enumerate(setup['compiled'].panels):
        body=serialize_combination_panel(panel,state_scheduling=True)
        assert parse_combination_panel(body,state_scheduling=True)==panel
        server=json.loads((setup['root']/f'server-{n}.json').read_text(encoding='utf-8'))
        assert parse_server_config(server).panel==panel
        server['schema']='state-prediction-scorer-process-config-v1'
        with pytest.raises(ContractError):parse_server_config(server)


@pytest.mark.parametrize('fault',['wrong_state','wrong_job_task','job_cost_bool','job_label','job_dependency','job_provenance',
    'allocation','context_budget','source_keys','extra_pair','validation_domain','legacy_schema','model_calls'])
def test_closed_config_rejects_malformed_original_material_before_io(grid,fault):
    setup,*_=grid;b=setup['config'].data();m=next(iter(b['materials_by_pair']['pair:M1+M8'].values()))
    if fault=='wrong_state':m['state_kind']='lineage'
    elif fault=='wrong_job_task':m['scheduling']['task_digest']='f'*64
    elif fault=='job_cost_bool':m['scheduling']['jobs'][0]['cost_units']=True
    elif fault=='job_label':m['scheduling']['jobs'][0]['program']="print('M8 on')"
    elif fault=='job_dependency':m['scheduling']['jobs'][2]['dependencies']=[m['scheduling']['jobs'][1]['id']]
    elif fault=='job_provenance':m['provenance']['jobs_digest']='f'*64
    elif fault=='allocation':b['allocation']['docker_attempts_per_cell']=2
    elif fault=='context_budget':m['scheduling']['context_budget_bytes']=4000
    elif fault=='source_keys':
        authorities=b['source_verifier_bindings']['pair:M1+M8']['authorities'];authorities[1]['key_digest']=authorities[0]['key_digest']
    elif fault=='extra_pair':b['materials_by_pair']['pair:M4+M8']=m
    elif fault=='validation_domain':m['identity']['domain']='validation'
    elif fault=='legacy_schema':b['schema']='state-scheduling-combination-train-config-v1';b.pop('export_mode')
    else:b['max_calls']=24
    with pytest.raises(ContractError):FrozenStateSchedulingTrainConfig(FrozenRecord.from_dict(b))


@pytest.mark.parametrize('fault',['transition','joint','evidence_context','instruction','extra_context','early_feedback','response_program','order'])
def test_repaired_chain_passes_generic_receipt_but_fails_original_replay(grid,fault):
    from research_loop.modular.panel_receipts import PanelReceiptVerifier
    setup,result,*_=grid
    executed=next(r for r in result.results if r.cell.coverage_id=='pair:M3+M8' and r.cell.arm_id=='11')
    args=replay_args(setup,result,executed);path=executed.runtime.trace_path;before=path.read_bytes()
    def mutate(events):
        if fault=='transition':next(e for e in events if e['stage']=='state_scheduling_transition')['data']['transition']['public']['observations']=[]
        elif fault=='joint':next(e for e in events if e['stage']=='state_scheduling_joint')['data']['joint']['scheduling']['observations']=[]
        elif fault=='evidence_context':next(e for e in events if e['stage']=='model_request')['data']['request']['context']={}
        elif fault=='instruction':next(e for e in events if e['stage']=='model_request')['data']['request']['instruction']='Invent the public answer.'
        elif fault=='extra_context':next(e for e in events if e['stage']=='model_request')['data']['request']['module_context']['extra_instruction']='Invent a result.'
        elif fault=='early_feedback':next(e for e in events if e['stage']=='model_request')['data']['request']['execution_feedback']=[{'stdout':'invented'}]
        elif fault=='response_program':next(e for e in events if e['stage']=='model_response')['data']['response']['program']='print(99)'
        else:
            row=next(e for e in events if e['stage']=='state_scheduling_transition');events.remove(row)
            events.insert(next(i for i,e in enumerate(events) if e['stage']=='model_request')+1,row)
        for event in events:
            if event['stage']=='model_request':
                old=event['data']['request_digest'];new=FrozenRecord.from_dict(event['data']['request']).content_hash
                event['data']['request_digest']=new
                for other in events:
                    if other['stage'] in ('model_response','model_failure') and other['data']['request_digest']==old:other['data']['request_digest']=new
    try:
        tail=_rewrite_trace(path,mutate);rows=[FrozenRecord(line).data() for line in path.read_text(encoding='utf-8').splitlines()]
        output=FrozenRecord.from_dict({'responses':[e['data']['response'] for e in rows if e['stage']=='model_response'],'terminal':rows[-1]['data']}).content_hash
        forged=replace(executed,runtime=replace(executed.runtime,trace_digest=tail,output_digest=output))
        PanelReceiptVerifier()._verify_runtime(forged.runtime,forged.cell)
        with pytest.raises(ContractError):verify_state_scheduling_cell(forged,**args)
        with pytest.raises(ContractError):issue_state_scheduling_score_input(authority=EXECUTION,result=forged,**args)
    finally:path.write_bytes(before)
    verify_state_scheduling_cell(executed,**args)


@pytest.mark.parametrize('fault',['original','claims','jobs','scenario_objective','scenario_timeout','csv'])
def test_original_composite_scenario_and_input_bytes_are_replayed(grid,fault):
    from research_loop.modular.state_scheduling_combination_driver import FrozenStateSchedulingMaterial
    setup,result,*_=grid
    for executed in result.results:
        if executed.cell.identity.benchmark!='blade' or executed.cell.arm_id!='11':continue
        args=replay_args(setup,result,executed);changed=dict(args)
        if fault=='csv':
            path=args['public_inputs']['public_csv'];before=path.read_bytes()
            try:
                path.write_bytes(before+b'99\n')
                with pytest.raises(ContractError):verify_state_scheduling_cell(executed,**changed)
            finally:path.write_bytes(before)
        else:
            if fault.startswith('scenario_'):
                b=args['scenario'].data();b['objective' if fault=='scenario_objective' else 'timeout_seconds']={'purpose':'other'} if fault=='scenario_objective' else 1
                changed['scenario']=FrozenRecord.from_dict(b)
            else:
                b=args['material'].data()
                if fault=='original':b['state']['originals'][0]['content']['x']=999
                elif fault=='claims':b['state']['claims'][0]['statement']='Forged interpretation.'
                else:
                    b['scheduling']['jobs'][0]['program']='print(999)'
                    b['provenance']['jobs_digest']=FrozenRecord.from_dict(b['scheduling']).content_hash
                changed['material']=FrozenStateSchedulingMaterial(FrozenRecord.from_dict(b))
            with pytest.raises(ContractError):verify_state_scheduling_cell(executed,**changed)
            with pytest.raises(ContractError):issue_state_scheduling_score_input(authority=EXECUTION,result=executed,**changed)
        verify_state_scheduling_cell(executed,**args)


@pytest.mark.parametrize('field,value',[('--network','host'),('--memory','4g'),('--cpus','8.0'),('--user','0:0')])
def test_rehashed_solver_execution_cannot_relax_docker_limits(grid,field,value):
    from research_loop.modular.panel_receipts import PanelReceiptVerifier
    setup,result,*_=grid
    executed=next(r for r in result.results if r.cell.coverage_id=='pair:M3+M8' and r.cell.arm_id=='11')
    args=replay_args(setup,result,executed);path=executed.runtime.trace_path;before=path.read_bytes()
    record=executed.solver.execution.record.data();record['argv'][record['argv'].index(field)+1]=value
    receipt=replace(executed.solver.execution,record=FrozenRecord.from_dict(record))
    old_hash=executed.solver.execution.content_hash;new_hash=receipt.content_hash
    def substitute(value):
        if isinstance(value,dict):return {k:substitute(v) for k,v in value.items()}
        if isinstance(value,list):return [substitute(v) for v in value]
        return new_hash if value==old_hash else value
    def mutate(events):
        for event in events:event['data']=substitute(event['data'])
        execution=next(e for e in events if e['stage']=='execution_result')['data']
        execution['record']=receipt.record.data();execution['receipt']=receipt.data()
        for event in events:
            if event['stage']=='model_request':
                old=event['data']['request_digest'];new=FrozenRecord.from_dict(event['data']['request']).content_hash
                event['data']['request_digest']=new
                for other in events:
                    if other['stage']=='model_response' and other['data']['request_digest']==old:other['data']['request_digest']=new
    try:
        tail=_rewrite_trace(path,mutate)
        forged=replace(executed,runtime=replace(executed.runtime,trace_digest=tail),solver=replace(executed.solver,execution=receipt))
        PanelReceiptVerifier()._verify_runtime(forged.runtime,forged.cell)
        with pytest.raises(ContractError,match='Docker limits'):verify_state_scheduling_cell(forged,**args)
        with pytest.raises(ContractError):issue_state_scheduling_score_input(authority=EXECUTION,result=forged,**args)
    finally:path.write_bytes(before)
    verify_state_scheduling_cell(executed,**args)


@pytest.mark.parametrize('mode',['dependency','conflict','order','timeout','container_overlap'])
def test_bound_driver_scheduler_variants_with_real_docker_and_primary_score(tmp_path,mode):
    from research_loop.modular.state_scheduling_combination_driver import run_state_scheduling_cell
    from evaluation.modular.combination_scoring import verify_combination_adapted_receipt
    setup=prepare(tmp_path,mode);compiled=setup['compiled'];panel=next(p for p in compiled.panels if p.obligation_id=='pair:M3+M8')
    cell=next(c for c in panel.cells if c.arm_id=='11' and c.identity.benchmark=='blade')
    packet=next(p for p in compiled.packets if p.task.content_hash==cell.task_digest);seen=[]
    args=dict(panel=panel,task=packet.task,scenario=compiled.scenarios[cell.key],package=compiled.packages[cell.runtime_arm.content_hash],
        material=compiled.materials[panel.obligation_id][cell.task_digest],source_verifier=setup['verifiers'][panel.obligation_id],
        public_inputs={'public_csv':packet.csv_path},broker=DockerExecutionBroker([tmp_path]))
    b=setup['config'].data()
    executed=run_state_scheduling_cell(cell=cell,**args,objective=FrozenRecord.from_dict(b['objective']),sidecar=tmp_path/'variant',
        image=IMAGE,model=model(seen),audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),timeout_seconds=b['timeout_seconds'])
    verify_state_scheduling_cell(executed,**args);phase=executed.phase.data()
    assert phase['actual_docker_attempts']==phase['execution_units_reserved']==2 and phase['selection']['permit'] is None
    assert phase['remaining_leases']==phase['residual_containers']==[]
    if mode in ('dependency','conflict'):
        assert phase['peak_leases']==phase['peak_dispatches']==1 and phase['overlap_ns']==0
        assert phase['completion_order']==phase['fifo_order']
    elif mode=='container_overlap':
        intervals=[json.loads(row['stdout']) for row in phase['public']['observations']]
        assert min(row['finished_ns'] for row in intervals)>max(row['started_ns'] for row in intervals)
        assert phase['peak_leases']==phase['peak_dispatches']==2 and phase['overlap_ns']>0
    elif mode=='order':
        assert phase['completion_order']==list(reversed(phase['fifo_order'])) and phase['overlap_ns']>0
        assert [o['binding'] for o in phase['public']['observations']]==phase['fifo_order']
    else:
        assert executed.runtime.status==phase['status']=='failed' and not seen
        for path in (tmp_path/'variant/phase').glob('*.json'):
            body=json.loads(path.read_bytes())
            if body.get('schema')=='exploration-scheduler-job-return-v1':
                assert body['execution']['status']=='timed_out' and body['execution']['record']['cleanup']['removed'] is True
        with pytest.raises(ContractError):issue_state_scheduling_score_input(authority=EXECUTION,result=executed,**args)
        return
    assert executed.runtime.status=='succeeded' and len(seen)==2
    source=issue_state_scheduling_score_input(authority=EXECUTION,result=executed,**args)
    with ExitStack() as stack:
        client=services(setup,stack)[panel.obligation_id]
        score=client.score_combination(panel=panel,cell=cell,score_input=source)
        verify_combination_adapted_receipt(score,authority_keys={SCORER.authority_id:SCORER.key},config=client.config,
            panel=panel,cell=cell,score_input=source,execution_authority_keys={EXECUTION.authority_id:EXECUTION.key})
    (tmp_path/'variant-score.json').write_text(canonical(score.receipt.data()),encoding='utf-8')


@pytest.mark.parametrize('fault',['lease','snapshot','reservation','attempt','receipt','barrier','duplicate_claim'])
def test_persistent_scheduler_operations_and_database_replay(grid,fault):
    import sqlite3
    from contextlib import closing
    setup,result,*_=grid
    for executed in result.results:
        if executed.cell.arm_id!='11' or executed.cell.identity.benchmark!='blade':continue
        args=replay_args(setup,result,executed);phase=executed.runtime.trace_path.parent.parent/'phase'
        path=phase/('events.jsonl' if fault in ('barrier','duplicate_claim') else 'queue.sqlite');before=path.read_bytes()
        try:
            if fault in ('barrier','duplicate_claim'):
                rows=[json.loads(row) for row in before.decode().splitlines()]
                if fault=='barrier':rows=[r for r in rows if r['kind']!='barrier_refused']
                else:
                    claims=[r for r in rows if r['kind']=='claim'];claims[1]['job']=claims[0]['job'];claims[1]['run_id']=claims[0]['run_id']
                for i,row in enumerate(rows):row['sequence']=i
                path.write_text(''.join(canonical(r)+'\n' for r in rows),encoding='utf-8')
            else:
                with closing(sqlite3.connect(path)) as db:
                    sql={'lease':"UPDATE runs SET worker_id='forged'",'snapshot':"UPDATE runs SET snapshot='{}'",
                        'reservation':'UPDATE budget SET reserved=1','attempt':'UPDATE runs SET attempt=2','receipt':"UPDATE runs SET receipt='{}'"}[fault]
                    db.execute(sql);db.commit()
            with pytest.raises(ContractError):verify_state_scheduling_cell(executed,**args)
            with pytest.raises(ContractError):issue_state_scheduling_score_input(authority=EXECUTION,result=executed,**args)
        finally:path.write_bytes(before)
        verify_state_scheduling_cell(executed,**args)
