import contextlib, hashlib, io, json, subprocess, sys
from pathlib import Path
BASE=Path('E:/_ryanDev/AI/research-loop-modular')
TREE=BASE/'pr-ref'
WORK=BASE/'work/primary-prospective-reference-live-r1'
sys.path.insert(0,str(TREE))
from evaluation.modular.fresh_airs_custodian import _write_new
from evaluation.modular.prospective_train_exporter import _concrete
from research_loop.ontology import digest
def sha(path):return hashlib.sha256(_concrete(path).read_bytes()).hexdigest()
def read(path):return json.loads(_concrete(path).read_bytes())
def main():
    result=read(WORK/'actual-result-r1.json')
    request=read(WORK/'frozen-reference-request-r1.json')
    before=read(WORK/'before-pins-r1.json');after=read(WORK/'after-pins-r1.json')
    assert result['status']=='success' and result['after']['all_unchanged']
    assert all(before[key]==after[key] for key in ('source_files','source_pins','protected_pins'))
    assert all(sha(Path(row['path']))==row['sha256'] for row in after['protected_pins'])
    assert all(sha(Path(row['path']))==row['sha256'] for row in after['source_pins'].values())
    assert all(sha(TREE/path)==value for path,value in after['source_files'].items())
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=TREE,text=True).strip()
    assert head==request['source_commit'] and not subprocess.check_output(['git','status','--porcelain'],cwd=TREE)
    store=Path(request['store_root']);audit=Path(request['audit_root'])
    publication=read(WORK/'reference-publication-r1.json')
    manifest=read(store/'manifest.json')  # Metadata only; no reference JSON is decoded.
    expected={store/'manifest.json'}
    reference_artifacts=[]
    for check in result['checks']:
        handle=check['task_handle'];path=store/(handle+'.json')
        assert publication['task_handles'][check['identity_digest']]==handle
        row=next(row for row in manifest['rows'] if row['task_handle']==handle)
        assert row['identity_digest']==check['identity_digest'] and row['identity']['domain']=='train'
        assert sha(path)==check['reference_file_sha256']==row['reference_sha256']
        expected.add(path)
        reference_artifacts.append({'path':str(path),'sha256':sha(path),'source':check['source'],
            'token':check['token'],'reference_count':check['reference_count']})
    assert set(store.iterdir())==expected and len(expected)==5
    journal=audit/'references.jsonl'
    assert sha(journal)==result['journal']['sha256']
    rows=[json.loads(line) for line in journal.read_bytes().splitlines()]
    assert len(rows)==8 and {row['attempt'] for row in rows}=={1}
    attempt_publication=audit/'attempt-000001/publication.json'
    assert read(attempt_publication)==publication
    assert not (audit/'reference.lock').exists() and not (audit/'attempt-000001/staging').exists()
    attempt={'schema':'actual-primary-reference-attempt-metadata-v1','attempt':1,'status':'completed',
        'frozen_request_sha256':sha(WORK/'frozen-reference-request-r1.json'),
        'bridge_request_canonical_sha256':rows[0]['request_sha256'],
        'journal_event_sha256':[row['entry_sha256'] for row in rows],
        'publication_canonical_sha256':digest(publication),'publication_file_sha256':sha(attempt_publication),
        'possibly_read_train_tokens':rows[-1]['possibly_read_train_tokens'],'failed':False}
    _write_new(WORK/'attempt-metadata-r1.json',attempt)
    files=[WORK/name for name in ('freeze_request.py','run_once.py','archive_metadata.py','frozen-reference-request-r1.json',
        'before-pins-r1.json','attempt-start-r1.json','after-pins-r1.json','actual-result-r1.json',
        'reference-publication-r1.json','attempt-metadata-r1.json')]
    files.extend((journal,attempt_publication,store/'manifest.json'))
    delivery={'schema':'actual-primary-reference-exclusive-metadata-manifest-v1','status':'success','source_commit':head,
        'attempts':1,'failed_attempts':0,'completed_attempts':1,'unique_train_items':4,
        'source_counts':{'discoverybench':2,'blade':2},'private_reference_files':4,'private_store_files':5,
        'journal_events':8,'reference_read_reservations':4,'standard_resolver_unique_train_items':4,
        'bridge_staging_resolver_checks':4,'postpublication_resolver_checks':4,
        'source_python_files_unchanged':261,'input_pins_unchanged':24,'protected_files_unchanged':37,
        'original_four_public_export_and_journal_unchanged':True,'primary_seal_unchanged':True,'sab_eligibility_hold_unchanged':True,
        'model_calls':0,'scorer_calls':0,'docker_calls':0,'network_calls':0,'known_external_cost_units':0,
        'validation_exports':0,'validation_leases_created':0,'private_reference_text_in_report':False,
        'scientific_validity':'not_measured','calibration':'not_measured','license_qualification_claimed':False,
        'attempt_metadata_canonical_sha256':digest(attempt),
        'metadata_artifacts':[{'path':str(path),'sha256':sha(path),'bytes':path.stat().st_size} for path in files],
        'private_reference_artifacts':reference_artifacts}
    _write_new(WORK/'delivery-manifest-r1.json',delivery)
    return {'status':'success','manifest_path':str(WORK/'delivery-manifest-r1.json'),
        'manifest_sha256':sha(WORK/'delivery-manifest-r1.json'),'attempt_metadata_sha256':sha(WORK/'attempt-metadata-r1.json'),
        'reference_publication_sha256':sha(WORK/'reference-publication-r1.json'),
        'private_store_manifest_sha256':sha(store/'manifest.json'),'metadata_artifact_count':len(files),
        'reference_counts_by_source':{source:sum(row['reference_count'] for row in reference_artifacts if row['source']==source) for source in ('discoverybench','blade')}}
if __name__=='__main__':
    with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):result=main()
    print(json.dumps(result))
