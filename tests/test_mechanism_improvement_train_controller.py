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
from evaluation.modular.mechanism_improvement_scoring import issue_mechanism_improvement_score_input
from evaluation.modular.train_io import TrainPacketExporter
from research_loop.modular.contracts import FrozenRecord, PublicTask, DataIdentity
from research_loop.modular.benchmark_solver import run_benchmark_solve
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest, FrozenBuilderVersion, RestrictedBuilderPort
from research_loop.modular.runtime import AuditVerifier, verify_trace
from research_loop.modular.metaprogram_training import FrozenTrainHistory, model_configuration, metaprogram_schemas
from research_loop.modular.mechanism_improvement_combination_controller import FrozenMechanismImprovementPlan, run_mechanism_improvement_train, recipes, ALLOCATION, selections, ESTIMAND
from research_loop.modular.state_improvement_build import material_class, verify_build, FrozenProviderLedger
from research_loop.modular.mechanism_improvement_panel import MechanismImprovementPanel, DESIGNS
from research_loop.modular.combination_panels import CombinationPanel
from research_loop.modular.combination_train_controller import _ANALYSIS
from research_loop.ontology import ContractError, canonical
from test_remaining_prospective_train_sources import prepared_primary, corrupt_export
from test_state_retrieval_combination_driver import state_material, IMAGE, Provider
from research_loop.modular.state_retrieval_combination_driver import freeze_material, FrozenStateRetrievalMaterial
from research_loop.modular.lineage_combination_material import DualMaterialVerifier, MaterialAuthority
from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from research_loop.modular.mechanism_improvement_modules import model_schemas, MEASUREMENT
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
        assert len(frozen['builds'])==6 and len(frozen['targets'])==24 and len(frozen['structural_exclusions'])==0
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
        assert len(barrier['build_receipts'])==6 and len(barrier['candidate_selections'])==12 and len(frozen['panels'])==3
        assert all(marker not in request.encoded for marker in ('"arm_id"','"enabled"','PRIVATE-REFERENCE-SENTINEL','private-origin-'))
        if b['slot']=='m4_plan':
            assert b['execution_feedback']==[]
            proposal=_plan();proposal['question']='What will the fresh target statistic show?'
            if fault=='nondiscriminating':
                for branch in proposal['branches']:
                    branch['elimination_condition']='Fresh target statistic does not increase'
                    for prediction in branch['predictions']:prediction.update(direction='increase',failure_condition='not increase')
            for branch in proposal['branches']:
                for prediction in branch['predictions']:
                    prediction.update(observable=MEASUREMENT['observable'],discriminator_id=MEASUREMENT['discriminator_id'])
            if fault=='prediction':proposal['branches'][0]['predictions'][0]['observable']='historical_x'
            return FrozenRecord.from_dict(proposal)
        if b['slot'].startswith('review_'):
            context=b['module_context'];prior=context['prior_responses']
            return FrozenRecord.from_dict({'assessment':'concern','evidence_refs':['public candidate guidance'],
                'counterexamples':['Check public outliers'] if not prior else ['Check the first reviewer observation too'],
                'uncertainty':'Use robust median' if not prior else 'Use mean after shared sequential discussion'})
        joint=b['module_context']['joint_mechanism'];candidate=joint['candidate_context'];value=candidate['instructions']
        if b['slot']=='analysis_program':
            adjustment=float(value.split('=')[1]);reviews=joint['reviews'];retrieval=joint['retrieval']
            robust=bool(reviews and all('median' in review['uncertainty'] for review in reviews))
            counter=len(retrieval['by_lane']['counter']) if retrieval else 0
            prediction=joint['prediction_plan'] or joint['prediction_proposal']
            directions=[branch['predictions'][0]['direction'] for branch in prediction['branches']] if prediction else []
            program="import csv,json,statistics\nwith open('/input/public_csv') as f: xs=[float(r['x']) for r in csv.DictReader(f)]\n"
            program+="statistic="+('statistics.median(xs)' if robust or counter else 'sum(xs)/len(xs)')+"+"+repr(adjustment)+"\n"
            program+="directions="+repr(directions)+"\nprint(json.dumps({'target_statistic':statistic,'candidate':"+repr(adjustment)+",'forecast_checks':{d:(statistic>0 if d=='increase' else statistic<0 if d=='decrease' else statistic==0) for d in directions},'counter_sources':"+str(counter)+",'review_checks':"+repr([review['counterexamples'] for review in reviews])+"}))"
            if fault=='docker':program="raise RuntimeError('retained synthetic execution failure')"
            if fault=='analysis':program=''
            return FrozenRecord.from_dict({'analysis':'Execute the forecast, review checks and corpus method using frozen candidate guidance.','program':program})
        return FrozenRecord.from_dict({'objective_digest':b['module_context']['required_objective_digest'],'outcome':'unknown',
            'evidence_ids':[],'conclusion':'Actual synthetic observation: '+b['execution_feedback'][0]['stdout'],'programme_complete':False})
    port=model_port(root/'port',patch,max_calls=78,max_tokens=1000,schemas=model_schemas(),response_factory=response)
    store,handles,manifest_sha=_store(root,{'tasks':{p.task.content_hash:p.task for p in packets}})
    body={'schema':'mechanism-improvement-train-plan-v1','export_mode':'primary_prospective','domain':'train','stage':'synthetic-mechanism-improvement',
        'item_ids':[i.token for i in selected],'task_bindings':{i.token:{'identity':p.task.identity.data(),'task_digest':p.task.content_hash,
            'csv_sha256':hashlib.sha256(p.csv_path.read_bytes()).hexdigest(),'csv_byte_count':p.csv_path.stat().st_size} for i,p in zip(selected,packets,strict=True)},
        'baseline_digest':'a'*64,'history_binding':history.binding.data(),'history_inputs':{'public_csv':{'sha256':hashlib.sha256(csv.read_bytes()).hexdigest(),'byte_count':csv.stat().st_size}},
        'parent':parent.record.data(),'fixed_builder':{'entrypoint':'emit_literal_change_v1','surface':'prompt','key':'instructions','value':'Use candidate adjustment=2'},
        'history_materials':histories,'target_materials':{pair:{p.task.content_hash:state_material(p.task,p.csv_path,False).data() for p in packets} for pair in DESIGNS},
        'source_verifier_bindings':{pair:q.binding().data() for pair,q in verifiers.items()},'model_config':model_configuration(port).data(),
        'scorer':ScorerConfig.create(benchmark='core_pair',evaluator_id='synthetic-primary',version='v1',rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest()).record.data(),
        'scorer_handle_bindings':{k:hashlib.sha256(v.encode()).hexdigest() for k,v in handles.items()},'acceptance_criteria':{'contrast_analysis':_ANALYSIS},
        'objective':{'purpose':'Analyze public TRAIN measurements with frozen candidate and state.'},'image':IMAGE,'timeout_seconds':20,'allocation':ALLOCATION,
        'pipeline_estimand':ESTIMAND,'candidate_selections':selections('a'*64),'retrieval_verifier_binding':corpus.binding().data(),
        'retrieval_materials':{p.task.content_hash:freeze_material(p.task,state_material(p.task,p.csv_path,False),
            [{'source_id':'origin-'+str(i),'root_source_id':'root-'+str(i),'lane':lane,'text':text} for i,(lane,text) in enumerate([
                ('support','Use the public mean.'),('counter','Check public outliers with a median.'),('method','Compute the CSV mean or robust median.')])],
            'Which public method should analyze the target observations?').data() for p in packets}}
    plan=FrozenMechanismImprovementPlan(FrozenRecord.from_dict(body),history,(('public_csv',csv),))
    return dict(root=root,exporter=exporter,selected=selected,all_items=all_items,packets=packets,plan=plan,verifiers=verifiers,
        port=port,seen=seen,calls=calls,corpus=corpus,corpus_calls=corpus_calls,retrieval_calls=retrieval_calls,store=store,handles=handles,manifest_sha=manifest_sha)


