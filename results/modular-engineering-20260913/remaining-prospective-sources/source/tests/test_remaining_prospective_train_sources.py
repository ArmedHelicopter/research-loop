"""Closed source-mode bridge checks before actual controller integration grids."""
import pytest
from research_loop.modular.contracts import FrozenRecord
from test_admission_combination import fixture as admission_fixture, sources
from test_exploration_scheduler_combination import fixture as scheduler_fixture
from research_loop.modular.admission_combination_controller import FrozenAdmissionTrainConfig
from research_loop.modular.exploration_scheduler_controller import FrozenExplorationSchedulerTrainConfig
from research_loop.modular.q32_execution import run_q32_execution_panel


@pytest.mark.parametrize('kind', ['admission', 'scheduler'])
def test_explicit_v2_source_configuration_accepts_opaque_tokens(tmp_path, kind):
    if kind == 'admission':
        _, _, config, _, _ = admission_fixture(tmp_path, sources([]))
    else:
        _, _, config, _, _ = scheduler_fixture(tmp_path)
    body = config.data();body['schema'] = body['schema'].removesuffix('v1') + 'v2'
    body['export_mode'] = 'primary_prospective'
    body['task_bindings'] = {str(i + 1).zfill(64): binding for i, binding in enumerate(body['task_bindings'].values())}
    body['item_ids'] = list(body['task_bindings'])
    # Tokens are source handles, not labels: the actual exporter must still
    # verify them against its sealed split before any data or model use.
    actual = type(config)(FrozenRecord.from_dict(body))
    assert actual.data() == body


def test_q32_exposes_separate_typed_prospective_entry():
    from research_loop.modular.q32_execution import FrozenQ32ProspectiveConfig, run_q32_prospective_execution_panel
    assert callable(run_q32_prospective_execution_panel)
    assert FrozenQ32ProspectiveConfig is not FrozenRecord


import hashlib
import json
import os
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from evaluation.modular.primary_prospective_exporter import PrimaryProspectiveTrainExporter
from evaluation.modular.fresh_airs_custodian import CustodyError
from evaluation.modular.scorer_process import CombinationScorerProcessClient, serialize_combination_panel
from evaluation.modular.scoring_service import ScorerConfig
from research_loop.modular.combination_train_source import packet_index
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError, canonical
from test_primary_prospective_exporter import setup_export, events
from test_scorer_process import _store, _command
from test_modular_train_controller import model_port, FINAL
import test_admission_combination as adm
import test_exploration_scheduler_combination as es
import test_q32_prospective_execution as q32


def prepared_primary(root):
    first, selected, all_items, _ = setup_export(root/'primary', output_name='prepared')
    packets = first.export_packets(selected)
    exporter = PrimaryProspectiveTrainExporter(first.config, first.sealed_root,
        expected_split_digest=first.expected_split_digest, expected_audit_digest=first.expected_audit_digest,
        expected_split_sha256=first.seal_file_sha256['split'], expected_audit_sha256=first.seal_file_sha256['audit'],
        eligibility_path=first.eligibility_path, eligibility_sha256=first.eligibility_sha256,
        output_root=root/'export', audit_root=root/'export-audit')
    return exporter, selected, all_items, packets


