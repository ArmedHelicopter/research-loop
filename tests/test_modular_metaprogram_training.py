"""Synthetic fixtures exercise actual prior journals, Codex process seam and Docker.

These recorded fixture runs are not scientific training-history qualification.
"""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from evaluation.modular.train_io import TrainPacketExporter
from research_loop.modular.benchmark_solver import run_benchmark_solve
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.modules.improvement import CandidatePackage, FrozenBuilderVersion, RestrictedBuilderPort, TrainingManifest
from research_loop.modular.panel_plan import executable_arms, obligation_grids
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.metaprogram_training import (
    FrozenTrainHistory, FrozenMetaTarget, FrozenMetaTrainingPlan,
    metaprogram_schemas, model_configuration, run_metaprogram_training, verify_metaprogram_training)
from research_loop.ontology import ContractError
from test_modular_train_controller import snapshot_and_custody, model_port

IMAGE='research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349'


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(tmp_path,monkeypatch,*,fault=None,surface='prompt',history_failure=False):
    snapshot,custody=snapshot_and_custody(tmp_path)
    packets=TrainPacketExporter(custody,snapshot,tmp_path/'export').export(['discoverybench:synth:train:family_1_1','blade:fish'])
    manifest=TrainingManifest.freeze([p.task.identity for p in packets])
    parent=CandidatePackage.create(parent_digest=None,manifest=manifest,changes={'prompt':{'instructions':'Public training parent'}},search_cost=0)
    control=FrozenRecord.from_dict({'always_enabled':True,'scope':'synthetic training'})
    grid=obligation_grids(('Q6.3',),baseline_digest='a'*64,p0_control=control)['Q6.3']
    historical_arm=next(iter(executable_arms(grid).values()))
    schemas=metaprogram_schemas()
    def failed_history_response(request):
        body=request.data()
        if body['slot']=='analysis_program':
            return FrozenRecord.from_dict({'analysis':'calculate the public x mean','program':"raise RuntimeError('retained previous training failure')"})
        return FrozenRecord.from_dict({'objective_digest':body['module_context']['required_objective_digest'],
            'outcome':'unknown','evidence_ids':[],'conclusion':'Previous execution failed; unresolved','programme_complete':False})
    history_port=model_port(tmp_path/'history-port',monkeypatch,max_calls=4,schemas={k:v for k,v in schemas.items() if k!='builder_proposal'},
        response_factory=failed_history_response if history_failure else None)
    histories=[];targets=[]
    history_root=tmp_path/'prior-runs';history_root.mkdir()
    broker=DockerExecutionBroker([tmp_path/'export',history_root])
    for packet in packets:
        objective=FrozenRecord.from_dict({'question':'describe the public x statistic'})
        actual=run_benchmark_solve(task=packet.task,public_inputs={'public_csv':packet.csv_path},image=IMAGE,
            package_digest=parent.digest,arm=historical_arm,objective=objective,sidecar=history_root/packet.task.identity.benchmark,
            broker=broker,model=history_port,audit_verifier=AuditVerifier({'unused-a':b'a'*32,'unused-b':b'b'*32}))
        assert actual.status==('execution_failed' if history_failure else 'execution_succeeded')
        trace=actual.session.sidecar/'trace.jsonl'
        histories.append(FrozenTrainHistory.freeze(packet.task,trace,expected_sha256=sha(trace),
            source_notes=FrozenRecord.from_dict({'origin':'recorded synthetic test execution','qualification':'not scientific training-history validation'})))
        targets.append(FrozenMetaTarget.freeze(packet.task,public_inputs={'public_csv':packet.csv_path},objective=objective))
    seen=[]
    def response(request):
        body=request.data();seen.append(body)
        if fault=='provider': raise OSError('controlled provider transport failure with unknown usage')
        for marker in ('"arm_id"','"variant"','"selected_builder"','"parent_package"','"training_manifest"','"argv"','"authority"'):
            assert marker not in request.encoded
        if body['slot']=='builder_proposal':
            history=body['module_context']['public_history']
            assert len(history)==2 and all(row['observations']['analysis']=='calculate the public x mean' for row in history)
            value='Use statistic=mean' if history[0]['observations']['analysis'].endswith('mean') else 'Use statistic=sum'
            return FrozenRecord.from_dict({'entrypoint':'emit_literal_change_v1','surface':surface,
                'key':'lesson' if surface=='memory' or fault=='proposal' else 'instructions','value':value})
        if body['slot']=='analysis_program':
            context=body['module_context']['predecessor_context']
            value=context['instructions'] or context['memory_lesson']
            statistic=value.split('=')[1]
            program=("import csv,json\nwith open('/input/public_csv') as f: xs=[float(r['x']) for r in csv.DictReader(f)]\n"
                +("raise RuntimeError('controlled synthetic failure')" if fault=='docker' else
                  "print(json.dumps({'statistic':"+repr(statistic)+",'value':sum(xs)"+('/len(xs)' if statistic=='mean' else '')+"}))"))
            return FrozenRecord.from_dict({'analysis':'Apply supplied public training instruction: '+value,'program':program})
        return FrozenRecord.from_dict({'objective_digest':body['module_context']['required_objective_digest'],
            'outcome':'unknown','evidence_ids':[],
            'conclusion':body['module_context']['execution_feedback'][0]['stdout'] or 'Execution failed; unresolved',
            'programme_complete':False})
    port=model_port(tmp_path/'stage-port',monkeypatch,max_calls=24,schemas=schemas,response_factory=response)
    fixed=FrozenBuilderVersion.freeze({'entrypoint':'emit_literal_change_v1','surface':surface,
        'key':'lesson' if surface=='memory' else 'instructions','value':'Use statistic=sum'})
    plan=FrozenMetaTrainingPlan.freeze(targets=targets,histories=histories,parent=parent,fixed_builder=fixed,
        baseline_digest='a'*64,p0_control=control,image=IMAGE,model_config=model_configuration(port))
    args={'run_root':tmp_path/'stage','model':port,'audit_verifier':AuditVerifier({'unused-a':b'a'*32,'unused-b':b'b'*32})}
    return plan,args,seen,history_port


