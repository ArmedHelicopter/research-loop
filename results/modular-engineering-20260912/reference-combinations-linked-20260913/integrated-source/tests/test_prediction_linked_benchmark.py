"""Actual prediction artifacts must reach a subsequent benchmark execution."""
import json
from pathlib import Path

import pytest

from evaluation.modular.train_io import TrainPacketExporter
from evaluation.modular.scoring_service import ScorerConfig, FrozenBenchmarkRubricEndpoint
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.panel_plan import executable_arms, obligation_grids
from research_loop.modular.prediction_panel_drivers import freeze_prediction_bundle
from research_loop.modular.train_controller import FrozenTrainControllerConfig
from test_modular_train_controller import config, snapshot_and_custody, FINAL, SCENARIO, model_port
from test_modular_linked_train_controller import ANALYSIS
from test_modular_prediction_panel_drivers import branch, proposal, q32_plan

DEDUP={'type':'object','properties':{'kept_proposal_ids':{'type':'array','items':{'type':'string'}}},
       'required':['kept_proposal_ids'],'additionalProperties':False}

def neutral_material(task):
    a,b,c=branch('h0','m0','positive'),branch('h1','m1','negative'),branch('h2','m2','null')
    q32={'joint':{'plans':[q32_plan(task,'Assess the public observation',[a,b,c],3,'0')]},
         'separate':{'plans':[q32_plan(task,'Assess the public observation',branches,1,str(i))
                             for i,branches in enumerate(([a,b],[a,c],[b,c]))]}}
    q53={}
    for variant, mechanisms, directions, titles in [
        ('same_mechanism',('m0','m0'),('positive','positive'),('Study A','Study B')),
        ('opposite_prediction',('m0','m0'),('positive','negative'),('Study A','Study B')),
        ('title',('m0','m1'),('positive','null'),('Study A','Study A'))]:
        branches=[branch('h'+str(i),mechanisms[i],directions[i]) for i in range(2)]
        q53[variant]={'proposals':[proposal(b,'origin-'+str(i),titles[i]) for i,b in enumerate(branches)],
                     'plan':{'question':'Assess the public observation','branches':branches,'budget_units':2}}
    return freeze_prediction_bundle(task,public_evidence={'schema':'prediction-public-evidence-v1',
        'task_digest':task.content_hash,'source_id':'source-0','observation_id':'observation-0',
        'public_summary':'Recorded public observation'},controller_truth={'schema':'prediction-controller-truth-v1',
        'marker':'CONTROLLER_ONLY_REFERENCE_MARKER'},q32=q32,q53=q53)

def frozen_config(tmp_path):
    snapshot,custody=snapshot_and_custody(tmp_path)
    base=config(custody,snapshot,tmp_path).data()
    packets=TrainPacketExporter(custody,snapshot,tmp_path/'materials').export(base['item_ids'])
    evidence={p.task.content_hash:neutral_material(p.task).data() for p in packets}
    grids=obligation_grids(('Q3.2','Q5.3'),baseline_digest=base['baseline_digest'],
        p0_control=FrozenRecord.from_dict(base['p0_control']))
    package=next(iter(base['packages_by_arm'].values()))
    frozen=FrozenTrainControllerConfig(FrozenRecord.from_dict({**base,'schema':'train-panel-controller-v1',
        'engineering_scope':'train_only_panel_engineering','stage':'prediction-linked-fixture',
        'scope_ids':['Q3.2','Q5.3'],'evidence_by_task':evidence,
        'packages_by_arm':{a.content_hash:package for g in grids.values() for a in executable_arms(g).values()},
        'budget':{'maximum_mechanism_calls':4,'solver_calls':2,'solver_executions':1},
        'max_calls':96,'max_tokens':300,'schemas':{'plan_1':SCENARIO,'plan_2':SCENARIO,'plan_3':SCENARIO,
            'dedup':DEDUP,'final':FINAL,'analysis_program':ANALYSIS,'final_answer':FINAL},
        'scorer':ScorerConfig.create(benchmark='core_pair',evaluator_id='prediction-fixture',version='v1',
            rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest()).record.data(),
        'execution_mode':'linked_benchmark_solve'}))
    return snapshot,custody,frozen,evidence

