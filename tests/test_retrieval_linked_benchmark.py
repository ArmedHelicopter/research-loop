"""Retrieval output must reach the real paired benchmark solve, with no labels."""
import json
from dataclasses import replace

import pytest

from evaluation.modular.train_io import TrainPacketExporter
from evaluation.modular.scoring_service import ScorerConfig, FrozenBenchmarkRubricEndpoint, FrozenRubricTransport
from evaluation.modular.linked_scoring import (LinkedExecutionAuthority, LinkedAdaptedScoringService,
    issue_linked_score_input, verify_linked_adapted_receipt)
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.panel_plan import executable_arms, obligation_grids
from research_loop.modular.retrieval_panel_drivers import freeze_retrieval_bundle
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.train_controller import FrozenTrainControllerConfig, run_train_panel
from research_loop.modular.benchmark_cell import verify_linked_benchmark_cell
from research_loop.modular.linked_public_projection import project_linked_public_context
from research_loop.ontology import ContractError
from test_modular_train_controller import FINAL, config, model_port, snapshot_and_custody
from test_modular_linked_train_controller import ANALYSIS
from test_modular_retrieval_panel_drivers import Provider, _materials, admission
from test_modular_q82_q83_train_controller import independent_fixture_authority


def _neutral_materials():
    material=_materials()
    for variants in material.values():
        for row in variants.values():
            roots={}
            for index,doc in enumerate(row['sources']):
                root=doc['root_source_id']
                roots.setdefault(root,'public-origin-'+str(len(roots)))
                doc['source_id']='public-document-'+str(index)
                doc['root_source_id']=roots[root]
    return material


def _config(tmp_path):
    snapshot, custody = snapshot_and_custody(tmp_path)
    base = config(custody, snapshot, tmp_path).data()
    packets = TrainPacketExporter(custody, snapshot, tmp_path/'materials').export(base['item_ids'])
    evidence = {p.task.content_hash: freeze_retrieval_bundle(p.task,
        query={'task_digest':p.task.content_hash,'question':'fixed public train query'},
        budget={'provider_calls':3,'source_cap':3,'context_bytes':4096},materials=_neutral_materials()).data() for p in packets}
    grids = obligation_grids(('Q8.2','Q8.3'),baseline_digest=base['baseline_digest'],p0_control=FrozenRecord.from_dict(base['p0_control']))
    package=next(iter(base['packages_by_arm'].values()))
    frozen=FrozenTrainControllerConfig(FrozenRecord.from_dict({**base,'schema':'train-panel-controller-v1',
        'engineering_scope':'train_only_panel_engineering','stage':'retrieval-linked-synthetic',
        'scope_ids':['Q8.2','Q8.3'],'evidence_by_task':evidence,
        'packages_by_arm':{a.content_hash:package for g in grids.values() for a in executable_arms(g).values()},
        'budget':{'model_calls':1,'retrieval_calls':3},'max_calls':72,'max_tokens':200,
        'schemas':{'final':FINAL,'analysis_program':ANALYSIS,'final_answer':FINAL},
        'scorer':ScorerConfig.create(benchmark='core_pair',evaluator_id='fixture-retrieval',version='v1',
            rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest()).record.data(),
        'execution_mode':'linked_benchmark_solve'}))
    return snapshot,custody,frozen,evidence


def test_retrieval_linked_config_accepts_exact_driver_and_solver_budget(tmp_path):
    _,_,frozen,_=_config(tmp_path)
    assert frozen.data()['max_calls']==24*3
    assert set(frozen.data()['schemas'])=={'final','analysis_program','final_answer'}


class QueryAwareProvider(Provider):
    def search(self,**kwargs):
        rows=super().search(**kwargs)
        if kwargs['lane']=='counter' and 'counterevidence' not in kwargs['query'].data()['intent']:
            return ()
        return rows


def _response(request):
    body=request.data();context=body['module_context']
    if body['slot']=='analysis_program':
        return FrozenRecord.from_dict({'analysis':'Inspect the supplied public CSV after the recorded retrieval.',
            'program':"import csv, json\nwith open('/input/public_csv', newline='') as stream:\n    rows=list(csv.DictReader(stream))\nprint(json.dumps({'row_count':len(rows)}))"})
    docs=(context['retrieval']['by_lane'] if body['slot']=='final' else
          context['predecessor_context']['mechanism_material']['retrieval']['by_lane'])
    return FrozenRecord.from_dict({'objective_digest':context['required_objective_digest'],'outcome':'unknown',
        'evidence_ids':[],'conclusion':'\n'.join(d['text']['text'] for lane in docs.values() for d in lane) or 'No external source was available.',
        'programme_complete':False})


