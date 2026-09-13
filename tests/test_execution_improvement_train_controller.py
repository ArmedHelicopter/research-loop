"""Synthetic history/model/source fixtures; actual builder, Docker and scorer processes."""
from contextlib import ExitStack
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import pytest

from evaluation.modular.scorer_process import CombinationScorerProcessClient, serialize_combination_panel, parse_combination_panel
from evaluation.modular.scoring_service import ScorerConfig, FrozenBenchmarkRubricEndpoint
from evaluation.modular.execution_improvement_scoring import issue_execution_improvement_score_input
from evaluation.modular.train_io import TrainPacketExporter
from research_loop.modular.contracts import FrozenRecord, PublicTask, DataIdentity
from research_loop.modular.benchmark_solver import run_benchmark_solve
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest, FrozenBuilderVersion, RestrictedBuilderPort
from research_loop.modular.runtime import AuditVerifier, verify_trace
from research_loop.modular.metaprogram_training import FrozenTrainHistory, model_configuration, metaprogram_schemas
from research_loop.modular.execution_improvement_combination_controller import FrozenExecutionImprovementPlan, run_execution_improvement_train, recipes, ALLOCATION, selections, ESTIMAND
from research_loop.modular.state_improvement_build import material_class, verify_build, FrozenProviderLedger
from research_loop.modular.execution_improvement_panel import ExecutionImprovementPanel, DESIGNS
from research_loop.modular.combination_panels import CombinationPanel
from research_loop.modular.combination_train_controller import _ANALYSIS
from research_loop.ontology import ContractError, canonical
from test_remaining_prospective_train_sources import prepared_primary, corrupt_export
from test_state_retrieval_combination_driver import state_material, IMAGE, Provider
from research_loop.modular.state_retrieval_combination_driver import freeze_material, FrozenStateRetrievalMaterial
from research_loop.modular.lineage_combination_material import DualMaterialVerifier, MaterialAuthority
from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from research_loop.modular.execution_improvement_modules import model_schemas
from test_modular_combination_benchmark_driver import _plan
from test_admission_combination import sources
from test_modular_train_controller import model_port
from test_lineage_combination_controller import EXECUTION, SCORER
from test_scorer_process import _store, _command
from test_modular_combination_benchmark_driver import _rewrite_trace

AUDIT=AuditVerifier({'a':b'a'*32,'b':b'b'*32})


def phase_material(task,csv,fault=None):
    from research_loop.modular.exploration_scheduler_combination import FrozenExplorationSchedulerMaterial
    jobs=[]
    for i in range(3):
        # Useful ordinary mean/median checks versus a bounded range probe.
        statistic=('sum(xs)/len(xs)','statistics.median(xs)','max(xs)-min(xs)')[i]
        program="import csv,json,statistics,time\nstart=time.time_ns()\ntime.sleep(0.3)\nwith open('/input/public_csv') as f: xs=[float(r['x']) for r in csv.DictReader(f)]\nprint(json.dumps({'statistic':"+statistic+",'start_ns':start,'end_ns':time.time_ns()}))"
        if fault=='auxiliary_failed':program="raise RuntimeError('synthetic auxiliary failure')"
        jobs.append({'id':hashlib.sha256(('public-job-'+str(i)).encode()).hexdigest(),'purpose':'probe' if i==2 else 'main',
            'program':program,'dependencies':[],'resources':[hashlib.sha256(('resource-'+str(i)).encode()).hexdigest()],'cost_units':1})
    return FrozenExplorationSchedulerMaterial(FrozenRecord.from_dict({'schema':'exploration-scheduler-material-v1',
        'identity':task.identity.data(),'task_digest':task.content_hash,'context_budget_bytes':16000,
        'public_artifacts':state_material(task,csv,False).data()['public_artifacts'],'jobs':jobs}))