def test_linked_config_freezes_all_twenty_prediction_cells(tmp_path):
    _,_,frozen,_=frozen_config(tmp_path)
    assert frozen.data()['max_calls']==8*6+12*4


def response_factory(request):
    body=request.data();slot=body['slot'];context=body['module_context']
    if slot.startswith('plan_'):
        return FrozenRecord.from_dict({k:context['plan_material'][k] for k in ('question','branches','budget_units')})
    if slot=='dedup':
        return FrozenRecord.from_dict({'kept_proposal_ids':context['retained_proposal_ids']})
    if slot=='analysis_program':
        material=context['predecessor_context']['mechanism_material']
        branches=([b['hypothesis_id'] for b in material['retained_branches']] if 'retained_branches' in material else
                  [[b['hypothesis_id'] for b in p['assessment']['branches']] for p in material['plans']])
        return FrozenRecord.from_dict({'analysis':'Analyze the CSV with the supplied operational branches.',
            'program':"import csv,json\nwith open('/input/public_csv',newline='') as stream:\n    rows=list(csv.DictReader(stream))\n"
                      +"print(json.dumps({'row_count':len(rows),'branches':"+repr(branches)+"}))"})
    return FrozenRecord.from_dict({'objective_digest':context['required_objective_digest'],'outcome':'unknown',
        'evidence_ids':[],'conclusion':'The public analysis was executed; scientific evidence remains unqualified.',
        'programme_complete':False})


@pytest.fixture(scope='module')
def prediction_grid(tmp_path_factory):
    from research_loop.modular.runtime import AuditVerifier
    from research_loop.modular.train_controller import run_train_panel
    root=tmp_path_factory.mktemp('prediction-linked-grid')
    with pytest.MonkeyPatch.context() as mp:
        snapshot,custody,frozen,evidence=frozen_config(root)
        port=model_port(root/'port',mp,max_calls=96,max_tokens=300,schemas=frozen.data()['schemas'],
                        response_factory=response_factory)
        result=run_train_panel(frozen,custody=custody,snapshot_root=snapshot,export_root=root/'export',
            run_root=root/'run',model=port,audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}))
    return result,port,root


