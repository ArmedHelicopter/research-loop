import contextlib, hashlib, io, json, subprocess, sys, time
from pathlib import Path
BASE=Path('E:/_ryanDev/AI/research-loop-modular')
TREE=BASE/'pr-ref'
WORK=BASE/'work/primary-prospective-reference-live-r1'
sys.path.insert(0,str(TREE))
from evaluation.modular.fresh_airs_custodian import _write_new
from evaluation.modular.prospective_train_exporter import _concrete
from evaluation.modular.primary_prospective_exporter import PrimaryProspectiveTrainExporter, PrimaryTrainExportItem
from evaluation.modular.primary_reference_bridge import PrimaryProspectiveReferenceBridge, PrimaryReferenceItem
from evaluation.modular.reference_store import FrozenTrainReferenceResolver
from evaluation.modular.train_io import PublicTrainPacket
from research_loop.modular.contracts import PublicTask, DataIdentity, FrozenRecord
from research_loop.ontology import digest

def sha(path):return hashlib.sha256(_concrete(path).read_bytes()).hexdigest()
def read(path):return json.loads(_concrete(path).read_bytes())
def verify_pins(request):
    assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=TREE,text=True).strip()==request['source_commit']=='e573bf75f404715dfadbce7b461e78a41ddd88f9'
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=TREE)
    assert sha(WORK/'frozen-reference-request-r1.json')=='d7f94a0968c05f0e16ebd7506213746dd621504f7c661e80362e546dfc77efb2'
    assert all(sha(TREE/path)==value for path,value in request['source_files'].items())
    assert all(sha(Path(row['path']))==row['sha256'] for row in request['source_pins'].values())
    assert all(sha(Path(row['path']))==row['sha256'] for row in request['protected_pins'])
    assert sha(Path(request['config_path']))==request['config_sha256']
    return {'source_commit':request['source_commit'],'source_file_count':len(request['source_files']),
        'source_inputs_verified':len(request['source_pins']),'protected_files_verified':len(request['protected_pins']),
        'all_unchanged':True}