def provenance(calls,fault=None,corpus=False):
    authorities=[]
    for i in range(2):
        signer=LinkedExecutionAuthority(('corpus-' if corpus else 'state-')+str(i),bytes([90+i if corpus else 80+i])*32)
        group=('corpus-observation-' if corpus else 'state-observation-')+str(i)
        def verify(request,signer=signer,group=group):
            calls.append(request)
            if fault=='source_exception':raise RuntimeError('synthetic source failure')
            b=request.data()
            return signer.issue({'schema':'lineage-material-provenance-response-v1','request_digest':request.content_hash,
                'material_digest':b['material_digest'],'identity':b['material']['identity'],'source_group':group,
                'verdict':'verified','cost_units':None if fault=='unknown_cost' else 1})
        authorities.append(MaterialAuthority(signer,group,verify))
    return DualMaterialVerifier(tuple(authorities))


def prepare(root,patch,fault=None):
    exporter,selected,all_items,packets=prepared_primary(root)
    task=PublicTask.create(DataIdentity('blade','closed-history','closed-history-group','e'*64,'f'*64,'train'),
        {'question':'Inspect existing public calibration history.','columns':['x']})
    historyroot=root/'history';historyroot.mkdir();csv=historyroot/'data.csv';csv.write_text('x\n8\n1\n99\n',encoding='utf-8')
    parent=CandidatePackage.create(parent_digest=None,manifest=TrainingManifest.freeze([task.identity]),
        changes={'prompt':{'instructions':'Use supplied public measurements.'}},search_cost=0)
    def previous(request):
        b=request.data()
        if b['slot']=='analysis_program':
            return FrozenRecord.from_dict({'analysis':'Read the existing three calibration observations.',
                'program':"import csv,json\nwith open('/input/public_csv') as f: v=[float(r['x']) for r in csv.DictReader(f)]\nprint(json.dumps({k:{'x':x} for k,x in zip(['old','current','uncalibrated'],v)}))"})
        return FrozenRecord.from_dict({'objective_digest':b['module_context']['required_objective_digest'],'outcome':'unknown',
            'evidence_ids':[],'conclusion':b['execution_feedback'][0]['stdout'],'programme_complete':False})
    prior=model_port(root/'prior-port',patch,max_calls=2,schemas={k:v for k,v in metaprogram_schemas().items() if k!='builder_proposal'},response_factory=previous)
    actual=run_benchmark_solve(task=task,public_inputs={'public_csv':csv},image=IMAGE,package_digest=parent.digest,
        arm=FrozenRecord.from_dict(recipes('a'*64)[0]['arm']),objective=FrozenRecord.from_dict({'purpose':'Record existing calibration history.'}),
        sidecar=historyroot/'runtime',broker=DockerExecutionBroker([historyroot]),model=prior,audit_verifier=AUDIT)
    assert actual.status=='execution_succeeded'
    trace=actual.session.sidecar/'trace.jsonl';history=FrozenTrainHistory.freeze(task,trace,expected_sha256=hashlib.sha256(trace.read_bytes()).hexdigest())
    calls=[];verifiers={pair:provenance(calls,fault) for pair in DESIGNS}
    histories={}
    for pair in DESIGNS:
        m=state_material(task,csv,False).data()
        for row in m['originals']:row['root_material']={'history_digest':history.binding.content_hash,'observation_key':row['key']}
        histories[pair]=material_class(pair)(FrozenRecord.from_dict(m)).data()
    seen=[]
    def response(request):
        b=request.data();seen.append(b)
        frozen=json.loads((root/'run/controller-attempt.json').read_bytes())
        assert len(frozen['builds'])==6 and len(frozen['targets'])==32 and len(frozen['structural_exclusions'])==0
        assert 'PRIVATE-REFERENCE-SENTINEL' not in request.encoded
        if fault=='model_unknown' or fault=='target_unknown' and b['slot']=='analysis_program': raise RuntimeError('synthetic unknown provider usage')
        if b['slot']=='builder_proposal':
            assert b['task']==task.data()
            for p in packets: assert p.task.content_hash not in request.encoded and p.task.identity.task_id not in request.encoded
            assert not (root/'run/candidate-barrier.json').exists()
            public=b['module_context']['state_projection'];values=[next(iter(r['content'].values())) for r in public['observations']]
            pending=sum(r.get('needs_review') is True for r in public['memory'])
            value='Use candidate adjustment='+str(sum(values)/len(values)-pending)
            if fault=='mid_build_source_drift' and len(seen)==1:
                exported=next((root/'export').glob('*/data.csv'));exported.write_bytes(exported.read_bytes()+b' ')
            return FrozenRecord.from_dict({'entrypoint':'emit_literal_change_v1','surface':'prompt',
                'key':'lesson' if fault=='proposal' else 'instructions','value':value})
        barrier=json.loads((root/'run/candidate-barrier.json').read_bytes())
        assert len(barrier['build_receipts'])==6 and len(barrier['candidate_selections'])==16 and len(frozen['panels'])==3
        assert all(marker not in request.encoded for marker in ('"arm_id"','"enabled"','PRIVATE-REFERENCE-SENTINEL','private-origin-'))
        joint=b['module_context']['joint_mechanism'];candidate=joint['candidate_context'];value=candidate['instructions']
        if b['slot']=='analysis_program':
            adjustment=float(value.split('=')[1]);observations=joint['execution_observations']
            values=[json.loads(o['stdout'])['statistic'] for o in observations]
            assert len(values)==2 and all(o['status']=='succeeded' for o in observations)
            state_values=[next(iter(o['content'].values())) for o in joint['state_projection']['observations']]
            program="import csv,json\nwith open('/input/public_csv') as f: xs=[float(r['x']) for r in csv.DictReader(f)]\n"
            program+="print(json.dumps({'candidate':"+repr(adjustment)+",'phase_values':"+repr(values)+",'state_values':"+repr(state_values)+",'statistic':sum(xs)/len(xs)+"+repr(sum(values)+adjustment+sum(state_values))+"}))"
            if fault=='docker':program="raise RuntimeError('retained synthetic execution failure')"
            if fault=='analysis':program=''
            return FrozenRecord.from_dict({'analysis':'Consume actual selected work outputs, candidate and qualified state.','program':program})
        return FrozenRecord.from_dict({'objective_digest':b['module_context']['required_objective_digest'],'outcome':'unknown',
            'evidence_ids':[],'conclusion':'Actual synthetic observation: '+b['execution_feedback'][0]['stdout'],'programme_complete':False})
    port=model_port(root/'port',patch,max_calls=70,max_tokens=1000,schemas=model_schemas(),response_factory=response)
    store,handles,manifest_sha=_store(root,{'tasks':{p.task.content_hash:p.task for p in packets}})
    body={'schema':'execution-improvement-train-plan-v1','export_mode':'primary_prospective','domain':'train','stage':'synthetic-execution-improvement',
        'item_ids':[i.token for i in selected],'task_bindings':{i.token:{'identity':p.task.identity.data(),'task_digest':p.task.content_hash,
            'csv_sha256':hashlib.sha256(p.csv_path.read_bytes()).hexdigest(),'csv_byte_count':p.csv_path.stat().st_size} for i,p in zip(selected,packets,strict=True)},
        'baseline_digest':'a'*64,'history_binding':history.binding.data(),'history_inputs':{'public_csv':{'sha256':hashlib.sha256(csv.read_bytes()).hexdigest(),'byte_count':csv.stat().st_size}},
        'parent':parent.record.data(),'fixed_builder':{'entrypoint':'emit_literal_change_v1','surface':'prompt','key':'instructions','value':'Use candidate adjustment=2'},
        'history_materials':histories,'target_materials':{pair:{p.task.content_hash:state_material(p.task,p.csv_path,False).data() for p in packets} for pair in DESIGNS},
        'source_verifier_bindings':{pair:q.binding().data() for pair,q in verifiers.items()},'model_config':model_configuration(port).data(),
        'scorer':ScorerConfig.create(benchmark='core_pair',evaluator_id='synthetic-primary',version='v1',rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest()).record.data(),
        'scorer_handle_bindings':{k:hashlib.sha256(v.encode()).hexdigest() for k,v in handles.items()},'acceptance_criteria':{'contrast_analysis':_ANALYSIS},
        'objective':{'purpose':'Analyze public TRAIN measurements with frozen candidate and state.'},'image':IMAGE,'timeout_seconds':20,'allocation':ALLOCATION,
        'pipeline_estimand':ESTIMAND,'candidate_selections':selections('a'*64),
        'phase_materials':{p.task.content_hash:phase_material(p.task,p.csv_path,fault).data() for p in packets}}
    plan=FrozenExecutionImprovementPlan(FrozenRecord.from_dict(body),history,(('public_csv',csv),))
    return dict(root=root,exporter=exporter,selected=selected,all_items=all_items,packets=packets,plan=plan,verifiers=verifiers,
        port=port,seen=seen,calls=calls,store=store,handles=handles,manifest_sha=manifest_sha)