@pytest.mark.parametrize('surface',['prompt','memory'])
def test_eight_cells_execute_real_builder_changes_in_subsequent_analysis_and_docker(tmp_path,monkeypatch,surface):
    plan,args,seen,history=fixture(tmp_path,monkeypatch,surface=surface)
    run=run_metaprogram_training(plan,**args)
    assert len(run.cells)==8 and len(seen)==24 and len(history.ledger['calls'])==4
    assert run.receipt.data()['status']=='engineering_complete'
    assert run.receipt.data()['scientific_effect']=='not_measured'
    assert run.receipt.data()['actual']['provider_calls']==24 and run.receipt.data()['actual']['reported_tokens']==48
    checked=verify_metaprogram_training(run,plan=plan)
    assert checked.data()['observed_cells']==8
    expected={c['cell_id']:c for c in plan.record.data()['cells']}
    for cell in run.cells:
        row=cell.record.data();declared=expected[row['cell_id']]
        adapted=declared['variant']=='train_proposed' and 'M9' in declared['arm']['enabled']
        assert row['actual']['builder_attempts']==row['actual']['docker_attempts']==1
        events=[json.loads(line) for line in (cell.root/'solver'/'trace.jsonl').read_text().splitlines()]
        answer=next(e['data']['response'] for e in events if e['stage']=='model_response' and 'conclusion' in e['data']['response'])
        assert json.loads(answer['conclusion'])['statistic']==('mean' if adapted else 'sum')
        requests=[e['data']['request'] for e in events if e['stage']=='model_request']
        assert len(requests)==2
        assert requests[0]['module_context']['predecessor_context']==requests[1]['module_context']['predecessor_context']
        assert ('Use statistic=mean' if adapted else 'Use statistic=sum') in json.dumps(requests[0])


@pytest.mark.parametrize('fault',['proposal','docker','builder'])
def test_failures_keep_full_eight_cell_denominator_and_actual_cost(tmp_path,monkeypatch,fault):
    plan,args,seen,_=fixture(tmp_path,monkeypatch,fault=fault)
    if fault=='builder':
        def fail(*a,**k): raise ContractError('controlled restricted builder failure')
        monkeypatch.setattr(RestrictedBuilderPort,'execute',fail)
    run=run_metaprogram_training(plan,**args)
    assert len(run.cells)==8 and run.receipt.data()['status']=='engineering_incomplete'
    assert all(c.record.data()['status']!='succeeded' for c in run.cells)
    count=24 if fault=='docker' else 8
    assert run.receipt.data()['actual']['provider_calls']==count
    assert run.receipt.data()['actual']['reported_tokens']==count*2
    assert run.receipt.data()['actual']['docker_attempts']==(8 if fault=='docker' else 0)
    assert run.receipt.data()['actual']['builder_attempts']==(0 if fault=='proposal' else 8)


