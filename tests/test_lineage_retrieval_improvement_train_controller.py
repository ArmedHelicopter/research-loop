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
from evaluation.modular.lineage_retrieval_improvement_scoring import issue_lineage_retrieval_improvement_score_input
from evaluation.modular.train_io import TrainPacketExporter
from research_loop.modular.contracts import FrozenRecord, PublicTask, DataIdentity
from research_loop.modular.benchmark_solver import run_benchmark_solve
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest, FrozenBuilderVersion, RestrictedBuilderPort
from research_loop.modular.runtime import AuditVerifier, verify_trace
from research_loop.modular.metaprogram_training import FrozenTrainHistory, model_configuration, metaprogram_schemas
from research_loop.modular.lineage_retrieval_improvement_combination_controller import FrozenLineageRetrievalImprovementPlan, run_lineage_retrieval_improvement_train, recipes, ALLOCATION, selections, ESTIMAND
from research_loop.modular.state_improvement_build import material_class, verify_build, FrozenProviderLedger
from research_loop.modular.lineage_retrieval_improvement_panel import LineageRetrievalImprovementPanel, DESIGNS
from research_loop.modular.combination_panels import CombinationPanel
from research_loop.modular.combination_train_controller import _ANALYSIS
from research_loop.ontology import ContractError, canonical
from test_remaining_prospective_train_sources import prepared_primary, corrupt_export
from test_state_retrieval_combination_driver import state_material, IMAGE, Provider
from research_loop.modular.state_retrieval_combination_driver import freeze_material, FrozenStateRetrievalMaterial
from research_loop.modular.lineage_combination_material import DualMaterialVerifier, MaterialAuthority
from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from research_loop.modular.lineage_retrieval_improvement_modules import model_schemas
from research_loop.modular.lineage_retrieval_improvement_contrasts import component_policy
from test_modular_combination_benchmark_driver import _plan
from test_admission_combination import sources
from test_modular_train_controller import model_port
from test_lineage_combination_controller import EXECUTION, SCORER
from test_scorer_process import _store, _command
from test_modular_combination_benchmark_driver import _rewrite_trace