def events(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def test_all_twenty_cells_apply_actual_artifacts_before_docker(prediction_grid):
    from research_loop.modular.benchmark_cell import verify_linked_benchmark_cell
    result,port,root=prediction_grid
    assert len(result.linked_results)==20
    assert result.receipt.data()['execution_status']=='engineering_complete'
    assert len(port.ledger['calls'])==96 and port.ledger['tokens']==192
    assert all(r.status=='linked_succeeded' and r.solver.execution.status=='succeeded' for r in result.linked_results)
    observations=[]
    for row in result.linked_results:
        verify_linked_benchmark_cell(row,task=result.compiled.tasks[row.cell.task_digest],
            scenario=result.compiled.scenarios[row.cell.key],package=result.compiled.packages[row.cell.runtime_arm.content_hash])
        mechanism=events(row.mechanism.runtime.trace_path)
        final=next(e['data']['request']['module_context']['prediction_artifacts'] for e in mechanism
                   if e['stage']=='model_request' and e['data']['request']['slot']=='final')
        solver=events(row.solver.session.sidecar/'trace.jsonl')
        requests=[e['data']['request'] for e in solver if e['stage']=='model_request']
        assert len(requests)==2
        for request in requests:
            material=request['module_context']['predecessor_context']['mechanism_material']
            assert material=={'kind':'operational_prediction_material',**final}
        all_requests=[e['data']['request'] for e in mechanism+solver if e['stage']=='model_request']
        for request in all_requests:
            visible=FrozenRecord.from_dict(request['module_context']).encoded
            assert all(secret not in visible for secret in ('CONTROLLER_ONLY_REFERENCE_MARKER','controller_truth',
                'caller_admission_receipt','planning_status','title_baseline','same_mechanism',
                'opposite_prediction','Q3.2','Q5.3','"variant"','"enabled"','"arm_id"'))
            # Solver execution_status is real Docker feedback. The planning
            # qualification must stay out of its predecessor and all precursors.
            public=request['module_context'].get('predecessor_context',request['module_context'])
            assert 'execution_status' not in FrozenRecord.from_dict(public).encoded
        count=len(final.get('retained_branches',[]))
        if row.cell.coverage_id=='Q5.3':
            enabled='M4' in row.cell.runtime_arm.data()['enabled']
            expected=1 if (enabled and row.cell.variant=='same_mechanism') or (not enabled and row.cell.variant=='title') else 2
            assert count==expected
            assert [b['hypothesis_id'] for b in final['retained_branches']]==['h'+str(i) for i in range(expected)]
            actual_output=json.loads(row.solver.execution.record.data()['stdout'])
            assert actual_output=={'row_count':1,'branches':['h'+str(i) for i in range(expected)]}
        observations.append({'cell_key':list(row.cell.key),'retained_branch_count':count,
                             'status':row.status,'execution_digest':row.solver.execution.content_hash})
    (root/'independent-grid-observations.json').write_text(json.dumps(observations,indent=2),encoding='utf-8')


@pytest.mark.parametrize('fault',['artifact','request','registry','response','arm_stage','source'])
def test_prediction_projection_rejects_rehashed_false_provenance(prediction_grid,fault):
    from research_loop.modular.linked_public_projection import project_linked_public_context
    from research_loop.ontology import ContractError
    result,_,_=prediction_grid
    row=next(r for r in result.linked_results if r.cell.coverage_id=='Q5.3' and r.cell.variant=='opposite_prediction'
             and 'M4' in r.cell.runtime_arm.data()['enabled'])
    body=row.provenance.data()
    stage={r['stage']:r['data'] for r in body['mechanism_stages']}
    if fault=='artifact':stage['prediction_artifacts']['artifacts']['deduplication']['retained_branches']=[]
    elif fault=='registry':stage['prediction_registry_observation']['events']=[]
    elif fault=='arm_stage':
        entry=next(s for s in body['mechanism_stages'] if s['stage']=='stage_1')
        entry['stage']='operation_m4_control';entry['data']['stage']='operation_m4_control'
    elif fault=='response':
        call=body['responses'][0];call['response']['kept_proposal_ids']=['h0']
        call['response_digest']=FrozenRecord.from_dict(call['response']).content_hash
    else:
        call=body['responses'][0]
        if fault=='request':call['request']['module_context']['retained_proposal_ids']=['h0']
        else:call['request']['module_context']['public_evidence']['source_id']='foreign-source'
        call['request_digest']=FrozenRecord.from_dict(call['request']).content_hash
    with pytest.raises(ContractError):
        project_linked_public_context(provenance=FrozenRecord.from_dict(body),cell=row.cell,
            task=result.compiled.tasks[row.cell.task_digest],scenario=result.compiled.scenarios[row.cell.key])


def test_changed_persisted_registry_is_rejected_without_touching_original(prediction_grid,tmp_path):
    import shutil
    from dataclasses import replace
    from research_loop.modular.benchmark_cell import verified_mechanism_provenance
    from research_loop.modular.linked_public_projection import project_linked_public_context
    from research_loop.ontology import ContractError
    result,_,_=prediction_grid
    row=next(r for r in result.linked_results if r.cell.coverage_id=='Q5.3' and r.cell.variant=='opposite_prediction'
             and 'M4' in r.cell.runtime_arm.data()['enabled'])
    copy=tmp_path/'copied-closed-mechanism'
    shutil.copytree(row.mechanism.runtime.trace_path.parent,copy)
    (copy/'predictions.jsonl').write_bytes(b'')
    runtime=replace(row.mechanism.runtime,trace_path=copy/'trace.jsonl')
    mechanism=replace(row.mechanism,runtime=runtime)
    task=result.compiled.tasks[row.cell.task_digest];scenario=result.compiled.scenarios[row.cell.key]
    provenance=verified_mechanism_provenance(cell=row.cell,task=task,scenario=scenario,
        package=result.compiled.packages[row.cell.runtime_arm.content_hash],mechanism=mechanism)
    with pytest.raises(ContractError,match='persisted registry'):
        project_linked_public_context(provenance=provenance,cell=row.cell,task=task,scenario=scenario)


def test_dedup_response_failure_keeps_all_twenty_denominators(tmp_path,monkeypatch):
    from research_loop.modular.runtime import AuditVerifier
    from research_loop.modular.train_controller import run_train_panel
    snapshot,custody,frozen,_=frozen_config(tmp_path)
    def fail(request):
        return FrozenRecord.from_dict({'kept_proposal_ids':['foreign']}) if request.data()['slot']=='dedup' else response_factory(request)
    port=model_port(tmp_path/'port',monkeypatch,max_calls=96,max_tokens=300,schemas=frozen.data()['schemas'],response_factory=fail)
    result=run_train_panel(frozen,custody=custody,snapshot_root=snapshot,export_root=tmp_path/'export',run_root=tmp_path/'run',
        model=port,audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}))
    assert len(result.runtimes)==len(result.linked_results)==20
    assert sum(r.status=='linked_succeeded' for r in result.linked_results)==8
    assert sum(r.status=='mechanism_failed' for r in result.linked_results)==12
    assert len(port.ledger['calls'])==60 and result.receipt.data()['execution_status']=='execution_incomplete'