@pytest.mark.parametrize('fault',['history_bytes','history_response','input_bytes','model_schema','budget','fake_history','validation_history'])
def test_frozen_inputs_fail_closed_before_any_stage_model_call(tmp_path,monkeypatch,fault):
    plan,args,seen,_=fixture(tmp_path,monkeypatch)
    if fault=='history_bytes': plan.histories[0].trace_path.write_bytes(plan.histories[0].trace_path.read_bytes()+b'\n')
    elif fault=='history_response':
        path=plan.histories[0].trace_path; rows=[json.loads(x) for x in path.read_text().splitlines()]
        rows[2]['data']['response']['analysis']='forged history'
        prior=None;lines=[]
        for index,row in enumerate(rows):
            row.update(sequence=index,previous=prior);frozen=FrozenRecord.from_dict(row);prior=frozen.content_hash;lines.append(frozen.encoded)
        path.write_text('\n'.join(lines)+'\n')
    elif fault=='input_bytes': next(iter(plan.targets[0].public_inputs.values())).write_bytes(b'x\n99\n')
    elif fault=='model_schema': args['model'].schemas['builder_proposal']['properties']['value']['type']='boolean'
    elif fault=='budget': args['model'].max_calls=23
    elif fault=='validation_history':
        history=plan.histories[0];foreign=replace(history.task,identity=replace(history.task.identity,domain='validation'))
        with pytest.raises(ContractError): FrozenTrainHistory.freeze(foreign,history.trace_path,expected_sha256=sha(history.trace_path))
        assert not seen
        return
    elif fault=='fake_history':
        with pytest.raises(ContractError): FrozenTrainHistory(plan.histories[0].task,plan.histories[0].trace_path,FrozenRecord.from_dict({'fixture':True}))
        return
    with pytest.raises(ContractError): run_metaprogram_training(plan,**args)
    assert not seen and not (args['run_root']).exists()


def test_readonly_stage_verifier_rejects_actual_candidate_or_solver_context_tampering(tmp_path,monkeypatch):
    plan,args,_,_=fixture(tmp_path,monkeypatch);run=run_metaprogram_training(plan,**args)
    path=run.cells[0].root/'candidate.json';original=path.read_bytes();body=json.loads(original)
    body['changes']['prompt']['instructions']='foreign'
    path.write_text(FrozenRecord.from_dict(body).encoded)
    with pytest.raises(ContractError): verify_metaprogram_training(run,plan=plan)
    path.write_bytes(original)
    path=run.cells[0].root/'solver'/'trace.jsonl';rows=[json.loads(x) for x in path.read_text().splitlines()]
    rows[1]['data']['request']['module_context']['predecessor_context']['instructions']='foreign'
    prior=None;lines=[]
    for index,row in enumerate(rows):
        row.update(sequence=index,previous=prior);frozen=FrozenRecord.from_dict(row);prior=frozen.content_hash;lines.append(frozen.encoded)
    path.write_text('\n'.join(lines)+'\n')
    with pytest.raises(ContractError): verify_metaprogram_training(run,plan=plan)


def test_unknown_provider_cost_does_not_retry_or_drop_unexecuted_cells(tmp_path,monkeypatch):
    plan,args,seen,_=fixture(tmp_path,monkeypatch,fault='provider')
    run=run_metaprogram_training(plan,**args)
    assert len(run.cells)==8 and len(seen)==1
    actual=run.receipt.data()['actual']
    assert actual['model_requests']==8 and actual['provider_calls']==1
    assert actual['unknown_cost'] and actual['provider_usage_incomplete']
    assert actual['reported_tokens']==0 and actual['builder_attempts']==actual['docker_attempts']==0
    assert run.receipt.data()['status']=='engineering_incomplete'


def test_real_failed_training_journals_remain_in_the_complete_history_whitelist(tmp_path,monkeypatch):
    plan,args,seen,_=fixture(tmp_path,monkeypatch,history_failure=True)
    assert all(h.binding.data()['public']['observations']['execution_status']=='failed' for h in plan.histories)
    run=run_metaprogram_training(plan,**args)
    assert len(run.cells)==8 and len(seen)==24
    proposals=[r for r in seen if r['slot']=='builder_proposal']
    assert all(len(r['module_context']['public_history'])==2 for r in proposals)
    assert all(all(h['observations']['execution_status']=='failed' for h in r['module_context']['public_history']) for r in proposals)
    assert run.receipt.data()['scientific_effect']=='not_measured'