AUDIT=AuditVerifier({'a':b'a'*32,'b':b'b'*32})


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
    corpus_calls=[];retrieval_calls=[];corpus=provenance(corpus_calls,'unknown_cost' if fault=='corpus_unknown' else None,True)
    histories={}
    for pair in DESIGNS:
        m=state_material(task,csv,False).data()
        for row in m['originals']:row['root_material']={'history_digest':history.binding.content_hash,'observation_key':row['key']}
        histories[pair]=material_class(pair)(FrozenRecord.from_dict(m)).data()
    seen=[]
    def response(request):
        b=request.data();seen.append(b)
        frozen=json.loads((root/'run/controller-attempt.json').read_bytes())
        assert len(frozen['builds'])==2 and len(frozen['targets'])==16 and len(frozen['structural_exclusions'])==0
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
        assert len(barrier['build_receipts'])==2 and len(barrier['candidate_selections'])==8 and len(frozen['panels'])==1
        assert all(marker not in request.encoded for marker in ('"arm_id"','"enabled"','PRIVATE-REFERENCE-SENTINEL','private-origin-'))
        joint=b['module_context']['joint_mechanism'];candidate=joint['candidate_context'];value=candidate['instructions']
        if b['slot']=='analysis_program':
            adjustment=float(value.split('=')[1]);retrieval=joint['retrieval']
            observations=[next(iter(r['content'].values())) for r in joint['state_projection']['observations']]
            pending=sum(r.get('needs_review') is True for r in joint['state_projection']['memory'])
            counter=len(retrieval['by_lane']['counter'])
            program="import csv,json,statistics\nwith open('/input/public_csv') as f: xs=[float(r['x']) for r in csv.DictReader(f)]\n"
            program+="statistic="+('statistics.median(xs)' if counter else 'sum(xs)/len(xs)')+"+"+repr(adjustment)+"+"+repr(sum(observations)/len(observations)-pending)+"\n"
            program+="print(json.dumps({'target_statistic':statistic,'candidate':"+repr(adjustment)+",'counter_sources':"+str(counter)+",'pending':"+repr(pending)+",'observations':"+repr(observations)+"}))"
            if fault=='docker':program="raise RuntimeError('retained synthetic execution failure')"
            if fault=='analysis':program=''
            return FrozenRecord.from_dict({'analysis':'Execute the qualified lineage state and corpus method using the frozen history candidate.','program':program})
        return FrozenRecord.from_dict({'objective_digest':b['module_context']['required_objective_digest'],'outcome':'unknown',
            'evidence_ids':[],'conclusion':'Actual synthetic observation: '+b['execution_feedback'][0]['stdout'],'programme_complete':False})
    port=model_port(root/'port',patch,max_calls=34,max_tokens=1000,schemas=model_schemas(),response_factory=response)
    store,handles,manifest_sha=_store(root,{'tasks':{p.task.content_hash:p.task for p in packets}})
    body={'schema':'lineage-retrieval-improvement-train-plan-v1','export_mode':'primary_prospective','domain':'train','stage':'synthetic-lineage-retrieval-improvement',
        'item_ids':[i.token for i in selected],'task_bindings':{i.token:{'identity':p.task.identity.data(),'task_digest':p.task.content_hash,
            'csv_sha256':hashlib.sha256(p.csv_path.read_bytes()).hexdigest(),'csv_byte_count':p.csv_path.stat().st_size} for i,p in zip(selected,packets,strict=True)},
        'baseline_digest':'a'*64,'history_binding':history.binding.data(),'history_inputs':{'public_csv':{'sha256':hashlib.sha256(csv.read_bytes()).hexdigest(),'byte_count':csv.stat().st_size}},
        'parent':parent.record.data(),'fixed_builder':{'entrypoint':'emit_literal_change_v1','surface':'prompt','key':'instructions','value':'Use candidate adjustment=2'},
        'history_materials':histories,'target_materials':{pair:{p.task.content_hash:state_material(p.task,p.csv_path,False).data() for p in packets} for pair in DESIGNS},
        'source_verifier_bindings':{pair:q.binding().data() for pair,q in verifiers.items()},'model_config':model_configuration(port).data(),
        'scorer':ScorerConfig.create(benchmark='core_pair',evaluator_id='synthetic-primary',version='v1',rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest()).record.data(),
        'scorer_handle_bindings':{k:hashlib.sha256(v.encode()).hexdigest() for k,v in handles.items()},'acceptance_criteria':{'contrast_analysis':_ANALYSIS,'factorial_components':component_policy().data()},
        'objective':{'purpose':'Analyze public TRAIN measurements with frozen candidate and state.'},'image':IMAGE,'timeout_seconds':20,'allocation':ALLOCATION,
        'pipeline_estimand':ESTIMAND,'candidate_selections':selections('a'*64),'retrieval_verifier_binding':corpus.binding().data(),
        'retrieval_materials':{p.task.content_hash:freeze_material(p.task,state_material(p.task,p.csv_path,False),
            [{'source_id':'origin-'+str(i),'root_source_id':'root-'+str(i),'lane':lane,'text':text} for i,(lane,text) in enumerate([
                ('support','Use the public mean.'),('counter','Check public outliers with a median.'),('method','Compute the CSV mean or robust median.')])],
            'Which public method should analyze the target observations?').data() for p in packets}}
    plan=FrozenLineageRetrievalImprovementPlan(FrozenRecord.from_dict(body),history,(('public_csv',csv),))
    return dict(root=root,exporter=exporter,selected=selected,all_items=all_items,packets=packets,plan=plan,verifiers=verifiers,
        port=port,seen=seen,calls=calls,corpus=corpus,corpus_calls=corpus_calls,retrieval_calls=retrieval_calls,store=store,handles=handles,manifest_sha=manifest_sha)


