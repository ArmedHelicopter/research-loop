"""Exact prospective TRAIN mechanism/exploration controller and independent scorer checks.

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
from evaluation.modular.mechanism_exploration_scoring import issue_mechanism_exploration_score_input
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.mechanism_exploration_combination_controller import (
    FrozenMechanismExplorationTrainConfig, compile_mechanism_exploration_train_panels, run_mechanism_exploration_train_panels, _arms)
from research_loop.modular.mechanism_exploration_combination_driver import DESIGNS, SLOTS, KINDS, freeze_material, verify_mechanism_exploration_cell
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.combination_train_controller import _ANALYSIS
from research_loop.ontology import ContractError, canonical
from test_remaining_prospective_train_sources import prepared_primary, changed_source_config, corrupt_export
from test_primary_prospective_exporter import events
from test_lineage_combination_controller import EXECUTION, SCORER
from test_modular_train_controller import model_port, FINAL, SCENARIO, REVIEW
from test_modular_combination_train_controller import ANALYSIS
from test_state_retrieval_combination_driver import provenance, Provider, IMAGE
from research_loop.modular.exploration_scheduler_combination import FrozenExplorationSchedulerMaterial
from test_modular_combination_benchmark_driver import _rewrite_trace, _plan
from research_loop.modular.retrieval_review_combination_driver import freeze_material as freeze_retrieval
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
            'pair:M4','pair:M5','pair:M6','PRIVATE-REFERENCE-SENTINEL'))
        if b['slot']=='proposal':
            proposal=_plan()
            if b['instruction']!=PLAN_INSTRUCTION:
                for branch in proposal['branches']:branch['predictions'][0]['direction']='increase'
            return FrozenRecord.from_dict(proposal)
        if b['slot'].startswith('review_'):
            # The sequential second assessment uses its supplied earlier review.
            count=2 if context['earlier_reviews'] else 1
            return FrozenRecord.from_dict({'assessment':'concern','evidence_refs':[],
                'counterexamples':['Check public measurement '+str(i) for i in range(count)],'uncertainty':'Public observations remain unvalidated.'})
        joint=context['joint_mechanism'];mechanism=joint['mechanism']
        if b['slot']=='analysis_program':
            if mechanism['kind']=='prediction':
                useful=[p['direction'] for h in mechanism['proposal']['branches'] for p in h['predictions']]
                weight=sum({'increase':1,'decrease':-1,'unchanged':0}[v] for v in useful)
            elif mechanism['kind']=='review':
                useful=mechanism['review_responses'];weight=sum(len(v['counterexamples']) for v in useful)
            else:
                useful=mechanism['retrieval']['by_lane'];weight=sum(len(v) for v in useful.values())
                assert useful['support'] and useful['method']
            phase_values=[json.loads(o['stdout']) for o in joint['exploration']['observations']]
            program="import csv,json\nwith open('/input/public_csv',newline='') as f: xs=[float(r['x']) for r in csv.DictReader(f)]\nuseful="+repr(useful)+"\nweight="+repr(weight)+"\nphase="+repr(phase_values)+"\nprint(json.dumps({'mean':sum(xs)/len(xs),'phase':phase,'useful':useful,'adjusted':weight-sum(next(iter(v.values())) for v in phase)},sort_keys=True))"
            return FrozenRecord.from_dict({'analysis':'Compute public observations using every selected mechanism and auxiliary output.','program':program})
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
    verifiers = {pair:provenance(calls,'unknown' if fault=='source_exception' else None) for pair in DESIGNS}
    materials={}
    docs=[{'source_id':'public-source-'+str(i),'root_source_id':'public-root-'+str(i),'lane':lane,'text':text}
        for i,(lane,text) in enumerate([('support','The public values suggest a high mean.'),('counter','Check the older measurement.'),('method','Calculate the current public CSV mean.')])]
    for pair in DESIGNS:
        materials[pair]={}
        for packet in packets:
            inputs=FrozenRecord.from_dict({'context_budget_bytes':24000,'public_artifacts':[{'artifact':{
                'artifact_id':'public_csv','sha256':hashlib.sha256(packet.csv_path.read_bytes()).hexdigest(),
                'byte_count':packet.csv_path.stat().st_size},'container_path':'/input/public_csv'}]})
            kind=KINDS[pair]
            mechanism=(FrozenRecord.from_dict({'question':_plan()['question']}) if kind=='prediction' else
                FrozenRecord.from_dict(_plan()) if kind=='review' else freeze_retrieval(packet.task,docs,'Which observations distinguish the public explanations?'))
            materials[pair][packet.task.content_hash]=freeze_material(packet.task,kind,mechanism,job_material(packet.task,inputs,fault)).data()
    package=CandidatePackage.create(parent_digest=None,manifest=TrainingManifest.freeze([p.task.identity for p in packets]),
        changes={'prompt':{'instructions':'Analyze the supplied public training observations.'}},search_cost=0)
    store,handles,manifest_sha=_store(root,{'tasks':{p.task.content_hash:p.task for p in packets}})
    b={'schema':'mechanism-exploration-combination-train-config-v2','export_mode':'primary_prospective','domain':'train',
        'stage':'synthetic-prospective-mechanism-exploration','item_ids':[i.token for i in selected],
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
        'image':IMAGE,'timeout_seconds':20,'max_calls':72,'max_tokens':1000,
        'schemas':{'proposal':SCENARIO,'review_first':REVIEW,'review_second':REVIEW,'analysis_program':ANALYSIS,'final_answer':FINAL},
        'allocation':{'model_slots_by_pair':{p:list(v) for p,v in SLOTS.items()},'retrieval_calls_by_pair':{p:3 if KINDS[p]=='retrieval' else 0 for p in DESIGNS},'docker_attempts_per_cell':3,
            'auxiliary_docker_attempts_per_cell':2,'solver_docker_attempts_per_cell':1,
            'scorer_calls_per_cell':1,'scorer_call_limit':24,'scorer_token_accounting':'transport_not_provided',
            'source_calls_per_cell':2,'phase_cost_units_per_cell':2,'phase_job_limit':2,'phase_policy':'fifo','context_budget_bytes':24000}}
    config=FrozenMechanismExplorationTrainConfig(FrozenRecord.from_dict(b)); compiled=compile_mechanism_exploration_train_panels(config,packets)
    (root/'frozen-config.json').write_text(config.record.encoded+'\n',encoding='utf-8')
    return dict(root=root,exporter=exporter,selected=selected,all_items=all_items,packets=packets,
        config=config,compiled=compiled,verifiers=verifiers,calls=calls,retrieval_calls=[],
        store=store,handles=handles,manifest_sha=manifest_sha)


def services(setup, stack, scorer_fault=False):
    root=setup['root'];b=setup['config'].data();rubric=ScorerConfig(FrozenRecord.from_dict(b['scorer']))
    (root/'execution.key').write_bytes(EXECUTION.key);(root/'score.key').write_bytes(SCORER.key)
    clients={}
    for n,panel in enumerate(setup['compiled'].panels):
        server={'schema':'mechanism-exploration-scorer-process-config-v1',
            'panel':serialize_combination_panel(panel,mechanism_exploration=True),'scorer_config':rubric.record.data(),
            'scorer_config_digest':rubric.digest,'train_reference_store':{'root':str(setup['store'].resolve()),
                'manifest_sha256':setup['manifest_sha'],'inventory_digest':panel.cells[0].identity.dataset_version,'split_digest':panel.split_digest},
            'task_handles':setup['handles'],'execution_authority_key_files':{EXECUTION.authority_id:str(root/'execution.key')},
            'scorer_authority':{'id':SCORER.authority_id,'key_file':str(root/'score.key')},
            'evaluator':{'synthetic_mode':'fail' if scorer_fault else 'normal'}}
        path=root/f'server-{n}.json';path.write_text(canonical(server),encoding='utf-8')
        command=_command(path,root/f'worker-{n}.jsonl');command[1]=str((Path(__file__).parent/'helpers/mechanism_exploration_scorer_process_helper.py').resolve())
        client=CombinationScorerProcessClient(panel=panel,config=rubric,mechanism_exploration=True,command=command,
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
    kwargs=dict(custody=None,prospective_exporter=exporter,snapshot_root=Path(exporter.config['snapshot_root']),
        export_root=exporter.output_root,run_root=root/'run',model=port,audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),
        source_verifiers=setup['verifiers'],provider=Provider(setup['retrieval_calls'],fail=fault=='provider'),
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
            with pytest.raises((ContractError,CustodyError)):run_mechanism_exploration_train_panels(config,**kwargs)
            assert not seen and not setup['calls'] and not port.ledger['calls']
            assert not list((root/'run').glob('cells/*/runtime/analysis-1.py')) and not list(root.glob('worker-*.jsonl'))
            return
        result=run_mechanism_exploration_train_panels(config,**kwargs)
    return result,port,seen


@pytest.fixture(scope='module')
def grid(tmp_path_factory):
    setup=prepare(tmp_path_factory.mktemp('mechanism-exploration-controller'))
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
    assert len(seen)==len(port.ledger['calls'])==72
    assert len(setup['retrieval_calls'])==24
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
        assert phase['peak_dispatches']==1 and phase['peak_leases']==0 and phase['remaining_leases']==phase['residual_containers']==[]
        assert phase['completion_order']==phase['fifo_order']
        assert (phase['selection']['permit'] is not None)==('M7' in executed.cell.runtime_arm.data()['enabled'])
        assert len(phase['public']['observations'])==2 and all(o['status']=='succeeded' for o in phase['public']['observations'])
        verify_mechanism_exploration_cell(executed,**replay_args(setup,result,executed))
        assert 'M8' not in executed.cell.runtime_arm.data()['enabled']
        mechanism=executed.mechanism.data();runtime=executed.runtime.trace_path.parent
        if mechanism['kind']=='prediction':
            assert (mechanism['prediction_plan'] is not None)==('M4' in executed.cell.runtime_arm.data()['enabled'])
            assert bool((runtime/'predictions.jsonl').read_text().strip())==('M4' in executed.cell.runtime_arm.data()['enabled'])
        elif mechanism['kind']=='review':
            assert len(mechanism['review_responses'])==2
            assert bool((runtime/'reviews.jsonl').read_text().strip())==('M5' in executed.cell.runtime_arm.data()['enabled'])
        else:assert all(mechanism['retrieval']['by_lane'][lane] for lane in ('support','method'))
    for pair in DESIGNS:
        for benchmark in ('blade','discoverybench'):
            values=[json.loads(r.solver.execution.record.data()['stdout'])['adjusted'] for r in result.results
                if r.cell.coverage_id==pair and r.cell.identity.benchmark==benchmark]
            assert len(set(values))==4
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
    assert b['actual_docker_attempts']==0 and b['actual_scorer_calls']==0
    assert b['unused_model_opportunities']==71 and b['source_calls']==2 and b['auxiliary_docker_attempts']==0
    assert b['pruned_cells']==[] and all(c.data()['status']=='inconclusive' for c in result.contrasts)


@pytest.mark.parametrize('fault',['source_exception','phase','scorer'])
def test_original_failures_keep_all24_denominators(tmp_path,monkeypatch,fault):
    setup=prepare(tmp_path,fault);result,port,seen=invoke(setup,monkeypatch,fault);b=result.receipt.data()
    assert len(result.attempts)==len(result.results)==24 and b['failed_cells']==24 and b['pruned_cells']==[]
    assert b['source_calls']==48 and b['actual_docker_attempts']=={'source_exception':0,'phase':48,'scorer':72}[fault]
    assert len(seen)==len(port.ledger['calls'])==({'scorer':72,'phase':24}.get(fault,0))
    assert b['actual_scorer_calls']==(24 if fault=='scorer' else 0)
    if fault=='phase':
        for executed in result.results:verify_mechanism_exploration_cell(executed,**replay_args(setup,result,executed))
    assert all(c.data()['status']=='inconclusive' for c in result.contrasts)


@pytest.mark.parametrize('fault',['predictions_journal','reviews_journal','request_context','program','source_signature',
    'literal_job','phase_input','phase_budget','phase_permit','phase_return','phase_order','phase_binding','operation_order'])
def test_persistent_replay_and_score_issuance_reject_forgeries(grid,fault):
    setup,result,*_=grid;mutations=[]
    for executed in result.results:
        if executed.cell.identity.benchmark!='blade' or executed.cell.arm_id!='11':continue
        args=replay_args(setup,result,executed);path=executed.runtime.trace_path;before=path.read_bytes();extra=None;saved=None
        def mutate(rows):
            if fault=='request_context':
                request=next(e for e in rows if e['stage']=='model_request' and e['data']['request']['slot']=='analysis_program')['data'];old=request['request_digest']
                request['request']['module_context']['joint_mechanism']['mechanism']={}
                request['request_digest']=FrozenRecord.from_dict(request['request']).content_hash
                for row in rows:
                    if row['stage']=='model_response' and row['data']['request_digest']==old:row['data']['request_digest']=request['request_digest']
            elif fault=='phase_binding':next(e for e in rows if e['stage']=='mechanism_exploration_phase')['data']['phase_digest']='f'*64
            elif fault=='operation_order':
                first=next(e for e in rows if e['stage']=='mechanism_exploration_mechanism');rows.remove(first)
                rows.insert(next(i for i,e in enumerate(rows) if e['stage']=='mechanism_exploration_phase_start')+1,first)
        try:
            phase=path.parent.parent/'phase'
            if fault in ('request_context','phase_binding','operation_order'):
                tail=_rewrite_trace(path,mutate);forged=replace(executed,runtime=replace(executed.runtime,trace_digest=tail))
            else:
                if fault in ('predictions_journal','reviews_journal','program','source_signature'):
                    extra={'predictions_journal':path.parent/'predictions.jsonl','reviews_journal':path.parent/'reviews.jsonl',
                        'program':path.parent/'analysis-1.py','source_signature':path.parent.parent/'source-verification.json'}[fault]
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
            with pytest.raises((ContractError,ValueError)):verify_mechanism_exploration_cell(forged,**args)
            with pytest.raises((ContractError,ValueError)):issue_mechanism_exploration_score_input(authority=EXECUTION,result=forged,**args)
            mutations.append({'pair':executed.cell.coverage_id,'fault':fault})
        finally:
            path.write_bytes(before)
            if extra is not None:extra.write_bytes(saved)
        verify_mechanism_exploration_cell(executed,**args)
    assert {m['pair'] for m in mutations}==set(DESIGNS)
    (setup['root']/('replay-'+fault+'.json')).write_text(canonical(mutations),encoding='utf-8')


@pytest.mark.parametrize('flags',[{}, {'mechanism_exploration':1},{'mechanism_exploration':'true'},
    {'mechanism_exploration':True,'state_prediction':True},{'mechanism_exploration':True,'state_retrieval':True},{'mechanism_exploration':True,'state_exploration':True},{'mechanism_exploration':True,'state_scheduling':True},{'mechanism_exploration':True,'lineage':True},
    {'mechanism_exploration':True,'retrieval_review':True},{'mechanism_exploration':True,'admission':True},
    {'mechanism_exploration':True,'exploration_scheduler':True},
    {'mechanism_exploration':True,'state_improvement':True},{'state_improvement':True}])
def test_strict_scorer_family_scope_no_default_relaxation(grid,flags):
    setup,*_=grid
    with pytest.raises(ContractError):serialize_combination_panel(setup['compiled'].panels[0],**flags)


def test_roundtrip_each_pair_and_reject_schema_substitution(grid):
    setup,*_=grid
    for n,panel in enumerate(setup['compiled'].panels):
        body=serialize_combination_panel(panel,mechanism_exploration=True)
        assert parse_combination_panel(body,mechanism_exploration=True)==panel
        server=json.loads((setup['root']/f'server-{n}.json').read_text(encoding='utf-8'))
        assert parse_server_config(server).panel==panel
        server['schema']='state-prediction-scorer-process-config-v1'
        with pytest.raises(ContractError):parse_server_config(server)


@pytest.mark.parametrize('fault',['wrong_state','wrong_job_task','job_cost_bool','job_label','job_dependency','job_provenance',
    'allocation','context_budget','source_keys','extra_pair','validation_domain','legacy_schema','model_calls'])
def test_closed_config_rejects_malformed_original_material_before_io(grid,fault):
    setup,*_=grid;b=setup['config'].data();m=next(iter(b['materials_by_pair']['pair:M4+M7'].values()))
    if fault=='wrong_state':m['kind']='review'
    elif fault=='wrong_job_task':m['exploration']['task_digest']='f'*64
    elif fault=='job_cost_bool':m['exploration']['jobs'][0]['cost_units']=True
    elif fault=='job_label':m['exploration']['jobs'][0]['program']="print('M7 on')"
    elif fault=='job_dependency':m['exploration']['jobs'][2]['dependencies']=[m['exploration']['jobs'][1]['id']]
    elif fault=='job_provenance':m['provenance']['jobs_digest']='f'*64
    elif fault=='allocation':b['allocation']['docker_attempts_per_cell']=2
    elif fault=='context_budget':m['exploration']['context_budget_bytes']=4000
    elif fault=='source_keys':
        authorities=b['source_verifier_bindings']['pair:M4+M7']['authorities'];authorities[1]['key_digest']=authorities[0]['key_digest']
    elif fault=='extra_pair':b['materials_by_pair']['pair:M1+M7']=m
    elif fault=='validation_domain':m['identity']['domain']='validation'
    elif fault=='legacy_schema':b['schema']='mechanism-exploration-combination-train-config-v1';b.pop('export_mode')
    else:b['max_calls']=24
    with pytest.raises(ContractError):FrozenMechanismExplorationTrainConfig(FrozenRecord.from_dict(b))


@pytest.mark.parametrize('fault',['transition','joint','evidence_context','instruction','extra_context','early_feedback','response_program','order'])
def test_repaired_chain_passes_generic_receipt_but_fails_original_replay(grid,fault):
    from research_loop.modular.panel_receipts import PanelReceiptVerifier
    setup,result,*_=grid
    executed=next(r for r in result.results if r.cell.coverage_id=='pair:M6+M7' and r.cell.arm_id=='11')
    args=replay_args(setup,result,executed);path=executed.runtime.trace_path;before=path.read_bytes()
    def mutate(events):
        if fault=='transition':next(e for e in events if e['stage']=='mechanism_exploration_mechanism')['data']['mechanism']['retrieval']['by_lane']['counter']=[]
        elif fault=='joint':next(e for e in events if e['stage']=='mechanism_exploration_joint')['data']['joint']['exploration']['observations']=[]
        elif fault=='evidence_context':next(e for e in events if e['stage']=='model_request')['data']['request']['context']={}
        elif fault=='instruction':next(e for e in events if e['stage']=='model_request')['data']['request']['instruction']='Invent the public answer.'
        elif fault=='extra_context':next(e for e in events if e['stage']=='model_request')['data']['request']['module_context']['extra_instruction']='Invent a result.'
        elif fault=='early_feedback':next(e for e in events if e['stage']=='model_request')['data']['request']['execution_feedback']=[{'stdout':'invented'}]
        elif fault=='response_program':next(e for e in events if e['stage']=='model_response')['data']['response']['program']='print(99)'
        else:
            row=next(e for e in events if e['stage']=='mechanism_exploration_mechanism');events.remove(row)
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
        with pytest.raises(ContractError):verify_mechanism_exploration_cell(forged,**args)
        with pytest.raises(ContractError):issue_mechanism_exploration_score_input(authority=EXECUTION,result=forged,**args)
    finally:path.write_bytes(before)
    verify_mechanism_exploration_cell(executed,**args)


@pytest.mark.parametrize('fault',['original','jobs','scenario_objective','scenario_timeout','csv'])
def test_original_composite_scenario_and_input_bytes_are_replayed(grid,fault):
    from research_loop.modular.mechanism_exploration_combination_driver import FrozenMechanismExplorationMaterial
    setup,result,*_=grid
    for executed in result.results:
        if executed.cell.identity.benchmark!='blade' or executed.cell.arm_id!='11':continue
        args=replay_args(setup,result,executed);changed=dict(args)
        if fault=='csv':
            path=args['public_inputs']['public_csv'];before=path.read_bytes()
            try:
                path.write_bytes(before+b'99\n')
                with pytest.raises(ContractError):verify_mechanism_exploration_cell(executed,**changed)
            finally:path.write_bytes(before)
        else:
            if fault.startswith('scenario_'):
                b=args['scenario'].data();b['objective' if fault=='scenario_objective' else 'timeout_seconds']={'purpose':'other'} if fault=='scenario_objective' else 1
                changed['scenario']=FrozenRecord.from_dict(b)
            else:
                b=args['material'].data()
                if fault=='original':
                    if b['kind']=='prediction':b['mechanism']['question']='Forged public question.'
                    elif b['kind']=='review':b['mechanism']['branches'][0]['mechanism']='Forged mechanism.'
                    else:b['mechanism']['original_sources'][0]['text']='Forged original source.'
                    b['provenance']['mechanism_digest']=FrozenRecord.from_dict(b['mechanism']).content_hash
                else:
                    b['exploration']['jobs'][0]['program']='print(999)'
                    b['provenance']['jobs_digest']=FrozenRecord.from_dict(b['exploration']).content_hash
                changed['material']=FrozenMechanismExplorationMaterial(FrozenRecord.from_dict(b))
            with pytest.raises(ContractError):verify_mechanism_exploration_cell(executed,**changed)
            with pytest.raises(ContractError):issue_mechanism_exploration_score_input(authority=EXECUTION,result=executed,**changed)
        verify_mechanism_exploration_cell(executed,**args)


@pytest.mark.parametrize('field,value',[('--network','host'),('--memory','4g'),('--cpus','8.0'),('--user','0:0')])
def test_rehashed_solver_execution_cannot_relax_docker_limits(grid,field,value):
    from research_loop.modular.panel_receipts import PanelReceiptVerifier
    setup,result,*_=grid
    executed=next(r for r in result.results if r.cell.coverage_id=='pair:M6+M7' and r.cell.arm_id=='11')
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
        with pytest.raises(ContractError,match='Docker limits'):verify_mechanism_exploration_cell(forged,**args)
        with pytest.raises(ContractError):issue_mechanism_exploration_score_input(authority=EXECUTION,result=forged,**args)
    finally:path.write_bytes(before)
    verify_mechanism_exploration_cell(executed,**args)


def test_partial_provider_failure_preserves_pair_denominators(tmp_path,monkeypatch):
    setup=prepare(tmp_path);result,port,seen=invoke(setup,monkeypatch,'provider');b=result.receipt.data()
    assert len(result.results)==24 and b['failed_cells']==8 and b['scored_cells']==16
    assert len(seen)==56 and b['actual_docker_attempts']==48 and b['actual_scorer_calls']==16
    assert b['source_calls']==48 and b['retrieval_calls']==len(setup['retrieval_calls'])==8
    assert b['unused_retrieval_opportunities']==16 and b['unused_model_opportunities']==16
    assert b['unused_docker_opportunities']==24 and b['pruned_cells']==[]
    for row,executed in zip(result.attempts,result.results,strict=True):
        if executed.cell.coverage_id=='pair:M6+M7':
            assert row.data()['retrieval_failures'][0]['verified_external_cost']=={'units':None,'status':'unknown'}
            verify_mechanism_exploration_cell(executed,**replay_args(setup,result,executed))
    assert result.contrasts[-1].data()['status']=='inconclusive'


@pytest.mark.parametrize('pair,fault',[
    ('pair:M4+M7','proposal_response'),('pair:M4+M7','proposal_instruction'),('pair:M4+M7','registry'),
    ('pair:M5+M7','earlier_review'),('pair:M5+M7','review_response'),('pair:M5+M7','review_barrier'),
    ('pair:M6+M7','retrieval_item'),('pair:M6+M7','retrieval_budget'),('pair:M6+M7','retrieval_query')])
def test_rehashed_actual_mechanism_forgery_passes_generic_but_not_score_gate(grid,pair,fault):
    from research_loop.modular.panel_receipts import PanelReceiptVerifier
    setup,result,*_=grid
    executed=next(r for r in result.results if r.cell.coverage_id==pair and r.cell.arm_id=='11')
    path=executed.runtime.trace_path;before=path.read_bytes();args=replay_args(setup,result,executed)
    def mutate(rows):
        if fault=='proposal_response':next(e for e in rows if e['stage']=='model_response')['data']['response']['branches'][0]['mechanism']='Fabricated public explanation.'
        elif fault=='proposal_instruction':next(e for e in rows if e['stage']=='model_request')['data']['request']['instruction']='Skip discriminating predictions.'
        elif fault=='registry':next(e for e in rows if e['stage']=='mechanism_prediction')['data']['registered_plan']=None
        elif fault=='earlier_review':
            r=next(e for e in rows if e['stage']=='model_request' and e['data']['request']['slot']=='review_second')
            r['data']['request']['module_context']['earlier_reviews']=[{'assessment':'leaked'}]
        elif fault=='review_response':next(e for e in rows if e['stage']=='model_response')['data']['response']['counterexamples']=[]
        elif fault=='review_barrier':next(e for e in rows if e['stage']=='mechanism_review_submission')['data']['barrier_open']=True
        elif fault=='retrieval_item':next(e for e in rows if e['stage']=='q8_retrieval_item')['data']['source_digest']='f'*64
        elif fault=='retrieval_budget':next(e for e in rows if e['stage']=='q8_retrieval_budget')['data']['provider_calls']=2
        else:
            q=next(e for e in rows if e['stage']=='q8_retrieval_request')['data'];q['query']['question']='Other question';q['query_digest']=FrozenRecord.from_dict(q['query']).content_hash
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
        with pytest.raises(ContractError):verify_mechanism_exploration_cell(forged,**args)
        with pytest.raises(ContractError):issue_mechanism_exploration_score_input(authority=EXECUTION,result=forged,**args)
    finally:path.write_bytes(before)
    verify_mechanism_exploration_cell(executed,**args)


@pytest.mark.parametrize('pair',['pair:M4+M7','pair:M5+M7'])
def test_invalid_original_module_response_stops_before_phase_and_replays(tmp_path,monkeypatch,pair):
    import research_loop.modular.mechanism_exploration_combination_driver as driver
    setup=prepare(tmp_path);packet=setup['packets'][0];panel=next(p for p in setup['compiled'].panels if p.obligation_id==pair)
    cell=next(c for c in panel.cells if c.task_digest==packet.task.content_hash and c.arm_id=='11')
    args=dict(panel=panel,task=packet.task,scenario=setup['compiled'].scenarios[cell.key],
        package=setup['compiled'].packages[cell.runtime_arm.content_hash],material=setup['compiled'].materials[pair][cell.task_digest],
        source_verifier=setup['verifiers'][pair],public_inputs={'public_csv':packet.csv_path},broker=DockerExecutionBroker([tmp_path]))
    seen=[]
    def invalid(request):
        seen.append(request)
        return FrozenRecord.from_dict({'invalid':True})
    result=driver.run_mechanism_exploration_cell(cell=cell,**args,provider=Provider([]),
        objective=FrozenRecord.from_dict(setup['config'].data()['objective']),sidecar=tmp_path/'bad-module',image=IMAGE,
        model=invalid,audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),timeout_seconds=20)
    assert len(seen)==1 and result.runtime.status=='failed' and result.phase is None and result.solver is None
    assert not (tmp_path/'bad-module/phase').exists()
    verify_mechanism_exploration_cell(result,**args)
    with pytest.raises(ContractError):issue_mechanism_exploration_score_input(authority=EXECUTION,result=result,**args)


def test_unknown_phase_cost_is_retained_for_all24_cells(tmp_path,monkeypatch):
    def unknown(*args,**kwargs):raise RuntimeError('synthetic unobserved broker failure')
    monkeypatch.setattr(DockerExecutionBroker,'execute',unknown)
    setup=prepare(tmp_path);result,port,seen=invoke(setup,monkeypatch);b=result.receipt.data()
    assert b['failed_cells']==24 and b['actual_docker_attempts']==48 and b['phase_unknown_cost_attempts']==48
    assert len(seen)==24 and b['retrieval_calls']==24 and b['source_calls']==48
    assert b['actual_scorer_calls']==0 and b['unused_docker_opportunities']==24 and b['pruned_cells']==[]
    for executed in result.results:verify_mechanism_exploration_cell(executed,**replay_args(setup,result,executed))

