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
from evaluation.modular.state_improvement_scoring import issue_state_improvement_score_input
from evaluation.modular.train_io import TrainPacketExporter
from research_loop.modular.contracts import FrozenRecord, PublicTask, DataIdentity
from research_loop.modular.benchmark_solver import run_benchmark_solve
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest, FrozenBuilderVersion, RestrictedBuilderPort
from research_loop.modular.runtime import AuditVerifier, verify_trace
from research_loop.modular.metaprogram_training import FrozenTrainHistory, model_configuration, metaprogram_schemas
from research_loop.modular.state_improvement_combination_controller import FrozenStateImprovementPlan, run_state_improvement_train, recipes, ALLOCATION
from research_loop.modular.state_improvement_build import material_class, verify_build, FrozenProviderLedger
from research_loop.modular.state_improvement_panel import StateImprovementPanel, DESIGNS
from research_loop.modular.combination_panels import CombinationPanel
from research_loop.modular.combination_train_controller import _ANALYSIS
from research_loop.ontology import ContractError, canonical
from test_remaining_prospective_train_sources import prepared_primary, corrupt_export
from test_state_retrieval_combination_driver import state_material, provenance, IMAGE
from test_admission_combination import sources
from test_modular_train_controller import model_port
from test_lineage_combination_controller import EXECUTION, SCORER
from test_scorer_process import _store, _command
from test_modular_combination_benchmark_driver import _rewrite_trace

AUDIT=AuditVerifier({'a':b'a'*32,'b':b'b'*32})


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
    calls=[];verifiers={pair:sources(calls,fault='source_unknown' if fault=='source_rejected' else fault if fault in {'source_exception','unknown_cost','source_cell_drift'} else None)
        if pair=='pair:M1+M9' else provenance(calls) for pair in DESIGNS}
    histories={}
    for pair in DESIGNS:
        m=state_material(task,csv,pair=='pair:M1+M9').data()
        for row in m['originals']:row['root_material']={'history_digest':history.binding.content_hash,'observation_key':row['key']}
        histories[pair]=material_class(pair)(FrozenRecord.from_dict(m)).data()
    seen=[]
    def response(request):
        b=request.data();seen.append(b)
        frozen=json.loads((root/'run/controller-attempt.json').read_bytes())
        assert len(frozen['builds'])==11 and len(frozen['targets'])==22 and len(frozen['structural_exclusions'])==2
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
        assert len(barrier['build_receipts'])==11 and len(frozen['panels'])==3
        joint=b['module_context']['joint_mechanism'];candidate=joint['candidate_context'];value=candidate['instructions']
        assert set(joint)=={'schema','panel_cell','state_projection','candidate_context'}
        if b['slot']=='analysis_program':
            public=joint['state_projection'];values=[next(iter(r['content'].values())) for r in public['observations']]
            pending=sum(r.get('needs_review') is True for r in public['memory'])
            adjustment=float(value.split('=')[1])
            program="import csv,json\nwith open('/input/public_csv') as f: xs=[float(r['x']) for r in csv.DictReader(f)]\n"
            program+="print(json.dumps({'mean':sum(xs)/len(xs),'state':"+repr(sum(values)/len(values)-pending)+",'candidate':"+repr(adjustment)+",'adjusted':sum(xs)/len(xs)+"+repr(sum(values)/len(values)-pending+adjustment)+"}))"
            if fault=='docker':program="raise RuntimeError('retained synthetic execution failure')"
            if fault=='analysis':program=''
            return FrozenRecord.from_dict({'analysis':'Compute public mean using the supplied state and candidate instructions.','program':program})
        return FrozenRecord.from_dict({'objective_digest':b['module_context']['required_objective_digest'],'outcome':'unknown',
            'evidence_ids':[],'conclusion':'Actual synthetic observation: '+b['execution_feedback'][0]['stdout'],'programme_complete':False})
    port=model_port(root/'port',patch,max_calls=55,max_tokens=1000,schemas=metaprogram_schemas(),response_factory=response)
    store,handles,manifest_sha=_store(root,{'tasks':{p.task.content_hash:p.task for p in packets}})
    body={'schema':'state-improvement-train-plan-v1','export_mode':'primary_prospective','domain':'train','stage':'synthetic-state-improvement',
        'item_ids':[i.token for i in selected],'task_bindings':{i.token:{'identity':p.task.identity.data(),'task_digest':p.task.content_hash,
            'csv_sha256':hashlib.sha256(p.csv_path.read_bytes()).hexdigest(),'csv_byte_count':p.csv_path.stat().st_size} for i,p in zip(selected,packets,strict=True)},
        'baseline_digest':'a'*64,'history_binding':history.binding.data(),'history_inputs':{'public_csv':{'sha256':hashlib.sha256(csv.read_bytes()).hexdigest(),'byte_count':csv.stat().st_size}},
        'parent':parent.record.data(),'fixed_builder':{'entrypoint':'emit_literal_change_v1','surface':'prompt','key':'instructions','value':'Use candidate adjustment=2'},
        'history_materials':histories,'target_materials':{pair:{p.task.content_hash:state_material(p.task,p.csv_path,pair=='pair:M1+M9').data() for p in packets} for pair in DESIGNS},
        'source_verifier_bindings':{pair:q.binding().data() for pair,q in verifiers.items()},'model_config':model_configuration(port).data(),
        'scorer':ScorerConfig.create(benchmark='core_pair',evaluator_id='synthetic-primary',version='v1',rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest()).record.data(),
        'scorer_handle_bindings':{k:hashlib.sha256(v.encode()).hexdigest() for k,v in handles.items()},'acceptance_criteria':{'contrast_analysis':_ANALYSIS},
        'objective':{'purpose':'Analyze public TRAIN measurements with frozen candidate and state.'},'image':IMAGE,'timeout_seconds':20,'allocation':ALLOCATION,
        'pipeline_estimand':'total_history_build_and_target_state_interaction'}
    plan=FrozenStateImprovementPlan(FrozenRecord.from_dict(body),history,(('public_csv',csv),))
    return dict(root=root,exporter=exporter,selected=selected,all_items=all_items,packets=packets,plan=plan,verifiers=verifiers,
        port=port,seen=seen,calls=calls,store=store,handles=handles,manifest_sha=manifest_sha)