def prepare_controller(root, kind):
    exporter, selected, all_items, packets = prepared_primary(root)
    calls=[]; qualifier=adm.sources(calls, root=root/'run')
    module = adm if kind=='admission' else es
    if kind=='admission': _,custody,old,_,_ = module.fixture(root/'legacy', qualifier)
    else: _,custody,old,_,_ = module.fixture(root/'legacy')
    b=old.data();bindings=list(b['task_bindings'].values());materials=b['materials_by_task'];b['materials_by_task']={}
    b['schema']=b['schema'].removesuffix('v1')+'v2';b['export_mode']='primary_prospective'
    b['item_ids']=[i.token for i in selected]
    b['task_bindings']={i.token:{'identity':p.task.identity.data(),'task_digest':p.task.content_hash,
        'csv_sha256':hashlib.sha256(p.csv_path.read_bytes()).hexdigest(),'csv_byte_count':p.csv_path.stat().st_size}
        for i,p in zip(selected,packets,strict=True)}
    package=CandidatePackage.create(parent_digest=None,manifest=TrainingManifest.freeze([p.task.identity for p in packets]),
        changes={'prompt':{'instructions':'Analyze the supplied public training observations.'}},search_cost=0)
    b['packages_by_arm']={a:package.record.data() for a in b['packages_by_arm']}
    for packet in packets:
        prior=next(v for v in bindings if v['identity']['benchmark']==packet.task.identity.benchmark)
        material=materials[prior['task_digest']];material['identity']=packet.task.identity.data();material['task_digest']=packet.task.content_hash
        material['public_artifacts'][0]['artifact'].update(sha256=hashlib.sha256(packet.csv_path.read_bytes()).hexdigest(),byte_count=packet.csv_path.stat().st_size)
        if kind=='admission':
            for row in material['originals']+material['claims']:row['subject_bindings']['task']=packet.task.identity.task_id
        b['materials_by_task'][packet.task.content_hash]=material
    store,handles,manifest_sha=_store(root,{'tasks':{p.task.content_hash:p.task for p in packets}})
    b['scorer_handle_bindings']={k:hashlib.sha256(v.encode()).hexdigest() for k,v in handles.items()}
    config=type(old)(FrozenRecord.from_dict(b))
    compiled=(module.compile_admission_train_panels(config,packets) if kind=='admission' else module.compile_exploration_scheduler_train_panel(config,packets))
    return dict(root=root,kind=kind,module=module,exporter=exporter,selected=selected,all_items=all_items,packets=packets,
        custody=custody,config=config,compiled=compiled,qualifier=qualifier,source_calls=calls,store=store,handles=handles,manifest_sha=manifest_sha)


def actual_services(setup, stack):
    root=setup['root'];kind=setup['kind'];module=setup['module'];b=setup['config'].data()
    panels=setup['compiled'].panels if kind=='admission' else [setup['compiled'].panel]
    (root/'executor.key').write_bytes(module.EXECUTION.key);(root/'score.key').write_bytes(module.SCORER.key)
    flags={'admission':True} if kind=='admission' else {'exploration_scheduler':True}
    schema='admission-combination-scorer-process-config-v1' if kind=='admission' else 'exploration-scheduler-scorer-process-config-v1'
    services={};rubric=ScorerConfig(FrozenRecord.from_dict(b['scorer']))
    for n,panel in enumerate(panels):
        server={'schema':schema,'panel':serialize_combination_panel(panel,**flags),'scorer_config':rubric.record.data(),'scorer_config_digest':rubric.digest,
            'train_reference_store':{'root':str(setup['store'].resolve()),'manifest_sha256':setup['manifest_sha'],
                'inventory_digest':panel.cells[0].identity.dataset_version,'split_digest':panel.split_digest},
            'task_handles':setup['handles'],'execution_authority_key_files':{module.EXECUTION.authority_id:str(root/'executor.key')},
            'scorer_authority':{'id':module.SCORER.authority_id,'key_file':str(root/'score.key')},'evaluator':{'synthetic_mode':'normal'}}
        path=root/f'server-{n}.json';path.write_text(canonical(server),encoding='utf-8')
        command=_command(path,root/f'worker-{n}.jsonl');command[1]=str((Path(__file__).parent/'helpers/admission_scorer_process_helper.py').resolve())
        service=CombinationScorerProcessClient(panel=panel,config=rubric,command=command,journal_path=root/f'client-{n}.jsonl',
            task_handle_bindings=b['scorer_handle_bindings'],execution_authority_keys={module.EXECUTION.authority_id:module.EXECUTION.key},
            scorer_authority_keys={module.SCORER.authority_id:module.SCORER.key},environment={**os.environ,'PYTHONIOENCODING':'gbk'},**flags)
        stack.callback(service.close);services[panel.obligation_id]=service
    return services if kind=='admission' else next(iter(services.values()))