def main():
    request=read(WORK/'frozen-reference-request-r1.json')
    report={'schema':'actual-primary-reference-preparation-result-v1','status':'pending','attempts':1,
        'requested_train_items':4,'source_counts':{'discoverybench':2,'blade':2},'request_sha256':sha(WORK/'frozen-reference-request-r1.json'),
        'run_script_sha256':sha(Path(__file__)),'model_calls':0,'scorer_calls':0,'docker_calls':0,'network_calls':0,
        'known_external_cost_units':0,'validation_reference_exports':0,'validation_leases_created':0,
        'scientific_validity':'not_measured','calibration':'not_measured','license_qualification_claimed':False}
    started=time.time();phase='before_checks';bridge=None;publication=None
    try:
        assert not Path(request['store_root']).exists() and not Path(request['audit_root']).exists()
        assert not (WORK/'attempt-start-r1.json').exists()
        report['before']=verify_pins(request)
        _write_new(WORK/'attempt-start-r1.json',{'schema':'actual-primary-reference-attempt-start-v1',
            'request_sha256':report['request_sha256'],'source_commit':request['source_commit'],
            'run_script_sha256':report['run_script_sha256'],'attempt':1,'requested_train_items':4,
            'model_calls':0,'network_calls':0})
        phase='public_packet_consumption'
        packets=[];requests=[]
        for row in request['requests']:
            item=PrimaryTrainExportItem(**row['item'])
            typed=PrimaryReferenceItem(item, row['task_sha256'],row['public_sha256'],row['csv_sha256'],row['receipt_sha256'])
            root=Path(request['export_root'])/item.token
            assert sha(root/'public.json')==row['public_sha256']
            assert sha(root/'data.csv')==row['csv_sha256']
            assert sha(root/'receipt.json')==row['receipt_sha256']
            envelope=read(root/'public.json')
            task=PublicTask(DataIdentity.parse(envelope['task']['identity']),FrozenRecord.from_dict(envelope['task']['payload']))
            task.identity.require_train()
            assert task.content_hash==row['task_sha256']
            packets.append(PublicTrainPacket(task,root/'public.json',root/'data.csv',FrozenRecord.from_dict(envelope['receipt'])))
            requests.append(typed)
        exporter=PrimaryProspectiveTrainExporter(read(Path(request['config_path'])),Path(request['sealed_root']),
            expected_split_digest=request['split_digest'],expected_audit_digest=request['audit_digest'],
            expected_split_sha256=request['split_raw_sha256'],expected_audit_sha256=request['audit_raw_sha256'],
            eligibility_path=Path(request['eligibility_path']),eligibility_sha256=request['eligibility_sha256'],
            output_root=Path(request['export_root']),audit_root=Path(request['export_audit_root']))
        bridge=PrimaryProspectiveReferenceBridge(exporter=exporter,export_receipt_sha256=request['export_receipt_sha256'],
            store_root=Path(request['store_root']),audit_root=Path(request['audit_root']),
            discovery_answer_keys=request['discovery_answer_keys'])
        phase='bridge_prepare'
        publication=bridge.prepare(requests,packets)
        report['bridge_returned_success']=True
        _write_new(WORK/'reference-publication-r1.json',publication.data())
        phase='standard_resolver_verification'
        body=publication.data()
        assert body['reference_count']==4 and len(body['task_handles'])==4
        resolver=FrozenTrainReferenceResolver(bridge.store_root,manifest_sha256=body['manifest_sha256'],
            inventory_digest=body['inventory_digest'],split_digest=body['split_digest'])
        checks=[]
        for item,packet in zip(requests,packets,strict=True):
            identity_digest=digest(packet.task.identity.data())
            handle=body['task_handles'][identity_digest]
            reference=resolver(handle,packet.task.identity.benchmark)
            value=reference.data()
            assert value['identity_digest']==identity_digest and value['split']=='train'
            assert value['task_context']==packet.task.payload.data() and value['benchmark']==item.item.source
            assert value['references']
            checks.append({'source':item.item.source,'token':item.item.token,'identity_digest':identity_digest,
                'task_handle':handle,'reference_record_digest':reference.content_hash,'reference_count':len(value['references']),
                'reference_file_sha256':sha(bridge.store_root/(handle+'.json')),'resolver_verified':True})
        report['checks']=checks
        report['postpublication_resolver_checks']=4
        report['bridge_staging_resolver_checks']=4
        key=request['discovery_answer_keys']['synth']
        assert bridge._observed[_concrete(key['path'])]==key['sha256']
        report['actual_answer_key_bytes_verified']=True
        report['actual_answer_key_sha256']=key['sha256']
        phase='journal_verification'
        journal=bridge.audit_root/'references.jsonl'
        rows=[json.loads(line) for line in journal.read_bytes().splitlines()]
        assert [row['event'] for row in rows]==['attempt_reserved','sources_verified']+['reference_read_reserved']*4+['publication_reserved','completed']
        previous='0'*64
        for index,row in enumerate(rows,1):
            core={key:value for key,value in row.items() if key!='entry_sha256'}
            assert row['entry_sha256']==digest(core) and row['previous_sha256']==previous and row['sequence']==index
            assert row['request_sha256']==digest([item.data() for item in requests])
            assert row['model_calls']==row['network_calls']==row['known_cost_units']==0
            assert row['validation_reference_count']==0
            previous=row['entry_sha256']
        assert rows[-1]['publication_sha256']==publication.content_hash
        assert rows[-1]['possibly_read_train_tokens']==sorted(item.item.token for item in requests)
        report['journal']={'path':str(journal),'sha256':sha(journal),'events':len(rows),'hash_chain_verified':True,
            'attempts':1,'completed_attempts':1,'failed_attempts':0,'reserved_reference_reads':4}
        report['private_store_manifest']={'path':str(bridge.store_root/'manifest.json'),'sha256':sha(bridge.store_root/'manifest.json')}
        report['publication_canonical_sha256']=publication.content_hash
        report['status']='success'
    except BaseException as error:
        report['status']='failed'
        report['failure_phase']=phase
        report['error_category']=type(error).__name__ if type(error).__name__ in {'CustodyError','AssertionError','ContractError','OSError','ValueError','KeyError','TypeError'} else 'other_exception'
        journal=Path(request['audit_root'])/'references.jsonl'
        if journal.exists():
            rows=[json.loads(line) for line in journal.read_bytes().splitlines()]
            report['journal']={'path':str(journal),'sha256':sha(journal),'events':len(rows),
                'completed_attempts':sum(row['event']=='completed' for row in rows),'failed_attempts':sum(row['event']=='failed' for row in rows),
                'reserved_reference_reads':sum(row['event']=='reference_read_reserved' for row in rows)}
    try:
        report['after']=verify_pins(request)
        _write_new(WORK/'after-pins-r1.json',{'schema':'actual-primary-reference-after-pins-v1',
            'source_files':{path:sha(TREE/path) for path in request['source_files']},
            'source_pins':{key:{'path':row['path'],'sha256':sha(Path(row['path']))} for key,row in request['source_pins'].items()},
            'protected_pins':[{'path':row['path'],'sha256':sha(Path(row['path']))} for row in request['protected_pins']],
            'all_unchanged':True})
    except BaseException:
        report['after']={'all_unchanged':False};report['status']='failed'
    report['elapsed_seconds']=round(time.time()-started,3)
    _write_new(WORK/'actual-result-r1.json',report)
    return {'status':report['status'],'actual_result_path':str(WORK/'actual-result-r1.json'),
        'actual_result_sha256':sha(WORK/'actual-result-r1.json'),'failure_phase':report.get('failure_phase'),
        'bridge_returned_success':report.get('bridge_returned_success',False),'after':report['after'],'journal':report.get('journal')}

if __name__=='__main__':
    with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):result=main()
    print(json.dumps(result))
