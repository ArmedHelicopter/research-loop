"""Public synthetic train shadow operations; never create validation approval."""
import json
import pytest
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.modules.improvement import CandidatePackage,TrainingManifest
from research_loop.modular.modules.improvement import AcceptanceAuthority,AcceptanceReceipt,ExecutionRuntime
from research_loop.modular.deployment import FileDeploymentPort
from research_loop.modular.metaprogram_training import metaprogram_schemas,model_configuration
from research_loop.modular.train_operations import (FrozenTrainOperationPlan,TrainOperationAuthority,
    TrainStagingAuthorization,check_existing_production_acceptance,run_train_operations,verify_train_operations)
from research_loop.ontology import ContractError
from test_modular_metaprogram_training import fixture
from test_modular_train_controller import model_port


def operation_fixture(tmp_path,monkeypatch,experiment,feedback_fault=None):
    original,args,_,_=fixture(tmp_path,monkeypatch,max_calls=240)
    parent=CandidatePackage.create(parent_digest=None,
        manifest=TrainingManifest(
            FrozenRecord.from_dict(original.parent.record.data()['training_manifest'])),
        changes={'prompt':{'instructions':'Use statistic=sum'}},search_cost=0)
    seen=[];feedback_calls=[]
    def model(request):
        body=request.data();seen.append(body)
        assert all(marker not in request.encoded for marker in ('"arm_id"','"variant"','"authority"','"signature"','"argv"'))
        if body['slot']=='builder_proposal':
            history=body['module_context']['public_history']
            value='mean'
            if len(history)>2:
                prior=json.loads(history[-1]['observations']['stdout'])
                value='sum' if prior['statistic']=='mean' else 'mean'
            return FrozenRecord.from_dict({'entrypoint':'emit_literal_change_v1','surface':'memory','key':'lesson','value':'Use statistic='+value})
        if body['slot']=='analysis_program':
            context=body['module_context']['predecessor_context']
            assert 'operation_observation' in context
            value=(context['instructions'] or context['memory_lesson']).split('=')[1]
            return FrozenRecord.from_dict({'analysis':'consume actual '+value,'program':
                "import csv,json\nwith open('/input/public_csv') as f: xs=[float(x['x']) for x in csv.DictReader(f)]\n"
                +"print(json.dumps({'statistic':"+repr(value)+",'value':sum(xs)"+('/len(xs)' if value=='mean' else '')+"}))"})
        return FrozenRecord.from_dict({'objective_digest':body['module_context']['required_objective_digest'],
            'outcome':'unknown','evidence_ids':[],'conclusion':body['module_context']['execution_feedback'][0]['stdout'],'programme_complete':False})
    port=model_port(tmp_path/'operation-port',monkeypatch,max_calls=240,max_tokens=500,
        schemas=metaprogram_schemas(),response_factory=model)
    def feedback(request):
        feedback_calls.append(request)
        source=tmp_path/'stage'/'cells'/request.data()['subject']['cell_id']/'host-operation'/'operations.jsonl'
        reserved=json.loads(source.read_text(encoding='utf-8').splitlines()[-1])
        assert reserved['stage']=='feedback_reserved' and reserved['data']['request_digest']==request.content_hash
        assert reserved['data']['request']['limits']=={'calls':1,'max_units':2}
        if feedback_fault=='throw': raise OSError('controlled independent feedback failure')
        return FrozenRecord.from_dict({'subject_digest':request.content_hash if feedback_fault!='foreign' else '0'*64,
            'status':'ineligible','units':1})
    authority=TrainOperationAuthority('synthetic-host',b'host-only-train-secret-distinct-32',feedback=feedback if experiment=='Q6.5' else None)
    data=original.record.data()
    plan=FrozenTrainOperationPlan.freeze(targets=original.targets,histories=original.histories,parent=parent,
        fixed_builder=original.fixed_builder,experiment_id=experiment,baseline_digest=data['baseline_digest'],
        p0_control=FrozenRecord.from_dict(data['p0_control']),image=data['image'],model_config=model_configuration(port),authority=authority,
        feedback_rules=FrozenRecord.from_dict({'criterion':'Independent train-only feedback qualification; no scientific calibration inference','max_units':2}) if experiment=='Q6.5' else None)
    args.update(model=port,authority=authority)
    return plan,args,seen,feedback_calls