def services(setup,stack,panels,fault=None):
    root=setup['root'];b=setup['plan'].data();rubric=ScorerConfig(FrozenRecord.from_dict(b['scorer']))
    (root/'execution.key').write_bytes(EXECUTION.key);(root/'score.key').write_bytes(SCORER.key);clients={}
    for n,panel in enumerate(panels):
        server={'schema':'execution-improvement-scorer-process-config-v1','panel':serialize_combination_panel(panel,execution_improvement=True),
            'scorer_config':rubric.record.data(),'scorer_config_digest':rubric.digest,
            'train_reference_store':{'root':str(setup['store'].resolve()),'manifest_sha256':setup['manifest_sha'],
                'inventory_digest':panel.cells[0].identity.dataset_version,'split_digest':panel.split_digest},'task_handles':setup['handles'],
            'execution_authority_key_files':{EXECUTION.authority_id:str(root/'execution.key')},
            'scorer_authority':{'id':SCORER.authority_id,'key_file':str(root/'score.key')},'evaluator':{'synthetic_mode':'fail' if fault=='scorer' else 'normal'}}
        path=root/f'server-{n}.json';path.write_text(canonical(server),encoding='utf-8')
        command=_command(path,root/f'worker-{n}.jsonl');command[1]=str((Path(__file__).parent/'helpers/execution_improvement_scorer_process_helper.py').resolve())
        client=CombinationScorerProcessClient(panel=panel,config=rubric,execution_improvement=True,command=command,
            journal_path=root/f'client-{n}.jsonl',task_handle_bindings=b['scorer_handle_bindings'],execution_authority_keys={EXECUTION.authority_id:EXECUTION.key},
            scorer_authority_keys={SCORER.authority_id:SCORER.key},environment={**os.environ,'PYTHONIOENCODING':'gbk'})
        stack.callback(client.close);clients[panel.obligation_id]=client
    return clients


