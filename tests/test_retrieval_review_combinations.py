import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from evaluation.modular.train_io import TrainPacketExporter
from evaluation.modular.scorer_process import CombinationScorerProcessClient, serialize_combination_panel
from research_loop.modular.retrieval_review_combination_driver import (DESIGNS, SLOTS, BUDGET, registered_design,
    freeze_material, admission_receipt, verify_retrieval_review_cell)
from research_loop.modular.retrieval_review_combination_controller import (FrozenRetrievalReviewConfig,
    compile_retrieval_review_panels, run_retrieval_review_panels, _arms)
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError, canonical
from test_modular_combination_train_controller import _fixture as old_fixture, EXECUTION, SCORER, ANALYSIS
from test_modular_combination_benchmark_driver import _plan
from test_modular_train_controller import model_port, SCENARIO, REVIEW, FINAL
from test_scorer_process import _store, _command

SCHEMAS = dict(zip(SLOTS, (SCENARIO, REVIEW, REVIEW, ANALYSIS, FINAL)))


def test_registered_combination_scope():
    from research_loop.modular.retrieval_review_combination_driver import DESIGNS, registered_design
    assert {name: sum(c['status'] == 'executable' for c in registered_design(name, 'a'*64).data()['cells'])
            for name in DESIGNS} == {'pair:M4+M6': 4, 'pair:M5+M6': 4, 'triple:M4+M5+M6': 8}


def fixture(root):
    snapshot, custody, packets, old, rubric, _ = old_fixture(root)
    store, handles, manifest_sha = _store(root, {'tasks': {p.task.content_hash:p.task for p in packets}})
    b = old.data(); b['schema'] = 'retrieval-review-combination-train-config-v1'
    b['stage'] = 'public-custody-combination'; b['max_calls'] = 160; b['max_tokens'] = 800; b['schemas'] = SCHEMAS
    package = next(iter(b['packages_by_arm'].values()))
    b['packages_by_arm'] = {h:package for h in _arms(b['baseline_digest'])}
    for p in packets:
        b['task_bindings'][f'{p.task.identity.benchmark}:{p.task.identity.task_id}']['csv_byte_count'] = len(p.csv_path.read_bytes())
    b['scorer_handle_bindings'] = {k:hashlib.sha256(v.encode()).hexdigest() for k,v in handles.items()}
    b['allocation'].update(model_slots_per_cell=list(SLOTS), scorer_call_limit=32, source_calls_per_cell=3,
        source_cap_per_cell=3, context_bytes_per_cell=4096)
    # Deliberately coded PRIVATE origin identifiers exercise projection sanitization.
    sources = [{'source_id': f'private-variant-{i}', 'root_source_id': f'private-root-{i}', 'lane': lane, 'text': text}
        for i,(lane,text) in enumerate((('support','Observe the mean of x.'), ('counter','A positive mean alone does not establish increase.'),
            ('method','Compare the mean with the prespecified value zero.')),1)]
    b['materials_by_task'] = {p.task.content_hash:freeze_material(p.task, sources, 'Which observations distinguish the public explanations?').data() for p in packets}
    config = FrozenRetrievalReviewConfig(FrozenRecord.from_dict(b)); compiled = compile_retrieval_review_panels(config, packets)
    (root/'execution.key').write_bytes(EXECUTION.key); (root/'score.key').write_bytes(SCORER.key)
    service_args = {}
    for index,panel in enumerate(compiled.panels):
        server = {'schema':'retrieval-review-scorer-process-config-v1','panel':serialize_combination_panel(panel,retrieval_review=True),
            'scorer_config':rubric.record.data(),'scorer_config_digest':rubric.digest,
            'train_reference_store':{'root':str(store.resolve()),'manifest_sha256':manifest_sha,
                'inventory_digest':packets[0].task.identity.dataset_version,'split_digest':panel.split_digest},
            'task_handles':handles,'execution_authority_key_files':{EXECUTION.authority_id:str((root/'execution.key').resolve())},
            'scorer_authority':{'id':SCORER.authority_id,'key_file':str((root/'score.key').resolve())},'evaluator':{}}
        path=root/f'server-{index}.json'; path.write_text(canonical(server),encoding='utf-8')
        service_args[panel.obligation_id] = dict(panel=panel,config=rubric,retrieval_review=True,command=_command(path,root/f'worker-{index}.jsonl'),
            journal_path=root/f'client-{index}.jsonl',task_handle_bindings=b['scorer_handle_bindings'],
            execution_authority_keys={EXECUTION.authority_id:EXECUTION.key},scorer_authority_keys={SCORER.authority_id:SCORER.key},
            environment={**os.environ,'PYTHONIOENCODING':'gbk'})
    return snapshot,custody,config,compiled,service_args


