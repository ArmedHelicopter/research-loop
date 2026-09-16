"""Independent child recomputation; expose only aggregate split evidence."""
from datetime import datetime,timezone
import hashlib,json,subprocess,sys,traceback
from pathlib import Path

BASE=Path('E:/_ryanDev/AI/research-loop-modular')
ROOT=BASE/'artifact-evidence-provenance'; WORK=BASE/'work'
PRIVATE=BASE/'custody-private/primary-holdout-recompute-20260916-r1'
PUBLIC=WORK/'primary-holdout-recompute-20260916-r1-public.json'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def write(path,value):
    with path.open('x',encoding='utf-8',newline='\n') as out:
        out.write(json.dumps(value,sort_keys=True,indent=2)+'\n')
def sources():
    names=subprocess.check_output(['git','ls-files','-z','*.py','*.md'],cwd=ROOT).decode().split('\0')
    return {n:sha((ROOT/n).read_bytes()) for n in names if n and not n.startswith(('results/','data/'))}

def main():
    assert not PRIVATE.exists() and not PUBLIC.exists()
    PRIVATE.mkdir(parents=True)
    before=sources()
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    map_path=WORK/'actual-m4m5-train-material-map-r1.json'
    mapping=json.loads(map_path.read_bytes()); spec=mapping['exporter_constructor']
    config_path=Path(spec['config_path']); config_raw=config_path.read_bytes()
    assert sha(config_raw)==spec['config_sha256']
    config=json.loads(config_raw); sealed=Path(spec['sealed_root'])
    audit_raw=(sealed/'process-audit.json').read_bytes()
    split_raw=(sealed/'prospective-split.json').read_bytes()
    assert sha(audit_raw)==spec['expected_audit_sha256']
    assert sha(split_raw)==spec['expected_split_sha256']
    old_audit=json.loads(audit_raw); old_split=json.loads(split_raw)
    sys.path.insert(0,str(ROOT))
    from evaluation.modular import primary_process_qualification as p
    from research_loop.ontology import digest
    assert digest(old_audit)==spec['expected_audit_digest']
    assert digest(old_split)==spec['expected_split_digest']
    instances=[]
    original=p.PinnedReads
    class RecordedReads(original):
        def __init__(self,inputs):
            super().__init__(inputs);instances.append(self)
    p.PinnedReads=RecordedReads
    write(PRIVATE/'intent.json',{'source_commit':head,'source_before':before,
        'helper_sha256':sha(Path(__file__).read_bytes()),'config_sha256':sha(config_raw),
        'audit_sha256':sha(audit_raw),'split_sha256':sha(split_raw),
        'scope':'recompute recorded metadata exposure and family allocation; opaque source hashing only',
        'model_calls':0,'network_calls':0,'payload_exports':0,'validation_lease_issued':False})
    fresh,groups=p.audit_primary_process(config)
    assert len(instances)==1
    # Time belongs to the new observation. Compare every other original field.
    normalized=dict(fresh); normalized['end_boundary_utc']=old_audit['end_boundary_utc']
    assert normalized==old_audit,'prior process audit changed'
    assert p.partition_primary(old_audit,groups)==old_split,'partition replay differs'
    declared_reads=[{'path':str(path),'sha256':value,'bytes':path.stat().st_size,
                     'locator_sha256':digest(str(path))}
                    for path,value in sorted(instances[0].observed.items(),key=lambda item:str(item[0]))]
    assert len(declared_reads)==len(fresh['input_bindings'])
    assert [{'locator_sha256':r['locator_sha256'],'sha256':r['sha256']} for r in declared_reads]==fresh['input_bindings']
    held={token for group in old_split['groups'] if group['split']=='validation' for token in group['member_tokens']}
    train={token for group in old_split['groups'] if group['split']=='train' for token in group['member_tokens']}
    known={row['token'] for row in fresh['rows'] if row['forced_train']}
    assert not held.intersection(train|known)
    assert set(mapping['selected_token_allowlist'])<=train
    assert all(group['known_train_member_count']==0 for group in old_split['groups'] if group['split']=='validation')
    for row in declared_reads:assert sha(Path(row['path']).read_bytes())==row['sha256']
    assert config_path.read_bytes()==config_raw
    assert (sealed/'process-audit.json').read_bytes()==audit_raw and (sealed/'prospective-split.json').read_bytes()==split_raw
    assert sources()==before
    (PRIVATE/'config-original.json').write_bytes(config_raw)
    (PRIVATE/'audit-original.json').write_bytes(audit_raw)
    (PRIVATE/'split-original.json').write_bytes(split_raw)
    write(PRIVATE/'audit-recomputed.json',fresh)
    write(PRIVATE/'groups-recomputed.json',groups)
    write(PRIVATE/'declared-read-manifest.json',declared_reads)
    write(PRIVATE/'source-after.json',before)
    pins={path.name:{'sha256':sha(path.read_bytes()),'bytes':path.stat().st_size} for path in sorted(PRIVATE.iterdir())}
    result={'schema':'primary-holdout-independent-recompute-v1','status':'recomputed_equal',
        'created_at_utc':datetime.now(timezone.utc).isoformat(),'source_commit':head,'source_unchanged':True,
        'source_files':len(before),'counts':old_split['counts'],'group_count':len(groups),
        'declared_read_count':len(declared_reads),'recorded_forced_train_overlap_with_validation':0,
        'observed_family_partition_recomputed':True,'original_audit_and_split_bytes_unchanged':True,
        'scope':'pinned recorded exposure, recorded relationship graph and exact declared source bytes',
        'historical_gaps_unchanged':old_audit['gaps'],
        'complete_read_manifest_scope':'all declared inputs observed by this auditor only; not OS-wide history',
        'independent_clean_attestation_issued':False,'acceptance_ready':False,
        'validation_payload_decoded':False,'validation_payload_exported':False,'validation_lease_issued':False,
        'model_calls':0,'network_calls':0,'private_evidence_root':str(PRIVATE),'private_evidence_pins':pins,
        'next_step':'bind bounded source and exposure qualification to the frozen candidate and isolated validation adapter; do not invent absolute independence'}
    write(PUBLIC,result)
    print(json.dumps({key:result[key] for key in ('status','counts','group_count','declared_read_count','source_unchanged','acceptance_ready')}))

if __name__=='__main__':
    try:main()
    except BaseException as exc:
        if PRIVATE.exists():
            fault=PRIVATE/'failure.json'
            if not fault.exists():write(fault,{'status':'failed','error_type':type(exc).__name__,
                'traceback_frames':[{'filename':Path(f.filename).name,'lineno':f.lineno,'function':f.name} for f in traceback.extract_tb(exc.__traceback__)],
                'validation_payload_exported':False,'validation_lease_issued':False,'model_calls':0})
        print(json.dumps({'status':'failed','error_type':type(exc).__name__}))
        raise SystemExit(1)
