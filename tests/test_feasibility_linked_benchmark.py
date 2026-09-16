"""All original Q5.1/Q5.2 arms: native peers, live Docker and private scorer."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from evaluation.modular.linked_scoring import issue_linked_score_input, verify_linked_adapted_receipt
from evaluation.modular.scoring_service import ScorerConfig, FrozenBenchmarkRubricEndpoint
from evaluation.modular.train_io import TrainPacketExporter
from research_loop.modular.benchmark_cell import verify_linked_benchmark_cell, restore_completed_benchmark_cell
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.feasibility_panel_drivers import freeze_feasibility_panel_bundle
from research_loop.modular.linked_feasibility_projection import derive_feasibility_replay
from research_loop.modular.linked_public_projection import project_linked_public_context
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.panel_plan import compile_train_panel, obligation_grids, executable_arms
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.train_controller import FrozenTrainControllerConfig, run_train_panel
from research_loop.ontology import ContractError, canonical
from helpers.headless_train_provider import headless_train_provider
from test_headless_train_controllers import _native_body, _response
from test_modular_feasibility_panel_drivers import _Authority, _item, _branches, _model
from test_modular_semantic_train_controller import _closed_shape
from test_modular_linked_train_controller import ANALYSIS, AUDIT
from test_modular_train_controller import config, snapshot_and_custody, FINAL
from test_headless_evaluator_factory import native_spec
from test_scorer_process import _config as scorer_config
from test_train_adapted_selection import EXEC, SCORER
from test_ordinary_headless_scoring import client


def setup(root, patch, *, fail=False):
    snapshot, custody = snapshot_and_custody(root)
    old = config(custody, snapshot, root).data()
    packets = TrainPacketExporter(custody, snapshot, root/'material').export(old['item_ids'])
    tasks = {p.task.content_hash:p.task for p in packets}; authority = _Authority(); bundles = {}
    for packet in packets:
        task, csv = packet.task, packet.csv_path
        bundles[task.content_hash] = freeze_feasibility_panel_bundle(task,
            q51={name:_item(task,csv,authority,level=i) for i,name in enumerate(
                ('subjective','data','minimal_run','measurement','independent'))},
            q52={'zero_exit_same_prediction':_item(task,csv,authority,branches=_branches(False)),
                 'negative_control':_item(task,csv,authority,branches=_branches(True))}).data()
    scopes=('Q5.1','Q5.2'); grids=obligation_grids(scopes,baseline_digest=old['baseline_digest'],p0_control=FrozenRecord.from_dict(old['p0_control']))
    package=next(iter(old['packages_by_arm'].values()))
    final=deepcopy(FINAL);final['properties']['outcome']['enum']=['unknown','invalid']
    schemas={'subjective':_closed_shape({'feasibility':'feasible','rationale':'assessment'}),
        'diagnostic':_closed_shape({'decision':'continue','rationale':'observations'}),
        'final':final,'analysis_program':ANALYSIS,'final_answer':FINAL}
    old.update(stage='feasibility-linked',scope_ids=list(scopes),evidence_by_task=bundles,
        packages_by_arm={arm.content_hash:package for grid in grids.values() for arm in executable_arms(grid).values()},
        budget={'model_calls':3,'execution_limit':1},max_calls=180,schemas=schemas,execution_mode='linked_benchmark_solve')
    seen=[]; mechanism=_model(seen)
    def response(request):
        if fail: raise OSError('synthetic producer unavailable before first response')
        b=request.data()
        if b['slot']=='analysis_program':
            material=b['module_context']['predecessor_context']['mechanism_material']
            assert material['kind']=='bounded_feasibility'
            assert material['scientific_effect']=='not_measured'
            return {'analysis':'Read the verified bounded diagnostic and count the actual public rows.',
                'program':"import csv,json\nwith open('/input/public_csv',newline='') as f: rows=list(csv.DictReader(f))\nprint(json.dumps({'rows':len(rows)}))"}
        if b['slot']=='final_answer': return _response(request)
        return mechanism(request)
    provider,calls,gets=headless_train_provider(root/'p',patch,schemas=schemas,max_calls=180,response=response,timeout_seconds=600)
    rubric=ScorerConfig.create(benchmark='core_pair',evaluator_id='fixture',version='v1',rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest())
    data=_native_body(old,provider);data['scorer']=rubric.record.data()
    frozen=FrozenTrainControllerConfig(FrozenRecord.from_dict(data))
    compiled=compile_train_panel(stage=data['stage'],scope_ids=scopes,tasks=tuple(tasks.values()),
        evidence_by_task={k:FrozenRecord.from_dict(v) for k,v in bundles.items()},budget=FrozenRecord.from_dict(data['budget']),
        baseline_digest=data['baseline_digest'],p0_control=FrozenRecord.from_dict(data['p0_control']),
        packages_by_arm={k:CandidatePackage(FrozenRecord.from_dict(v)) for k,v in data['packages_by_arm'].items()},
        scorer=rubric.record,acceptance_criteria=FrozenRecord.from_dict(data['acceptance_criteria']),replicates=('r1',))
    assert len(compiled.panel.cells)==36
    server=scorer_config(root,{'panel':compiled.panel,'tasks':tasks,'config':rubric})
    with pytest.MonkeyPatch.context() as private:
        spec,_,_=native_spec(root/'e',private)
    spec.update(max_calls=36,max_tokens=36*131072,timeout_seconds=600,evaluator_id='fixture',evaluator_version='v1')
    server['evaluator']=spec;path=root/'server.json';path.write_text(canonical(server),encoding='utf-8')
    return dict(root=root,snapshot=snapshot,custody=custody,provider=provider,calls=calls,gets=gets,
        rubric=rubric,frozen=frozen,compiled=compiled,server=server,path=path,authority=authority)


@pytest.fixture(scope='module')
def complete(tmp_path_factory):
    root=tmp_path_factory.mktemp('feasibility-linked')
    with pytest.MonkeyPatch.context() as patch:
        value=setup(root,patch);service=client(value)
        try:
            result=run_train_panel(value['frozen'],custody=value['custody'],snapshot_root=value['snapshot'],
                export_root=root/'export',run_root=root/'run',model=value['provider'],audit_verifier=AuditVerifier(AUDIT),
                feasibility_authority=value['authority'])
            value['result']=result
            assert result.receipt.data()['execution_status']=='engineering_complete'
            assert len(result.linked_results)==36 and len(value['calls'])==180
            assert len(value['authority'].calls)==160
            scores=[]
            for row in result.linked_results:
                task=result.compiled.tasks[row.cell.task_digest];scenario=result.compiled.scenarios[row.cell.key]
                package=result.compiled.packages[row.cell.runtime_arm.content_hash]
                assert verify_linked_benchmark_cell(row,task=task,scenario=scenario,package=package).data()['engineering_verified']
                assert json.loads(row.solver.execution.record.data()['stdout'])=={'rows':1}
                linked=issue_linked_score_input(panel=result.compiled.panel,result=row,task=task,scenario=scenario,package=package,authority=EXEC)
                score=service.submit(cell_key=row.cell.key,linked_input=linked)
                verify_linked_adapted_receipt(score,authority_keys={SCORER.authority_id:SCORER.key},config=value['rubric'],
                    panel=result.compiled.panel,cell=row.cell,linked_input=linked,execution_authority_keys={EXEC.authority_id:EXEC.key})
                scores.append(score)
            value['scores']=scores;value['closure']=service.finalize_headless_evaluator(receipts=scores)
            assert value['closure'].data()['body']['scope']['unscored_cell_count']==0
        finally: service.close()
        yield value


def test_all_original_variants_native_docker_scoring_and_independent_consumer(complete):
    value=complete; result=value['result']; observed=set()
    for row in result.linked_results:
        task=result.compiled.tasks[row.cell.task_digest];scenario=result.compiled.scenarios[row.cell.key]
        package=result.compiled.packages[row.cell.runtime_arm.content_hash]
        restored=restore_completed_benchmark_cell(cell=row.cell,task=task,scenario=scenario,package=package,
            runtime=row.mechanism.runtime,linked_receipt=row.receipt,solver_sidecar=row.solver.session.sidecar,
            public_inputs={'public_csv':next(p.csv_path for p in result.packets if p.task.content_hash==task.content_hash)})
        assert restored.receipt==row.receipt
        public=project_linked_public_context(provenance=row.provenance,cell=row.cell,task=task,scenario=scenario)
        observation=public.data()['mechanism_material']['observation']; enabled=row.cell.runtime_arm.data()['enabled']
        if 'M7' not in enabled: assert all(v is None for v in observation['stages'].values())
        if 'M4' not in enabled: assert all(v is None for v in observation['prediction'].values())
        if row.cell.coverage_id=='Q5.2' and row.cell.variant=='zero_exit_same_prediction' and 'M4' in enabled:
            assert public.data()['mechanism_material']['diagnostic']['decision']=='stop'
        encoded=public.encoded
        for forbidden in ('"authority_id"','"source_group"','"argv"','"variant"','"arm_id"','PRIVATE-REFERENCE-SENTINEL'):
            assert forbidden not in encoded
        observed.add((row.cell.identity.benchmark,row.cell.coverage_id,row.cell.variant,row.cell.arm_id))
    assert len(observed)==36
    for path in (value['root']/'client.jsonl',value['root']/'worker.jsonl'):
        assert 'PRIVATE-REFERENCE-SENTINEL' not in path.read_text(encoding='utf-8')
    (value['root']/'independent-readback.json').write_text(canonical({'cells':36,'producer_calls':180,
        'authority_calls':160,'docker_executions':72,'scores':[s.receipt.data() for s in value['scores']],
        'closure':value['closure'].data(),'scientific_effect':'not_measured','activation':False}),encoding='utf-8')


@pytest.mark.parametrize('fault',['missing','subject','response','order','masked','cross_cell','prediction_log'])
def test_original_replay_rejects_missing_tamper_and_cross_cell(complete,fault):
    result=complete['result'];row=next(r for r in result.linked_results if r.cell.coverage_id=='Q5.2' and r.cell.variant=='negative_control' and 'M4' in r.cell.runtime_arm.data()['enabled'])
    task=result.compiled.tasks[row.cell.task_digest];scenario=result.compiled.scenarios[row.cell.key]
    package=result.compiled.packages[row.cell.runtime_arm.content_hash]
    events=[json.loads(line) for line in row.mechanism.runtime.trace_path.read_text().splitlines()]
    if fault=='prediction_log':
        path=row.mechanism.runtime.trace_path.parent/'predictions.jsonl';raw=path.read_bytes()
        try:
            path.write_bytes(raw+b'{}\n')
            with pytest.raises(ContractError): verify_linked_benchmark_cell(row,task=task,scenario=scenario,package=package)
        finally:path.write_bytes(raw)
        return
    i=next(i for i,e in enumerate(events) if e['stage']=='feasibility_verifier_response')
    if fault=='missing': events.pop(i)
    elif fault=='subject': events[i]['data']['subject_digest']='0'*64
    elif fault=='response': events[i]['data']['receipt']['cost']['units']=999
    elif fault=='order': events[i-1],events[i]=events[i],events[i-1]
    elif fault=='masked':
        e=next(e for e in events if e['stage']=='modular_workflow' and e['data'].get('stage')=='stage_3')
        e['data']['public_observation']['prediction']['identifiable']=None
    elif fault=='cross_cell':
        cell=next(r.cell for r in result.linked_results if r.cell.coverage_id=='Q5.1')
        with pytest.raises(ContractError): derive_feasibility_replay(cell=cell,task=task,scenario=scenario,package=package,events=events)
        return
    with pytest.raises(ContractError): derive_feasibility_replay(cell=row.cell,task=task,scenario=scenario,package=package,events=events)


def test_failed_producer_retains_complete_36_cell_null_score_denominator(tmp_path,monkeypatch):
    value=setup(tmp_path,monkeypatch,fail=True);service=client(value)
    try:
        result=run_train_panel(value['frozen'],custody=value['custody'],snapshot_root=value['snapshot'],
            export_root=tmp_path/'export',run_root=tmp_path/'run',model=value['provider'],audit_verifier=AuditVerifier(AUDIT),
            feasibility_authority=value['authority'])
        assert result.receipt.data()['execution_status']!='engineering_complete'
        attempt=json.loads((tmp_path/'run'/'controller-attempt.json').read_text())
        assert len(attempt['cells'])==36
        assert all(r['status']!='succeeded' for r in attempt['cells'])
        assert not value['authority'].calls
        closure=service.finalize_headless_evaluator(receipts=[])
        assert closure.data()['body']['scope']['unscored_cell_count']==36
    finally:service.close()
