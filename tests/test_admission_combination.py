"""Actual synthetic admission combinations; no private or validation payloads."""
import hashlib
import json
import os
import re
from dataclasses import replace
import pytest

from research_loop.modular.admission_combination import DESIGNS, AdmissionMaterialVerifier, FrozenAdmissionMaterial
from research_loop.modular.admission_combination_controller import FrozenAdmissionTrainConfig, compile_admission_train_panels, run_admission_train_panels
from research_loop.modular.lineage_combination_driver import SLOTS, verify_lineage_combination_cell
from research_loop.modular.lineage_combination_material import MaterialAuthority
from research_loop.modular.lineage_combination_controller import _arms
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.ontology import ContractError, canonical
from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from evaluation.modular.scorer_process import CombinationScorerProcessClient, serialize_combination_panel
from evaluation.modular.scoring_service import ScorerConfig, FrozenBenchmarkRubricEndpoint
from test_lineage_combination_controller import _fixture as old_fixture, _sources as old_sources, _model, SCHEMAS, EXECUTION, SCORER
from test_modular_train_controller import model_port
from test_scorer_process import _store, _command

def test_admission_controller_has_closed_three_designs():
    from research_loop.modular.admission_combination import DESIGNS, registered_design
    assert list(DESIGNS) == ['pair:M1+M2', 'pair:M1+M3', 'pair:M1+M5']
    for name in DESIGNS:
        design = registered_design(name, 'a'*64).data()
        rows = [r for r in design['cells'] if r['status'] == 'executable']
        assert len(rows) == 4
        for row in rows:
            enabled = row['arm']['enabled']
            if name == 'pair:M1+M3': assert 'M2' in enabled
            if name == 'pair:M1+M5': assert 'M2' not in enabled


def sources(calls, fault=None, root=None):
    authorities = []
    for i in range(2):
        key = LinkedExecutionAuthority('origin-'+str(i), bytes([65+i])*32)
        group = 'independent-observation-'+str(i)
        def verify(request, key=key, group=group):
            calls.append(request); b = request.data()
            if root is not None:
                journals = [json.loads(p.read_text(encoding='utf-8')) for p in root.glob('cells/*/source-verification.json')]
                assert any(j['calls'][-1]['status']=='reserved' and j['calls'][-1]['cost_unknown'] is True and
                           j['calls'][-1]['request_digest']==request.content_hash for j in journals)
            if fault == 'source_exception': raise RuntimeError('synthetic source outage')
            assessments = {}
            for phase, subjects in b['subjects'].items():
                assessments[phase] = {}
                for name, subject in subjects.items():
                    observation = b['material']['qualification_observations'][phase][name]
                    passed = abs(observation['calibration_error']) <= 0.1
                    assessments[phase][name] = {'subject_digest':subject,
                        'state':{'validity':'valid' if passed else 'invalid','support':'undetermined','novelty':'unknown','investment':'explore'},
                        'outcome':'negative' if observation['effect'] < 0 else 'positive', 'execution_success':True,
                        'audit':[{'name':'measurement','executed':True,'passed':passed}]}
            if fault == 'source_foreign': assessments['before']['old']['subject_digest']='0'*64
            if fault == 'source_bool': assessments['before']['old']['execution_success']=1
            if fault == 'source_disagree' and group.endswith('1'): assessments['before']['old']['state']['validity']='unknown'
            return key.issue({'schema':'admission-material-response-v1','request_digest':request.content_hash,
                'material_digest':b['material_digest'],'identity':b['material']['identity'],'source_group':group,
                'verdict':'unknown' if fault=='source_unknown' else 'verified','cost_units':None if fault=='unknown_cost' else 1,
                'assessments':assessments})
        authorities.append(MaterialAuthority(key, group, verify))
    return AdmissionMaterialVerifier(tuple(authorities))