def invoke(setup,patch,fault=None):
    def forbidden(*a,**k):raise AssertionError('legacy exporter invoked')
    patch.setattr(TrainPacketExporter,'export',forbidden)
    exporter=setup['exporter'];plan=setup['plan']
    if fault=='builder':
        def fail(*a,**k): raise ContractError('synthetic restricted builder failure')
        patch.setattr(RestrictedBuilderPort,'execute',fail)
    if fault=='auxiliary_unknown':
        original=DockerExecutionBroker.execute
        def unknown(broker,request):
            if request.program.parent.name=='phase':raise RuntimeError('synthetic unknown auxiliary transport')
            return original(broker,request)
        patch.setattr(DockerExecutionBroker,'execute',unknown)
    with ExitStack() as stack:
        return run_execution_improvement_train(plan,prospective_exporter=exporter,snapshot_root=Path(exporter.config['snapshot_root']),
            export_root=exporter.output_root,run_root=setup['root']/'run',model=setup['port'],audit_verifier=AUDIT,source_verifiers=setup['verifiers'],
            scorer_factory=lambda panels:services(setup,stack,panels,fault),execution_authority=EXECUTION,scorer_authority_keys={SCORER.authority_id:SCORER.key})


@pytest.fixture(scope='module')
def grid(tmp_path_factory):
    root=tmp_path_factory.mktemp('execution-improvement')
    with pytest.MonkeyPatch.context() as patch:
        setup=prepare(root,patch);run=invoke(setup,patch)
    return setup,run