def services(setup,stack,panels,fault=None):
    root=setup['root'];b=setup['plan'].data();rubric=ScorerConfig(FrozenRecord.from_dict(b['scorer']))
    (root/'execution.key').write_bytes(EXECUTION.key);(root/'score.key').write_bytes(SCORER.key);clients={}
    for n,panel in enumerate(panels):
        server={'schema':'state-improvement-scorer-process-config-v1','panel':serialize_combination_panel(panel,state_improvement=True),
            'scorer_config':rubric.record.data(),'scorer_config_digest':rubric.digest,
            'train_reference_store':{'root':str(setup['store'].resolve()),'manifest_sha256':setup['manifest_sha'],
                'inventory_digest':panel.cells[0].identity.dataset_version,'split_digest':panel.split_digest},'task_handles':setup['handles'],
            'execution_authority_key_files':{EXECUTION.authority_id:str(root/'execution.key')},
            'scorer_authority':{'id':SCORER.authority_id,'key_file':str(root/'score.key')},'evaluator':{'synthetic_mode':'fail' if fault=='scorer' else 'normal'}}
        path=root/f'server-{n}.json';path.write_text(canonical(server),encoding='utf-8')
        command=_command(path,root/f'worker-{n}.jsonl');command[1]=str((Path(__file__).parent/'helpers/state_improvement_scorer_process_helper.py').resolve())
        client=CombinationScorerProcessClient(panel=panel,config=rubric,state_improvement=True,command=command,
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
        return run_state_improvement_train(plan,prospective_exporter=exporter,snapshot_root=Path(exporter.config['snapshot_root']),
            export_root=exporter.output_root,run_root=setup['root']/'run',model=setup['port'],audit_verifier=AUDIT,source_verifiers=setup['verifiers'],
            scorer_factory=lambda panels:services(setup,stack,panels,fault),execution_authority=EXECUTION,scorer_authority_keys={SCORER.authority_id:SCORER.key})


@pytest.fixture(scope='module')
def grid(tmp_path_factory):
    root=tmp_path_factory.mktemp('state-improvement')
    with pytest.MonkeyPatch.context() as patch:
        setup=prepare(root,patch);run=invoke(setup,patch)
    return setup,run


def replay_args(setup,run,result):
    panel=next(p for p in run.panels if result.cell in p.cells);packet=next(p for p in run.barrier.packets if p.task.content_hash==result.cell.task_digest)
    return dict(panel=panel,task=packet.task,scenario=run.scenarios[result.cell.key],package=run.barrier.package(panel.obligation_id,result.cell.arm_id),
        material=setup['plan'].target_material(panel.obligation_id,result.cell.task_digest),source_verifier=setup['verifiers'][panel.obligation_id],
        barrier=run.barrier,public_inputs={'public_csv':packet.csv_path},broker=run.barrier.broker,ledger=run.ledger)


def test_11_builds_frozen_before_22_actual_target_docker_and_process_scores(grid):
    setup,run=grid;b=run.receipt.data()
    assert b['status']=='complete_train_engineering',b
    assert len(run.builds)==11 and len(run.results)==len(run.scores)==len(run.attempts)==22
    assert len(setup['seen'])==len(setup['port'].ledger['calls'])==55 and len(setup['calls'])==66
    assert b['actual_builder_executions']==11 and b['actual_docker_attempts']==b['actual_scorer_calls']==22
    assert len(b['structural_exclusions'])==2 and b['pruned_cells']==[] and not b['validation_opened'] and not b['scientific_effectiveness_proven']
    assert [r['slot'] for r in setup['seen'][:11]]==['builder_proposal']*11
    assert all(r['slot']!='builder_proposal' for r in setup['seen'][11:])
    run.barrier.verify()
    for result in run.results:
        issue_state_improvement_score_input(authority=EXECUTION,result=result,**replay_args(setup,run,result))
        if result.cell.coverage_id in {'pair:M1+M9','pair:M3+M9'}: assert 'M2' in result.cell.runtime_arm.data()['enabled']
        actual=json.loads(result.solver.execution.record.data()['stdout'])
        if 'M9' not in result.cell.runtime_arm.data()['enabled']: assert actual['candidate']==2
    for panel in run.panels:
        for benchmark in ('blade','discoverybench'):
            values=[json.loads(r.solver.execution.record.data()['stdout'])['adjusted'] for r in run.results if r.cell.coverage_id==panel.obligation_id and r.cell.identity.benchmark==benchmark]
            assert len(set(values))==len(values)


def test_versioned_process_scope_and_legacy_exact_manifest_unchanged(grid):
    _,run=grid
    for panel in run.panels:
        wire=serialize_combination_panel(panel,state_improvement=True)
        assert parse_combination_panel(wire,state_improvement=True)==panel
        for flags in ({},{'state_improvement':1},
                {'state_improvement':True,'state_retrieval':True},
                {'state_improvement':True,'state_exploration':True},
                {'state_improvement':True,'state_scheduling':True},
                {'state_improvement':True,'mechanism_exploration':True},
                {'mechanism_exploration':True},{'state_exploration':True},{'state_scheduling':True}):
            with pytest.raises(ContractError):serialize_combination_panel(panel,**flags)
        with pytest.raises(ContractError):
            CombinationPanel(panel.stage,panel.domain,panel.split_digest,panel.obligation_id,panel.estimand,panel.design,
                panel.package_bundle,panel.acceptance_criteria,panel.cells)
        wire['panel'].pop('training_provenance')
        with pytest.raises(ContractError):parse_combination_panel(wire,state_improvement=True)


@pytest.mark.parametrize('fault',['model_unknown','source_exception','unknown_cost','proposal','builder','target_unknown','analysis'])
def test_failed_and_unknown_costs_preserve_build_and_target_denominators(tmp_path,monkeypatch,fault):
    setup=prepare(tmp_path,monkeypatch,fault);run=invoke(setup,monkeypatch,fault);b=run.receipt.data()
    assert b['status']=='inconclusive' and len(run.attempts)==22 and len(b['structural_exclusions'])==2 and b['pruned_cells']==[]
    assert all(c['status']=='inconclusive' for c in b['contrasts'])
    if fault in {'model_unknown','source_exception','unknown_cost'}:
        assert b['blocked_cells']==22 and b['actual_docker_attempts']==b['actual_scorer_calls']==0
        assert len(setup['seen'])==(1 if fault=='model_unknown' else 0)
        assert len(setup['calls'])==2
    elif fault in {'proposal','builder'}:
        assert len(setup['seen'])==11 and b['blocked_cells']==22 and b['actual_docker_attempts']==0
        assert b['actual_builder_executions']==(11 if fault=='builder' else 0)
    elif fault=='target_unknown':
        assert len(setup['seen'])==12 and b['failed_cells']==1 and b['blocked_cells']==21 and b['source_calls']==24
    else:
        assert b['failed_cells']==22 and b['actual_docker_attempts']==0 and len(setup['seen'])==33


@pytest.mark.parametrize('fault',['csv','history','receipt','completion','material'])
def test_source_faults_precede_all_qualification_and_model_calls(tmp_path,monkeypatch,fault):
    setup=prepare(tmp_path,monkeypatch)
    if fault=='csv':
        path=Path(setup['exporter'].config['snapshot_root'])/'scienceagent/work/BLADE/blade_bench/datasets/case0/data.csv';path.write_bytes(path.read_bytes()+b' ')
    elif fault=='history':setup['plan'].history.trace_path.write_bytes(setup['plan'].history.trace_path.read_bytes()+b' ')
    elif fault in {'receipt','completion'}:corrupt_export(monkeypatch,setup['exporter'],'export_receipt' if fault=='receipt' else 'completion_anchor')
    else:
        original=setup['exporter'].export_controller_packets
        def drift(tokens):
            packets=original(tokens);packets[0].csv_path.write_bytes(b'drift');return packets
        monkeypatch.setattr(setup['exporter'],'export_controller_packets',drift)
    with pytest.raises(Exception):invoke(setup,monkeypatch)
    assert not setup['calls'] and not setup['seen'] and not setup['port'].ledger['calls']


@pytest.mark.parametrize('relative',['candidate-barrier.json','plan.json','build-provider-ledger.json','target-provider-ledger.json',
    'builds/0/candidate.json','builds/0/builder.json','builds/0/builder-receipt.json','builds/0/proposal/evidence.jsonl',
    'builds/0/source/source-verification.json','controller.jsonl'])
def test_original_build_barrier_and_provider_files_replay_bound(grid,relative):
    setup,run=grid;path=run.root/relative;raw=path.read_bytes()
    try:
        path.write_bytes(raw+b' ')
        with pytest.raises(ContractError):issue_state_improvement_score_input(authority=EXECUTION,result=run.results[0],**replay_args(setup,run,run.results[0]))
    finally:path.write_bytes(raw)


def test_barrier_proxy_cannot_bypass_corrupted_build_replay_without_new_io(grid,monkeypatch):
    from types import SimpleNamespace
    setup,run=grid;result=run.results[0];args=replay_args(setup,run,result)
    barrier=run.barrier;path=run.builds[0].root/'candidate.json';raw=path.read_bytes()
    before=(len(setup['seen']),len(setup['calls']),len(setup['port'].ledger['calls']))
    def forbidden(*a,**k):raise AssertionError('replay attempted new external I/O')
    monkeypatch.setattr(DockerExecutionBroker,'execute',forbidden)
    monkeypatch.setattr(RestrictedBuilderPort,'execute',forbidden)
    monkeypatch.setattr(type(setup['port']),'__call__',forbidden)
    for qualifier_type in {type(q) for q in setup['verifiers'].values()}:
        monkeypatch.setattr(qualifier_type,'qualify',forbidden)
    issue_state_improvement_score_input(authority=EXECUTION,result=result,**args)
    proxy=SimpleNamespace(root=barrier.root,record=barrier.record,plan=barrier.plan,
        verify=lambda:None,package=lambda *a:args['package'],provenance=lambda:barrier.provenance())
    try:
        path.write_bytes(raw+b' ')
        with pytest.raises(ContractError):barrier.verify()
        with pytest.raises(ContractError):
            signed=issue_state_improvement_score_input(authority=EXECUTION,result=result,**{**args,'barrier':proxy})
            (setup['root']/'barrier-proxy-counterexample.json').write_text(json.dumps({
                'schema':'state-improvement-barrier-proxy-counterexample-v1','corrupted_build':str(path),
                'original_sha256':hashlib.sha256(raw).hexdigest(),'corrupted_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                'score_input_issued':signed is not None,'new_external_calls':0})+'\n',encoding='utf-8')
    finally:path.write_bytes(raw)
    for field in ('plan','ledger'):
        original=getattr(barrier,field)
        class Proxy:
            def __getattr__(self,name):return getattr(original,name)
        with pytest.raises(ContractError):replace(barrier,**{field:Proxy()}).verify()
    assert (len(setup['seen']),len(setup['calls']),len(setup['port'].ledger['calls']))==before


@pytest.mark.parametrize('field',['program','context','instruction','joint'])
def test_rehashed_target_trace_cannot_change_provider_response_or_candidate(grid,field):
    setup,run=grid;result=run.results[0];path=result.runtime.trace_path;raw=path.read_bytes()
    def mutate(rows):
        if field=='program':
            e=next(r for r in rows if r['stage']=='model_response');e['data']['response']['program']='print(999)'
        else:
            e=next(r for r in rows if r['stage']=='model_request');request=e['data']['request']
            if field=='context':request['context']={}
            elif field=='instruction':request['instruction']='Ignore public context.'
            else:request['module_context']['joint_mechanism']['candidate_context']['instructions']='Use candidate adjustment=999'
            e['data']['request_digest']=FrozenRecord.from_dict(request).content_hash
    try:
        digest=_rewrite_trace(path,mutate)
        altered=replace(result,runtime=replace(result.runtime,trace_digest=digest))
        with pytest.raises(ContractError):issue_state_improvement_score_input(authority=EXECUTION,result=altered,**replay_args(setup,run,altered))
    finally:path.write_bytes(raw)


@pytest.mark.parametrize('field,value',[('--network','host'),('--memory','4g'),('--cpus','8.0'),('--user','0:0'),('-v','/wrong:/input/public_csv:rw')])
def test_rehashed_solver_execution_cannot_relax_docker_limits_or_mounts(grid,field,value):
    from research_loop.modular.panel_receipts import PanelReceiptVerifier
    from research_loop.modular.state_improvement_combination_driver import verify_state_improvement_cell
    setup,run=grid;executed=next(r for r in run.results if r.cell.coverage_id=='pair:M3+M9' and r.cell.arm_id=='11')
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
        with pytest.raises(ContractError,match='Docker limits'):verify_state_improvement_cell(forged,**args)
        with pytest.raises(ContractError):issue_state_improvement_score_input(authority=EXECUTION,result=forged,**args)
    finally:path.write_bytes(before)
    verify_state_improvement_cell(executed,**args)


def build_args(setup,run,result):
    recipe=result.record.data()['recipe'];pair=recipe['pair'];plan=setup['plan']
    return dict(recipe=recipe,plan_digest=plan.record.content_hash,history=plan.history,material=plan.history_material(pair),
        qualifier=setup['verifiers'][pair],parent=plan.parent,fixed_builder=plan.fixed_builder,broker=run.barrier.broker,
        inputs=dict(plan.history_inputs),ledger=run.barrier.ledger)


@pytest.mark.parametrize('fault',['provider','package','source'])
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
        else:
            path=root/'source/source-verification.json';body=json.loads(path.read_bytes())
            for entry,authority in zip(body['calls'],setup['verifiers']['pair:M1+M9'].authorities,strict=True):
                signed=entry['response']['body'];signed['assessments']['before']['old']['state']['validity']='invalid'
                entry['response']=authority.authority.issue({k:v for k,v in signed.items() if k!='authority'}).data()
            path.write_text(canonical(body),encoding='utf-8')
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


@pytest.mark.parametrize('fault',['scorer','source_cell_drift'])
def test_complete_execution_does_not_hide_scorer_failure_or_qualification_confound(tmp_path,monkeypatch,fault):
    setup=prepare(tmp_path,monkeypatch,fault);run=invoke(setup,monkeypatch,fault);b=run.receipt.data()
    assert b['status']=='inconclusive' and b['successful_builds']==11 and b['actual_model_usage']['model_calls']==55
    assert b['actual_docker_attempts']==b['actual_scorer_calls']==22 and b['scorer_usage_unknown'] is True
    assert b['known_source_cost_units']==66 and b['source_cost_unknown'] is False
    if fault=='scorer':
        assert len(run.scores)==0 and b['failed_cells']==22 and all(c['status']=='inconclusive' for c in b['contrasts'])
    else:
        assert len(run.scores)==22 and b['failed_cells']==0
        assert b['contrasts'][0]['status']=='inconclusive' and 'qualification_semantic_drift' in b['contrasts'][0]['reason']
        assert [c['status'] for c in b['contrasts'][1:]]==['not_identifiable','estimated']


@pytest.mark.parametrize('fault',['source_rejected','mid_build_source_drift'])
def test_known_source_rejection_and_later_source_drift_keep_unused_targets(tmp_path,monkeypatch,fault):
    setup=prepare(tmp_path,monkeypatch,fault);run=invoke(setup,monkeypatch,fault);b=run.receipt.data()
    assert len(run.attempts)==22 and b['blocked_cells']==22 and b['unused_docker_opportunities']==b['unused_scorer_opportunities']==22
    assert b['source_cost_unknown'] is False and b['pruned_cells']==[]
    if fault=='source_rejected':
        assert len(setup['seen'])==7 and len(setup['calls'])==22 and b['failed_builds']==4 and b['successful_builds']==7
    else:
        assert len(setup['seen'])==1 and len(setup['calls'])==2 and b['failed_builds']==1 and b['blocked_builds']==9