def fixture(root, verifier, scorer_fault=None):
    snapshot,custody,packets,old,rubric,_ = old_fixture(root, old_sources([]))
    body = old.data(); body.update(schema='admission-combination-train-config-v1',stage='synthetic-admission',max_calls=96)
    rubric = ScorerConfig.create(benchmark='core_pair',evaluator_id='synthetic-primary',version='v1',
        rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest())
    body['scorer']=rubric.record.data()
    package = next(iter(body['packages_by_arm'].values()))
    body['packages_by_arm'] = {k:package for k in _arms('a'*64, DESIGNS)}
    body['allocation']['scorer_call_limit']=24
    body['source_verifier_binding']=verifier.binding().data()
    for material in body['materials_by_task'].values():
        material['schema']='admission-combination-material-v1'; material['withdrawals']=[]
        material['originals'].append({'key':'uncalibrated','root_material':{'observation':'instrument-c'},'content':{'x':99},
            'subject_bindings':material['originals'][0]['subject_bindings']})
        material['qualification_observations'] = {
            'before': {'old':{'effect':1,'calibration_error':0},'current':{'effect':-1,'calibration_error':0},'uncalibrated':{'effect':1,'calibration_error':2}},
            'after': {'old':{'effect':1,'calibration_error':2},'current':{'effect':-1,'calibration_error':0},'uncalibrated':{'effect':1,'calibration_error':2}}}
    store,handles,manifest_sha = _store(root, {'tasks':{p.task.content_hash:p.task for p in packets}})
    body['scorer_handle_bindings']={k:hashlib.sha256(v.encode()).hexdigest() for k,v in handles.items()}
    config = FrozenAdmissionTrainConfig(FrozenRecord.from_dict(body)); compiled = compile_admission_train_panels(config,packets)
    (root/'frozen-config.json').write_text(config.record.encoded,encoding='utf-8')
    (root/'execution.key').write_bytes(EXECUTION.key); (root/'score.key').write_bytes(SCORER.key)
    services = {}
    for n,panel in enumerate(compiled.panels):
        server = {'schema':'admission-combination-scorer-process-config-v1','panel':serialize_combination_panel(panel,admission=True),
            'scorer_config':rubric.record.data(),'scorer_config_digest':rubric.digest,
            'train_reference_store':{'root':str(store.resolve()),'manifest_sha256':manifest_sha,
                'inventory_digest':packets[0].task.identity.dataset_version,'split_digest':panel.split_digest},
            'task_handles':handles,'execution_authority_key_files':{EXECUTION.authority_id:str((root/'execution.key').resolve())},
            'scorer_authority':{'id':SCORER.authority_id,'key_file':str((root/'score.key').resolve())},
            'evaluator':{'synthetic_mode':'fail' if scorer_fault else 'normal'}}
        path=root/f'server-{n}.json';path.write_text(canonical(server),encoding='utf-8')
        command = _command(path,root/f'worker-{n}.jsonl')
        from pathlib import Path
        command[1]=str((Path(__file__).parent/'helpers/admission_scorer_process_helper.py').resolve())
        services[panel.obligation_id] = CombinationScorerProcessClient(panel=panel,config=rubric,admission=True,
            command=command,journal_path=root/f'client-{n}.jsonl',
            task_handle_bindings=body['scorer_handle_bindings'],execution_authority_keys={EXECUTION.authority_id:EXECUTION.key},
            scorer_authority_keys={SCORER.authority_id:SCORER.key},environment={**os.environ,'PYTHONIOENCODING':'gbk'})
    return snapshot,custody,config,compiled,services


def run(root, monkeypatch, fault=None):
    calls=[]; verifier=sources(calls,fault,root/'run')
    snapshot,custody,config,compiled,services=fixture(root,verifier,scorer_fault=fault=='scorer_failed')
    seen=[]; respond=_model(seen,fault)
    port=model_port(root/'port',monkeypatch,max_calls=96,max_tokens=1000,schemas=SCHEMAS,response_factory=respond)
    try:
        result=run_admission_train_panels(config,custody=custody,snapshot_root=snapshot,export_root=root/'export',run_root=root/'run',
            model=port,audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),source_verifier=verifier,
            execution_authority=EXECUTION,scoring_service=services,scorer_authority_keys={SCORER.authority_id:SCORER.key})
    finally:
        for service in services.values(): service.close()
    return result,port,seen,calls,verifier,root