def replay_args(setup,run,result):
    panel=next(p for p in run.panels if result.cell in p.cells);packet=next(p for p in run.barrier.packets if p.task.content_hash==result.cell.task_digest)
    return dict(panel=panel,task=packet.task,scenario=run.scenarios[result.cell.key],package=run.barrier.package(panel.obligation_id,result.cell.arm_id),
        material=setup['plan'].target_material(panel.obligation_id,result.cell.task_digest),source_verifier=setup['verifiers'][panel.obligation_id],
        barrier=run.barrier,public_inputs={'public_csv':packet.csv_path},broker=run.barrier.broker,ledger=run.ledger,
        phase_material=setup['plan'].phase_material(result.cell.task_digest))



def test_complete_shared_builds_and_actual_execution_factorial(grid):
    setup,run=grid;b=run.receipt.data()
    assert b['status']=='complete_train_engineering',b
    assert b['expected_builds']==len(run.builds)==6 and len(b['arm_recipe_bindings'])==16
    assert b['expected_cells']==len(run.results)==len(run.scores)==len(run.attempts)==32
    assert len(setup['seen'])==70 and len(setup['calls'])==76
    assert b['actual_auxiliary_docker_attempts']==64 and b['actual_solver_docker_attempts']==32
    assert b['actual_docker_attempts']==96 and b['actual_scorer_calls']==32 and b['actual_builder_executions']==6
    assert b['actual_retrieval_calls']==b['unused_docker_opportunities']==b['unused_model_opportunities']==0
    assert b['structural_exclusions']==b['pruned_cells']==[] and not b['validation_opened']
    for panel in run.panels:
        assert panel.design.data()['background']==['M2']
        for bit in '01':assert len({c.package_digest for c in panel.cells if c.arm_id[-1]==bit})==1
    for result in run.results:
        issue_execution_improvement_score_input(authority=EXECUTION,result=result,**replay_args(setup,run,result))
        assert 'M2' in result.cell.runtime_arm.data()['enabled']
        observed=json.loads(result.solver.execution.record.data()['stdout'])
        assert observed['phase_values']==[json.loads(o['stdout'])['statistic'] for o in result.phase.data()['public']['observations']]
        assert observed['state_values'] and ('candidate' in observed)
        phase=result.phase.data();assert phase['actual_docker_attempts']==phase['execution_units_reserved']==2
        assert phase['remaining_leases']==phase['residual_containers']==[]
        if 'M8' not in result.cell.runtime_arm.data()['enabled']:assert phase['overlap_ns']==0
    triples=[c for c in b['contrasts'] if len(c['normalized_descriptive_terms'])==7]
    assert len(triples)==1
    assert set(triples[0]['normalized_descriptive_terms'])=={'M7','M8','M9','M7+M8','M7+M9','M8+M9','M7+M8+M9'}
    for term in triples[0]['normalized_descriptive_terms'].values():
        assert len(term['coefficients'])==8 and set(term['coefficients'].values())=={-.25,.25}
        for estimate in term['benchmark_estimates'].values():assert estimate['independent_groups']==1 and estimate['confidence_interval'] is None
    for request in setup['seen'][:6]:assert request['slot']=='builder_proposal' and not any(m in canonical(request) for m in ('M7','M8'))


