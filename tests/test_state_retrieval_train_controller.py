"""Exact prospective TRAIN state/retrieval controller and independent scorer checks.

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
from evaluation.modular.state_retrieval_scoring import issue_state_retrieval_score_input
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.state_retrieval_combination_controller import (
    FrozenStateRetrievalTrainConfig, compile_state_retrieval_train_panels, run_state_retrieval_train_panels, _arms)
from research_loop.modular.state_retrieval_combination_driver import DESIGNS, SLOTS, freeze_material, verify_state_retrieval_cell
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.combination_train_controller import _ANALYSIS
from research_loop.ontology import ContractError, canonical
from test_remaining_prospective_train_sources import prepared_primary, changed_source_config, corrupt_export
from test_primary_prospective_exporter import events
from test_lineage_combination_controller import EXECUTION, SCORER
from test_admission_combination import sources
from test_modular_train_controller import model_port, FINAL
from test_modular_combination_train_controller import ANALYSIS
from test_state_retrieval_combination_driver import state_material, provenance, Provider, model, IMAGE
from test_modular_combination_benchmark_driver import _rewrite_trace
from test_scorer_process import _store, _command


def prepare(root, fault=None):
    exporter, selected, all_items, packets = prepared_primary(root)
    calls=[]; corpus_calls=[]
    verifiers = {pair:(sources(calls, fault='source_exception' if fault=='source_exception' else fault)
        if pair=='pair:M1+M6' else provenance(calls,'unknown' if fault=='source_exception' else None)) for pair in DESIGNS}
    corpus_verifiers = {pair:provenance(corpus_calls,'unknown' if fault=='corpus_exception' else None) for pair in DESIGNS}
    docs=[{'source_id':'private-origin-'+str(i),'root_source_id':'private-origin-root-'+str(i),'lane':lane,'text':text}
        for i,(lane,text) in enumerate([('support','The old values suggest a high mean.'),
            ('counter','Check a withdrawn old measurement.'),('method','Calculate the public CSV mean.')])]
    materials={pair:{p.task.content_hash:freeze_material(p.task,state_material(p.task,p.csv_path,pair=='pair:M1+M6'),
        docs,'Which public observations distinguish the explanations?').data() for p in packets} for pair in DESIGNS}
    package=CandidatePackage.create(parent_digest=None,manifest=TrainingManifest.freeze([p.task.identity for p in packets]),
        changes={'prompt':{'instructions':'Analyze the supplied public training observations.'}},search_cost=0)
    store,handles,manifest_sha=_store(root,{'tasks':{p.task.content_hash:p.task for p in packets}})
    b={'schema':'state-retrieval-combination-train-config-v2','export_mode':'primary_prospective','domain':'train',
        'stage':'synthetic-prospective-state-retrieval','item_ids':[i.token for i in selected],
        'task_bindings':{i.token:{'identity':p.task.identity.data(),'task_digest':p.task.content_hash,
            'csv_sha256':hashlib.sha256(p.csv_path.read_bytes()).hexdigest(),'csv_byte_count':p.csv_path.stat().st_size}
            for i,p in zip(selected,packets,strict=True)},'baseline_digest':'a'*64,
        'packages_by_arm':{a:package.record.data() for a in _arms('a'*64)},
        'scorer':ScorerConfig.create(benchmark='core_pair',evaluator_id='synthetic-primary',version='v1',
            rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest()).record.data(),
        'scorer_handle_bindings':{k:hashlib.sha256(v.encode()).hexdigest() for k,v in handles.items()},
        'acceptance_criteria':{'contrast_analysis':_ANALYSIS},'replicates':['r1'],'model':'gpt-5.6-luna','effort':'low',
        'materials_by_pair':materials,'source_verifier_bindings':{p:v.binding().data() for p,v in verifiers.items()},
        'retrieval_verifier_bindings':{p:v.binding().data() for p,v in corpus_verifiers.items()},
        'objective':{'purpose':'Analyze public TRAIN measurements with frozen module context.'},
        'image':IMAGE,'timeout_seconds':20,'max_calls':48,'max_tokens':1000,
        'schemas':{'analysis_program':ANALYSIS,'final_answer':FINAL},
        'allocation':{'model_slots_per_cell':list(SLOTS),'docker_attempts_per_cell':1,'scorer_calls_per_cell':1,
            'scorer_call_limit':24,'scorer_token_accounting':'transport_not_provided','source_calls_per_cell':4,
            'state_calls_per_cell':2,'corpus_calls_per_cell':2,'retrieval_calls_per_cell':3,
            'retrieval_source_cap':3,'retrieval_context_bytes':4096}}
    config=FrozenStateRetrievalTrainConfig(FrozenRecord.from_dict(b)); compiled=compile_state_retrieval_train_panels(config,packets)
    (root/'frozen-config.json').write_text(config.record.encoded+'\n',encoding='utf-8')
    return dict(root=root,exporter=exporter,selected=selected,all_items=all_items,packets=packets,
        config=config,compiled=compiled,verifiers=verifiers,corpus_verifiers=corpus_verifiers,calls=calls,corpus_calls=corpus_calls,
        store=store,handles=handles,manifest_sha=manifest_sha)


def services(setup, stack, scorer_fault=False):
    root=setup['root'];b=setup['config'].data();rubric=ScorerConfig(FrozenRecord.from_dict(b['scorer']))
    (root/'execution.key').write_bytes(EXECUTION.key);(root/'score.key').write_bytes(SCORER.key)
    clients={}
    for n,panel in enumerate(setup['compiled'].panels):
        server={'schema':'state-retrieval-scorer-process-config-v1',
            'panel':serialize_combination_panel(panel,state_retrieval=True),'scorer_config':rubric.record.data(),
            'scorer_config_digest':rubric.digest,'train_reference_store':{'root':str(setup['store'].resolve()),
                'manifest_sha256':setup['manifest_sha'],'inventory_digest':panel.cells[0].identity.dataset_version,'split_digest':panel.split_digest},
            'task_handles':setup['handles'],'execution_authority_key_files':{EXECUTION.authority_id:str(root/'execution.key')},
            'scorer_authority':{'id':SCORER.authority_id,'key_file':str(root/'score.key')},
            'evaluator':{'synthetic_mode':'fail' if scorer_fault else 'normal'}}
        path=root/f'server-{n}.json';path.write_text(canonical(server),encoding='utf-8')
        command=_command(path,root/f'worker-{n}.jsonl');command[1]=str((Path(__file__).parent/'helpers/state_retrieval_scorer_process_helper.py').resolve())
        client=CombinationScorerProcessClient(panel=panel,config=rubric,state_retrieval=True,command=command,
            journal_path=root/f'client-{n}.jsonl',task_handle_bindings=b['scorer_handle_bindings'],
            execution_authority_keys={EXECUTION.authority_id:EXECUTION.key},scorer_authority_keys={SCORER.authority_id:SCORER.key},
            environment={**os.environ,'PYTHONIOENCODING':'gbk'})
        stack.callback(client.close);clients[panel.obligation_id]=client
    return clients


def invoke(setup,monkeypatch,fault=None):
    root=setup['root'];config=setup['config'];b=config.data();seen=[];provider_calls=[];respond=model(seen)
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
        source_verifiers=setup['verifiers'],retrieval_verifiers=setup['corpus_verifiers'],provider=Provider(provider_calls,fault=='provider'),
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
            with pytest.raises((ContractError,CustodyError)):run_state_retrieval_train_panels(config,**kwargs)
            assert not seen and not setup['calls'] and not setup['corpus_calls'] and not provider_calls and not port.ledger['calls']
            assert not list((root/'run').glob('cells/*/runtime/analysis-1.py')) and not list(root.glob('worker-*.jsonl'))
            return
        result=run_state_retrieval_train_panels(config,**kwargs)
    return result,port,seen,provider_calls


@pytest.fixture(scope='module')
def grid(tmp_path_factory):
    setup=prepare(tmp_path_factory.mktemp('state-retrieval-controller'))
    with pytest.MonkeyPatch.context() as patch: result,port,seen,retrieved=invoke(setup,patch)
    return setup,result,port,seen,retrieved


def replay_args(setup,result,executed):
    panel=next(p for p in result.compiled.panels if executed.cell in p.cells)
    packet=next(p for p in result.compiled.packets if p.task.content_hash==executed.cell.task_digest)
    return dict(panel=panel,task=packet.task,scenario=result.compiled.scenarios[executed.cell.key],
        package=result.compiled.packages[executed.cell.runtime_arm.content_hash],material=result.compiled.materials[panel.obligation_id][executed.cell.task_digest],
        source_verifier=setup['verifiers'][panel.obligation_id],retrieval_verifier=setup['corpus_verifiers'][panel.obligation_id],
        public_inputs={'public_csv':packet.csv_path},broker=DockerExecutionBroker([setup['root']/'export',setup['root']/'run']))


def test_full24_prospective_cells_docker_and_independent_primary_scores(grid):
    setup,result,port,seen,retrieved=grid
    assert len(result.scores)==len(result.results)==len(result.attempts)==24,[a.data() for a in result.attempts if a.data()['status']!='succeeded']
    assert len(seen)==len(port.ledger['calls'])==48 and len(retrieved)==72
    assert len(setup['calls'])==len(setup['corpus_calls'])==48
    b=result.receipt.data();assert b['status']=='complete_train_engineering'
    assert b['actual_docker_attempts']==b['actual_scorer_calls']==24
    assert b['source_calls']==96 and b['retrieval_calls']==72 and b['pruned_cells']==[]
    assert b['validation_opened'] is b['scientific_effectiveness_proven'] is False
    assert [e['event'] for e in events(setup['exporter'])]==['export_reserved','sources_verified','exposure_reserved','exposure_reserved','export_completed']
    for attempt,executed in zip(result.attempts,result.results,strict=True):
        row=attempt.data();assert row['status']=='succeeded'
        assert len(row['source_verification']['calls'])==len(row['corpus_verification']['calls'])==2
        assert row['docker_attempts']==row['scorer_calls']==1 and row['retrieval_calls']==3
        assert row['execution_receipt']['record']['argv'][-3:]==[IMAGE,'python3','/task/analysis.py']
        verify_state_retrieval_cell(executed,**replay_args(setup,result,executed))
        if executed.cell.coverage_id=='pair:M3+M6':assert 'M2' in executed.cell.runtime_arm.data()['enabled']
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
    setup=prepare(tmp_path);result,port,seen,retrieved=invoke(setup,monkeypatch,'poison');b=result.receipt.data()
    assert len(result.attempts)==24 and b['failed_cells']==1 and b['blocked_cells']==23
    assert len(seen)==len(port.ledger['calls'])==1 and port.ledger['usage_incomplete'] is True
    assert b['actual_docker_attempts']==b['actual_scorer_calls']==0
    assert b['unused_model_opportunities']==47 and b['source_calls']==4 and b['retrieval_calls']==3
    assert b['pruned_cells']==[] and all(c.data()['status']=='inconclusive' for c in result.contrasts)


@pytest.mark.parametrize('fault',['source_exception','corpus_exception','provider'])
def test_qualification_and_provider_failures_keep_denominators(tmp_path,monkeypatch,fault):
    setup=prepare(tmp_path,fault);result,port,seen,retrieved=invoke(setup,monkeypatch,fault);b=result.receipt.data()
    assert len(result.attempts)==len(result.results)==24 and b['failed_cells']==24 and b['pruned_cells']==[]
    assert not seen and not port.ledger['calls'] and b['actual_docker_attempts']==b['actual_scorer_calls']==0
    assert b['source_calls']==(48 if fault=='source_exception' else 96)
    assert b['retrieval_calls']==(24 if fault=='provider' else 0)
    assert all(c.data()['status']=='inconclusive' for c in result.contrasts)


def test_m1_semantic_drift_preserves_scores_but_blocks_contrast(tmp_path,monkeypatch):
    setup=prepare(tmp_path,'source_cell_drift');result,port,seen,_=invoke(setup,monkeypatch)
    assert len(result.scores)==len(result.attempts)==24 and len(seen)==48
    contrasts={p.obligation_id:c.data() for p,c in zip(result.compiled.panels,result.contrasts,strict=True)}
    assert contrasts['pair:M1+M6']['status']=='inconclusive'
    assert contrasts['pair:M1+M6']['reason']=='admission_qualification_semantic_drift'
    assert all(contrasts[p]['status']=='estimated' for p in DESIGNS if p!='pair:M1+M6')
    assert result.receipt.data()['status']=='inconclusive'


@pytest.mark.parametrize('fault',['state_journal','claims_journal','retrieval_context','request_context','program','state_signature','corpus_signature'])
def test_persistent_replay_and_score_issuance_reject_forgeries(grid,fault):
    setup,result,*_=grid;mutations=[]
    for executed in result.results:
        if executed.cell.identity.benchmark!='blade' or executed.cell.arm_id!='11':continue
        args=replay_args(setup,result,executed);path=executed.runtime.trace_path;before=path.read_bytes();extra=None;saved=None
        def mutate(rows):
            if fault=='retrieval_context':next(e for e in rows if e['stage']=='retrieval_review_sources')['data']['projection']['by_lane']['counter']=[]
            if fault=='request_context':
                request=next(e for e in rows if e['stage']=='model_request')['data'];old=request['request_digest']
                request['request']['module_context']['joint_mechanism']['state_projection']={}
                request['request_digest']=FrozenRecord.from_dict(request['request']).content_hash
                for row in rows:
                    if row['stage']=='model_response' and row['data']['request_digest']==old:row['data']['request_digest']=request['request_digest']
        try:
            if fault in ('state_journal','claims_journal','program','state_signature','corpus_signature'):
                extra={'state_journal':path.parent/'evidence.jsonl','claims_journal':path.parent/'claims.jsonl','program':path.parent/'analysis-1.py',
                    'state_signature':path.parent.parent/'source-verification.json','corpus_signature':path.parent.parent/'retrieval'/'source-verification.json'}[fault]
                saved=extra.read_bytes();extra.write_bytes(saved+b'{}\n');forged=executed
            else:
                tail=_rewrite_trace(path,mutate);forged=replace(executed,runtime=replace(executed.runtime,trace_digest=tail))
            with pytest.raises((ContractError,ValueError)):verify_state_retrieval_cell(forged,**args)
            with pytest.raises((ContractError,ValueError)):issue_state_retrieval_score_input(authority=EXECUTION,result=forged,**args)
            mutations.append({'pair':executed.cell.coverage_id,'fault':fault})
        finally:
            path.write_bytes(before)
            if extra is not None:extra.write_bytes(saved)
        verify_state_retrieval_cell(executed,**args)
    assert {m['pair'] for m in mutations}==set(DESIGNS)
    (setup['root']/('replay-'+fault+'.json')).write_text(canonical(mutations),encoding='utf-8')


@pytest.mark.parametrize('flags',[{}, {'state_retrieval':1},{'state_retrieval':'true'},
    {'state_retrieval':True,'state_prediction':True},{'state_retrieval':True,'lineage':True},
    {'state_retrieval':True,'retrieval_review':True},{'state_retrieval':True,'admission':True},
    {'state_retrieval':True,'exploration_scheduler':True}])
def test_strict_scorer_family_scope_no_default_relaxation(grid,flags):
    setup,*_=grid
    with pytest.raises(ContractError):serialize_combination_panel(setup['compiled'].panels[0],**flags)


def test_roundtrip_each_pair_and_reject_schema_substitution(grid):
    setup,*_=grid
    for n,panel in enumerate(setup['compiled'].panels):
        body=serialize_combination_panel(panel,state_retrieval=True)
        assert parse_combination_panel(body,state_retrieval=True)==panel
        server=json.loads((setup['root']/f'server-{n}.json').read_text(encoding='utf-8'))
        assert parse_server_config(server).panel==panel
        server['schema']='state-prediction-scorer-process-config-v1'
        with pytest.raises(ContractError):parse_server_config(server)