def invoke_controller(setup, monkeypatch, *, fault=None):
    root=setup['root'];kind=setup['kind'];b=setup['config'].data();seen=[];ordinary=adm._model(seen)
    def response(request):
        data=request.data()
        assert 'PRIVATE-REFERENCE-SENTINEL' not in request.encoded
        if data['slot']=='final_answer':
            seen.append(data);assert data['execution_feedback'][0]['status']=='succeeded'
            return FrozenRecord.from_dict({'objective_digest':data['module_context']['required_objective_digest'],'outcome':'unknown',
                'evidence_ids':[],'conclusion':'Actual output '+data['execution_feedback'][0]['stdout'],'programme_complete':False})
        if kind=='admission':return ordinary(request)
        seen.append(data);observations=data['module_context']['joint_mechanism']['material']['observations']
        assert len(observations)==2 and all(o['status']=='succeeded' for o in observations)
        value=sum(float(o['stdout']) for o in observations)
        return FrozenRecord.from_dict({'analysis':'Use actual bound job outputs.','program':'print('+repr(value)+')'})
    port=model_port(root/'port',monkeypatch,max_calls=b['max_calls'],max_tokens=b['max_tokens'],schemas=b['schemas'],response_factory=response)
    exporter=setup['exporter'];kwargs=dict(custody=None,prospective_exporter=exporter,snapshot_root=Path(exporter.config['snapshot_root']),
        export_root=exporter.output_root,run_root=root/'run',model=port,audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),
        execution_authority=adm.EXECUTION,scorer_authority_keys={adm.SCORER.authority_id:adm.SCORER.key})
    if fault=='both':kwargs['custody']=setup['custody']
    if fault=='roots':kwargs['export_root']=root/'wrong-export'
    config=setup['config']
    if fault=='wrong_port':kwargs.update(custody=setup['custody'],prospective_exporter=None)
    if fault=='split':exporter.expected_split_digest='f'*64
    if fault in ('validation','swapped_tokens'):
        config=changed_source_config(config,setup['all_items'],fault)
    if fault in ('export_receipt','completion_anchor'):corrupt_export(monkeypatch,exporter,fault)

    with ExitStack() as stack:
        kwargs['scoring_service']=actual_services(setup,stack)
        if kind=='admission':kwargs['source_verifier']=setup['qualifier'];run=adm.run_admission_train_panels
        else:run=es.run_exploration_scheduler_train_panel
        if fault:
            with pytest.raises((ContractError,CustodyError)):run(config,**kwargs)
            assert not seen and not setup['source_calls'] and not port.ledger['calls']
            if fault in ('swapped_tokens','export_receipt','completion_anchor'):
                assert sum(e['event']=='exposure_reserved' for e in events(exporter))==2
                assert json.loads((root/'run/controller-attempt.json').read_text(encoding='utf-8'))['status']=='blocked_before_execution'
            return
        result=run(setup['config'],**kwargs)
    return result,seen


@pytest.mark.parametrize('kind',['admission','scheduler'])
def test_real_prospective_combination_controllers(tmp_path,monkeypatch,kind):
    setup=prepare_controller(tmp_path,kind);result,seen=invoke_controller(setup,monkeypatch)
    n=24 if kind=='admission' else 8
    assert len(result.scores)==len(result.attempts)==n
    assert all(a.data()['status']=='succeeded' for a in result.attempts)
    assert len(seen)==setup['config'].data()['max_calls']
    assert [e['event'] for e in events(setup['exporter'])]==['export_reserved','sources_verified','exposure_reserved','exposure_reserved','export_completed']


@pytest.mark.parametrize('kind',['admission','scheduler'])
@pytest.mark.parametrize('fault',['both','wrong_port','roots','split','validation','swapped_tokens','export_receipt','completion_anchor'])
def test_prospective_source_fault_precedes_all_downstream_io(tmp_path,monkeypatch,kind,fault):
    invoke_controller(prepare_controller(tmp_path,kind),monkeypatch,fault=fault)