class Provider:
    def __init__(self, root, fail=False): self.root,self.fail,self.calls=root,fail,[]
    def search(self, *, lane, query, source_bundle, call_limit, source_limit):
        # Actual caller observes reservation bytes already persisted before entering I/O.
        pending=[]
        for path in (self.root/'run'/'cells').glob('*/trace.jsonl'):
            last=json.loads(path.read_text(encoding='utf-8').splitlines()[-1])
            if last['stage']=='q8_retrieval_request': pending.append(last['data'])
        assert len(pending)==1 and pending[0]['query']==query.data() and pending[0]['reservation']=={'provider_calls':1,'source_slots':1}
        self.calls.append((lane,query.data(),source_limit))
        assert call_limit==source_limit==1
        documents=[d for d in source_bundle.documents if d.lane==lane]
        if self.fail:
            yield documents[0]
            error=RuntimeError('partial public provider failure'); error.cost=7; raise error
        # Same pool and per-lane opportunities; neutral search misses the targeted counter source.
        if lane!='counter' or query.data()['intent'].startswith('Seek support,'):
            yield documents[0]


def model_response(seen, fail=False):
    def respond(request):
        b=request.data(); seen.append(b); context=b['module_context']; slot=b['slot']
        assert all(x not in request.encoded for x in ('private-variant-', 'private-root-', 'pair:M4', 'pair:M5', 'triple:M4',
            '"enabled"','"arm_id"','"contrast"','PRIVATE-REFERENCE-SENTINEL','"scorer_handle_bindings"'))
        def check_ids(value):
            if isinstance(value,dict):
                for k,v in value.items():
                    if k=='source_id': assert v in ('s001','s002','s003')
                    if k=='root_source_id': assert v in ('r001','r002','r003')
                    check_ids(v)
            elif isinstance(value,list):
                for v in value: check_ids(v)
        check_ids(b)
        if slot=='proposal':
            plan=_plan(); plan['question']='Which observation distinguishes the public explanations?'
            for branch in plan['branches']:
                branch['mechanism']='Explanation of the available public measurements'
            return FrozenRecord.from_dict(plan)
        if slot in ('review_first','review_second'):
            source=context['retrieval']['by_lane']; prior=context['prior_responses']
            concern=' '.join(d['text']['text'] for d in source['counter']) or 'Inspect the observed public mean.'
            if prior: concern='Follow up: '+prior[0]['uncertainty']
            return FrozenRecord.from_dict({'assessment':'concern','evidence_refs':[],'counterexamples':[],
                'uncertainty':context['question']+' '+concern})
        if slot=='analysis_program':
            if fail: raise RuntimeError('synthetic transport failure')
            joint=context['joint_mechanism']; plan=joint['prediction_plan']
            # The actual program consumes the prediction observables, review text and retrieved text.
            metadata={'predictions':[] if plan is None else [p for branch in plan['branches'] for p in branch['predictions']],
                'notes':joint['ordinary_notes'], 'reviews':joint['review_responses'], 'sources':joint['retrieval']['by_lane']}
            program="import csv,json\nwith open('/input/public_csv',newline='') as f: rows=list(csv.DictReader(f))\nmean=sum(float(r['x']) for r in rows)/len(rows)\nm="+repr(metadata)+"\nchecks=[{'observable':p['observable'],'direction':p['direction'],'observed_mean':mean} for p in m['predictions']]\nprint(json.dumps({'mean':mean,'checks':checks,'notes':m['notes'],'reviews':m['reviews'],'sources':m['sources']},sort_keys=True))"
            return FrozenRecord.from_dict({'analysis':'Compute the public mean and report the supplied prediction observations and review concerns.','program':program})
        observed=json.loads(b['execution_feedback'][0]['stdout']); assert observed['mean']==1.0
        return FrozenRecord.from_dict({'objective_digest':context['required_objective_digest'],'outcome':'unknown','evidence_ids':[],
            'conclusion':'Public mean 1.0; observations and open concerns: '+canonical(observed),'programme_complete':False})
    return respond


def run(root, monkeypatch, *, fail_provider=False, fail_model=False):
    setup=fixture(root); snapshot,custody,config,compiled,args=setup
    seen=[]; port=model_port(root/'port',monkeypatch,max_calls=160,max_tokens=800,schemas=SCHEMAS,
        response_factory=model_response(seen,fail_model))
    provider=Provider(root,fail_provider); services={}
    try:
        for name,kw in args.items(): services[name]=CombinationScorerProcessClient(**kw)
        result=run_retrieval_review_panels(config,custody=custody,snapshot_root=snapshot,export_root=root/'export',run_root=root/'run',
            model=port,audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),provider=provider,admission_port=admission_receipt,
            execution_authority=EXECUTION,scoring_services=services,scorer_authority_keys={SCORER.authority_id:SCORER.key})
    finally:
        for service in services.values(): service.close()
    return result,port,seen,provider,setup