@pytest.mark.parametrize('coverage,variant', [('Q3.2','joint'), ('Q3.2','separate'), ('Q5.3','opposite_prediction')])
@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('fault', ['late_freeze', 'early_aggregate', 'reversed_artifacts', 'extra_aggregate'])
def test_actual_rehashed_chronology_rejected(prediction_grid,tmp_path,coverage,variant,enabled,fault):
    import hashlib
    import shutil
    from dataclasses import replace
    from research_loop.modular.benchmark_cell import verified_mechanism_provenance
    from research_loop.modular.panel_receipts import PanelReceiptVerifier
    from research_loop.ontology import ContractError
    from test_modular_combination_benchmark_driver import _rewrite_trace
    result,_,_=prediction_grid
    row=next(r for r in result.linked_results if r.cell.coverage_id==coverage and r.cell.variant==variant
             and ('M4' in r.cell.runtime_arm.data()['enabled'])==enabled)
    original=row.mechanism.runtime.trace_path.parent
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in original.iterdir() if p.is_file()}
    copy=tmp_path/'closed-mechanism'
    shutil.copytree(original,copy)
    def reorder(trace):
        operation=next(e for e in trace if e['stage']=='modular_workflow'
                       and e['data'].get('stage') in {'stage_1','operation_m4_control'})
        artifact=next(e for e in trace if e['stage']=='modular_workflow'
                      and e['data'].get('stage')=='prediction_artifacts')
        if fault=='late_freeze':
            trace.remove(operation);trace.remove(artifact)
            last=max(i for i,e in enumerate(trace) if e['stage']=='model_response')
            trace[last+1:last+1]=[operation,artifact]
        elif fault=='early_aggregate':
            trace.remove(operation)
            responses=[e for e in trace if e['stage']=='model_response']
            trace.insert(trace.index(responses[-2]),operation)
        elif fault=='reversed_artifacts':
            trace.remove(artifact);trace.insert(trace.index(operation),artifact)
        else:
            trace.insert(trace.index(operation),dict(operation))
    digest=_rewrite_trace(copy/'trace.jsonl',reorder)
    runtime=replace(row.mechanism.runtime,trace_path=copy/'trace.jsonl',trace_digest=digest)
    # These attacks retain the existing general receipt/hash-chain validity.
    PanelReceiptVerifier()._verify_runtime(runtime,row.cell)
    with pytest.raises(ContractError,match='prediction chronology'):
        verified_mechanism_provenance(cell=row.cell,task=result.compiled.tasks[row.cell.task_digest],
            scenario=result.compiled.scenarios[row.cell.key],package=result.compiled.packages[row.cell.runtime_arm.content_hash],
            mechanism=replace(row.mechanism,runtime=runtime))
    assert hashes=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in original.iterdir() if p.is_file()}