def test_provider_output_hash_must_bind_actual_runtime_response_not_only_charge_bookkeeping(tmp_path,monkeypatch):
    from research_loop.modular.metaprogram_training import _proof
    plan,args,_,_=fixture(tmp_path,monkeypatch);run=run_metaprogram_training(plan,**args)
    ledger=json.loads(run.model_ledger_path.read_text());ledger['calls'][0]['output_hash']='0'*64
    run.model_ledger_path.write_text(json.dumps(ledger))
    first=run.cells[0];path=first.root/'phase.jsonl';rows=[json.loads(x) for x in path.read_text().splitlines()]
    charge=next(e for e in rows if e['stage']=='model_charge');charge['data']['provider_calls'][0]['output_hash']='0'*64
    prior=None;lines=[]
    for index,event in enumerate(rows):
        event.update(sequence=index,previous=prior);frozen=FrozenRecord.from_dict(event);prior=frozen.content_hash;lines.append(frozen.encoded)
    path.write_text('\n'.join(lines)+'\n')
    cell_record=FrozenRecord.from_dict({**first.record.data(),'phase_trace':_proof(path)})
    (first.root/'cell-receipt.json').write_text(cell_record.encoded)
    cells=(replace(first,record=cell_record),*run.cells[1:])
    receipt=FrozenRecord.from_dict({**run.receipt.data(),'model_ledger_sha256':sha(run.model_ledger_path),
        'cell_receipt_digests':[c.record.content_hash for c in cells]})
    (run.root/'training-receipt.json').write_text(receipt.encoded)
    changed=replace(run,cells=cells,receipt=receipt)
    with pytest.raises(ContractError,match='response differs from provider output'):
        verify_metaprogram_training(changed,plan=plan)


def test_foreign_builder_return_is_archived_and_never_reaches_solver(tmp_path,monkeypatch):
    plan,args,seen,_=fixture(tmp_path,monkeypatch)
    original=RestrictedBuilderPort.execute
    def foreign(port,builder,manifest,parent,**kwargs):
        candidate,receipt=original(port,builder,manifest,parent,**kwargs)
        changed=CandidatePackage.create(parent_digest=parent.digest,manifest=manifest,changes={'prompt':{'instructions':'foreign'}},search_cost=1)
        return changed,receipt
    monkeypatch.setattr(RestrictedBuilderPort,'execute',foreign)
    run=run_metaprogram_training(plan,**args)
    assert run.receipt.data()['status']=='engineering_incomplete' and len(seen)==8
    assert run.receipt.data()['actual']['builder_attempts']==8 and run.receipt.data()['actual']['docker_attempts']==0
    for cell in run.cells:
        phase=[json.loads(x) for x in (cell.root/'phase.jsonl').read_text().splitlines()]
        returned=next(e['data'] for e in phase if e['stage']=='builder_returned')
        assert returned['candidate']['changes']['prompt']['instructions']=='foreign'
        assert not (cell.root/'solver').exists()


def test_history_annotations_cannot_duplicate_one_actual_source_in_the_whitelist(tmp_path,monkeypatch):
    plan,args,seen,_=fixture(tmp_path,monkeypatch)
    source=plan.histories[0]
    duplicate=FrozenTrainHistory.freeze(source.task,source.trace_path,expected_sha256=sha(source.trace_path),
        source_notes=FrozenRecord.from_dict({'different_note':'does not create another source'}))
    with pytest.raises(ContractError,match='history.*whitelist|duplicate'):
        FrozenMetaTrainingPlan.freeze(targets=plan.targets,histories=(*plan.histories,duplicate),parent=plan.parent,
            fixed_builder=plan.fixed_builder,baseline_digest=plan.record.data()['baseline_digest'],
            p0_control=FrozenRecord.from_dict(plan.record.data()['p0_control']),image=IMAGE,
            model_config=FrozenRecord.from_dict(plan.record.data()['model_config']))
    assert not seen


def test_original_driver_failure_from_invalid_response_is_retained_as_failed_history(tmp_path,monkeypatch):
    plan,args,seen,_=fixture(tmp_path,monkeypatch)
    target=plan.targets[0]
    def invalid_analysis(request): return FrozenRecord.from_dict({'analysis':'','program':''})
    port=model_port(tmp_path/'invalid-history-port',monkeypatch,max_calls=2,
        schemas={k:v for k,v in metaprogram_schemas().items() if k!='builder_proposal'},response_factory=invalid_analysis)
    source_root=tmp_path/'invalid-history';source_root.mkdir()
    broker=DockerExecutionBroker([tmp_path/'export',source_root])
    actual=run_benchmark_solve(task=target.task,public_inputs=target.public_inputs,image=IMAGE,
        package_digest=plan.parent.digest,arm=FrozenRecord.from_dict(plan.record.data()['cells'][0]['arm']),
        objective=target.objective,sidecar=source_root/'run',broker=broker,model=port,
        audit_verifier=AuditVerifier({'unused-a':b'a'*32,'unused-b':b'b'*32}))
    assert actual.status=='analysis_rejected' and len(port.ledger['calls'])==1
    path=actual.session.sidecar/'trace.jsonl'
    history=FrozenTrainHistory.freeze(target.task,path,expected_sha256=sha(path))
    observation=history.binding.data()['public']['observations']
    assert observation['terminal']=='driver_failure' and observation['response_contract_valid']is False
    assert observation['analysis']is None and observation['execution_status']is None
    assert len(history.binding.data()['response_digests'])==1 and not seen