def test_new_exposure_and_process_scope_leave_old_exact_panel_contract(grid):
    _,run=grid
    for panel in run.panels:
        wire=serialize_combination_panel(panel,execution_improvement=True)
        assert parse_combination_panel(wire,execution_improvement=True)==panel
        for flags in ({},{'state_improvement':True},{'mechanism_improvement':True},{'state_retrieval':True},{'execution_improvement':1},
                {'state_improvement':True,'execution_improvement':True}):
            with pytest.raises(ContractError):serialize_combination_panel(panel,**flags)
        with pytest.raises(ContractError):
            CombinationPanel(panel.stage,panel.domain,panel.split_digest,panel.obligation_id,panel.estimand,
                panel.design,panel.package_bundle,panel.acceptance_criteria,panel.cells)


@pytest.mark.parametrize('relative',['candidate-barrier.json','plan.json','build-provider-ledger.json','target-provider-ledger.json',
    'builds/0/candidate.json','builds/0/builder.json','builds/0/builder-receipt.json','builds/0/proposal/evidence.jsonl',
    'builds/0/source/source-verification.json','controller.jsonl'])
def test_original_history_build_provider_and_barrier_files_are_bound(grid,relative):
    setup,run=grid;path=run.root/relative;raw=path.read_bytes()
    try:
        path.write_bytes(raw+b' ')
        with pytest.raises(ContractError):issue_execution_improvement_score_input(authority=EXECUTION,result=run.results[0],**replay_args(setup,run,run.results[0]))
    finally:path.write_bytes(raw)



@pytest.mark.parametrize('field,value',[('--network','host'),('--memory','4g'),('--cpus','8.0'),('--user','0:0'),('-v','/wrong:/input/public_csv:rw')])
def test_rehashed_solver_execution_cannot_relax_docker_limits_or_mounts(grid,field,value):
    from research_loop.modular.panel_receipts import PanelReceiptVerifier
    from research_loop.modular.execution_improvement_combination_driver import verify_execution_improvement_cell
    setup,run=grid;executed=next(r for r in run.results if r.cell.coverage_id=='pair:M7+M9' and r.cell.arm_id=='11')
    args=replay_args(setup,run,executed);path=executed.runtime.trace_path;before=path.read_bytes()
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
        with pytest.raises(ContractError,match='Docker limits'):verify_execution_improvement_cell(forged,**args)
        with pytest.raises(ContractError):issue_execution_improvement_score_input(authority=EXECUTION,result=forged,**args)
    finally:path.write_bytes(before)
    verify_execution_improvement_cell(executed,**args)


def test_proxy_cannot_skip_original_barrier_replay(grid):
    from types import SimpleNamespace
    setup,run=grid;result=run.results[0];args=replay_args(setup,run,result);barrier=run.barrier
    proxy=SimpleNamespace(root=barrier.root,record=barrier.record,plan=barrier.plan,verify=lambda:None,
        package=barrier.package,provenance=barrier.provenance)
    with pytest.raises(ContractError):issue_execution_improvement_score_input(authority=EXECUTION,result=result,**{**args,'barrier':proxy})



@pytest.mark.parametrize('fault',['csv','history','receipt','completion','material'])
def test_source_faults_precede_any_new_source_or_model_calls(tmp_path,monkeypatch,fault):
    setup=prepare(tmp_path,monkeypatch)
    if fault=='csv':
        path=Path(setup['exporter'].config['snapshot_root'])/'scienceagent/work/BLADE/blade_bench/datasets/case0/data.csv';path.write_bytes(path.read_bytes()+b' ')
    elif fault=='history':setup['plan'].history.trace_path.write_bytes(setup['plan'].history.trace_path.read_bytes()+b' ')
    elif fault in ('receipt','completion'):corrupt_export(monkeypatch,setup['exporter'],'export_receipt' if fault=='receipt' else 'completion_anchor')
    else:
        original=setup['exporter'].export_controller_packets
        def drift(tokens):
            packets=original(tokens);packets[0].csv_path.write_bytes(b'drift');return packets
        monkeypatch.setattr(setup['exporter'],'export_controller_packets',drift)
    with pytest.raises(Exception):invoke(setup,monkeypatch)
    assert setup['seen']==setup['calls']==[]