@pytest.fixture(scope='module')
def grid(tmp_path_factory):
    with pytest.MonkeyPatch.context() as patch:
        yield run(tmp_path_factory.mktemp('admission-grid'),patch)


def test_complete_24_actual_cells_and_primary_process(grid):
    result,port,seen,calls,_,root = grid
    assert len(result.results)==len(result.scores)==24, [a.data() for a in result.attempts if a.data()['status']!='succeeded']
    assert len(seen)==len(port.ledger['calls'])==96 and len(calls)==48
    assert [len(p.cells) for p in result.compiled.panels]==[8,8,8]
    assert all(c.data()['status']=='estimated' for c in result.contrasts)
    assert all(all(v['mean']==0 for v in c.data()['benchmark_estimates'].values()) for c in result.contrasts)
    assert result.receipt.data()['actual_docker_attempts']==24
    for executed in result.results:
        enabled=set(executed.cell.runtime_arm.data()['enabled']); t=executed.transition.data()
        assert t['raw_representation_denominator']==5 and t['root_denominator']==3
        if 'M1' in enabled:
            assert t['decisions']['before']['current']['admitted'] is True # valid negative admitted
            assert t['decisions']['before']['uncalibrated']['admitted'] is False # invalid positive rejected
            assert t['revoked']==['old'] and len(t['public']['observations'])==1
        else:
            assert t['revoked']==[] and len(t['public']['observations'])==(3 if 'M2' in enabled else 5)
        if 'M2' not in enabled:
            assert (executed.runtime.trace_path.parent/'evidence.jsonl').read_bytes()==b''
            assert (executed.runtime.trace_path.parent/'claims.jsonl').read_bytes()==b''
        if {'M1','M2'} <= enabled: assert len(t['evidence']['withdrawn'])==1
        if {'M1','M3'} <= enabled: assert t['context_before_digest'] != t['context_after_digest']
        assert "'observations': "+str(len(t['public']['observations'])) in executed.solver.execution.record.data()['stdout']
        assert "'reviews': "+('2' if 'M5' in enabled else '0') in executed.solver.execution.record.data()['stdout']
    for n in range(3):
        for kind in ('client','worker'):
            rows=[json.loads(line) for line in (root/f'{kind}-{n}.jsonl').read_text(encoding='utf-8').splitlines()]
            assert len(rows)==16 and [r['status'] for r in rows]==['reserved','succeeded']*8
    assert result.receipt.data()['scientific_effectiveness_proven'] is False
    assert result.receipt.data()['pruned_cells']==[]
    assert all(not re.search(r'M[1-9]|Q\d+\.\d+|source-quorum|origin-[01]|independent-observation|PRIVATE-REFERENCE-SENTINEL',canonical(r)) for r in seen)


@pytest.mark.parametrize('fault',['source_exception','source_unknown','source_bool','source_foreign','source_disagree'])
def test_source_failures_preserve_all_24_cells_and_both_authority_calls(tmp_path,monkeypatch,fault):
    result,port,seen,calls,_,_=run(tmp_path,monkeypatch,fault)
    assert len(result.results)==24 and not result.scores and len(calls)==48 and seen==[]
    assert result.receipt.data()['failed_cells']==24 and result.receipt.data()['actual_docker_attempts']==0
    assert all(a.data()['source_verification']['calls'] for a in result.attempts)
    assert all(c.data()['status']=='inconclusive' for c in result.contrasts)