@pytest.fixture(scope='module')
def grid(tmp_path_factory):
    root=tmp_path_factory.mktemp('retrieval-grid')
    with pytest.MonkeyPatch.context() as patch:
        result=run(root,patch)
    return root,*result


def verify_all(result):
    tasks={p.task.content_hash:p.task for p in result.compiled.packets}
    for panel in result.compiled.panels:
        for executed in [r for r in result.results if r and r.cell in panel.cells]:
            verify_retrieval_review_cell(executed,panel=panel,task=tasks[executed.cell.task_digest],
                scenario=result.compiled.scenarios[executed.cell.key],package=result.compiled.packages[executed.cell.runtime_arm.content_hash],
                material=result.compiled.materials[executed.cell.task_digest])


def test_full_registry_custody_shared_session_grid_real_docker_and_scorer_processes(grid):
    root,result,port,seen,provider,setup=grid
    verify_all(result)
    receipt=result.receipt.data()
    assert receipt['expected_cells']==receipt['observed_cells']==len(result.attempts)==32
    assert len(result.scores)==32, [r.data() for r in result.attempts if r.data()['status']!='succeeded']
    assert receipt['failed_cells']==receipt['blocked_cells']==0
    assert len(seen)==len(port.ledger['calls'])==160 and len(provider.calls)==96
    assert receipt['actual_docker_attempts']==32 and receipt['source_calls']==96
    assert receipt['pruned_cells']==[] and receipt['scientific_effectiveness_proven'] is receipt['validation_opened'] is False
    assert receipt['mechanism_endpoint_independently_scored'] is False
    assert all(c.data()['status']=='estimated' for c in result.contrasts)
    for panel in result.compiled.panels:
        cells=[r for r in result.results if r.cell in panel.cells]
        assert len(cells)==(16 if len(DESIGNS[panel.obligation_id])==3 else 8)
        assert {r.cell.identity.benchmark for r in cells}=={'blade','discoverybench'}
        for r in cells:
            enabled=r.cell.runtime_arm.data()['enabled']; observed=json.loads(r.solver.execution.record.data()['stdout'])
            assert len(observed['checks'])==(3 if 'M4' in enabled else 0)
            assert len(observed['sources']['counter'])==(1 if 'M6' in enabled else 0)
            assert ('Follow up:' in observed['reviews'][1]['uncertainty'])==('M5' not in enabled)
            assert r.solver.session.sidecar==r.runtime.trace_path.parent and r.solver.answer.data()['programme_complete'] is False
        for benchmark in ('blade','discoverybench'):
            outputs=[r.solver.execution.record.data()['stdout'] for r in cells if r.cell.identity.benchmark==benchmark]
            assert len(set(outputs))==len(outputs)  # actual context/program output differs, not only hashes
    for i in range(3):
        for prefix in ('client','worker'):
            text=(root/f'{prefix}-{i}.jsonl').read_text(encoding='utf-8')
            assert 'PRIVATE-REFERENCE-SENTINEL' not in text
            assert [json.loads(line)['status'] for line in text.splitlines()]==['reserved','succeeded']*(16 if i==2 else 8)


@pytest.mark.parametrize('failure',['partial_provider','model'])
def test_failures_preserve_complete_grid_budget_unknown_cost_and_no_scores(tmp_path,monkeypatch,failure):
    result,port,seen,provider,_=run(tmp_path,monkeypatch,fail_provider=failure=='partial_provider',fail_model=failure=='model')
    verify_all(result)
    b=result.receipt.data()
    assert b['expected_cells']==b['observed_cells']==len(result.attempts)==32 and b['pruned_cells']==[]
    assert b['scored_cells']==b['actual_docker_attempts']==0 and all(c.data()['status']=='inconclusive' for c in result.contrasts)
    if failure=='partial_provider':
        assert len(provider.calls)==32 and len(seen)==0 and b['failed_cells']==32
        assert b['unused_source_call_opportunities']==64 and b['source_items']==32
        for a in result.attempts:
            f=a.data()['source_failures'][0]
            assert f['reported_cost']==7 and f['returned_before_failure']==1
            assert f['verified_external_cost']=={'units':None,'status':'unknown'}
    else:
        assert len(seen)==4 and b['blocked_cells']==31 and len(provider.calls)==3
        assert b['actual_model_usage']['model_usage_incomplete'] is True