@pytest.mark.parametrize('fault',[None,'wrong_port','roots','split','validation','swapped_tokens','export_receipt','completion_anchor','material'])
def test_actual_q32_prospective_packets_reach_all_twelve_measurements(tmp_path,monkeypatch,fault):
    from research_loop.modular.q32_execution import FrozenQ32ProspectiveConfig,run_q32_prospective_execution_panel
    exporter,selected,all_items,packets=prepared_primary(tmp_path)
    config=FrozenQ32ProspectiveConfig(FrozenRecord.from_dict({'schema':'q32-prospective-source-config-v2','domain':'train','export_mode':'primary_prospective',
        'item_ids':[i.token for i in selected], 'task_bindings':{i.token:{'identity':p.task.identity.data(),'task_digest':p.task.content_hash,
            'csv_sha256':hashlib.sha256(p.csv_path.read_bytes()).hexdigest(),'csv_byte_count':p.csv_path.stat().st_size} for i,p in zip(selected,packets,strict=True)},
        'material_by_task':{p.task.content_hash:q32.material() for p in packets},'image':q32.IMAGE}))
    if fault in ('validation','swapped_tokens'):config=changed_source_config(config,all_items,fault)
    if fault=='material':
        bad=config.data();next(iter(bad['material_by_task'].values()))['measurements']=[]
        config=type(config)(FrozenRecord.from_dict(bad))
    if fault=='split':exporter.expected_split_digest='f'*64
    if fault in ('export_receipt','completion_anchor'):corrupt_export(monkeypatch,exporter,fault)
    calls=[];factories=[]
    def response(request):calls.append(request.data());return q32.fixture_response(request)
    def factory(i):
        factories.append(i)
        return model_port(tmp_path/f'port-{i}',monkeypatch,max_calls=4,max_tokens=q32.BUDGET['model_token_stop_threshold'],
            schemas={s:FINAL if s=='final' else q32.PROGRAM_SCHEMA for s in q32.SLOTS},response_factory=response)
    kwargs=dict(prospective_exporter=object() if fault=='wrong_port' else exporter,snapshot_root=Path(exporter.config['snapshot_root']),
        export_root=tmp_path/'wrong-root' if fault=='roots' else exporter.output_root,run_root=tmp_path/'run',model_factory=factory,
        verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}))
    if fault:
        with pytest.raises((ContractError,CustodyError)):run_q32_prospective_execution_panel(config,**kwargs)
        assert not calls and not factories
        if fault in ('swapped_tokens','export_receipt','completion_anchor','material'):
            assert sum(e['event']=='exposure_reserved' for e in events(exporter))==2
            assert json.loads((tmp_path/'run/source-attempt.json').read_text(encoding='utf-8'))['status']=='blocked_before_execution'
        return
    result=run_q32_prospective_execution_panel(config,**kwargs)
    body=result.data()['result'];assert body['cell_count']==4 and body['measurement_denominator']==12 and len(calls)==16
    assert all(row['status']=='succeeded' for cell in body['results'] for row in cell['rows'])
    compiled=FrozenRecord((tmp_path/'run/compiled.json').read_text(encoding='utf-8'))
    for i in range(4):q32.verify_q32_execution(tmp_path/'run'/str(i)/'trace.jsonl',compiled)



def changed_source_config(config, items, fault):
    b=config.data()
    if fault=='validation':
        new=items['validation'][0].token;old=b['item_ids'][0]
        b['item_ids'][0]=new;b['task_bindings'][new]=b['task_bindings'].pop(old)
    else:
        left,right=b['item_ids'];b['task_bindings'][left],b['task_bindings'][right]=b['task_bindings'][right],b['task_bindings'][left]
    return type(config)(FrozenRecord.from_dict(b))


def corrupt_export(monkeypatch, exporter, fault):
    original=exporter.export_controller_packets
    def corrupt(tokens):
        packets=original(tokens)
        if fault=='completion_anchor':
            p=exporter.audit_root/'exports.jsonl';p.write_bytes(b'\n'.join(p.read_bytes().splitlines()[:-1])+b'\n');return packets
        packet=packets[0];receipt={**packet.receipt.data(),'eligibility_sha256':'0'*64}
        packet.packet_path.write_text(canonical({'task':packet.task.data(),'receipt':receipt}),encoding='utf-8')
        (packet.packet_path.parent/'receipt.json').write_text(canonical(receipt),encoding='utf-8')
        p=exporter.output_root/'export-receipt.json';batch=json.loads(p.read_text(encoding='utf-8'));batch['packets'][0]=receipt
        p.write_text(canonical(batch),encoding='utf-8')
        return (replace(packet,receipt=FrozenRecord.from_dict(receipt)),*packets[1:])
    monkeypatch.setattr(exporter,'export_controller_packets',corrupt)