@pytest.mark.parametrize('fault',['analysis_invalid','docker_failed','answer_invalid'])
def test_original_solver_failure_keeps_denominator_and_costs(tmp_path,monkeypatch,fault):
    result,port,seen,calls,_,_=run(tmp_path,monkeypatch,fault)
    assert len(result.results)==24 and not result.scores and len(calls)==48
    assert all(r.runtime.status=='failed' for r in result.results)
    assert all(a.data()['phase']=='execution' for a in result.attempts)
    assert len(seen)==(72 if fault=='analysis_invalid' else 96)
    assert result.receipt.data()['actual_docker_attempts']==(0 if fault=='analysis_invalid' else 24)


def test_unknown_solver_cost_blocks_future_cells_without_erasing_denominator(tmp_path,monkeypatch):
    result,port,seen,calls,_,_=run(tmp_path,monkeypatch,'solver_transport')
    assert len(result.results)==24 and len(seen)==3 and len(calls)==2 and not result.scores
    assert result.receipt.data()['blocked_cells']==23 and port.ledger['usage_incomplete'] is True


def test_actual_scorer_failures_keep_all_reservations_and_executions(tmp_path,monkeypatch):
    result,port,seen,calls,_,root=run(tmp_path,monkeypatch,'scorer_failed')
    assert len(result.results)==24 and not result.scores and len(seen)==96 and len(calls)==48
    assert result.receipt.data()['actual_scorer_calls']==24 and result.receipt.data()['actual_docker_attempts']==24
    assert result.receipt.data()['failed_cells']==24 and result.receipt.data()['scorer_usage_unknown'] is True
    for n in range(3):
        rows=[json.loads(line) for line in (root/f'worker-{n}.jsonl').read_text(encoding='utf-8').splitlines()]
        assert [r['status'] for r in rows]==['reserved','unknown']*8


@pytest.mark.parametrize('fault',['labels','hostpath','duplicate_root','foreign_claim','missing_phase','scripted_withdrawal',
                                 'budget_bool','wrong_rubric','missing_arm','source_key_same'])
def test_malformed_frozen_inputs_rejected_without_any_call(grid,fault):
    root=grid[-1]; body=json.loads((root/'frozen-config.json').read_text(encoding='utf-8'))
    m=next(iter(body['materials_by_task'].values()))
    if fault=='labels':m['originals'][0]['content']['note']='M1 on expected_correct'
    elif fault=='hostpath':m['ordinary_summary']='See E:/private/source.csv'
    elif fault=='duplicate_root':m['originals'][1]['root_material']=m['originals'][0]['root_material']
    elif fault=='foreign_claim':m['claims'][0]['subject_bindings']['task']='foreign'
    elif fault=='missing_phase':del m['qualification_observations']['after']['old']
    elif fault=='scripted_withdrawal':m['withdrawals']=[{'root':'old','reason':'scripted success'}]
    elif fault=='budget_bool':body['allocation']['docker_attempts_per_cell']=True
    elif fault=='wrong_rubric':body['scorer']['rubric_digest']='0'*64
    elif fault=='missing_arm':body['packages_by_arm'].pop(next(iter(body['packages_by_arm'])))
    else:body['source_verifier_binding']['authorities'][1]['key_digest']=body['source_verifier_binding']['authorities'][0]['key_digest']
    with pytest.raises(ContractError):FrozenAdmissionTrainConfig(FrozenRecord.from_dict(body))


@pytest.mark.parametrize('flag',[False,1,'true',None])
def test_process_family_requires_explicit_strict_scope(grid,flag):
    panel=grid[0].compiled.panels[0]
    with pytest.raises(ContractError):serialize_combination_panel(panel,admission=flag)


@pytest.mark.parametrize('fault',['gate_decision','ledger_withdrawal','builtin_context','joint_observations',
                                 'script_bytes','source_subject','source_other_cell','final_execution','review_barrier'])
