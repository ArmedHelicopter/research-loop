import hashlib,json,subprocess,zipfile
from pathlib import Path
base=Path('E:/_ryanDev/AI/research-loop-modular');repo=base/'ordinary-provider-port'
dest=repo/'results/ordinary-provider-family-checkpoint-20260914'
run=base/'work/ordinary-provider-family-r1'
sha=lambda b:hashlib.sha256(b).hexdigest()
def write(name,value):(dest/name).write_bytes(value if isinstance(value,bytes) else json.dumps(value,indent=2).encode())
write('ARCHIVE-FIRST-FAILURE.json',{'failed_operation':'tested-source reconstruction from Git LF/CRLF candidates',
    'source':'6e0221f94f00ca6396c3bef5f99412b9b9c3a785','file':'research_loop/modular/train_controller.py',
    'expected_disk_sha256':'06d72eb9b23f5f43f424f4c59c7b8e2a35ae811fde49174607bf5bbf384558a2',
    'error':'AssertionError: no candidate matches; incomplete tested-source.zip preserved as first-attempt evidence'})
before=json.loads((run/'source-before.json').read_bytes());after=json.loads((run/'source-after.json').read_bytes());assert before==after
check=json.loads((run/'check.json').read_bytes());source=check['source_commit'];source_rows={}
with zipfile.ZipFile(dest/'pinned-git-source.zip','w',zipfile.ZIP_DEFLATED) as z:
    for rel,expected in before.items():
        raw=subprocess.check_output(['git','-C',str(repo),'show',source+':'+rel]);z.writestr(rel,raw)
        source_rows[rel]={'git_blob_sha256':sha(raw),'tested_disk_sha256':expected,'git_bytes_equal_tested_disk':sha(raw)==expected}
write('SOURCE-QUALIFICATION.json',{'files':source_rows,'tested_before_equals_after':True,
    'qualification':'Pinned Git source bytes are exact to commit. Tested disk bytes were independently hashed unchanged; checkout line endings can differ. No byte identity between Git snapshot and all tested disk files is asserted.'})
members=json.loads((dest/'RAW-MANIFEST.json').read_bytes())
with zipfile.ZipFile(dest/'raw-evidence.zip') as z:
    assert set(z.namelist())==set(members)
    for name,row in members.items():assert sha(z.read(name))==row['sha256']
write('SUMMARY.json',{'schema':'ordinary-provider-family-checkpoint-v1','source_commit':source,'check':check,
    'tests_passed':67,'raw_member_count':len(members),'tested_source_files':len(before),
    'scope':['43 singleton slot-union configurations','11 family configurations','24 state/prediction cells:72 synthetic native MAIN,24 actual Docker,24 independent scores','unknown MAIN and first-score provenance failures retain24 rows'],
    'remaining':['10 other full native family panels','singleton native dispatch','Q3.2 native execution','reviewed last-score/final provenance gate repair'],
    'raw_zip_members_verified_to_originals_by_first_builder':True,'source_qualification':'See SOURCE-QUALIFICATION.json; mixed line-ending reconstruction failure retained.',
    'real_model_or_api_calls':0,'scientific_effectiveness_proven':False})
write('first-archive-builder.py',(base/'work/archive-ordinary-family-checkpoint.py').read_bytes())
write('archive-builder.py',Path(__file__).read_bytes())
write('MANIFEST.json',{p.name:{'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for p in sorted(dest.iterdir()) if p.is_file() and p.name!='MANIFEST.json'})
outer=dest.with_suffix('.zip')
with zipfile.ZipFile(outer,'w',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(dest.iterdir()):z.writestr(p.name,p.read_bytes())
with zipfile.ZipFile(outer) as z:
    for name in z.namelist():assert z.read(name)==(dest/name).read_bytes()
print(json.dumps({'outer_sha256':sha(outer.read_bytes()),'payload_files':len(list(dest.iterdir())),'raw_members':len(members),'tested_source_files':len(before)}))