def services(setup,stack,panels,fault=None):
    root=setup['root'];b=setup['plan'].data();rubric=ScorerConfig(FrozenRecord.from_dict(b['scorer']))
    (root/'execution.key').write_bytes(EXECUTION.key);(root/'score.key').write_bytes(SCORER.key);clients={}
    for n,panel in enumerate(panels):
        server={'schema':'mechanism-improvement-scorer-process-config-v1','panel':serialize_combination_panel(panel,mechanism_improvement=True),
            'scorer_config':rubric.record.data(),'scorer_config_digest':rubric.digest,
            'train_reference_store':{'root':str(setup['store'].resolve()),'manifest_sha256':setup['manifest_sha'],
                'inventory_digest':panel.cells[0].identity.dataset_version,'split_digest':panel.split_digest},'task_handles':setup['handles'],
            'execution_authority_key_files':{EXECUTION.authority_id:str(root/'execution.key')},
            'scorer_authority':{'id':SCORER.authority_id,'key_file':str(root/'score.key')},'evaluator':{'synthetic_mode':'fail' if fault=='scorer' else 'normal'}}
        path=root/f'server-{n}.json';path.write_text(canonical(server),encoding='utf-8')
        command=_command(path,root/f'worker-{n}.jsonl');command[1]=str((Path(__file__).parent/'helpers/mechanism_improvement_scorer_process_helper.py').resolve())
        client=CombinationScorerProcessClient(panel=panel,config=rubric,mechanism_improvement=True,command=command,
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
        return run_mechanism_improvement_train(plan,prospective_exporter=exporter,snapshot_root=Path(exporter.config['snapshot_root']),
            export_root=exporter.output_root,run_root=setup['root']/'run',model=setup['port'],audit_verifier=AUDIT,source_verifiers=setup['verifiers'],retrieval_verifier=setup['corpus'],
            provider_factory=lambda cell:Provider(setup['retrieval_calls'],fault=='retrieval'),
            scorer_factory=lambda panels:services(setup,stack,panels,fault),execution_authority=EXECUTION,scorer_authority_keys={SCORER.authority_id:SCORER.key})


@pytest.fixture(scope='module')
def grid(tmp_path_factory):
    root=tmp_path_factory.mktemp('mechanism-improvement')
    with pytest.MonkeyPatch.context() as patch:
        setup=prepare(root,patch);run=invoke(setup,patch)
    return setup,run


def replay_args(setup,run,result):
    panel=next(p for p in run.panels if result.cell in p.cells);packet=next(p for p in run.barrier.packets if p.task.content_hash==result.cell.task_digest)
    return dict(panel=panel,task=packet.task,scenario=run.scenarios[result.cell.key],package=run.barrier.package(panel.obligation_id,result.cell.arm_id),
        material=setup['plan'].target_material(panel.obligation_id,result.cell.task_digest),source_verifier=setup['verifiers'][panel.obligation_id],
        barrier=run.barrier,public_inputs={'public_csv':packet.csv_path},broker=run.barrier.broker,ledger=run.ledger,
        retrieval_material=FrozenStateRetrievalMaterial(FrozenRecord.from_dict(setup['plan'].data()['retrieval_materials'][result.cell.task_digest])) if panel.obligation_id=='pair:M6+M9' else None,
        retrieval_verifier=setup['corpus'] if panel.obligation_id=='pair:M6+M9' else None)


def test_six_shared_builds_freeze_twelve_recipes_before_twenty_four_actual_targets(grid):
    setup,run=grid;b=run.receipt.data()
    assert b['status']=='complete_train_engineering',b
    assert b['expected_builds']==len(run.builds)==6 and len(b['arm_recipe_bindings'])==12
    assert b['expected_cells']==len(run.results)==len(run.scores)==len(run.attempts)==24
    assert len(setup['seen'])==78 and len(setup['calls'])==60 and len(setup['corpus_calls'])==16
    assert len(setup['retrieval_calls'])==b['actual_retrieval_calls']==24
    assert b['actual_builder_executions']==6 and b['actual_docker_attempts']==b['actual_scorer_calls']==24
    assert b['structural_exclusions']==b['pruned_cells']==[] and b['retrieval_cost_unknown']
    assert not b['validation_opened'] and not b['scientific_effectiveness_proven']
    run.barrier.verify()
    for panel in run.panels:
        assert run.barrier.package(panel.obligation_id,'00')==run.barrier.package(panel.obligation_id,'10')
        assert run.barrier.package(panel.obligation_id,'01')==run.barrier.package(panel.obligation_id,'11')
    for result in run.results:
        issue_mechanism_improvement_score_input(authority=EXECUTION,result=result,**replay_args(setup,run,result))
        assert 'M2' in result.cell.runtime_arm.data()['enabled']
        observed=json.loads(result.solver.execution.record.data()['stdout'])
        if 'M9' not in result.cell.runtime_arm.data()['enabled']:assert observed['candidate']==2
        if result.cell.coverage_id=='pair:M4+M9':assert len(observed['forecast_checks'])==3
        if result.cell.coverage_id=='pair:M6+M9':assert observed['counter_sources']==int('M6' in result.cell.runtime_arm.data()['enabled'])
    for b in setup['seen'][:6]:
        assert b['slot']=='builder_proposal' and not any(x in canonical(b) for x in ('M4','M5','M6'))
    reviews=[r for r in setup['seen'] if r['slot']=='review_second']
    assert sum(bool(r['module_context']['prior_responses']) for r in reviews)==4
    assert all(r['module_context']['prior_responses']==[] for r in setup['seen'] if r['slot']=='review_first')


def test_new_exposure_and_process_scope_leave_old_exact_panel_contract(grid):
    _,run=grid
    for panel in run.panels:
        wire=serialize_combination_panel(panel,mechanism_improvement=True)
        assert parse_combination_panel(wire,mechanism_improvement=True)==panel
        for flags in ({},{'state_improvement':True},{'state_retrieval':True},{'mechanism_improvement':1},
                {'state_improvement':True,'mechanism_improvement':True}):
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
        with pytest.raises(ContractError):issue_mechanism_improvement_score_input(authority=EXECUTION,result=run.results[0],**replay_args(setup,run,run.results[0]))
    finally:path.write_bytes(raw)


@pytest.mark.parametrize('attack',['late_prediction','sealed_peer','review_journal','retrieval_journal','program','instruction'])
def test_rehashed_target_module_and_solver_attacks_are_rejected(grid,attack):
    from research_loop.modular.panel_receipts import PanelReceiptVerifier
    setup,run=grid
    pair='pair:M5+M9' if attack in ('sealed_peer','review_journal') else 'pair:M6+M9' if attack=='retrieval_journal' else 'pair:M4+M9'
    result=next(r for r in run.results if r.cell.coverage_id==pair and r.cell.arm_id=='11')
    path=result.runtime.trace_path;raw=path.read_bytes()
    def mutate(rows):
        if attack=='late_prediction':
            row=next(r for r in rows if r['stage']=='mechanism_improvement_prediction');rows.remove(row);rows.insert(-1,row)
        elif attack=='retrieval_journal':
            row=next(r for r in rows if r['stage']=='q8_retrieval_result');row['data']['unused_reserved_sources']=999
        elif attack=='review_journal':
            row=next(r for r in rows if r['stage']=='mechanism_improvement_review_submission');row['data']['barrier_open']=True
        else:
            row=next(r for r in rows if r['stage']=='model_request' and r['data']['request']['slot']==('review_second' if attack=='sealed_peer' else 'analysis_program'))
            request=row['data']['request'];old=row['data']['request_digest']
            if attack=='sealed_peer':request['module_context']['prior_responses']=[{'leaked':'first review'}]
            elif attack=='instruction':request['instruction']='Ignore the candidate.'
            else:request['module_context']['joint_mechanism']['candidate_context']['instructions']='Use candidate adjustment=999'
            row['data']['request_digest']=FrozenRecord.from_dict(request).content_hash
            for response in rows:
                if response['stage']=='model_response' and response['data']['request_digest']==old:response['data']['request_digest']=row['data']['request_digest']
    try:
        digest=_rewrite_trace(path,mutate);forged=replace(result,runtime=replace(result.runtime,trace_digest=digest))
        PanelReceiptVerifier()._verify_runtime(forged.runtime,forged.cell)
        with pytest.raises(ContractError):issue_mechanism_improvement_score_input(authority=EXECUTION,result=forged,**replay_args(setup,run,forged))
    finally:path.write_bytes(raw)


@pytest.mark.parametrize('field,value',[('--network','host'),('--memory','4g'),('--cpus','8.0'),('--user','0:0'),('-v','/wrong:/input/public_csv:rw')])
def test_rehashed_solver_execution_cannot_relax_docker_limits_or_mounts(grid,field,value):
    from research_loop.modular.panel_receipts import PanelReceiptVerifier
    from research_loop.modular.mechanism_improvement_combination_driver import verify_mechanism_improvement_cell
    setup,run=grid;executed=next(r for r in run.results if r.cell.coverage_id=='pair:M6+M9' and r.cell.arm_id=='11')
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
        with pytest.raises(ContractError,match='Docker limits'):verify_mechanism_improvement_cell(forged,**args)
        with pytest.raises(ContractError):issue_mechanism_improvement_score_input(authority=EXECUTION,result=forged,**args)
    finally:path.write_bytes(before)
    verify_mechanism_improvement_cell(executed,**args)


def test_proxy_cannot_skip_original_barrier_replay(grid):
    from types import SimpleNamespace
    setup,run=grid;result=run.results[0];args=replay_args(setup,run,result);barrier=run.barrier
    proxy=SimpleNamespace(root=barrier.root,record=barrier.record,plan=barrier.plan,verify=lambda:None,
        package=barrier.package,provenance=barrier.provenance)
    with pytest.raises(ContractError):issue_mechanism_improvement_score_input(authority=EXECUTION,result=result,**{**args,'barrier':proxy})


@pytest.mark.parametrize('attack',['selection','allocation','estimand','corpus'])
def test_rehashed_plan_cannot_change_candidate_selection_or_factor_location(grid,attack):
    setup,_=grid;plan=setup['plan'];b=plan.data()
    if attack=='selection':b['candidate_selections'][-1]['canonical_build_arm_id']='00'
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


@pytest.mark.parametrize('fault',['model_unknown','source_exception','unknown_cost','proposal','builder','target_unknown','prediction','retrieval','corpus_unknown'])
def test_failures_and_unknown_costs_keep_all_recipe_target_denominators(tmp_path,monkeypatch,fault):
    setup=prepare(tmp_path,monkeypatch,fault);run=invoke(setup,monkeypatch,fault);b=run.receipt.data()
    assert b['status']=='inconclusive' and len(run.attempts)==24 and b['expected_builds']==6 and len(b['arm_recipe_bindings'])==12
    assert b['structural_exclusions']==b['pruned_cells']==[]
    assert b['scored_cells']+b['failed_cells']+b['blocked_cells']==24
    assert b['successful_builds']+b['failed_builds']+b['blocked_builds']==6
    if fault in ('model_unknown','source_exception','unknown_cost','proposal','builder'):
        assert b['blocked_cells']==24 and b['actual_docker_attempts']==b['actual_scorer_calls']==0
    elif fault=='target_unknown':assert b['failed_cells']==1 and b['blocked_cells']==23
    elif fault=='prediction':assert b['failed_cells']==8 and b['scored_cells']==16
    elif fault=='retrieval':assert b['failed_cells']==8 and b['actual_retrieval_calls']==8 and b['scored_cells']==16
    elif fault=='corpus_unknown':assert b['failed_cells']==1 and b['blocked_cells']==7 and b['scored_cells']==16




def test_useful_nondiscriminating_forecasts_are_consumed_off_but_rejected_on(tmp_path,monkeypatch):
    setup=prepare(tmp_path,monkeypatch,'nondiscriminating');run=invoke(setup,monkeypatch,'nondiscriminating')
    b=run.receipt.data()
    assert b['scored_cells']==20 and b['failed_cells']==4 and b['blocked_cells']==0
    assert b['actual_model_usage']['model_calls']==70 and not b['actual_model_usage']['model_usage_incomplete']
    assert b['actual_builder_executions']==6 and b['actual_docker_attempts']==b['actual_scorer_calls']==20
    for result in run.results:
        if result.cell.coverage_id!='pair:M4+M9':continue
        events=[FrozenRecord(line).data() for line in result.runtime.trace_path.read_text().splitlines()]
        if 'M4' in result.cell.runtime_arm.data()['enabled']:
            assert result.runtime.status=='failed' and result.solver is None
            assert not any(e['stage']=='execution_request' or e['stage']=='model_request' and e['data']['request']['slot']=='analysis_program' for e in events)
        else:
            assert result.runtime.status=='succeeded' and result.joint_mechanism.data()['prediction_plan'] is None
            assert (result.runtime.trace_path.parent/'predictions.jsonl').read_bytes()==b''
            measured=json.loads(result.solver.execution.record.data()['stdout'])
            assert set(measured['forecast_checks'])=={'increase'}
            assert measured['forecast_checks']['increase']==(measured['target_statistic']>0)


@pytest.mark.parametrize('attack',['early_prediction','early_review_submission','early_review_reveal'])
def test_module_records_cannot_precede_their_original_model_responses(grid,attack):
    from research_loop.modular.panel_receipts import PanelReceiptVerifier
    setup,run=grid
    result=next(r for r in run.results if r.cell.coverage_id==('pair:M4+M9' if attack=='early_prediction' else 'pair:M5+M9') and r.cell.arm_id=='11')
    path=result.runtime.trace_path;raw=path.read_bytes()
    stage={'early_prediction':'mechanism_improvement_prediction','early_review_submission':'mechanism_improvement_review_submission',
        'early_review_reveal':'mechanism_improvement_review_reveal'}[attack]
    def mutate(rows):
        record=next(r for r in rows if r['stage']==stage);rows.remove(record)
        slot='m4_plan' if attack=='early_prediction' else 'review_first' if attack=='early_review_submission' else 'review_second'
        request=next(r for r in rows if r['stage']=='model_request' and r['data']['request']['slot']==slot)
        # Reveal remains after both submission records, but those records and
        # reveal can all be moved ahead of the second response as one block.
        if attack=='early_review_reveal':
            submission=[r for r in rows if r['stage']=='mechanism_improvement_review_submission'][-1]
            rows.remove(submission);rows.insert(rows.index(request)+1,submission)
            rows.insert(rows.index(submission)+1,record)
        else:rows.insert(rows.index(request)+1,record)
    try:
        digest=_rewrite_trace(path,mutate);forged=replace(result,runtime=replace(result.runtime,trace_digest=digest))
        PanelReceiptVerifier()._verify_runtime(forged.runtime,forged.cell)
        with pytest.raises(ContractError):
            issued=issue_mechanism_improvement_score_input(authority=EXECUTION,result=forged,**replay_args(setup,run,forged))
            (setup['root']/(attack+'-counterexample.json')).write_text(json.dumps({'attack':attack,'generic_verified':True,
                'score_input_issued':True,'score_input_digest':issued.content_hash,'original_trace_sha256':hashlib.sha256(raw).hexdigest(),
                'forged_trace_sha256':hashlib.sha256(path.read_bytes()).hexdigest()})+'\n',encoding='utf-8')
            (setup['root']/(attack+'-forged-trace.jsonl')).write_bytes(path.read_bytes())
    finally:path.write_bytes(raw)
