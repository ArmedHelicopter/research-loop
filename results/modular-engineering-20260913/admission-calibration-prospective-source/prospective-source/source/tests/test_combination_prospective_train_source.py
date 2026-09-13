"""Real sealed broker -> three actual controllers; synthetic calls and references."""
from contextlib import ExitStack
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path

import pytest

from evaluation.modular.primary_prospective_exporter import PrimaryProspectiveTrainExporter
from evaluation.modular.fresh_airs_custodian import CustodyError
from evaluation.modular.scorer_process import CombinationScorerProcessClient, serialize_combination_panel
from evaluation.modular.scoring_service import ScorerConfig
from research_loop.modular import combination_train_controller as m4
from research_loop.modular import lineage_combination_controller as lineage
from research_loop.modular import retrieval_review_combination_controller as retrieval
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError, canonical
from test_primary_prospective_exporter import setup_export, events
from test_modular_train_controller import model_port
from test_scorer_process import _store, _command
import test_modular_combination_train_controller as old_m4
import test_lineage_combination_controller as old_lineage
import test_retrieval_review_combinations as old_retrieval


KINDS = ('m4', 'lineage', 'retrieval')


def prepare(root, kind):
    exporter, selected, all_items, _ = setup_export(root/'primary', output_name='prepared')
    packets = exporter.export_packets(selected)
    actual = PrimaryProspectiveTrainExporter(exporter.config, exporter.sealed_root,
        expected_split_digest=exporter.expected_split_digest, expected_audit_digest=exporter.expected_audit_digest,
        expected_split_sha256=exporter.seal_file_sha256['split'], expected_audit_sha256=exporter.seal_file_sha256['audit'],
        eligibility_path=exporter.eligibility_path, eligibility_sha256=exporter.eligibility_sha256,
        output_root=root/'export', audit_root=root/'export-audit')
    source_calls = []; sources = old_lineage._sources(source_calls, run_root=root/'run')
    if kind == 'm4':
        _, custody, _, old, _, _ = old_m4._fixture(root/'legacy')
        api, module = m4, old_m4
    elif kind == 'lineage':
        _, custody, _, old, _, _ = old_lineage._fixture(root/'legacy', sources)
        api, module = lineage, old_lineage
    else:
        _, custody, old, _, _ = old_retrieval.fixture(root/'legacy')
        api, module = retrieval, old_retrieval
    b = old.data(); original_bindings = list(b['task_bindings'].values())
    b['schema'] = b['schema'].removesuffix('v1')+'v2'; b['export_mode'] = 'primary_prospective'
    b['item_ids'] = [i.token for i in selected]
    b['task_bindings'] = {i.token: {'identity': p.task.identity.data(), 'task_digest': p.task.content_hash,
        'csv_sha256': hashlib.sha256(p.csv_path.read_bytes()).hexdigest(),
        **({} if kind == 'm4' else {'csv_byte_count': len(p.csv_path.read_bytes())})}
        for i,p in zip(selected, packets, strict=True)}
    package = CandidatePackage.create(parent_digest=None,
        manifest=TrainingManifest.freeze([p.task.identity for p in packets]),
        changes={'prompt': {'instructions': 'Analyze only the supplied public training observations.'}}, search_cost=0)
    b['packages_by_arm'] = {arm: package.record.data() for arm in b['packages_by_arm']}
    if kind != 'm4':
        old_materials = b['materials_by_task']; b['materials_by_task'] = {}
        for p in packets:
            prior = next(v for v in original_bindings if v['identity']['benchmark'] == p.task.identity.benchmark)
            material = old_materials[prior['task_digest']]
            if kind == 'retrieval':
                material = old_retrieval.freeze_material(p.task, material['original_sources'], material['query']['question']).data()
            else:
                material['identity'] = p.task.identity.data(); material['task_digest'] = p.task.content_hash
                material['public_artifacts'][0]['artifact'].update(sha256=hashlib.sha256(p.csv_path.read_bytes()).hexdigest(),
                                                                byte_count=len(p.csv_path.read_bytes()))
                for v in material['originals'] + material['claims']: v['subject_bindings']['task'] = p.task.identity.task_id
            b['materials_by_task'][p.task.content_hash] = material
    store, handles, manifest_sha = _store(root, {'tasks': {p.task.content_hash:p.task for p in packets}})
    b['scorer_handle_bindings'] = {k:hashlib.sha256(v.encode()).hexdigest() for k,v in handles.items()}
    config = type(old)(FrozenRecord.from_dict(b))
    compile_fn = {'m4':m4.compile_m4_m5_train_panel, 'lineage':lineage.compile_lineage_train_panels,
                  'retrieval':retrieval.compile_retrieval_review_panels}[kind]
    compiled = compile_fn(config, packets)
    return dict(root=root, kind=kind, exporter=actual, packets=packets, selected=selected, all_items=all_items,
        custody=custody, config=config, compiled=compiled, compile_fn=compile_fn, api=api, module=module,
        handles=handles, store=store, manifest_sha=manifest_sha, sources=sources, source_calls=source_calls)