def test_independent_replay_rejects_rehashed_operational_forgeries(grid,fault):
    from test_modular_combination_benchmark_driver import _rewrite_trace
    result,_,_,_,verifier,root=grid
    executed=next(r for r in result.results if set(r.cell.runtime_arm.data()['enabled'])==
                  ({'M1','M5'} if fault=='review_barrier' else {'M1','M2','M3'}))
    panel=next(p for p in result.compiled.panels if executed.cell in p.cells)
    packet=next(p for p in result.compiled.packets if p.task.content_hash==executed.cell.task_digest)
    args=dict(panel=panel,task=packet.task,scenario=result.compiled.scenarios[executed.cell.key],
        package=result.compiled.packages[executed.cell.runtime_arm.content_hash],material=result.compiled.materials[executed.cell.task_digest],
        source_verifier=verifier,public_inputs={'public_csv':packet.csv_path},broker=DockerExecutionBroker([root/'export',root/'run']))
    trace=executed.runtime.trace_path; source=trace.parent.parent/'source-verification.json'
    saved={p:p.read_bytes() for p in trace.parent.iterdir() if p.is_file()};saved[source]=source.read_bytes()
    def change(events):
        if fault=='gate_decision':next(e for e in events if e['stage']=='lineage_transition')['data']['transition']['decisions']['before']['uncalibrated']['admitted']=True
        elif fault=='ledger_withdrawal':
            path=trace.parent/'evidence.jsonl'; rows=[FrozenRecord(line).data() for line in path.read_text(encoding='utf-8').splitlines()]
            path.write_text(''.join(canonical(r)+'\n' for r in rows if r['event']!='withdraw'),encoding='utf-8')
        elif fault in {'builtin_context','final_execution','joint_observations'}:
            request=next(e for e in events if e['stage']=='model_request' and e['data']['request']['slot']==('final_answer' if fault=='final_execution' else 'analysis_program'))
            b=request['data']['request']
            if fault=='builtin_context':b['context']['entries']=[]
            elif fault=='final_execution':b['module_context']['execution_digest']='0'*64
            else:b['module_context']['joint_mechanism']['material']['observations']=[]
            old=request['data']['request_digest'];new=FrozenRecord.from_dict(b).content_hash;request['data']['request_digest']=new
            for e in events:
                if e['stage']=='model_response' and e['data']['request_digest']==old:e['data']['request_digest']=new
        elif fault=='script_bytes':
            path=trace.parent/'analysis-1.py';path.write_bytes(path.read_bytes().replace(b'print(',b'PRINT(',1))
        elif fault=='source_subject':
            b=json.loads(source.read_text(encoding='utf-8'))
            for row,authority in zip(b['calls'],verifier.authorities):
                response=row['response']['body'];response['assessments']['before']['old']['subject_digest']='0'*64
                row['response']=authority.authority.issue({k:v for k,v in response.items() if k!='authority'}).data()
            source.write_text(canonical(b),encoding='utf-8')
            next(e for e in events if e['stage']=='lineage_transition')['data']['source_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
        elif fault=='source_other_cell':
            other=next(r for r in result.results if r.cell.task_digest==executed.cell.task_digest and r.cell!=executed.cell)
            source.write_bytes((other.runtime.trace_path.parent.parent/'source-verification.json').read_bytes())
            next(e for e in events if e['stage']=='lineage_transition')['data']['source_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
        else:next(e for e in events if e['stage']=='lineage_review_submission')['data']['barrier_open']=True
    try:
        tail=_rewrite_trace(trace,change)
        with pytest.raises(ContractError):verify_lineage_combination_cell(replace(executed,runtime=replace(executed.runtime,trace_digest=tail)),**args)
    finally:
        for p,b in saved.items():p.write_bytes(b)


def test_unknown_source_cost_is_preserved_when_contract_succeeds(grid,tmp_path):
    from research_loop.modular.lineage_combination_driver import _source_binding
    executed=grid[0].results[0];material=grid[0].compiled.materials[executed.cell.task_digest]
    calls=[];verifier=sources(calls,'unknown_cost');path=tmp_path/'source'/'receipt.json'
    verifier.qualify(material,path,cell_binding=_source_binding(executed.cell))
    rows=json.loads(path.read_text(encoding='utf-8'))['calls']
    assert len(calls)==2 and all(r['cost_units'] is None and r['cost_unknown'] is True for r in rows)