@pytest.fixture(scope='module')
def linked_grid(tmp_path_factory):
    tmp_path=tmp_path_factory.mktemp('retrieval-linked-grid')
    with pytest.MonkeyPatch.context() as monkeypatch:
        snapshot,custody,frozen,evidence=_config(tmp_path)
        provider=QueryAwareProvider()
        port=model_port(tmp_path/'port',monkeypatch,max_calls=72,max_tokens=200,schemas=frozen.data()['schemas'],response_factory=_response)
        result=run_train_panel(frozen,custody=custody,snapshot_root=snapshot,export_root=tmp_path/'export',
            run_root=tmp_path/'run',model=port,audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),
            retrieval_provider=provider,retrieval_admission_port=admission)
    return result,provider,port,evidence,tmp_path


def test_all_24_retrieval_mechanisms_reach_docker_and_both_solver_requests(linked_grid):
    result,provider,port,evidence,tmp_path=linked_grid
    assert len(result.linked_results)==24 and len(port.ledger['calls'])==72
    assert len(provider.calls)==54
    report=independent_fixture_authority(result,evidence)
    assert report['verified_cells']==24
    assert result.receipt.data()['execution_status']=='engineering_complete'
    assert all(row.status=='linked_succeeded' and row.solver.execution.status=='succeeded' for row in result.linked_results)
    forbidden_digests = {stage['data'][key] for row in result.linked_results
        for stage in row.provenance.data()['mechanism_stages']
        for key in ('policy_digest', 'source_bundle_digest')}
    for row in result.linked_results:
        task=result.compiled.tasks[row.cell.task_digest];scenario=result.compiled.scenarios[row.cell.key]
        verify_linked_benchmark_cell(row,task=task,scenario=scenario,package=result.compiled.packages[row.cell.runtime_arm.content_hash])
        mechanism=[json.loads(line) for line in row.mechanism.runtime.trace_path.read_text(encoding='utf-8').splitlines()]
        actual=next(e['data']['request']['module_context']['retrieval'] for e in mechanism if e['stage']=='model_request')
        for docs in actual['by_lane'].values():
            for doc in docs:
                assert doc['source_id'].startswith('public-document-')
                assert doc['root_source_id'].startswith('public-origin-')
                assert all(label not in doc['source_id']+doc['root_source_id'] for label in
                    ('q82','q83','correct','method','reframe','support_only','neutral','three_lane'))
        expected={k:actual[k] for k in ('by_lane','source_qualification','scientific_admission')}
        solver=[json.loads(line) for line in (row.solver.session.sidecar/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
        requests=[e['data']['request'] for e in solver if e['stage']=='model_request']
        assert len(requests)==2
        precursors=[e['data']['request'] for e in mechanism if e['stage']=='model_request']
        assert len(precursors)==1
        for request in precursors + requests:
            encoded=FrozenRecord.from_dict(request).encoded
            assert all(key not in encoded for key in ('policy_digest', 'source_bundle_digest'))
            assert all(digest not in encoded for digest in forbidden_digests)
        for request in requests:
            public=request['module_context']['predecessor_context']
            assert public['mechanism_material']=={'kind':'retrieved_public_sources','retrieval':expected}
            assert 'q82-' not in FrozenRecord.from_dict(public['mechanism_material']).encoded
            encoded=FrozenRecord.from_dict(public).encoded
            assert all(label not in encoded for label in ('policy_digest','operation_m6_ordinary_baseline','stage_0.5','variant','enabled'))
    (tmp_path/'independent-fixture-authority.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


@pytest.mark.parametrize('fault',['stage_source','request_source','source_pool','arm_stage', 'request_policy', 'request_pool'])
def test_retrieval_public_projection_rejects_unbound_sources(linked_grid,fault):
    result,*_=linked_grid
    row=next(r for r in result.linked_results if r.cell.coverage_id=='Q8.3' and 'M6' in r.cell.runtime_arm.data()['enabled'])
    body=row.provenance.data()
    if fault=='stage_source':body['mechanism_stages'][0]['data']['by_lane']['support'][0]['text']['text']='forged public source'
    elif fault=='request_source':
        request=body['responses'][0]['request'];request['module_context']['retrieval']['by_lane']['support']=[]
        body['responses'][0]['request_digest']=FrozenRecord.from_dict(request).content_hash
    elif fault=='source_pool':body['mechanism_stages'][0]['data']['source_bundle_digest']='f'*64
    elif fault in {'request_policy', 'request_pool'}:
        key='policy_digest' if fault=='request_policy' else 'source_bundle_digest'
        request=body['responses'][0]['request']
        request['module_context']['retrieval'][key]=body['mechanism_stages'][0]['data'][key]
        body['responses'][0]['request_digest']=FrozenRecord.from_dict(request).content_hash
    else:
        body['mechanism_stages'][0]['stage']='operation_m6_ordinary_baseline'
        body['mechanism_stages'][0]['data']['stage']='operation_m6_ordinary_baseline'
    with pytest.raises(ContractError):
        project_linked_public_context(provenance=FrozenRecord.from_dict(body),cell=row.cell,
            task=result.compiled.tasks[row.cell.task_digest],scenario=result.compiled.scenarios[row.cell.key])


def test_all_retrieval_results_reach_independent_anonymous_primary_scorer(linked_grid):
    result,_,_,_,tmp_path=linked_grid
    execution=LinkedExecutionAuthority('fixture-execution',b'x'*32)
    scorer=LinkedExecutionAuthority('fixture-scorer',b'y'*32)
    config=ScorerConfig.create(benchmark='core_pair',evaluator_id='fixture-retrieval',version='v1',
        rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest())
    seen=[]
    def resolve(handle,benchmark):
        import hashlib
        return FrozenRecord.from_dict({'schema':'train-only-rubric-reference-v1','split':'train','benchmark':benchmark,
            'task_handle_digest':hashlib.sha256(handle.encode()).hexdigest(),'identity_digest':handle,
            'task_context':'Synthetic public CSV','references':[{'fixture_reference':True}]})
    def evaluate(request):
        seen.append(request.data())
        dimensions={'context':1,'variable_f1':1,'relation':1} if request.data()['benchmark']=='discoverybench' else {'cvars':2,'transform':2,'model':2}
        return FrozenRecord.from_dict({**dimensions,'reason':'Fixture transport check, not scientific calibration.'})
    endpoint=FrozenBenchmarkRubricEndpoint(resolver=resolve,evaluator=evaluate,evaluator_id='fixture-retrieval',evaluator_version='v1')
    handles={FrozenRecord.from_dict(row.cell.identity.data()).content_hash:FrozenRecord.from_dict(row.cell.identity.data()).content_hash for row in result.linked_results}
    service=LinkedAdaptedScoringService(config=config,evaluator=FrozenRubricTransport(endpoint),
        execution_authority_keys={execution.authority_id:execution.key},task_handles=handles,scorer_authority=scorer)
    receipts=[]
    for row in result.linked_results:
        source=issue_linked_score_input(panel=result.compiled.panel,result=row,task=result.compiled.tasks[row.cell.task_digest],
            scenario=result.compiled.scenarios[row.cell.key],package=result.compiled.packages[row.cell.runtime_arm.content_hash],authority=execution)
        score=service.score_linked(panel=result.compiled.panel,cell=row.cell,linked_input=source)
        verified=verify_linked_adapted_receipt(score,authority_keys={scorer.authority_id:scorer.key},config=config,
            panel=result.compiled.panel,cell=row.cell,linked_input=source,execution_authority_keys={execution.authority_id:execution.key})
        assert verified.data()['scientific_validity']=='not_measured'
        prompt=seen[-1]['prompt']
        assert row.solver.analysis.data()['analysis'] in prompt
        assert all(secret not in prompt for secret in ('mechanism_provenance','policy_digest','coverage_id',str(tmp_path)))
        receipts.append(score.receipt.data())
    assert len(seen)==len(receipts)==24
    (tmp_path/'signed-fixture-primary-scores.json').write_text(json.dumps(receipts,indent=2),encoding='utf-8')


def test_provider_failure_preserves_all_cells_and_unused_solver_budget(tmp_path,monkeypatch):
    snapshot,custody,frozen,_=_config(tmp_path)
    class FailingProvider:
        def __init__(self):self.calls=0
        def search(self,**kwargs):self.calls+=1;raise RuntimeError('fixed provider failure')
    provider=FailingProvider()
    port=model_port(tmp_path/'port',monkeypatch,max_calls=72,max_tokens=200,schemas=frozen.data()['schemas'],response_factory=_response)
    result=run_train_panel(frozen,custody=custody,snapshot_root=snapshot,export_root=tmp_path/'export',
        run_root=tmp_path/'run',model=port,audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),
        retrieval_provider=provider,retrieval_admission_port=admission)
    assert len(result.runtimes)==len(result.linked_results)==24
    assert sum(row.status=='linked_succeeded' for row in result.linked_results)==6
    assert sum(row.status=='mechanism_failed' for row in result.linked_results)==18
    assert len(port.ledger['calls'])==18 and provider.calls==18
    assert result.receipt.data()['execution_status']=='execution_incomplete'