def test_every_success_reaches_anonymous_independent_primary_score(prediction_grid):
    import hashlib
    from evaluation.modular.scoring_service import FrozenRubricTransport
    from evaluation.modular.linked_scoring import (LinkedExecutionAuthority, LinkedAdaptedScoringService,
        issue_linked_score_input, verify_linked_adapted_receipt)
    result,_,root=prediction_grid
    execution=LinkedExecutionAuthority('fixture-execution',b'x'*32)
    authority=LinkedExecutionAuthority('fixture-scoring',b'y'*32)
    scorer=ScorerConfig.create(benchmark='core_pair',evaluator_id='prediction-fixture',version='v1',
        rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest())
    seen=[]
    def resolve(handle,benchmark):
        return FrozenRecord.from_dict({'schema':'train-only-rubric-reference-v1','split':'train','benchmark':benchmark,
            'task_handle_digest':hashlib.sha256(handle.encode()).hexdigest(),'identity_digest':handle,
            'task_context':'Synthetic public data analysis','references':[{'fixture_reference':True}]})
    def evaluate(request):
        body=request.data();seen.append(body)
        assert all(label not in body['prompt'] for label in ('Q3.2','Q5.3','same_mechanism','opposite_prediction',
            'controller_truth','CONTROLLER_ONLY_REFERENCE_MARKER','mechanism_provenance',str(root)))
        dimensions={'context':1,'variable_f1':1,'relation':1} if body['benchmark']=='discoverybench' else {'cvars':2,'transform':2,'model':2}
        return FrozenRecord.from_dict({**dimensions,'reason':'Synthetic scorer transport, no scientific calibration.'})
    endpoint=FrozenBenchmarkRubricEndpoint(resolver=resolve,evaluator=evaluate,
        evaluator_id='prediction-fixture',evaluator_version='v1')
    handles={FrozenRecord.from_dict(r.cell.identity.data()).content_hash:FrozenRecord.from_dict(r.cell.identity.data()).content_hash
             for r in result.linked_results}
    service=LinkedAdaptedScoringService(config=scorer,evaluator=FrozenRubricTransport(endpoint),
        execution_authority_keys={execution.authority_id:execution.key},task_handles=handles,scorer_authority=authority)
    receipts=[]
    for row in result.linked_results:
        source=issue_linked_score_input(panel=result.compiled.panel,result=row,task=result.compiled.tasks[row.cell.task_digest],
            scenario=result.compiled.scenarios[row.cell.key],package=result.compiled.packages[row.cell.runtime_arm.content_hash],
            authority=execution)
        score=service.score_linked(panel=result.compiled.panel,cell=row.cell,linked_input=source)
        verified=verify_linked_adapted_receipt(score,authority_keys={authority.authority_id:authority.key},config=scorer,
            panel=result.compiled.panel,cell=row.cell,linked_input=source,execution_authority_keys={execution.authority_id:execution.key})
        assert verified.data()['scientific_validity']=='not_measured'
        assert row.solver.analysis.data()['analysis'] in seen[-1]['prompt']
        receipts.append(score.receipt.data())
    assert len(seen)==len(receipts)==20
    (root/'signed-primary-fixture-scores.json').write_text(json.dumps(receipts,indent=2),encoding='utf-8')