@pytest.mark.parametrize('fault',['model_unknown','source_exception','unknown_cost','proposal','builder','target_unknown','auxiliary_failed','auxiliary_unknown','scorer'])
def test_failures_and_unknown_costs_preserve_all_denominators(tmp_path,monkeypatch,fault):
    setup=prepare(tmp_path,monkeypatch,fault);run=invoke(setup,monkeypatch,fault);b=run.receipt.data()
    assert b['status']=='inconclusive' and len(run.attempts)==32 and b['expected_builds']==6 and len(b['arm_recipe_bindings'])==16
    assert b['scored_cells']+b['failed_cells']+b['blocked_cells']==32
    assert b['successful_builds']+b['failed_builds']+b['blocked_builds']==6
    assert b['actual_docker_attempts']+b['unused_docker_opportunities']==96
    assert b['actual_model_usage']['model_calls']+b['unused_model_opportunities']==70
    assert b['source_calls']+b['unused_source_opportunities']==76
    if fault in ('model_unknown','source_exception','unknown_cost','proposal','builder'):
        assert b['blocked_cells']==32 and b['actual_docker_attempts']==b['actual_scorer_calls']==0
    elif fault=='target_unknown':assert b['failed_cells']==1 and b['blocked_cells']==31 and b['actual_auxiliary_docker_attempts']==2
    elif fault=='auxiliary_unknown':assert b['failed_cells']==1 and b['blocked_cells']==31 and b['actual_model_usage']['model_calls']==6 and b['auxiliary_cost_unknown']
    elif fault=='auxiliary_failed':assert b['failed_cells']==32 and b['actual_model_usage']['model_calls']==6 and b['actual_auxiliary_docker_attempts']==64
    elif fault=='scorer':assert b['failed_cells']==32 and b['actual_scorer_calls']==32


@pytest.mark.parametrize('mode',['dependency','conflict','timeout','order','overlap'])
def test_actual_bounded_phase_dependency_resource_overlap_fifo_cleanup(grid,tmp_path,mode):
    from research_loop.modular.exploration_scheduler_combination import FrozenExplorationSchedulerMaterial,run_phase,verify_phase
    setup,run=grid;executed=next(r for r in run.results if r.cell.coverage_id=='triple:M7+M8+M9' and r.cell.arm_id=='111')
    args=replay_args(setup,run,executed);m=args['phase_material'].data()
    if mode=='dependency':
        for j in m['jobs'][1:]:j['dependencies']=[m['jobs'][0]['id']]
    if mode=='conflict':
        for j in m['jobs'][1:]:j['resources']=m['jobs'][0]['resources']
    for i,j in enumerate(m['jobs']):
        delay=10 if mode=='timeout' else 3 if mode=='overlap' or mode=='order' and i==0 else .1
        j['program']="import json,time\nstart=time.time_ns()\ntime.sleep("+str(delay)+")\nprint(json.dumps({'start':start,'end':time.time_ns(),'value':"+str(i)+"}))"
    supplied=dict(material=FrozenExplorationSchedulerMaterial(FrozenRecord.from_dict(m)),cell=executed.cell,objective=executed.solver.session.objective,
        root=tmp_path/'phase',broker=DockerExecutionBroker([next(iter(args['public_inputs'].values())).parent,tmp_path]),
        inputs=args['public_inputs'],image=IMAGE,timeout_seconds=1 if mode=='timeout' else 20)
    report=run_phase(**supplied);assert verify_phase(**{k:v for k,v in supplied.items() if k!='broker'})==report
    b=report.data();assert b['actual_docker_attempts']==2 and b['remaining_leases']==[]
    if mode in ('dependency','conflict'):assert b['peak_leases']==1 and b['overlap_ns']==0
    if mode=='timeout':
        assert b['status']=='failed' and b['residual_containers']==[]
        for job in b['fifo_order']:
            receipt=json.loads((supplied['root']/(job+'.json')).read_bytes())['execution']
            assert receipt['status']=='timed_out' and receipt['record']['cleanup']['removed'] is True
    else:
        values=[json.loads(o['stdout']) for o in b['public']['observations']]
        assert [v['value'] for v in values]==[0,2]
        if mode=='overlap':assert min(v['end'] for v in values)>max(v['start'] for v in values)
        if mode=='order':assert b['completion_order']==list(reversed(b['fifo_order']))
    with pytest.raises(ContractError,match='exclusive'):run_phase(**supplied)