def processes(setup, stack):
    root=setup['root']; module=setup['module']; config=setup['config']; b=config.data()
    panels=[setup['compiled'].panel] if setup['kind']=='m4' else setup['compiled'].panels
    (root/'executor.key').write_bytes(module.EXECUTION.key); (root/'scorer.key').write_bytes(module.SCORER.key)
    services={}; rubric=ScorerConfig(FrozenRecord.from_dict(b['scorer']))
    for n,panel in enumerate(panels):
        flag=setup['kind']=='retrieval'
        server={'schema':'retrieval-review-scorer-process-config-v1' if flag else 'combination-scorer-process-config-v1',
            'panel':serialize_combination_panel(panel,retrieval_review=flag),'scorer_config':rubric.record.data(),
            'scorer_config_digest':rubric.digest,'train_reference_store':{'root':str(setup['store'].resolve()),
                'manifest_sha256':setup['manifest_sha'],'inventory_digest':panel.cells[0].identity.dataset_version,'split_digest':panel.split_digest},
            'task_handles':setup['handles'],'execution_authority_key_files':{module.EXECUTION.authority_id:str(root/'executor.key')},
            'scorer_authority':{'id':module.SCORER.authority_id,'key_file':str(root/'scorer.key')},'evaluator':{}}
        path=root/f'server-{n}.json';path.write_text(canonical(server),encoding='utf-8')
        service=CombinationScorerProcessClient(panel=panel,config=rubric,retrieval_review=flag,
            command=_command(path,root/f'worker-{n}.jsonl'),journal_path=root/f'client-{n}.jsonl',
            task_handle_bindings=b['scorer_handle_bindings'],execution_authority_keys={module.EXECUTION.authority_id:module.EXECUTION.key},
            scorer_authority_keys={module.SCORER.authority_id:module.SCORER.key},environment={**os.environ,'PYTHONIOENCODING':'gbk'})
        stack.callback(service.close); services[panel.obligation_id]=service
    return next(iter(services.values())) if setup['kind']=='m4' else services


def run(setup, monkeypatch, *, fault=None):
    root=setup['root']; kind=setup['kind']; module=setup['module']; config=setup['config']; exporter=setup['exporter']
    seen=[]; scores=[]; ordinary=module._model(seen) if kind!='retrieval' else module.model_response(seen)
    def response(request):
        b=request.data()
        assert 'PRIVATE-REFERENCE-SENTINEL' not in request.encoded
        if b['slot']=='final_answer':
            seen.append(b)
            assert b['execution_feedback'][0]['status']=='succeeded'
            return FrozenRecord.from_dict({'objective_digest':b['module_context']['required_objective_digest'],
                'outcome':'unknown','evidence_ids':[],'conclusion':'Observed public output: '+b['execution_feedback'][0]['stdout'],
                'programme_complete':False})
        return ordinary(request)
    b=config.data()
    port=model_port(root/'port',monkeypatch,max_calls=b['max_calls'],max_tokens=b['max_tokens'],schemas=b['schemas'],response_factory=response)
    kwargs=dict(custody=None,prospective_exporter=exporter,snapshot_root=Path(exporter.config['snapshot_root']),
        export_root=exporter.output_root,run_root=root/'run',model=port,audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),
        execution_authority=module.EXECUTION,scorer_authority_keys={module.SCORER.authority_id:module.SCORER.key})
    if fault=='both': kwargs['custody']=setup['custody']
    if fault=='wrong_port': kwargs.update(custody=setup['custody'],prospective_exporter=None)
    if fault=='roots': kwargs['export_root']=root/'foreign-root'
    if fault=='split': exporter.expected_split_digest='f'*64
    if fault=='validation':
        new=setup['all_items']['validation'][0].token;old=b['item_ids'][0]
        b['item_ids'][0]=new;b['task_bindings'][new]=b['task_bindings'].pop(old)
        config=type(config)(FrozenRecord.from_dict(b))
    if fault=='swapped_tokens':
        left,right=b['item_ids'];b['task_bindings'][left],b['task_bindings'][right]=b['task_bindings'][right],b['task_bindings'][left]
        config=type(config)(FrozenRecord.from_dict(b))
    if fault in ('export_receipt','completion_anchor'):
        original=exporter.export_controller_packets
        def corrupt(tokens):
            packets=original(tokens)
            if fault=='export_receipt':
                packet=packets[0];receipt={**packet.receipt.data(),'eligibility_sha256':'0'*64}
                packet.packet_path.write_text(canonical({'task':packet.task.data(),'receipt':receipt}),encoding='utf-8')
                (packet.packet_path.parent/'receipt.json').write_text(canonical(receipt),encoding='utf-8')
                batch_path=exporter.output_root/'export-receipt.json';batch=json.loads(batch_path.read_text())
                batch['packets'][0]=receipt;batch_path.write_text(canonical(batch),encoding='utf-8')
                return (replace(packet,receipt=FrozenRecord.from_dict(receipt)),*packets[1:])
            journal=exporter.audit_root/'exports.jsonl';rows=journal.read_bytes().splitlines()
            journal.write_bytes(b'\n'.join(rows[:-1])+b'\n')
            return packets
        monkeypatch.setattr(exporter,'export_controller_packets',corrupt)
    with ExitStack() as stack:
        if kind=='lineage':
            kwargs.update(source_verifier=setup['sources'],scoring_service=module._service(ScorerConfig(FrozenRecord.from_dict(b['scorer'])),setup['handles'],scores))
            execute=lineage.run_lineage_train_panels
        elif kind=='m4':
            kwargs['scoring_service']=processes(setup,stack);execute=m4.run_m4_m5_train_panel
        else:
            kwargs.update(scoring_services=processes(setup,stack),provider=module.Provider(root),admission_port=module.admission_receipt)
            execute=retrieval.run_retrieval_review_panels
        if fault:
            with pytest.raises((ContractError,CustodyError)): execute(config,**kwargs)
            assert not seen and not scores and not setup['source_calls']
            assert all(not p.exists() for p in root.glob('worker-*.jsonl'))
            if fault in ('swapped_tokens','export_receipt','completion_anchor'):
                assert exporter.output_root.exists()
                journal=json.loads((root/'run/controller-attempt.json').read_text())
                assert journal['status']=='blocked_before_execution'
                if fault=='swapped_tokens': assert len(journal['packet_receipts'])==2
                assert sum(r['event']=='exposure_reserved' for r in events(exporter))==2
            else:
                assert not exporter.output_root.exists()
            return
        result=execute(config,**kwargs)
    return result,port,seen,scores