@pytest.mark.parametrize('experiment',['Q6.1','Q6.5','Q6.6'])
def test_full_operation_grids_execute_and_consume_actual_shadow_results(tmp_path,monkeypatch,experiment):
    plan,args,seen,feedback=operation_fixture(tmp_path,monkeypatch,experiment)
    run=run_train_operations(plan,**args)
    assert len(run.cells)=={'Q6.1':16,'Q6.5':16,'Q6.6':20}[experiment]
    assert verify_train_operations(run,plan=plan,authority=args['authority']).data()['observed_cells']==len(run.cells)
    declared=plan.record.data()['cells']
    for cell,result in zip(declared,run.cells):
        operation=json.loads((result.root/'host-operation'/'receipt.json').read_text(encoding='utf-8'))['record']
        assert operation['production_promotion']=='not_authorized'
        if experiment=='Q6.1': assert operation['status']=='rejected'
        blocked=experiment=='Q6.6' and cell['variant'] in {'drift','offline'}
        assert result.record.data()['actual']['docker_attempts']==(0 if blocked else 1)
        assert result.record.data()['status']==('failed' if blocked else 'succeeded')
        if blocked:
            assert operation['status']=='blocked' and not (result.root/'solver').exists()
        else:
            rows=[json.loads(x) for x in (result.root/'solver'/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
            response=json.loads(rows[-2]['data']['response']['conclusion'])
            selected=CandidatePackage(FrozenRecord.from_dict(operation['selected_package']))
            assert rows[0]['data']['package_digest']==selected.digest
            if experiment=='Q6.6' and cell['variant']=='rollback': assert response['statistic']=='sum'
            if experiment=='Q6.5':
                guarded=cell['variant']=='sealed_calibrated' and 'M9' in cell['arm']['enabled']
                assert response['statistic']==('sum' if guarded or cell['round']==2 else 'mean')
                if cell['round']==2:
                    # Actual history source binding and predecessor stdout are replayed by the controller verifier.
                    proposal=[json.loads(x) for x in (result.root/'proposal'/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
                    prior=proposal[1]['data']['request']['module_context']['public_history'][-1]
                    assert json.loads(prior['observations']['stdout'])['statistic']==('sum' if guarded else 'mean')
    if experiment=='Q6.5':
        assert len(feedback)==16 and run.receipt.data()['feedback_actual']=={'calls':16,'reported_units':16,'unknown_cost':False}
    assert run.receipt.data()['actual']['provider_calls']==(44 if experiment=='Q6.6' else 48)
    # A host MAC cannot substitute for an actual matching operation journal.
    path=run.cells[0].root/'host-operation'/'receipt.json';original=path.read_bytes()
    forged=json.loads(original);forged['record']['public']['status']='invented'
    forged['signature']=args['authority'].sign(FrozenRecord.from_dict(forged['record']))
    path.write_text(FrozenRecord.from_dict(forged).encoded,encoding='utf-8')
    with pytest.raises(ContractError): verify_train_operations(run,plan=plan,authority=args['authority'])
    path.write_bytes(original)


@pytest.mark.parametrize('fault',['throw','foreign'])
def test_feedback_unknown_keeps_attempts_cost_uncertainty_and_guarded_parent(tmp_path,monkeypatch,fault):
    plan,args,_,calls=operation_fixture(tmp_path,monkeypatch,'Q6.5',fault)
    run=run_train_operations(plan,**args)
    assert len(run.cells)==len(calls)==16 and run.receipt.data()['status']=='engineering_incomplete'
    assert run.receipt.data()['feedback_actual']['unknown_cost']
    for cell,result in zip(plan.record.data()['cells'],run.cells):
        receipt=json.loads((result.root/'host-operation'/'receipt.json').read_text(encoding='utf-8'))['record']
        assert receipt['feedback']['status']=='unknown'
        if cell['variant']=='sealed_calibrated' and 'M9' in cell['arm']['enabled']:
            assert receipt['selected_package']['changes']['prompt']['instructions']=='Use statistic=sum'


def test_operation_config_drift_refused_before_model_and_host_io(tmp_path,monkeypatch):
    plan,args,seen,calls=operation_fixture(tmp_path,monkeypatch,'Q6.5')
    args['authority']=TrainOperationAuthority('synthetic-host',b'other-host-private-key-32-bytes!!',feedback=lambda _:None)
    with pytest.raises(ContractError): run_train_operations(plan,**args)
    assert not seen and not calls and not args['run_root'].exists()


def test_staging_token_cannot_authorize_production_even_with_mistaken_key_reuse(tmp_path,monkeypatch):
    original,_,_,_=fixture(tmp_path,monkeypatch)
    key=b'independent-train-staging-key-32!!';authority=TrainOperationAuthority('stage',key)
    parent=original.parent
    candidate=CandidatePackage.create(parent_digest=parent.digest,
        manifest=TrainingManifest(FrozenRecord.from_dict(parent.record.data()['training_manifest'])),
        changes={'memory':{'lesson':'public change'}},search_cost=1)
    subject={'plan_digest':'a'*64,'cell_id':'b'*64,'candidate_digest':candidate.digest,
        'parent_digest':parent.digest,'task_digest':'c'*64}
    token=authority.staging_authorization(candidate,parent,subject)
    authority.verify_staging(token)
    def forbidden(_): pytest.fail('train-only test must not obtain validation approval')
    production=AcceptanceAuthority(key,b'other-independent-validator-key-32',forbidden)
    with pytest.raises(ContractError):
        check_existing_production_acceptance(token,candidate=candidate,active=parent,authority=production,source_verifier=forbidden)
    runtime=ExecutionRuntime(tmp_path/'shadow-production.sqlite',FileDeploymentPort(tmp_path/'shadow-production.json',parent),production,parent)
    try:
        with pytest.raises(ContractError): runtime.activate(token,candidate)
        with pytest.raises(ContractError): runtime.activate(AcceptanceReceipt(token.record,token.signature),candidate)
        assert runtime.active()==parent
    finally: runtime.close()


@pytest.mark.parametrize('fault',['domain','schema','missing','boolean_digest','subject','signature_type'])
def test_staging_contract_rejected_before_mac_for_bad_fields(monkeypatch,fault):
    authority=TrainOperationAuthority('synthetic-stage',b'stage-specific-private-key-32bytes')
    record={'schema':'train-staging-authorization-v1','domain':'train','candidate_digest':'a'*64,
        'expected_active_digest':'b'*64,'subject':{k:'c'*64 for k in ('plan_digest','cell_id','candidate_digest','parent_digest','task_digest')}}
    signature='d'*64
    if fault in {'domain','schema'}: record[fault]='foreign'
    elif fault=='missing': record.pop('candidate_digest')
    elif fault=='boolean_digest': record['candidate_digest']=True
    elif fault=='subject': record['subject']={}
    else: signature=b'not-a-string'
    def forbidden(_): pytest.fail('bad staging schema reached MAC verification')
    monkeypatch.setattr(authority,'_staging_signature',forbidden)
    with pytest.raises(ContractError): authority.verify_staging(TrainStagingAuthorization(FrozenRecord.from_dict(record),signature))
