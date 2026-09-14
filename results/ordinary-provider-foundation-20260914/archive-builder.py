import hashlib,json,subprocess,zipfile
from pathlib import Path
base=Path('E:/_ryanDev/AI/research-loop-modular');repo=base/'ordinary-provider-port'
dest=repo/'results/ordinary-provider-foundation-20260914';dest.mkdir(parents=True,exist_ok=False)
sha=lambda b:hashlib.sha256(b).hexdigest()
def write(name,data):
    p=dest/name;p.parent.mkdir(parents=True,exist_ok=True)
    p.write_bytes(data if isinstance(data,bytes) else json.dumps(data,indent=2).encode())
write('.gitattributes',b'** -text\n')
runs=['ordinary-provider-preflight-r1','ordinary-provider-terminal-r1','ordinary-provider-terminal-r2']
members={};excluded=[];raw=dest/'raw-evidence.zip'
with zipfile.ZipFile(raw,'w',zipfile.ZIP_DEFLATED) as z:
    for name in runs:
        root=base/'work'/name
        for p in sorted(root.rglob('*')):
            if not p.is_file():continue
            rel=p.relative_to(root)
            if p.name in {'auth.json','login-backup.json'} or p.suffix=='.key':
                excluded.append(name+'/'+rel.as_posix());continue
            if any(part in {'cache','__pycache__'} for part in rel.parts):continue
            b=p.read_bytes();key=name+'/'+rel.as_posix();z.writestr(key,b)
            members[key]={'sha256':sha(b),'bytes':len(b),'original_path':str(p)}
with zipfile.ZipFile(raw) as z:
    assert set(z.namelist())==set(members)
    for key,row in members.items():
        b=z.read(key);assert sha(b)==row['sha256'] and b==Path(row['original_path']).read_bytes()
write('RAW-MANIFEST.json',members)
write('EXCLUDED-NAMES.json',{'reason':'Opaque synthetic login bodies and key files omitted without opening them; caches omitted.','paths':excluded})
sourcefiles=['research_loop/modular/'+n+'.py' for n in ['train_provider','phase_provider','train_provider_preflight','grok_train_solver','grok_acp_transport','model_port','contracts']]
sourcefiles+=['tests/test_train_provider_terminal_snapshot.py','tests/test_train_provider_preflight.py','tests/test_train_provider.py','tests/helpers/native_ordinary_provider.py','tests/fixtures/grok_phase_peer.py','docs/TRAIN_PROVIDER_TERMINAL_SNAPSHOT_V1.md','docs/ORDINARY_NATIVE_TRAIN_PORT.md']
with zipfile.ZipFile(dest/'source-snapshot.zip','w',zipfile.ZIP_DEFLATED) as z:
    for name in sourcefiles:z.writestr(name,(repo/name).read_bytes())
checks={name:json.loads((base/'work'/name/'check.json').read_bytes()) for name in runs}
assert all(c['source_unchanged'] and not c['clean_status'] for c in checks.values())
write('SUMMARY.json',{'schema':'ordinary-provider-foundation-synthetic-archive-v1','checked_source':'dade5286ac7514bed8df1b31574dd9ccfda35c64',
    'source_scope':'Closed native ordinary preflight and terminal accounting extension only; ordinary controller admission unchanged',
    'checks':checks,'test_counts':{'ordinary-provider-preflight-r1':{'passed':33,'failed':0},'ordinary-provider-terminal-r1':{'passed':75,'failed':2},'ordinary-provider-terminal-r2':{'passed':77,'failed':0}},
    'retained_failure':'Two state/config tests incorrectly required all audit replay to fail after poison restored the durable stop marker; corrected tests distinguish ineligible audit evidence from unresolved source/response drift.',
    'raw_member_count':len(members),'raw_zip_sha256':sha(raw.read_bytes()),'original_to_zip_byte_equal':True,
    'real_model_or_api_calls':0,'scientific_effectiveness_proven':False,'validation_opened':False,'ordinary_73_controller_obligations_completed':False})
write('archive-builder.py',Path(__file__).read_bytes())
manifest={p.relative_to(dest).as_posix():{'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for p in sorted(dest.rglob('*')) if p.is_file()}
write('MANIFEST.json',manifest)
outer=dest.with_suffix('.zip')
with zipfile.ZipFile(outer,'w',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(dest.rglob('*')):
        if p.is_file():z.writestr(p.relative_to(dest).as_posix(),p.read_bytes())
with zipfile.ZipFile(outer) as z:
    for name in z.namelist():assert z.read(name)==(dest/name).read_bytes()
proof={'payload_files':len(manifest)+1,'raw_members':len(members),'outer_zip_sha256':sha(outer.read_bytes()),'raw_zip_sha256':sha(raw.read_bytes()),'byte_equal':True}
(base/'work/ordinary-provider-foundation-byte-proof.json').write_text(json.dumps(proof,indent=2));print(json.dumps(proof))
