"""Archive only closed checkpoints, with exact runtime and source byte proofs."""
import hashlib,json,subprocess,zipfile,sys
from pathlib import Path
base=Path('E:/_ryanDev/AI/research-loop-modular');repo=base/'grok130-deployment'
name=sys.argv[1];runs=[Path(p) for p in sys.argv[2:]]
dest=repo/'results'/name
checks=[]
import xml.etree.ElementTree as ET
sha=lambda b:hashlib.sha256(b).hexdigest()
for run in runs:
    check=json.loads((run/'check.json').read_bytes())
    assert check['source_unchanged'] and not check['clean_status']
    before=json.loads((run/'source-before.json').read_bytes())
    assert before==json.loads((run/'source-after.json').read_bytes())
    with zipfile.ZipFile(run/'exact-tested-source.zip') as source:
        assert set(source.namelist())==set(before)
        assert all(sha(source.read(p))==expected for p,expected in before.items())
    suite=ET.parse(run/'pytest.xml').getroot().find('testsuite')
    checks.append({'run':run.name,'pytest_counts':{k:suite.attrib[k] for k in ('tests','failures','errors','skipped')},'check':check,'exact_tested_source_sha256':sha((run/'exact-tested-source.zip').read_bytes())})
dest.mkdir(parents=True,exist_ok=False)
def write(name,body):(dest/name).write_bytes(body if isinstance(body,bytes) else json.dumps(body,indent=2).encode())
write('.gitattributes',b'** -text\n')
members={};excluded=[]
with zipfile.ZipFile(dest/'raw-evidence.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for run in runs:
        for path in sorted(run.rglob('*')):
            if not path.is_file():continue
            rel=path.relative_to(run)
            if path.name in {'auth.json','login-backup.json','synthetic-login','synthetic-auth'} or path.suffix=='.key':
                excluded.append(str(run.name+'/'+rel.as_posix()));continue
            if any(p in {'cache','__pycache__'} for p in rel.parts):continue
            name=run.name+'/'+rel.as_posix();raw=path.read_bytes()
            assert name not in members
            archive.writestr(name,raw)
            members[name]={'sha256':sha(raw),'bytes':len(raw),'original_path':str(path)}
with zipfile.ZipFile(dest/'raw-evidence.zip') as archive:
    assert set(archive.namelist())==set(members)
    for name,row in members.items():
        raw=archive.read(name)
        assert sha(raw)==row['sha256'] and raw==Path(row['original_path']).read_bytes()
write('RAW-MANIFEST.json',members)
write('EXCLUDED-NAMES.json',{'opaque_auth_or_key_bodies_never_opened':excluded,'caches_omitted':True})
write('CHECKPOINTS.json',checks)
write('SUMMARY.json',{'schema':'grok130-inventory-order-evidence-v1',
    'source_commits':sorted({c['check']['source_commit'] for c in checks}),
    'checkpoints':len(checks),'raw_members':len(members),'all_raw_bytes_equal_originals':True,
    'exact_tested_source_zip_matches_every_frozen_disk_hash':True,
    'scope':'Closed isolated 1.0.30 native deployment, diagnostic and material envelopes. Synthetic final-spawn peers exercise actual native launch preflight and original provenance readers. Legacy 1.0.13 default preserved; public TRAIN provider unchanged.',
    'runner_scope_correction':'The reused runner labels ordinary TRAIN engineering; actual executed suites and source pins are authoritative. This archive is deployment plumbing only.',
    'checkpoint_qualifications':{'r1':'0 passed /9 failed at8124b474: all new response-before-inventory cases stopped at premature preprompt_inventory_missing. Original failures retained.',
      'r2':'124 passed:29 deployment cases plus95 legacy cases; repaired sourcea086d8a. Explicit deployment waits under existing deadline; legacy unchanged.'},
    'prior_archive':'8994eed3046b81aa703f551078bf5f7e06999e07 remains immutable; this is additive inventory ordering closure.',
    'actual_readiness_failure':'root work/grok130-readiness-r1 remains unchanged, preprompt_inventory_missing,0prompt; not included because it contains actual private runtime data.',
    'binary_sha256':'ca24ea63272ba7881261f4a52498d1f5bd884b01da25845990422a10dd315266',
    'binary_source_equivalence_verified':False,
    'readiness_proven':False,'real_model_or_api_calls':0,'validation_opened':False,'scientific_effectiveness_proven':False})
write('archive-builder.py',Path(__file__).read_bytes())
write('checkpoint-runner.py',(base/'work/ordinary-provider-check.py').read_bytes())
manifest={p.name:{'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for p in dest.iterdir() if p.is_file()}
write('MANIFEST.json',manifest)
outer=dest.with_suffix('.zip')
with zipfile.ZipFile(outer,'w',zipfile.ZIP_STORED) as archive:
    for path in sorted(dest.iterdir()):archive.writestr(path.name,path.read_bytes())
with zipfile.ZipFile(outer) as archive:
    for name in archive.namelist():assert archive.read(name)==(dest/name).read_bytes()
proof={'archive':str(dest),'outer_zip_sha256':sha(outer.read_bytes()),
    'raw_zip_sha256':sha((dest/'raw-evidence.zip').read_bytes()),'raw_members':len(members),'payload_files':len(manifest)+1,
    'all_original_zip_manifest_bytes_equal':True}
(base/'work'/f'{dest.name}-byte-proof.json').write_text(json.dumps(proof,indent=2));print(json.dumps(proof))
