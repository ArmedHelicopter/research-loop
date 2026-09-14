import hashlib,json,subprocess,zipfile
from pathlib import Path
base=Path('E:/_ryanDev/AI/research-loop-modular');repo=base/'ordinary-provider-port'
name='ordinary-provider-family-checkpoint-20260914';dest=repo/'results'/name;dest.mkdir(parents=True,exist_ok=False)
run=base/'work/ordinary-provider-family-r1';check=json.loads((run/'check.json').read_bytes());source=check['source_commit']
sha=lambda b:hashlib.sha256(b).hexdigest()
def write(name,value):(dest/name).write_bytes(value if isinstance(value,bytes) else json.dumps(value,indent=2).encode())
write('.gitattributes',b'** -text\n');members={};omitted=[]
with zipfile.ZipFile(dest/'raw-evidence.zip','w',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(run.rglob('*')):
        if not p.is_file():continue
        rel=p.relative_to(run).as_posix()
        if p.name in {'auth.json','login-backup.json'} or p.suffix=='.key':omitted.append(rel);continue
        if any(part in {'cache','__pycache__'} for part in p.relative_to(run).parts):continue
        raw=p.read_bytes();z.writestr(rel,raw);members[rel]={'sha256':sha(raw),'bytes':len(raw),'original_path':str(p)}
with zipfile.ZipFile(dest/'raw-evidence.zip') as z:
    for rel,m in members.items():assert z.read(rel)==Path(m['original_path']).read_bytes()
write('RAW-MANIFEST.json',members);write('EXCLUDED-NAMES.json',{'unopened_opaque_or_key_files':omitted})
before=json.loads((run/'source-before.json').read_bytes());source_manifest={}
with zipfile.ZipFile(dest/'tested-source.zip','w',zipfile.ZIP_DEFLATED) as z:
    for rel,expected in before.items():
        blob=subprocess.check_output(['git','-C',str(repo),'show',source+':'+rel])
        candidates=[blob,blob.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')]
        matching=[raw for raw in candidates if sha(raw)==expected]
        assert matching,(rel,expected)
        raw=matching[0];z.writestr(rel,raw);source_manifest[rel]={'sha256':expected,'bytes':len(raw)}
write('TESTED-SOURCE-MANIFEST.json',source_manifest)
write('SUMMARY.json',{'schema':'ordinary-provider-family-checkpoint-v1','source_commit':source,'check':check,
    'tests_passed':67,'raw_member_count':len(members),'tested_source_files':len(before),
    'scope':['43 singleton native slot-union configurations','11 native combination-family configurations',
        '24 state/prediction cells,72 native MAIN,24 Docker executions,24 independent process scores',
        'unknown MAIN and first-score provenance failure both retain24 planned cells'],
    'remaining':['other10 full native family panels','singleton native dispatch','Q3.2 native execution',
        'newly reviewed last-score/final provenance gate repair'],
    'source_byte_method':'Pinned Git blobs reconstructed only when their LF/CRLF bytes match the recorded tested SHA256 exactly; every source file matches source-before and unchanged source-after.',
    'all_raw_bytes_match_originals':True,'real_model_or_api_calls':0,'scientific_effectiveness_proven':False})
write('archive-builder.py',Path(__file__).read_bytes())
manifest={p.name:{'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for p in sorted(dest.iterdir()) if p.is_file()}
write('MANIFEST.json',manifest)
outer=dest.with_suffix('.zip')
with zipfile.ZipFile(outer,'w',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(dest.iterdir()):z.writestr(p.name,p.read_bytes())
with zipfile.ZipFile(outer) as z:
    for name in z.namelist():assert z.read(name)==(dest/name).read_bytes()
proof={'outer_sha256':sha(outer.read_bytes()),'payload_files':len(manifest)+1,'raw_members':len(members),'tested_source_files':len(before)}
(base/'work/ordinary-provider-family-checkpoint-byte-proof.json').write_text(json.dumps(proof,indent=2));print(json.dumps(proof))