@pytest.mark.parametrize('attack',['late_phase','program','instruction','phase_program','queue_snapshot','phase_limits'])
def test_generic_passes_but_family_rejects_rehashed_native_execution_attacks(grid,attack):
    from research_loop.modular.panel_receipts import PanelReceiptVerifier
    import sqlite3
    setup,run=grid;result=next(r for r in run.results if r.cell.coverage_id=='triple:M7+M8+M9' and r.cell.arm_id=='111')
    args=replay_args(setup,run,result);path=result.runtime.trace_path;raw=path.read_bytes();phase=path.parent.parent/'phase';restores={}
    def mutate(rows):
        if attack=='late_phase':
            item=next(e for e in rows if e['stage']=='execution_improvement_phase');rows.remove(item);rows.insert(next(i for i,e in enumerate(rows) if e['stage']=='model_response'),item)
        elif attack=='instruction':
            event=next(e for e in rows if e['stage']=='model_request');event['data']['request']['instruction']='Use unbound target context.'
            old=event['data']['request_digest'];new=FrozenRecord.from_dict(event['data']['request']).content_hash;event['data']['request_digest']=new
            for row in rows:
                if row['stage']=='model_response' and row['data']['request_digest']==old:row['data']['request_digest']=new
    try:
        if attack in ('program','phase_program'):
            artifact=path.parent/'analysis-1.py' if attack=='program' else phase/(result.phase.data()['fifo_order'][0]+'.py')
            restores[artifact]=artifact.read_bytes();artifact.write_bytes(b'print(777)')
        elif attack=='queue_snapshot':
            artifact=phase/'queue.sqlite';restores[artifact]=artifact.read_bytes()
            with sqlite3.connect(artifact) as db:db.execute('UPDATE runs SET snapshot_hash=?',('0'*64,))
        elif attack=='phase_limits':
            artifact=phase/(result.phase.data()['fifo_order'][0]+'.json');restores[artifact]=artifact.read_bytes();body=json.loads(restores[artifact])
            argv=body['execution']['record']['argv'];argv[argv.index('--network')+1]='host';artifact.write_text(canonical(body),encoding='utf-8')
        tail=_rewrite_trace(path,mutate);forged=replace(result,runtime=replace(result.runtime,trace_digest=tail))
        PanelReceiptVerifier()._verify_runtime(forged.runtime,forged.cell)
        with pytest.raises(ContractError):issue_execution_improvement_score_input(authority=EXECUTION,result=forged,**args)
    finally:
        path.write_bytes(raw)
        for artifact,body in restores.items():artifact.write_bytes(body)


@pytest.mark.parametrize('attack',['selection','allocation','estimand','material'])
def test_rehashed_plan_cannot_change_fixed_allocation_or_phase_binding(grid,attack):
    setup,_=grid;plan=setup['plan'];b=plan.data()
    if attack=='selection':b['candidate_selections'][0]['canonical_build_arm_id']='01'
    elif attack=='allocation':b['allocation']['model_calls']+=1
    elif attack=='estimand':b['pipeline_estimand']='unconditional'
    else:next(iter(b['phase_materials'].values()))['public_artifacts'][0]['artifact']['sha256']='0'*64
    with pytest.raises(ContractError):replace(plan,record=FrozenRecord.from_dict(b))