@pytest.mark.parametrize('kind',KINDS)
def test_all_three_actual_controllers_consume_primary_packets(tmp_path,monkeypatch,kind):
    setup=prepare(tmp_path,kind);result,port,seen,scores=run(setup,monkeypatch)
    expected={'m4':8,'lineage':34,'retrieval':32}[kind]
    assert len(result.scores)==expected and len(result.attempts)==expected
    assert all(a.data()['status']=='succeeded' for a in result.attempts)
    assert len(seen)==setup['config'].data()['max_calls'] and not port.ledger['usage_incomplete']
    assert len({a.data()['cell']['identity']['task_id'] for a in result.attempts})==2
    assert [r['event'] for r in events(setup['exporter'])]==['export_reserved','sources_verified','exposure_reserved','exposure_reserved','export_completed']
    journal=json.loads((tmp_path/'run/controller-attempt.json').read_text())
    assert {p['export_token'] for p in journal['packet_receipts']}==set(setup['config'].data()['item_ids'])


@pytest.mark.parametrize('kind',KINDS)
@pytest.mark.parametrize('fault',('both','wrong_port','roots','split','validation','swapped_tokens','export_receipt','completion_anchor'))
def test_rejection_precedes_all_downstream_io_and_preserves_export(tmp_path,monkeypatch,kind,fault):
    run(prepare(tmp_path,kind),monkeypatch,fault=fault)


@pytest.mark.parametrize('kind',KINDS)
def test_explicit_configuration_and_serialized_packet_cannot_be_relabelled(tmp_path,kind):
    setup=prepare(tmp_path,kind);config=setup['config'];body=config.data()
    for change in ({'schema':body['schema'].removesuffix('v2')+'v1'}, {'export_mode':True},
                   {'export_mode':'legacy'}, {'export_mode':None}, {'unknown':True}):
        with pytest.raises(ContractError): type(config)(FrozenRecord.from_dict({**body,**change}))
    packets=setup['packets'];packet=packets[0]
    for mutation in ({'identity':packets[1].task.identity.data()}, {'export_token':packets[1].receipt.data()['export_token']},
                     {'source_group':'f'*64}, {'split_digest':'f'*64}):
        changed=replace(packet,receipt=FrozenRecord.from_dict({**packet.receipt.data(),**mutation}))
        with pytest.raises(ContractError): setup['compile_fn'](config,(changed,packets[1]))
    packet.packet_path.write_text(canonical({'task':packet.task.data(),'receipt':{}}),encoding='utf-8')
    with pytest.raises(ContractError): setup['compile_fn'](config,packets)


@pytest.mark.parametrize('kind',KINDS)
@pytest.mark.parametrize('field,value', [('csv_byte_count',-1),('input_bindings_digest','0'*64),('eligibility_sha256','0'*64)])
def test_independent_false_source_receipt_counterexamples(tmp_path,kind,field,value):
    setup=prepare(tmp_path,kind);packet,other=setup['packets']
    receipt=FrozenRecord.from_dict({**packet.receipt.data(),field:value})
    packet.packet_path.write_text(canonical({'task':packet.task.data(),'receipt':receipt.data()}),encoding='utf-8')
    with pytest.raises(ContractError): setup['compile_fn'](setup['config'],(replace(packet,receipt=receipt),other))
