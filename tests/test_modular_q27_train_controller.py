"""Real custody/CodexModelPort/Docker/source-finish/replay integration on public fixtures."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from evaluation.modular.train_io import TrainPacketExporter
from research_loop.modular import panel_runner, train_controller
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.panel_plan import obligation_grids, executable_arms
from research_loop.modular.panel_receipts import PanelReceiptVerifier
from research_loop.modular.protocol_panel_driver import (
    ProtocolReplayAuthority, freeze_protocol_bundle, verify_protocol_replay_receipt)
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.train_controller import FrozenTrainControllerConfig, run_train_panel
from research_loop.ontology import ContractError
from test_modular_train_controller import snapshot_and_custody, config, model_port, FINAL
from test_modular_q27_protocol_panel_driver import _audit_port, _measurement, _execution, AUDIT_KEYS


def _fixture(tmp_path, monkeypatch, *, outcome='positive', blocked=False):
    snapshot,custody=snapshot_and_custody(tmp_path)
    base=config(custody,snapshot,tmp_path).data()
    packets=TrainPacketExporter(custody,snapshot,tmp_path/'q27-material').export(base['item_ids'])
    control=FrozenRecord.from_dict(base['p0_control'])
    grid=obligation_grids(('Q2.7',),baseline_digest=base['baseline_digest'],p0_control=control)['Q2.7']
    evidence={}
    for packet in packets:
        execution=_execution(); raw=packet.csv_path.read_bytes()
        execution.update(csv_bytes_hex=raw.hex(),csv_sha256=hashlib.sha256(raw).hexdigest())
        evidence[packet.task.content_hash]=freeze_protocol_bundle(packet.task,execution=execution,
            p0_fixed_control=grid,measurement_contract=_measurement(packet.task)).data()
    schema=json.loads(json.dumps(FINAL)); schema['properties']['outcome']['enum']=['positive','negative','unknown','invalid','withdrawn']
    package=next(iter(base['packages_by_arm'].values()))
    raw_config={**base,'schema':'train-panel-controller-v1','engineering_scope':'train_only_panel_engineering',
        'stage':'synthetic-q27-production','scope_ids':['Q2.7'],'evidence_by_task':evidence,
        'packages_by_arm':{arm.content_hash:package for arm in executable_arms(grid).values()},
        'max_calls':8,'schemas':{'final':schema},'budget':{'docker_attempts':1,'audit_calls':1,'model_calls':1}}
    frozen=FrozenTrainControllerConfig(FrozenRecord.from_dict(raw_config)); seen=[]; audit_calls=[]
    def response(request):
        row=request.data(); seen.append(row)
        for marker in ('"controller_input"','"variant"','"arm_id"','"csv_bytes_hex"','"mac"','"key"','ProtocolReplayAuthority'):
            assert marker not in request.encoded
        digest=row['module_context']['public_execution']['execution_digest']
        return FrozenRecord.from_dict({'objective_digest':row['module_context']['required_objective_digest'],
            'outcome':outcome,'evidence_ids':[] if blocked or outcome=='unknown' else [digest],
            'conclusion':'registered synthetic mean observation','programme_complete':False})
    port=model_port(tmp_path/'port',monkeypatch,max_calls=8,schemas={'final':schema},response_factory=response)
    args=dict(custody=custody,snapshot_root=snapshot,export_root=tmp_path/'export',run_root=tmp_path/'run',model=port,
        audit_verifier=AuditVerifier(AUDIT_KEYS),protocol_audit_port=_audit_port(audit_calls),
        protocol_replay_authority=ProtocolReplayAuthority('replay-host',b'r'*32))
    return frozen,args,seen,audit_calls


def _events(runtime):
    return [FrozenRecord(x).data() for x in runtime.trace_path.read_text().splitlines()]


def _trusted(result,authority):
    return train_controller.protocol_post_runtime_verifier(result.compiled,authority)


def test_actual_eight_cell_train_entry_has_strict_post_runtime_qualification(tmp_path,monkeypatch):
    frozen,args,seen,audits=_fixture(tmp_path,monkeypatch)
    result=run_train_panel(frozen,**args)
    assert len(result.packets)==2 and len(result.runtimes)==len(result.compiled.panel.cells)==8
    assert len(seen)==len(audits)==8 and len(args['model'].ledger['calls'])==8 and args['model'].ledger['tokens']==16
    assert result.receipt.data()['execution_status']=='engineering_complete'
    assert result.verdict.decision=='engineering_verified' and not result.verdict.scientific_verified
    for runtime in result.runtimes:
        assert runtime.status=='succeeded'
        events=_events(runtime); assert events[-1]['stage']=='final_decision' and events[-1]['data']['decision']=='proceed'
        assert sum(e['stage']=='execution_request' for e in events)==sum(e['stage']=='q27_audit_request' for e in events)==1
        post=FrozenRecord((runtime.trace_path.parent/'protocol-post-runtime.json').read_text().strip()).data()
        assert post['status']=='refused' and post['source_trace_digest']==runtime.trace_digest and post['source_output_digest']==runtime.output_digest
        assert result.compiled.scenarios[runtime.cell_key].data()['controller_input']['schema']=='q27-protocol-controller-v2'
    with pytest.raises(ContractError,match='post.runtime'):
        PanelReceiptVerifier().verify(result.compiled.panel,result.runtimes)
    verdict=PanelReceiptVerifier(post_runtime_verifier=_trusted(result,args['protocol_replay_authority'])).verify(result.compiled.panel,result.runtimes)
    assert verdict.observed_cells==8


@pytest.mark.parametrize('mode',['unknown','blocked','hook_error','malformed_verifier','post_storage_error','plan_storage_error'])
def test_post_finish_failure_keeps_original_terminal_and_full_denominator(tmp_path,monkeypatch,mode):
    frozen,args,seen,audits=_fixture(tmp_path,monkeypatch,outcome='unknown' if mode=='unknown' else 'positive',blocked=mode=='blocked')
    if mode=='hook_error':
        def fail(**kwargs): raise OSError('synthetic replay storage failure')
        monkeypatch.setattr(panel_runner,'verify_after_finish',fail)
    if mode in {'post_storage_error','plan_storage_error'}:
        original=panel_runner._exclusive_record
        def fail_storage(path,record):
            if path.name==('protocol-post-runtime.json' if mode=='post_storage_error' else 'call-plan.json'):
                raise OSError('synthetic host path must not enter public reason')
            return original(path,record)
        monkeypatch.setattr(panel_runner,'_exclusive_record',fail_storage)
    if mode=='malformed_verifier':
        monkeypatch.setattr(panel_runner,'verify_protocol_replay_receipt',lambda *a,**k:FrozenRecord.from_dict({'status':'refused'}))
    result=run_train_panel(frozen,**args)
    assert len(result.runtimes)==8 and all(x.status=='unscored' for x in result.runtimes)
    assert result.verdict.unscored==8 and result.verdict.decision=='engineering_incomplete'
    assert result.receipt.data()['execution_status']=='execution_incomplete' and len(seen)==len(audits)==8
    expected='unknown' if mode=='unknown' else 'blocked' if mode=='blocked' else 'proceed'
    for runtime in result.runtimes:
        events=_events(runtime); assert events[-1]['stage']=='final_decision' and events[-1]['data']['decision']==expected
        observed=FrozenRecord.from_dict({'responses':[e['data']['response'] for e in events if e['stage']=='model_response'],'terminal':events[-1]['data']}).content_hash
        assert runtime.output_digest==observed and runtime.failure_reason
        assert (runtime.trace_path.parent/'protocol-post-runtime.json').is_file() is (mode!='post_storage_error')
        assert 'synthetic host path' not in runtime.failure_reason


@pytest.mark.parametrize('bad',['audit_port','replay_authority','model_schema','budget','p0_config','broker','roots','allocation'])
def test_dependencies_and_frozen_config_reject_before_export_or_model(tmp_path,monkeypatch,bad):
    frozen,args,seen,audits=_fixture(tmp_path,monkeypatch)
    if bad=='audit_port': args['protocol_audit_port']=None
    elif bad=='replay_authority': args['protocol_replay_authority']=object()
    elif bad=='model_schema': args['model'].schemas['final']['properties']['outcome']['enum']=['unknown']
    elif bad=='budget':
        raw=frozen.data();raw['max_calls']=7
        frozen=FrozenTrainControllerConfig(FrozenRecord.from_dict(raw)); args['model'].max_calls=7
    elif bad=='allocation':
        raw=frozen.data();raw['budget']['audit_calls']=0
        with pytest.raises(ContractError): FrozenTrainControllerConfig(FrozenRecord.from_dict(raw))
        return
    elif bad=='p0_config':
        raw=frozen.data();raw['p0_control']={'foreign':'control'}
        with pytest.raises(ContractError): FrozenTrainControllerConfig(FrozenRecord.from_dict(raw))
        return
    elif bad=='broker':
        def fail(*a,**k): raise ContractError('synthetic broker allocation failure')
        monkeypatch.setattr(train_controller,'DockerExecutionBroker',fail)
    elif bad=='roots': args['run_root']=args['snapshot_root']/'unsafe-run'
    with pytest.raises(ContractError): run_train_panel(frozen,**args)
    assert not seen and not audits and not (tmp_path/'export').exists()
    if bad=='broker':
        attempt=json.loads((tmp_path/'run'/'controller-attempt.json').read_text())
        assert attempt['status']=='blocked_before_execution'


def test_caller_csv_cannot_replace_actual_custody_export(tmp_path,monkeypatch):
    frozen,args,seen,audits=_fixture(tmp_path,monkeypatch)
    raw=frozen.data()
    for bundle in raw['evidence_by_task'].values():
        data=b'x\n9\n';bundle['execution'].update(csv_bytes_hex=data.hex(),csv_sha256=hashlib.sha256(data).hexdigest(),csv_byte_count=len(data))
    frozen=FrozenTrainControllerConfig(FrozenRecord.from_dict(raw))
    with pytest.raises(ContractError,match='custody.*CSV|CSV.*custody'):
        run_train_panel(frozen,**args)
    assert not seen and not audits


def test_trusted_callback_cannot_qualify_wrong_or_empty_finding(tmp_path,monkeypatch):
    frozen,args,_,_=_fixture(tmp_path,monkeypatch); result=run_train_panel(frozen,**args)
    with pytest.raises(ContractError,match='post.runtime'):
        PanelReceiptVerifier(post_runtime_verifier=lambda *a:FrozenRecord.from_dict({'status':'refused'})).verify(result.compiled.panel,result.runtimes)
    receipt_path=result.runtimes[0].trace_path.parent/'q27-replay'/'receipt.json'
    changed=json.loads(receipt_path.read_text());changed['mac']='0'*64;receipt_path.write_text(FrozenRecord.from_dict(changed).encoded)
    with pytest.raises(ContractError):
        PanelReceiptVerifier(post_runtime_verifier=_trusted(result,args['protocol_replay_authority'])).verify(result.compiled.panel,result.runtimes)


@pytest.mark.parametrize('fault',['transport','partial','nonboolean','unknown_cost'])
def test_audit_usage_and_failure_denominator_survive_production_entry(tmp_path,monkeypatch,fault):
    frozen,args,seen,audits=_fixture(tmp_path,monkeypatch)
    args['protocol_audit_port']=_audit_port(audits,fault)
    result=run_train_panel(frozen,**args)
    assert len(audits)==len(result.runtimes)==8
    if fault=='unknown_cost':
        assert result.verdict.failures==0 and len(seen)==8
    else:
        assert result.verdict.failures==8 and not seen
        assert result.verdict.decision=='engineering_incomplete'
    for runtime in result.runtimes:
        events=_events(runtime)
        assert sum(e['stage']=='execution_request' for e in events)==1
        request=next(e for e in events if e['stage']=='q27_audit_request')
        actual=next(e for e in events if e['stage']==('q27_audit_result' if fault=='unknown_cost' else 'q27_audit_failure'))
        assert request['sequence']<actual['sequence'] and actual['data']['cost']['units'] is None
        if fault=='partial': assert actual['data']['reported_cost']['units']==2


def test_production_callback_rechecks_sidecar_and_call_plan_actual_bytes(tmp_path,monkeypatch):
    frozen,args,_,_=_fixture(tmp_path,monkeypatch); result=run_train_panel(frozen,**args)
    verifier=PanelReceiptVerifier(post_runtime_verifier=_trusted(result,args['protocol_replay_authority']))
    for name,field in [('protocol-post-runtime.json','receipt_digest'),('call-plan.json','protocol_replay')]:
        path=result.runtimes[0].trace_path.parent/name; original=path.read_bytes()
        value=json.loads(original);value[field]='foreign'
        path.write_text(FrozenRecord.from_dict(value).encoded)
        with pytest.raises(ContractError,match='post-runtime'): verifier.verify(result.compiled.panel,result.runtimes)
        path.write_bytes(original)
    assert verifier.verify(result.compiled.panel,result.runtimes).observed_cells==8


def test_execution_transport_failure_keeps_reserved_cell_and_requires_preexecution_binding(tmp_path,monkeypatch):
    frozen,args,seen,audits=_fixture(tmp_path,monkeypatch); calls=[]
    def fail(broker,request):
        calls.append(request)
        raise OSError('synthetic Docker transport failure')
    monkeypatch.setattr(train_controller.DockerExecutionBroker,'execute',fail)
    result=run_train_panel(frozen,**args)
    assert len(calls)==result.verdict.failures==8 and not seen and not audits
    assert result.verdict.decision=='engineering_incomplete'
    for runtime in result.runtimes:
        events=_events(runtime)
        assert events[-1]['stage']=='execution_failure'
        assert sum(e['stage']=='execution_request' for e in events)==1
        assert len([e for e in events if e['stage']=='q27_panel_binding'])==1
    # A fully rechained journal still needs the early exact cell/P0 binding.
    runtime=result.runtimes[0]; events=[e for e in _events(runtime) if e['stage']!='q27_panel_binding']
    prior=None; lines=[]
    for index,event in enumerate(events):
        event.update(sequence=index,previous=prior); frozen_event=FrozenRecord.from_dict(event)
        lines.append(frozen_event.encoded); prior=frozen_event.content_hash
    runtime.trace_path.write_text('\n'.join(lines)+'\n')
    changed=replace(runtime,trace_digest=prior)
    with pytest.raises(ContractError,match='P0 control binding'):
        PanelReceiptVerifier().verify(result.compiled.panel,(changed,*result.runtimes[1:]))