def services(setup,stack,panels,fault=None):
    root=setup['root'];b=setup['plan'].data();rubric=ScorerConfig(FrozenRecord.from_dict(b['scorer']))
    (root/'execution.key').write_bytes(EXECUTION.key);(root/'score.key').write_bytes(SCORER.key);clients={}
    for n,panel in enumerate(panels):
        server={'schema':'lineage-retrieval-improvement-scorer-process-config-v1','panel':serialize_combination_panel(panel,lineage_retrieval_improvement=True),
            'scorer_config':rubric.record.data(),'scorer_config_digest':rubric.digest,
            'train_reference_store':{'root':str(setup['store'].resolve()),'manifest_sha256':setup['manifest_sha'],
                'inventory_digest':panel.cells[0].identity.dataset_version,'split_digest':panel.split_digest},'task_handles':setup['handles'],
            'execution_authority_key_files':{EXECUTION.authority_id:str(root/'execution.key')},
            'scorer_authority':{'id':SCORER.authority_id,'key_file':str(root/'score.key')},'evaluator':{'synthetic_mode':'fail' if fault=='scorer' else 'normal'}}
        path=root/f'server-{n}.json';path.write_text(canonical(server),encoding='utf-8')
        command=_command(path,root/f'worker-{n}.jsonl');command[1]=str((Path(__file__).parent/'helpers/lineage_retrieval_improvement_scorer_process_helper.py').resolve())
        client=CombinationScorerProcessClient(panel=panel,config=rubric,lineage_retrieval_improvement=True,command=command,
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
    with ExitStack() as stack:
        return run_lineage_retrieval_improvement_train(plan,prospective_exporter=exporter,snapshot_root=Path(exporter.config['snapshot_root']),
            export_root=exporter.output_root,run_root=setup['root']/'run',model=setup['port'],audit_verifier=AUDIT,source_verifiers=setup['verifiers'],retrieval_verifier=setup['corpus'],
            provider_factory=lambda cell:Provider(setup['retrieval_calls'],fault=='retrieval'),
            scorer_factory=lambda panels:services(setup,stack,panels,fault),execution_authority=EXECUTION,scorer_authority_keys={SCORER.authority_id:SCORER.key})


@pytest.fixture(scope='module')
def grid(tmp_path_factory):
    root=tmp_path_factory.mktemp('lineage-retrieval-improvement')
    with pytest.MonkeyPatch.context() as patch:
        setup=prepare(root,patch);run=invoke(setup,patch)
    return setup,run


def replay_args(setup,run,result):
    panel=next(p for p in run.panels if result.cell in p.cells);packet=next(p for p in run.barrier.packets if p.task.content_hash==result.cell.task_digest)
    return dict(panel=panel,task=packet.task,scenario=run.scenarios[result.cell.key],package=run.barrier.package(panel.obligation_id,result.cell.arm_id),
        material=setup['plan'].target_material(panel.obligation_id,result.cell.task_digest),source_verifier=setup['verifiers'][panel.obligation_id],
        barrier=run.barrier,public_inputs={'public_csv':packet.csv_path},broker=run.barrier.broker,ledger=run.ledger,
        retrieval_material=FrozenStateRetrievalMaterial(FrozenRecord.from_dict(setup['plan'].data()['retrieval_materials'][result.cell.task_digest])) if panel.obligation_id=='triple:M3+M6+M9' else None,
        retrieval_verifier=setup['corpus'] if panel.obligation_id=='triple:M3+M6+M9' else None)


def test_two_shared_builds_freeze_eight_recipes_before_sixteen_actual_targets(grid):
    setup,run=grid;b=run.receipt.data()
    assert b['status']=='complete_train_engineering',b
    assert b['expected_builds']==len(run.builds)==2 and len(b['arm_recipe_bindings'])==8
    assert b['expected_cells']==len(run.results)==len(run.scores)==len(run.attempts)==16
    assert len(setup['seen'])==34 and len(setup['calls'])==36 and len(setup['corpus_calls'])==32
    assert len(setup['retrieval_calls'])==b['actual_retrieval_calls']==48
    assert b['actual_builder_executions']==2 and b['actual_docker_attempts']==b['actual_scorer_calls']==16
    assert b['structural_exclusions']==b['pruned_cells']==[] and b['retrieval_cost_unknown']
    assert not b['validation_opened'] and not b['scientific_effectiveness_proven']
    run.barrier.verify();panel=run.panels[0]
    for level in '01':
        assert len({run.barrier.package(panel.obligation_id,c.arm_id).digest for c in panel.cells if c.arm_id[-1]==level})==1
    programs={benchmark:set() for benchmark in ('blade','discoverybench')}
    for result in run.results:
        issue_lineage_retrieval_improvement_score_input(authority=EXECUTION,result=result,**replay_args(setup,run,result))
        enabled=set(result.cell.runtime_arm.data()['enabled'])
        assert 'M2' in enabled and enabled <= {'M2','M3','M6','M9'}
        observed=json.loads(result.solver.execution.record.data()['stdout'])
        if 'M9' not in enabled:assert observed['candidate']==2
        assert observed['counter_sources']==int('M6' in enabled)
        assert bool(observed['pending'])==('M3' in enabled)
        assert observed['observations']
        programs[result.cell.identity.benchmark].add((result.runtime.trace_path.parent/'analysis-1.py').read_text())
        assert (result.runtime.trace_path.parent/'reviews.jsonl').read_bytes()==b''
        assert (result.runtime.trace_path.parent/'predictions.jsonl').read_bytes()==b''
    assert all(len(values)==8 for values in programs.values())
    for b in setup['seen'][:2]:
        assert b['slot']=='builder_proposal' and not any(x in canonical(b) for x in ('M3','M4','M5','M6','M7','M8'))
    stages=[FrozenRecord(line).data() for line in (run.root/'controller.jsonl').read_text().splitlines()]
    seal=next(i for i,e in enumerate(stages) if e['stage']=='target_ledger_sealed')
    assert all(i>seal for i,e in enumerate(stages) if e['stage']=='scorer_reserved')


def test_seven_normalized_terms_and_null_group_confidence_intervals(grid):
    _,run=grid;contrast=run.receipt.data()['contrasts'][0]
    assert contrast['status']=='estimated'
    assert set(contrast['components'])=={'M3','M6','M9','M3+M6','M3+M9','M6+M9','M3+M6+M9'}
    for name,component in contrast['components'].items():
        weights=component_policy().data()['coefficients'][name]
        assert sum(weights.values())==0
        assert {abs(v) for v in weights.values()}=={1/(2**(3-len(name.split('+'))))}
        for value in component['benchmark_estimates'].values():
            assert value['independent_groups']==1 and value['mean']==0
            assert value['confidence_interval']=={'status':'not_estimable','reason':'insufficient_independent_groups','level':0.95,'lower':None,'upper':None}


def test_new_exposure_and_process_scope_leave_old_exact_panel_contract(grid):
    _,run=grid
    for panel in run.panels:
        wire=serialize_combination_panel(panel,lineage_retrieval_improvement=True)
        assert parse_combination_panel(wire,lineage_retrieval_improvement=True)==panel
        for flags in ({},{'state_improvement':True},{'state_retrieval':True},{'lineage_retrieval_improvement':1},
                {'mechanism_improvement':True},{'execution_improvement':True},
                {'execution_improvement':True,'lineage_retrieval_improvement':True},
                {'state_improvement':True,'lineage_retrieval_improvement':True}):
            with pytest.raises(ContractError):serialize_combination_panel(panel,**flags)
            with pytest.raises(ContractError):parse_combination_panel(wire,**flags)
        with pytest.raises(ContractError):
            CombinationPanel(panel.stage,panel.domain,panel.split_digest,panel.obligation_id,panel.estimand,
                panel.design,panel.package_bundle,panel.acceptance_criteria,panel.cells)


@pytest.mark.parametrize('relative',['candidate-barrier.json','plan.json','build-provider-ledger.json','target-provider-ledger.json',
    'builds/0/candidate.json','builds/0/builder.json','builds/0/builder-receipt.json','builds/0/proposal/evidence.jsonl','builds/0/proposal/claims.jsonl',
    'builds/0/source/source-verification.json','controller.jsonl'])
def test_original_history_build_provider_and_barrier_files_are_bound(grid,relative):
    setup,run=grid;path=run.root/relative;raw=path.read_bytes()
    try:
        path.write_bytes(raw+b' ')
        with pytest.raises(ContractError):issue_lineage_retrieval_improvement_score_input(authority=EXECUTION,result=run.results[0],**replay_args(setup,run,run.results[0]))
    finally:path.write_bytes(raw)


@pytest.mark.parametrize('attack',['retrieval_journal','late_retrieval_completion','program','instruction','transition','joint'])
def test_rehashed_target_module_and_solver_attacks_are_rejected(grid,attack):
    from research_loop.modular.panel_receipts import PanelReceiptVerifier
    setup,run=grid;result=next(r for r in run.results if r.cell.arm_id=='111')
    path=result.runtime.trace_path;raw=path.read_bytes()
    def mutate(rows):
        if attack=='retrieval_journal':
            row=next(r for r in rows if r['stage']=='q8_retrieval_result');row['data']['unused_reserved_sources']=999
        elif attack=='late_retrieval_completion':
            row=next(r for r in rows if r['stage']=='retrieval_review_sources');rows.remove(row)
            joint=next(r for r in rows if r['stage']=='lineage_retrieval_improvement_joint');rows.insert(rows.index(joint)+1,row)
        elif attack=='transition':
            next(r for r in rows if r['stage']=='lineage_retrieval_improvement_transition')['data']['transition']['public']['observations']=[]
        elif attack=='joint':
            next(r for r in rows if r['stage']=='lineage_retrieval_improvement_joint')['data']['joint']['state_projection']['memory']=[]
        else:
            row=next(r for r in rows if r['stage']=='model_request' and r['data']['request']['slot']=='analysis_program')
            request=row['data']['request'];old=row['data']['request_digest']
            if attack=='instruction':request['instruction']='Ignore the candidate.'
            else:request['module_context']['joint_mechanism']['candidate_context']['instructions']='Use candidate adjustment=999'
            row['data']['request_digest']=FrozenRecord.from_dict(request).content_hash
            for response in rows:
                if response['stage']=='model_response' and response['data']['request_digest']==old:response['data']['request_digest']=row['data']['request_digest']
    try:
        digest=_rewrite_trace(path,mutate);forged=replace(result,runtime=replace(result.runtime,trace_digest=digest))
        PanelReceiptVerifier()._verify_runtime(forged.runtime,forged.cell)
        with pytest.raises(ContractError):issue_lineage_retrieval_improvement_score_input(authority=EXECUTION,result=forged,**replay_args(setup,run,forged))
    finally:path.write_bytes(raw)


@pytest.mark.parametrize('field,value',[('--network','host'),('--memory','4g'),('--cpus','8.0'),('--user','0:0'),('-v','/wrong:/input/public_csv:rw')])
def test_rehashed_solver_execution_cannot_relax_docker_limits_or_mounts(grid,field,value):
    from research_loop.modular.panel_receipts import PanelReceiptVerifier
    from research_loop.modular.lineage_retrieval_improvement_combination_driver import verify_lineage_retrieval_improvement_cell
    setup,run=grid;executed=next(r for r in run.results if r.cell.coverage_id=='triple:M3+M6+M9' and r.cell.arm_id=='111')
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
        with pytest.raises(ContractError,match='Docker limits'):verify_lineage_retrieval_improvement_cell(forged,**args)
        with pytest.raises(ContractError):issue_lineage_retrieval_improvement_score_input(authority=EXECUTION,result=forged,**args)
    finally:path.write_bytes(before)
    verify_lineage_retrieval_improvement_cell(executed,**args)


def test_proxy_cannot_skip_original_barrier_replay(grid):
    from types import SimpleNamespace
    setup,run=grid;result=run.results[0];args=replay_args(setup,run,result);barrier=run.barrier
    proxy=SimpleNamespace(root=barrier.root,record=barrier.record,plan=barrier.plan,verify=lambda:None,
        package=barrier.package,provenance=barrier.provenance)
    with pytest.raises(ContractError):issue_lineage_retrieval_improvement_score_input(authority=EXECUTION,result=result,**{**args,'barrier':proxy})


@pytest.mark.parametrize('attack',['selection','allocation','estimand','corpus'])
def test_rehashed_plan_cannot_change_candidate_selection_or_factor_location(grid,attack):
    setup,_=grid;plan=setup['plan'];b=plan.data()
    if attack=='selection':b['candidate_selections'][-1]['canonical_build_arm_id']='000'
    elif attack=='allocation':b['allocation']['build_recipes']=12
    elif attack=='estimand':b['pipeline_estimand']='total_history_and_target_interaction'
    else:next(iter(b['retrieval_materials'].values()))['provenance']['query_digest']='f'*64
    with pytest.raises(ContractError):replace(plan,record=FrozenRecord.from_dict(b))


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
    assert setup['seen']==setup['calls']==setup['corpus_calls']==setup['retrieval_calls']==[]


@pytest.mark.parametrize('fault',['model_unknown','source_exception','unknown_cost','proposal','builder','target_unknown','retrieval','corpus_unknown','docker','analysis','scorer'])
def test_failures_and_unknown_costs_keep_all_recipe_target_denominators(tmp_path,monkeypatch,fault):
    setup=prepare(tmp_path,monkeypatch,fault);run=invoke(setup,monkeypatch,fault);b=run.receipt.data()
    assert b['status']=='inconclusive' and len(run.attempts)==16 and b['expected_builds']==2 and len(b['arm_recipe_bindings'])==8
    assert b['structural_exclusions']==b['pruned_cells']==[]
    assert b['scored_cells']+b['failed_cells']+b['blocked_cells']==16
    assert b['successful_builds']+b['failed_builds']+b['blocked_builds']==2
    for key,actual in [('builder',b['actual_builder_executions']),('docker',b['actual_docker_attempts']),('scorer',b['actual_scorer_calls'])]:
        assert b['unused_'+key+'_opportunities']+actual=={'builder':2,'docker':16,'scorer':16}[key]
    assert b['unused_model_opportunities']+b['actual_model_usage']['model_calls']==34
    assert b['unused_source_opportunities']+b['source_calls']==68
    assert b['unused_retrieval_opportunities']+b['actual_retrieval_calls']==48
    if fault in ('model_unknown','source_exception','unknown_cost','proposal','builder'):
        assert b['blocked_cells']==16 and b['actual_docker_attempts']==b['actual_scorer_calls']==0
    elif fault in ('target_unknown','corpus_unknown'):assert b['failed_cells']==1 and b['blocked_cells']==15
    elif fault=='retrieval':assert b['failed_cells']==16 and b['actual_retrieval_calls']==16 and b['scored_cells']==0
    elif fault in ('docker','analysis','scorer'):assert b['failed_cells']==16 and b['blocked_cells']==0
    if fault=='scorer':assert b['actual_docker_attempts']==b['actual_scorer_calls']==16 and b['actual_model_usage']['model_calls']==34


def build_args(setup,run,result):
    recipe=result.record.data()['recipe'];pair=recipe['pair'];plan=setup['plan']
    return dict(recipe=recipe,plan_digest=plan.record.content_hash,history=plan.history,material=plan.history_material(pair),
        qualifier=setup['verifiers'][pair],parent=plan.parent,fixed_builder=plan.fixed_builder,broker=run.barrier.broker,
        inputs=dict(plan.history_inputs),ledger=run.barrier.ledger)


@pytest.mark.parametrize('fault',['provider','package'])
def test_rehashed_build_files_still_require_original_provider_builder_and_qualification(grid,fault):
    setup,run=grid;build=run.builds[1];root=build.root
    before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
    try:
        if fault=='provider':
            path=root/'proposal/trace.jsonl'
            def mutate(rows):
                response=next(e['data']['response'] for e in rows if e['stage']=='model_response')
                response['value']='Use candidate adjustment=999'
                builder=FrozenBuilderVersion(FrozenRecord.from_dict(response))
                rows[-1]['data']={'response_digest':builder.record.content_hash,'builder_digest':builder.digest}
            _rewrite_trace(path,mutate)
        elif fault=='package':
            candidate=json.loads((root/'candidate.json').read_bytes());candidate['changes']['prompt']['instructions']='Use candidate adjustment=999'
            candidate=CandidatePackage(FrozenRecord.from_dict(candidate))
            (root/'candidate.json').write_text(candidate.record.encoded+'\n',encoding='utf-8',newline='\n')
            receipt=json.loads((root/'builder-receipt.json').read_bytes());receipt['output_candidate_digest']=candidate.digest
            (root/'builder-receipt.json').write_text(canonical(receipt)+'\n',encoding='utf-8',newline='\n')
        metadata=build.record.data();metadata['files']={str(p.relative_to(root)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in before if p!=root/'build-receipt.json'}
        if fault=='package':metadata['candidate_digest']=candidate.digest
        altered=replace(build,record=FrozenRecord.from_dict(metadata))
        (root/'build-receipt.json').write_text(altered.record.encoded+'\n',encoding='utf-8',newline='\n')
        verify_trace(root/'proposal/trace.jsonl')
        with pytest.raises(ContractError):verify_build(altered,**build_args(setup,run,altered))
    finally:
        for p,raw in before.items():p.write_bytes(raw)
    verify_build(build,**build_args(setup,run,build))


def test_rehashed_history_cannot_replace_the_predeclared_history_binding(grid):
    setup,run=grid;history=setup['plan'].history;path=history.trace_path;before=path.read_bytes()
    def mutate(rows):
        response=next(e['data']['response'] for e in reversed(rows) if e['stage']=='model_response')
        response['conclusion']='Changed caller history after the build plan was frozen.'
        rows[-1]['data']['candidate_digest']=FrozenRecord.from_dict(response).content_hash
    try:
        _rewrite_trace(path,mutate);verify_trace(path)
        changed=FrozenTrainHistory.freeze(history.task,path,expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        with pytest.raises(ContractError):replace(setup['plan'],history=changed)
        with pytest.raises(ContractError):run.barrier.verify()
    finally:path.write_bytes(before)


def test_rehashed_barrier_and_controller_order_do_not_create_early_target_permission(grid):
    setup,run=grid;barrier=run.barrier;path=run.root/'controller.jsonl';before=path.read_bytes()
    try:
        rows=[json.loads(line) for line in path.read_bytes().splitlines()]
        a=next(i for i,r in enumerate(rows) if r['stage']=='candidate_barrier');rows[a],rows[a+1]=rows[a+1],rows[a]
        previous=None
        for i,row in enumerate(rows):
            row['sequence']=i;row['previous']=previous;previous=FrozenRecord.from_dict(row).content_hash
        path.write_text(''.join(canonical(r)+'\n' for r in rows),encoding='utf-8',newline='\n')
        from research_loop.modular.metaprogram_training import _phase_rows
        _phase_rows(path)
        with pytest.raises(ContractError,match='precedes'):barrier.verify()
    finally:path.write_bytes(before)
    path=run.root/'candidate-barrier.json';before=path.read_bytes()
    try:
        b=barrier.record.data();b['provider_ledger_digest']='e'*64;changed=FrozenRecord.from_dict(b)
        path.write_text(changed.encoded+'\n',encoding='utf-8',newline='\n')
        forged=replace(barrier,record=changed)
        with pytest.raises(ContractError):forged.verify()
    finally:path.write_bytes(before)




@pytest.mark.parametrize('relative',['evidence.jsonl','claims.jsonl','predictions.jsonl','reviews.jsonl','analysis-1.py'])
def test_original_target_journals_and_program_are_replayed(grid,relative):
    setup,run=grid;result=next(r for r in run.results if r.cell.arm_id=='111');path=result.runtime.trace_path.parent/relative;raw=path.read_bytes()
    try:
        path.write_bytes(raw+b' ')
        with pytest.raises((ContractError,ValueError)):issue_lineage_retrieval_improvement_score_input(authority=EXECUTION,result=result,**replay_args(setup,run,result))
    finally:path.write_bytes(raw)


def test_coherently_rehashed_final_response_cannot_replace_original_provider_output(grid):
    from research_loop.modular.panel_receipts import PanelReceiptVerifier
    from research_loop.modular.benchmark_cell import _solver_journal_state
    setup,run=grid;result=run.results[0];path=result.runtime.trace_path;raw=path.read_bytes()
    old=result.solver.answer;body=old.data();body['conclusion']='Forged replacement with all internal hashes updated.';new=FrozenRecord.from_dict(body)
    def substitute(value):
        if isinstance(value,dict):return {k:substitute(v) for k,v in value.items()}
        if isinstance(value,list):return [substitute(v) for v in value]
        return new.content_hash if value==old.content_hash else value
    def mutate(rows):
        for row in rows:row['data']=substitute(row['data'])
        [row for row in rows if row['stage']=='model_response'][-1]['data']['response']=new.data()
    try:
        digest=_rewrite_trace(path,mutate);rows=[FrozenRecord(line).data() for line in path.read_text().splitlines()]
        state=_solver_journal_state(rows)
        output=FrozenRecord.from_dict({'responses':[r['data']['response'] for r in rows if r['stage']=='model_response'],'terminal':rows[-1]['data']})
        forged=replace(result,runtime=replace(result.runtime,trace_digest=digest,output_digest=output.content_hash),
            solver=replace(result.solver,answer=state['answer'],decision=state['decision']))
        PanelReceiptVerifier()._verify_runtime(forged.runtime,forged.cell)
        with pytest.raises(ContractError,match='provider'):issue_lineage_retrieval_improvement_score_input(authority=EXECUTION,result=forged,**replay_args(setup,run,forged))
    finally:path.write_bytes(raw)


@pytest.mark.parametrize('kind',['state','corpus'])
def test_rehashed_verified_unknown_source_cost_cannot_issue_successful_target(grid,kind):
    from research_loop.modular.panel_receipts import PanelReceiptVerifier
    setup,run=grid;result=run.results[0];trace=result.runtime.trace_path
    source=trace.parent.parent/('source-verification.json' if kind=='state' else 'retrieval/source-verification.json')
    original_trace=trace.read_bytes();original_source=source.read_bytes()
    verifier=setup['verifiers'][result.cell.coverage_id] if kind=='state' else setup['corpus']
    b=json.loads(original_source)
    for row,authority in zip(b['calls'],verifier.authorities,strict=True):
        response=row['response']['body'];response['cost_units']=None
        row['response']=authority.authority.issue({k:v for k,v in response.items() if k!='authority'}).data()
        row['cost_units']=None;row['cost_unknown']=True
    try:
        source.write_text(canonical(b)+'\n',encoding='utf-8',newline='\n')
        digest=hashlib.sha256(source.read_bytes()).hexdigest()
        def mutate(rows):
            event=next(e for e in rows if e['stage']=='lineage_retrieval_improvement_transition')
            event['data']['source_sha256' if kind=='state' else 'retrieval_source_sha256']=digest
        tail=_rewrite_trace(trace,mutate);forged=replace(result,runtime=replace(result.runtime,trace_digest=tail))
        PanelReceiptVerifier()._verify_runtime(forged.runtime,forged.cell)
        with pytest.raises(ContractError,match='unknown.*cost'):
            issued=issue_lineage_retrieval_improvement_score_input(authority=EXECUTION,result=forged,**replay_args(setup,run,forged))
            proof=setup['root']/('cost-'+kind+'-counterexample.json')
            proof.write_text(canonical({'generic_replay_passed':True,'score_input_issued':True,'score_input':issued.data(),
                'forged_source_sha256':digest,'forged_trace_digest':tail,'original_source_sha256':hashlib.sha256(original_source).hexdigest(),
                'original_trace_sha256':hashlib.sha256(original_trace).hexdigest()})+'\n',encoding='utf-8')
            (setup['root']/('cost-'+kind+'-forged-source.json')).write_bytes(source.read_bytes())
            (setup['root']/('cost-'+kind+'-forged-trace.jsonl')).write_bytes(trace.read_bytes())
    finally:
        source.write_bytes(original_source);trace.write_bytes(original_trace)



def test_rehashed_build_unknown_source_cost_cannot_pass_canonical_replay(grid):
    setup,run=grid;build=run.builds[1];root=build.root;source=root/'source/source-verification.json';trace=root/'proposal/trace.jsonl'
    before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
    b=json.loads(source.read_bytes());verifier=setup['verifiers'][build.record.data()['recipe']['pair']]
    for row,authority in zip(b['calls'],verifier.authorities,strict=True):
        response=row['response']['body'];response['cost_units']=None
        row['response']=authority.authority.issue({k:v for k,v in response.items() if k!='authority'}).data()
        row['cost_units']=None;row['cost_unknown']=True
    try:
        source.write_text(canonical(b)+'\n',encoding='utf-8',newline='\n')
        digest=hashlib.sha256(source.read_bytes()).hexdigest()
        def mutate(rows):
            next(e for e in rows if e['stage']=='state_improvement_history')['data']['source_sha256']=digest
        _rewrite_trace(trace,mutate)
        metadata=build.record.data();metadata['files']={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in before if p!=root/'build-receipt.json'}
        forged=replace(build,record=FrozenRecord.from_dict(metadata))
        (root/'build-receipt.json').write_text(forged.record.encoded+'\n',encoding='utf-8',newline='\n')
        verify_trace(trace)
        from research_loop.modular.metaprogram_training import _phase_rows
        _phase_rows(root/'phase.jsonl')
        with pytest.raises(ContractError,match='unknown.*cost'):
            candidate=verify_build(forged,**build_args(setup,run,forged))
            (setup['root']/'cost-build-counterexample.json').write_text(canonical({'generic_trace_passed':True,
                'generic_phase_passed':True,'canonical_build_replay_passed':True,'candidate_digest':candidate.digest,
                'forged_build':forged.record.data(),'original_build_digest':build.record.content_hash})+'\n',encoding='utf-8')
            (setup['root']/'cost-build-forged-source.json').write_bytes(source.read_bytes())
            (setup['root']/'cost-build-forged-trace.jsonl').write_bytes(trace.read_bytes())
    finally:
        for p,raw in before.items():p.write_bytes(raw)
