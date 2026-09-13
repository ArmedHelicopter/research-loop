"""Exact prospective TRAIN state/exploration controller and independent scorer checks.

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
from evaluation.modular.admission_prediction_exploration_scoring import issue_admission_prediction_exploration_score_input
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.admission_prediction_exploration_controller import (
    FrozenAdmissionPredictionExplorationTrainConfig, compile_admission_prediction_exploration_train_panels, run_admission_prediction_exploration_train_panels, _arms)
from research_loop.modular.admission_prediction_exploration_driver import DESIGNS, SLOTS, freeze_material, verify_admission_prediction_exploration_cell
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.combination_train_controller import _ANALYSIS
from research_loop.ontology import ContractError, canonical
from test_remaining_prospective_train_sources import prepared_primary, changed_source_config, corrupt_export
from test_primary_prospective_exporter import events
from test_lineage_combination_controller import EXECUTION, SCORER
from test_admission_combination import sources
from test_modular_train_controller import model_port, FINAL, SCENARIO
from test_modular_combination_train_controller import ANALYSIS
from test_state_retrieval_combination_driver import state_material, provenance, IMAGE
from research_loop.modular.exploration_scheduler_combination import FrozenExplorationSchedulerMaterial
from test_modular_combination_benchmark_driver import _rewrite_trace, _plan
from research_loop.modular.admission_prediction_exploration_contrasts import component_policy
from research_loop.modular.m4_m5_useful_controls import PLAN_INSTRUCTION
from test_scorer_process import _store, _command


def job_material(task, state, fault=None):
    header = "import csv,json\nwith open('/input/public_csv',newline='') as f: xs=[float(r['x']) for r in csv.DictReader(f)]\n"
    # Common summary, ordinary dispersion, and restricted sensitivity probe all
    # perform useful computations on the same original public CSV.
    bodies = ["print(json.dumps({'mean':sum(xs)/len(xs)}))",
        "print(json.dumps({'variance':sum((x-sum(xs)/len(xs))**2 for x in xs)/len(xs)}))",
        "print(json.dumps({'range':max(xs)-min(xs)}))"]
    ids = [hashlib.sha256(('literal-public-analysis-'+str(i)).encode()).hexdigest() for i in range(3)]
    jobs = [{'id': ids[i], 'purpose': 'probe' if i == 2 else 'main',
        'program': "raise RuntimeError('original phase failure')" if fault == 'phase' else header+body,
        'dependencies': [] if i == 0 else [ids[0]], 'resources': [hashlib.sha256(b'shared-public-csv').hexdigest()],
        'cost_units': 1} for i,body in enumerate(bodies)]
    return FrozenExplorationSchedulerMaterial(FrozenRecord.from_dict({'schema':'exploration-scheduler-material-v1',
        'identity': task.identity.data(), 'task_digest': task.content_hash,
        'public_artifacts': state.data()['public_artifacts'], 'context_budget_bytes':state.data()['context_budget_bytes'], 'jobs':jobs}))


def model(seen):
    def respond(request):
        b=request.data();seen.append(b);context=b['module_context']
        assert all(marker not in request.encoded for marker in ('"enabled"','"arm_id"','"policy_digest"',
            'qualification_observations','triple:M1','PRIVATE-REFERENCE-SENTINEL'))
        if b['slot']=='proposal':
            observed=[next(iter(v['content'].values())) for v in context['state_projection']['observations']]
            proposal=_plan()
            for h in proposal['branches']:
                h['intervention']=str(sum(observed)/len(observed))
                if b['instruction']!=PLAN_INSTRUCTION:h['predictions'][0]['direction']='increase'
            return FrozenRecord.from_dict(proposal)
        joint=context['joint_mechanism'];mechanism=joint['mechanism']
        if b['slot']=='analysis_program':
            observations=[next(iter(v['content'].values())) for v in mechanism['state_projection']['observations']]
            proposal=mechanism['proposal'];directions=[p['direction'] for h in proposal['branches'] for p in h['predictions']]
            weight=sum({'increase':1,'decrease':-1,'unchanged':0}[v] for v in directions)
            proposed=[float(h['intervention']) for h in proposal['branches']]
            phase_values=[json.loads(o['stdout']) for o in joint['exploration']['observations']]
            program="import csv,json\nwith open('/input/public_csv',newline='') as f: xs=[float(r['x']) for r in csv.DictReader(f)]\nobservations="+repr(observations)+"\nproposed="+repr(proposed)+"\nweight="+repr(weight)+"\nphase="+repr(phase_values)+"\nprint(json.dumps({'mean':sum(xs)/len(xs),'phase':phase,'observations':observations,'proposed':proposed,'adjusted':10*sum(observations)/len(observations)+sum(proposed)+weight-sum(next(iter(v.values())) for v in phase)},sort_keys=True))"
            return FrozenRecord.from_dict({'analysis':'Compute public state, proposed predictions and selected auxiliary observations.','program':program})
        return FrozenRecord.from_dict({'objective_digest':context['required_objective_digest'],'outcome':'unknown',
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
        if pair=='triple:M1+M4+M7' else provenance(calls,'unknown' if fault=='source_exception' else None)) for pair in DESIGNS}
    materials={}
    for pair in DESIGNS:
        materials[pair]={}
        for packet in packets:
            state=state_material(packet.task,packet.csv_path,pair=='triple:M1+M4+M7')
            materials[pair][packet.task.content_hash]=freeze_material(packet.task,state,job_material(packet.task,state,fault)).data()
    package=CandidatePackage.create(parent_digest=None,manifest=TrainingManifest.freeze([p.task.identity for p in packets]),
        changes={'prompt':{'instructions':'Analyze the supplied public training observations.'}},search_cost=0)
    store,handles,manifest_sha=_store(root,{'tasks':{p.task.content_hash:p.task for p in packets}})
    b={'schema':'admission-prediction-exploration-combination-train-config-v2','export_mode':'primary_prospective','domain':'train',
        'stage':'synthetic-prospective-triple147','item_ids':[i.token for i in selected],
        'task_bindings':{i.token:{'identity':p.task.identity.data(),'task_digest':p.task.content_hash,
            'csv_sha256':hashlib.sha256(p.csv_path.read_bytes()).hexdigest(),'csv_byte_count':p.csv_path.stat().st_size}
            for i,p in zip(selected,packets,strict=True)},'baseline_digest':'a'*64,
        'packages_by_arm':{a:package.record.data() for a in _arms('a'*64)},
        'scorer':ScorerConfig.create(benchmark='core_pair',evaluator_id='synthetic-primary',version='v1',
            rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest()).record.data(),
        'scorer_handle_bindings':{k:hashlib.sha256(v.encode()).hexdigest() for k,v in handles.items()},
        'acceptance_criteria':{'contrast_analysis':_ANALYSIS,'factorial_components':component_policy().data()},'replicates':['r1'],'model':'gpt-5.6-luna','effort':'low',
        'materials_by_pair':materials,'source_verifier_bindings':{p:v.binding().data() for p,v in verifiers.items()},
        'objective':{'purpose':'Analyze public TRAIN measurements with frozen module context.'},
        'image':IMAGE,'timeout_seconds':20,'max_calls':48,'max_tokens':1000,
        'schemas':{'proposal':SCENARIO,'analysis_program':ANALYSIS,'final_answer':FINAL},
        'allocation':{'model_slots_per_cell':list(SLOTS),'docker_attempts_per_cell':3,
            'auxiliary_docker_attempts_per_cell':2,'solver_docker_attempts_per_cell':1,
            'scorer_calls_per_cell':1,'scorer_call_limit':16,'scorer_token_accounting':'transport_not_provided',
            'source_calls_per_cell':2,'phase_cost_units_per_cell':2,'phase_job_limit':2,'phase_policy':'fifo','context_budget_bytes':24000}}
    config=FrozenAdmissionPredictionExplorationTrainConfig(FrozenRecord.from_dict(b)); compiled=compile_admission_prediction_exploration_train_panels(config,packets)
    (root/'frozen-config.json').write_text(config.record.encoded+'\n',encoding='utf-8')
    return dict(root=root,exporter=exporter,selected=selected,all_items=all_items,packets=packets,
        config=config,compiled=compiled,verifiers=verifiers,calls=calls,
        store=store,handles=handles,manifest_sha=manifest_sha)


def services(setup, stack, scorer_fault=False):
    root=setup['root'];b=setup['config'].data();rubric=ScorerConfig(FrozenRecord.from_dict(b['scorer']))
    (root/'execution.key').write_bytes(EXECUTION.key);(root/'score.key').write_bytes(SCORER.key)
    clients={}
    for n,panel in enumerate(setup['compiled'].panels):
        server={'schema':'admission-prediction-exploration-scorer-process-config-v1',
            'panel':serialize_combination_panel(panel,admission_prediction_exploration=True),'scorer_config':rubric.record.data(),
            'scorer_config_digest':rubric.digest,'train_reference_store':{'root':str(setup['store'].resolve()),
                'manifest_sha256':setup['manifest_sha'],'inventory_digest':panel.cells[0].identity.dataset_version,'split_digest':panel.split_digest},
            'task_handles':setup['handles'],'execution_authority_key_files':{EXECUTION.authority_id:str(root/'execution.key')},
            'scorer_authority':{'id':SCORER.authority_id,'key_file':str(root/'score.key')},
            'evaluator':{'synthetic_mode':'fail' if scorer_fault else 'normal'}}
        path=root/f'server-{n}.json';path.write_text(canonical(server),encoding='utf-8')
        command=_command(path,root/f'worker-{n}.jsonl');command[1]=str((Path(__file__).parent/'helpers/admission_prediction_exploration_scorer_process_helper.py').resolve())
        client=CombinationScorerProcessClient(panel=panel,config=rubric,admission_prediction_exploration=True,command=command,
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
        assert len(frozen['cells'])==16 and len(frozen['panels'])==1
        assert [(p['digest'],p['cells']) for p in frozen['panels']]==[(p.digest,[c.data() for c in p.cells]) for p in setup['compiled'].panels]
        assert 'PRIVATE-REFERENCE-SENTINEL' not in request.encoded
        if not seen and fault=='poison':
            seen.append(request.data());raise RuntimeError('synthetic unknown model usage')
        return respond(request)
    port=model_port(root/'port',monkeypatch,max_calls=b['max_calls'],max_tokens=b['max_tokens'],schemas=b['schemas'],response_factory=response)
    def forbidden(*args,**kwargs):raise AssertionError('legacy exporter was invoked')
    monkeypatch.setattr(TrainPacketExporter,'export',forbidden)
    exporter=setup['exporter']
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
            with pytest.raises((ContractError,CustodyError)):run_admission_prediction_exploration_train_panels(config,**kwargs)
            assert not seen and not setup['calls'] and not port.ledger['calls']
            assert not list((root/'run').glob('cells/*/runtime/analysis-1.py')) and not list(root.glob('worker-*.jsonl'))
            return
        result=run_admission_prediction_exploration_train_panels(config,**kwargs)
    return result,port,seen


@pytest.fixture(scope='module')
def grid(tmp_path_factory):
    setup=prepare(tmp_path_factory.mktemp('triple147-controller'))
    with pytest.MonkeyPatch.context() as patch: result,port,seen=invoke(setup,patch)
    return setup,result,port,seen


def replay_args(setup,result,executed):
    panel=next(p for p in result.compiled.panels if executed.cell in p.cells)
    packet=next(p for p in result.compiled.packets if p.task.content_hash==executed.cell.task_digest)
    return dict(panel=panel,task=packet.task,scenario=result.compiled.scenarios[executed.cell.key],
        package=result.compiled.packages[executed.cell.runtime_arm.content_hash],material=result.compiled.materials[panel.obligation_id][executed.cell.task_digest],
        source_verifier=setup['verifiers'][panel.obligation_id],
        public_inputs={'public_csv':packet.csv_path},broker=DockerExecutionBroker([setup['root']/'export',setup['root']/'run']))


def test_full16_prospective_cells_docker_and_independent_primary_scores(grid):
    setup,result,port,seen=grid
    assert len(result.scores)==len(result.results)==len(result.attempts)==16,[a.data() for a in result.attempts if a.data()['status']!='succeeded']
    assert len(seen)==len(port.ledger['calls'])==48
    assert len(setup['calls'])==32
    b=result.receipt.data();assert b['status']=='complete_train_engineering'
    assert b['actual_docker_attempts']==48 and b['actual_scorer_calls']==16
    assert b['source_calls']==32 and b['auxiliary_docker_attempts']==32 and b['pruned_cells']==[]
    assert b['validation_opened'] is b['scientific_effectiveness_proven'] is False
    assert [e['event'] for e in events(setup['exporter'])]==['export_reserved','sources_verified','exposure_reserved','exposure_reserved','export_completed']
    for attempt,executed in zip(result.attempts,result.results,strict=True):
        row=attempt.data();assert row['status']=='succeeded'
        assert len(row['source_verification']['calls'])==2
        assert row['docker_attempts']==3 and row['scorer_calls']==1 and row['auxiliary_docker_attempts']==2
        assert row['execution_receipt']['record']['argv'][-3:]==[IMAGE,'python3','/task/analysis.py']
        phase=executed.phase.data()
        assert phase['actual_docker_attempts']==phase['execution_units_reserved']==2
        assert phase['peak_dispatches']==1 and phase['peak_leases']==0 and phase['remaining_leases']==phase['residual_containers']==[]
        assert phase['completion_order']==phase['fifo_order']
        assert (phase['selection']['permit'] is not None)==('M7' in executed.cell.runtime_arm.data()['enabled'])
        assert len(phase['public']['observations'])==2 and all(o['status']=='succeeded' for o in phase['public']['observations'])
        verify_admission_prediction_exploration_cell(executed,**replay_args(setup,result,executed))
        assert set(executed.cell.runtime_arm.data()['enabled']) <= {'M1','M4','M7'}
        assert (executed.mechanism.data()['prediction_plan'] is not None)==('M4' in executed.cell.runtime_arm.data()['enabled'])
        assert bool((executed.runtime.trace_path.parent/'predictions.jsonl').read_text().strip())==('M4' in executed.cell.runtime_arm.data()['enabled'])
    for pair in DESIGNS:
        for benchmark in ('blade','discoverybench'):
            values=[json.loads(r.solver.execution.record.data()['stdout'])['adjusted'] for r in result.results
                if r.cell.coverage_id==pair and r.cell.identity.benchmark==benchmark]
            assert len(set(values))==8
    for n in range(1):
        rows=[json.loads(l) for l in (setup['root']/f'worker-{n}.jsonl').read_text(encoding='utf-8').splitlines()]
        assert [r['status'] for r in rows]==['reserved','succeeded']*16
        assert 'PRIVATE-REFERENCE-SENTINEL' not in (setup['root']/f'client-{n}.jsonl').read_text(encoding='utf-8')


@pytest.mark.parametrize('fault',['both','wrong_port','roots','split','validation','swapped_tokens','export_receipt','completion_anchor','source','material'])
def test_source_faults_precede_downstream_io(tmp_path,monkeypatch,fault):invoke(prepare(tmp_path),monkeypatch,fault)


def test_poisoned_ledger_preserves_all16_opportunities(tmp_path,monkeypatch):
    setup=prepare(tmp_path);result,port,seen=invoke(setup,monkeypatch,'poison');b=result.receipt.data()
    assert len(result.attempts)==16 and b['failed_cells']==1 and b['blocked_cells']==15
    assert len(seen)==len(port.ledger['calls'])==1 and port.ledger['usage_incomplete'] is True
    assert b['actual_docker_attempts']==0 and b['actual_scorer_calls']==0
    assert b['unused_model_opportunities']==47 and b['source_calls']==2 and b['auxiliary_docker_attempts']==0
    assert b['pruned_cells']==[] and all(c.data()['status']=='inconclusive' for c in result.contrasts)


@pytest.mark.parametrize('fault',['source_exception','source_unknown','phase','scorer'])
def test_original_failures_keep_all16_denominators(tmp_path,monkeypatch,fault):
    setup=prepare(tmp_path,fault);result,port,seen=invoke(setup,monkeypatch,fault);b=result.receipt.data()
    assert len(result.attempts)==len(result.results)==16 and b['failed_cells']==16 and b['pruned_cells']==[]
    assert b['source_calls']==32 and b['actual_docker_attempts']=={'source_exception':0,'source_unknown':0,'phase':32,'scorer':48}[fault]
    assert len(seen)==len(port.ledger['calls'])==({'scorer':48,'phase':16}.get(fault,0))
    assert b['actual_scorer_calls']==(16 if fault=='scorer' else 0)
    if fault=='phase':
        for executed in result.results:verify_admission_prediction_exploration_cell(executed,**replay_args(setup,result,executed))
    assert all(c.data()['status']=='inconclusive' for c in result.contrasts)


def test_m1_semantic_drift_preserves_scores_but_blocks_contrast(tmp_path,monkeypatch):
    setup=prepare(tmp_path,'source_cell_drift');result,port,seen=invoke(setup,monkeypatch)
    assert len(result.scores)==len(result.attempts)==16 and len(seen)==48
    contrasts={p.obligation_id:c.data() for p,c in zip(result.compiled.panels,result.contrasts,strict=True)}
    assert contrasts['triple:M1+M4+M7']['status']=='inconclusive'
    assert contrasts['triple:M1+M4+M7']['reason']=='admission_qualification_semantic_drift'
    assert all(contrasts[p]['status']=='estimated' for p in DESIGNS if p!='triple:M1+M4+M7')
    assert result.receipt.data()['status']=='inconclusive'
    assert all(v['status']=='inconclusive' for v in result.contrasts[0].data()['components'].values())


@pytest.mark.parametrize('fault',['state_journal','claims_journal','request_context','program','state_signature',
    'literal_job','phase_input','phase_budget','phase_permit','phase_return','phase_order','phase_binding','operation_order'])
def test_persistent_replay_and_score_issuance_reject_forgeries(grid,fault):
    setup,result,*_=grid;mutations=[]
    for executed in result.results:
        if executed.cell.identity.benchmark!='blade' or executed.cell.arm_id!='111':continue
        args=replay_args(setup,result,executed);path=executed.runtime.trace_path;before=path.read_bytes();extra=None;saved=None
        def mutate(rows):
            if fault=='request_context':
                request=next(e for e in rows if e['stage']=='model_request' and e['data']['request']['slot']=='analysis_program')['data'];old=request['request_digest']
                request['request']['module_context']['joint_mechanism']['mechanism']['state_projection']={}
                request['request_digest']=FrozenRecord.from_dict(request['request']).content_hash
                for row in rows:
                    if row['stage']=='model_response' and row['data']['request_digest']==old:row['data']['request_digest']=request['request_digest']
            elif fault=='phase_binding':next(e for e in rows if e['stage']=='admission_prediction_exploration_phase')['data']['phase_digest']='f'*64
            elif fault=='operation_order':
                first=next(e for e in rows if e['stage']=='admission_prediction_transition');rows.remove(first)
                rows.insert(next(i for i,e in enumerate(rows) if e['stage']=='admission_prediction_exploration_phase_start')+1,first)
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
                    else:body['selection']['permit']=None
                    extra.write_text(canonical(body),encoding='utf-8')
                elif fault=='phase_return':
                    extra=next(p for p in phase.glob('*.json') if json.loads(p.read_bytes()).get('schema')=='exploration-scheduler-job-return-v1')
                    saved=extra.read_bytes();body=json.loads(saved);body['snapshot_digest']='e'*64;extra.write_text(canonical(body),encoding='utf-8')
                else:
                    extra=phase/'events.jsonl';saved=extra.read_bytes();body=[json.loads(x) for x in saved.decode().splitlines()]
                    next(e for e in body if e['kind']=='merge')['kind']='complete'
                    extra.write_text(''.join(canonical(e)+'\n' for e in body),encoding='utf-8')
                forged=executed
            with pytest.raises((ContractError,ValueError)):verify_admission_prediction_exploration_cell(forged,**args)
            with pytest.raises((ContractError,ValueError)):issue_admission_prediction_exploration_score_input(authority=EXECUTION,result=forged,**args)
            mutations.append({'pair':executed.cell.coverage_id,'fault':fault})
        finally:
            path.write_bytes(before)
            if extra is not None:extra.write_bytes(saved)
        verify_admission_prediction_exploration_cell(executed,**args)
    assert {m['pair'] for m in mutations}==set(DESIGNS)
    (setup['root']/('replay-'+fault+'.json')).write_text(canonical(mutations),encoding='utf-8')


@pytest.mark.parametrize('flags',[{}, {'admission_prediction_exploration':1},{'admission_prediction_exploration':'true'},
    {'admission_prediction_exploration':True,'state_prediction':True},{'admission_prediction_exploration':True,'state_retrieval':True},{'admission_prediction_exploration':True,'state_exploration':True},{'admission_prediction_exploration':True,'state_scheduling':True},{'admission_prediction_exploration':True,'mechanism_exploration':True},{'admission_prediction_exploration':True,'mechanism_scheduling':True},{'admission_prediction_exploration':True,'lineage':True},
    {'admission_prediction_exploration':True,'retrieval_review':True},{'admission_prediction_exploration':True,'admission':True},
    {'admission_prediction_exploration':True,'exploration_scheduler':True},
    {'mechanism_improvement':True},{'admission_prediction_exploration':True,'mechanism_improvement':True},
    {'state_improvement':True},{'admission_prediction_exploration':True,'state_improvement':True}])
def test_strict_scorer_family_scope_no_default_relaxation(grid,flags):
    setup,*_=grid
    with pytest.raises(ContractError):serialize_combination_panel(setup['compiled'].panels[0],**flags)


def test_roundtrip_each_pair_and_reject_schema_substitution(grid):
    setup,*_=grid
    for n,panel in enumerate(setup['compiled'].panels):
        body=serialize_combination_panel(panel,admission_prediction_exploration=True)
        assert parse_combination_panel(body,admission_prediction_exploration=True)==panel
        server=json.loads((setup['root']/f'server-{n}.json').read_text(encoding='utf-8'))
        assert parse_server_config(server).panel==panel
        server['schema']='state-prediction-scorer-process-config-v1'
        with pytest.raises(ContractError):parse_server_config(server)


@pytest.mark.parametrize('fault',['wrong_state','wrong_job_task','job_cost_bool','job_label','job_dependency','job_provenance',
    'allocation','context_budget','source_keys','extra_pair','validation_domain','legacy_schema','model_calls'])
def test_closed_config_rejects_malformed_original_material_before_io(grid,fault):
    setup,*_=grid;b=setup['config'].data();m=next(iter(b['materials_by_pair']['triple:M1+M4+M7'].values()))
    if fault=='wrong_state':m['state_kind']='lineage'
    elif fault=='wrong_job_task':m['exploration']['task_digest']='f'*64
    elif fault=='job_cost_bool':m['exploration']['jobs'][0]['cost_units']=True
    elif fault=='job_label':m['exploration']['jobs'][0]['program']="print('M7 on')"
    elif fault=='job_dependency':m['exploration']['jobs'][2]['dependencies']=[m['exploration']['jobs'][1]['id']]
    elif fault=='job_provenance':m['provenance']['jobs_digest']='f'*64
    elif fault=='allocation':b['allocation']['docker_attempts_per_cell']=2
    elif fault=='context_budget':m['exploration']['context_budget_bytes']=4000
    elif fault=='source_keys':
        authorities=b['source_verifier_bindings']['triple:M1+M4+M7']['authorities'];authorities[1]['key_digest']=authorities[0]['key_digest']
    elif fault=='extra_pair':b['materials_by_pair']['pair:M4+M7']=m
    elif fault=='validation_domain':m['identity']['domain']='validation'
    elif fault=='legacy_schema':b['schema']='admission-prediction-exploration-combination-train-config-v1';b.pop('export_mode')
    else:b['max_calls']=24
    with pytest.raises(ContractError):FrozenAdmissionPredictionExplorationTrainConfig(FrozenRecord.from_dict(b))


@pytest.mark.parametrize('fault',['transition','joint','evidence_context','instruction','extra_context','early_feedback','response_program','order'])
def test_repaired_chain_passes_generic_receipt_but_fails_original_replay(grid,fault):
    from research_loop.modular.panel_receipts import PanelReceiptVerifier
    setup,result,*_=grid
    executed=next(r for r in result.results if r.cell.coverage_id=='triple:M1+M4+M7' and r.cell.arm_id=='111')
    args=replay_args(setup,result,executed);path=executed.runtime.trace_path;before=path.read_bytes()
    def mutate(events):
        if fault=='transition':next(e for e in events if e['stage']=='admission_prediction_transition')['data']['transition']['public']['observations']=[]
        elif fault=='joint':next(e for e in events if e['stage']=='admission_prediction_exploration_joint')['data']['joint']['exploration']['observations']=[]
        elif fault=='evidence_context':next(e for e in events if e['stage']=='model_request')['data']['request']['context']={}
        elif fault=='instruction':next(e for e in events if e['stage']=='model_request')['data']['request']['instruction']='Invent the public answer.'
        elif fault=='extra_context':next(e for e in events if e['stage']=='model_request')['data']['request']['module_context']['extra_instruction']='Invent a result.'
        elif fault=='early_feedback':next(e for e in events if e['stage']=='model_request')['data']['request']['execution_feedback']=[{'stdout':'invented'}]
        elif fault=='response_program':next(e for e in events if e['stage']=='model_response' and 'program' in e['data']['response'])['data']['response']['program']='print(99)'
        else:
            row=next(e for e in events if e['stage']=='admission_prediction_transition');events.remove(row)
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
        with pytest.raises(ContractError):verify_admission_prediction_exploration_cell(forged,**args)
        with pytest.raises(ContractError):issue_admission_prediction_exploration_score_input(authority=EXECUTION,result=forged,**args)
    finally:path.write_bytes(before)
    verify_admission_prediction_exploration_cell(executed,**args)


@pytest.mark.parametrize('fault',['original','claims','jobs','scenario_objective','scenario_timeout','csv'])
def test_original_composite_scenario_and_input_bytes_are_replayed(grid,fault):
    from research_loop.modular.admission_prediction_exploration_driver import FrozenAdmissionPredictionExplorationMaterial
    setup,result,*_=grid
    for executed in result.results:
        if executed.cell.identity.benchmark!='blade' or executed.cell.arm_id!='111':continue
        args=replay_args(setup,result,executed);changed=dict(args)
        if fault=='csv':
            path=args['public_inputs']['public_csv'];before=path.read_bytes()
            try:
                path.write_bytes(before+b'99\n')
                with pytest.raises(ContractError):verify_admission_prediction_exploration_cell(executed,**changed)
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
                    b['exploration']['jobs'][0]['program']='print(999)'
                    b['provenance']['jobs_digest']=FrozenRecord.from_dict(b['exploration']).content_hash
                changed['material']=FrozenAdmissionPredictionExplorationMaterial(FrozenRecord.from_dict(b))
            with pytest.raises(ContractError):verify_admission_prediction_exploration_cell(executed,**changed)
            with pytest.raises(ContractError):issue_admission_prediction_exploration_score_input(authority=EXECUTION,result=executed,**changed)
        verify_admission_prediction_exploration_cell(executed,**args)


@pytest.mark.parametrize('field,value',[('--network','host'),('--memory','4g'),('--cpus','8.0'),('--user','0:0')])
def test_rehashed_solver_execution_cannot_relax_docker_limits(grid,field,value):
    from research_loop.modular.panel_receipts import PanelReceiptVerifier
    setup,result,*_=grid
    executed=next(r for r in result.results if r.cell.coverage_id=='triple:M1+M4+M7' and r.cell.arm_id=='111')
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
        with pytest.raises(ContractError,match='Docker limits'):verify_admission_prediction_exploration_cell(forged,**args)
        with pytest.raises(ContractError):issue_admission_prediction_exploration_score_input(authority=EXECUTION,result=forged,**args)
    finally:path.write_bytes(before)
    verify_admission_prediction_exploration_cell(executed,**args)


def test_seven_component_estimates_are_descriptive_with_unavailable_intervals(grid):
    setup,result,*_=grid;contrast=result.contrasts[0].data()
    expected={'M1','M4','M7','M1+M4','M1+M7','M4+M7','M1+M4+M7'}
    assert set(contrast['components'])==expected and contrast['status']=='estimated'
    for item in contrast['components'].values():
        assert item['status']=='estimated'
        for estimate in item['benchmark_estimates'].values():
            assert estimate['mean']==0 and estimate['independent_groups']==1
            assert estimate['confidence_interval']=={'status':'not_estimable','reason':'insufficient_independent_groups','level':0.95,'lower':None,'upper':None}
    assert contrast['highest_order']['status']=='estimated'
    assert setup['config'].data()['acceptance_criteria']['factorial_components']==component_policy().data()


def test_component_contrast_normalization_and_missing_arm_identifiability(grid):
    policy=component_policy().data();values={}
    for arm in policy['coefficients']['M1']:
        a,b,c=[2*int(bit)-1 for bit in arm]
        values[arm]=100+2*a+3*b+5*c+7*a*b+11*a*c+13*b*c+17*a*b*c
    observed={name:sum(weights[k]*v for k,v in values.items()) for name,weights in policy['coefficients'].items()}
    assert observed=={'M1':4,'M4':6,'M7':10,'M1+M4':28,'M1+M7':44,'M4+M7':52,'M1+M4+M7':136}
    from research_loop.modular.admission_prediction_exploration_contrasts import estimate_components
    from research_loop.modular.combination_panels import CombinationPanelVerifier
    setup,result,*_=grid;panel=result.compiled.panels[0]
    with pytest.raises(ContractError):estimate_components(panel,runtime=[r.runtime for r in result.results[:-1]],
        scorer_receipts=result.scores[:-1],verifier=CombinationPanelVerifier(scorer_verifier=lambda *a:None))


def test_unknown_phase_reservations_retain_all16_and_never_score(tmp_path,monkeypatch):
    def unknown(*args,**kwargs):raise RuntimeError('synthetic broker outcome unavailable')
    monkeypatch.setattr(DockerExecutionBroker,'execute',unknown)
    setup=prepare(tmp_path);result,port,seen=invoke(setup,monkeypatch);b=result.receipt.data()
    assert b['failed_cells']==16 and b['actual_docker_attempts']==b['phase_unknown_cost_attempts']==32
    assert len(seen)==16 and b['source_calls']==32 and b['actual_scorer_calls']==0
    assert b['unused_model_opportunities']==32 and b['unused_docker_opportunities']==16 and b['unused_scorer_opportunities']==16
    for executed in result.results:verify_admission_prediction_exploration_cell(executed,**replay_args(setup,result,executed))
    assert all(v['status']=='inconclusive' for v in result.contrasts[0].data()['components'].values())


@pytest.mark.parametrize('fault',['proposal_state','proposal_response','registry','source_binding','plan_order'])
def test_rehashed_admission_prediction_seam_passes_generic_first(grid,fault):
    from research_loop.modular.panel_receipts import PanelReceiptVerifier
    setup,result,*_=grid;executed=next(r for r in result.results if r.cell.arm_id=='111')
    args=replay_args(setup,result,executed);path=executed.runtime.trace_path;before=path.read_bytes()
    def mutate(rows):
        if fault=='proposal_state':next(e for e in rows if e['stage']=='model_request')['data']['request']['module_context']['state_projection']={}
        elif fault=='proposal_response':next(e for e in rows if e['stage']=='model_response')['data']['response']['branches'][0]['mechanism']='Forged explanation.'
        elif fault=='registry':next(e for e in rows if e['stage']=='admission_prediction_plan')['data']['registered_plan']=None
        elif fault=='source_binding':next(e for e in rows if e['stage']=='admission_prediction_exploration_source')['data']['source_sha256']='f'*64
        else:
            row=next(e for e in rows if e['stage']=='admission_prediction_plan');rows.remove(row)
            rows.insert(next(i for i,e in enumerate(rows) if e['stage']=='admission_prediction_exploration_phase_start')+1,row)
        for e in rows:
            if e['stage']=='model_request':
                old=e['data']['request_digest'];e['data']['request_digest']=FrozenRecord.from_dict(e['data']['request']).content_hash
                for other in rows:
                    if other['stage']=='model_response' and other['data']['request_digest']==old:other['data']['request_digest']=e['data']['request_digest']
    try:
        tail=_rewrite_trace(path,mutate);rows=[FrozenRecord(line).data() for line in path.read_text().splitlines()]
        output=FrozenRecord.from_dict({'responses':[e['data']['response'] for e in rows if e['stage']=='model_response'],'terminal':rows[-1]['data']}).content_hash
        forged=replace(executed,runtime=replace(executed.runtime,trace_digest=tail,output_digest=output))
        PanelReceiptVerifier()._verify_runtime(forged.runtime,forged.cell)
        with pytest.raises(ContractError):verify_admission_prediction_exploration_cell(forged,**args)
        with pytest.raises(ContractError):issue_admission_prediction_exploration_score_input(authority=EXECUTION,result=forged,**args)
    finally:path.write_bytes(before)
    verify_admission_prediction_exploration_cell(executed,**args)


@pytest.mark.parametrize('fault',['ordinary_off','malformed'])
def test_actual_m4_off_never_invokes_discrimination_or_registry(tmp_path,monkeypatch,fault):
    from research_loop.modular.modules.predictions import PredictionRegistry
    from research_loop.modular.admission_prediction_exploration_driver import run_admission_prediction_exploration_cell
    setup=prepare(tmp_path);panel=setup['compiled'].panels[0];cell=next(c for c in panel.cells if c.arm_id=='101')
    packet=next(p for p in setup['packets'] if p.task.content_hash==cell.task_digest)
    args=dict(panel=panel,task=packet.task,scenario=setup['compiled'].scenarios[cell.key],
        package=setup['compiled'].packages[cell.runtime_arm.content_hash],material=setup['compiled'].materials[panel.obligation_id][cell.task_digest],
        source_verifier=setup['verifiers'][panel.obligation_id],public_inputs={'public_csv':packet.csv_path},broker=DockerExecutionBroker([tmp_path]))
    def forbidden(*args,**kwargs):raise AssertionError('disabled registry was called')
    monkeypatch.setattr(PredictionRegistry,'freeze',forbidden);seen=[]
    respond=model(seen) if fault=='ordinary_off' else lambda r:FrozenRecord.from_dict({'invalid':True})
    executed=run_admission_prediction_exploration_cell(cell=cell,**args,objective=FrozenRecord.from_dict(setup['config'].data()['objective']),
        sidecar=tmp_path/'off-proof',image=IMAGE,model=respond,audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),timeout_seconds=20)
    verify_admission_prediction_exploration_cell(executed,**args)
    if fault=='ordinary_off':
        assert executed.runtime.status=='succeeded' and len(seen)==3
        assert all(h['predictions'][0]['direction']=='increase' for h in executed.mechanism.data()['proposal']['branches'])
        assert executed.mechanism.data()['prediction_plan'] is None
    else:assert executed.runtime.status=='failed' and executed.phase is None and executed.solver is None

