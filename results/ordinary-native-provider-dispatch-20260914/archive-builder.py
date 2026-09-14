"""Archive only closed checkpoints, with exact runtime and source byte proofs."""
import hashlib,json,subprocess,zipfile,sys
from pathlib import Path
base=Path('E:/_ryanDev/AI/research-loop-modular');repo=base/'ordinary-provider-port'
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
            if path.name in {'auth.json','login-backup.json'} or path.suffix=='.key':
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
full=next(run for run in runs if run.name=='ordinary-all-families-r2')
rows=[]
for i in range(11):
    root=full/'pytest'/f'test_full_registered_family_de{i}'
    config=json.loads((root/'native-config.json').read_bytes())
    attempt=json.loads((root/'run/controller-attempt.json').read_bytes())
    receipt=json.loads((root/'run/controller-receipt.json').read_bytes())
    cells=attempt['cells']
    rows.append({'configuration_schema':config['schema'],'status':receipt['status'],'cells':len(cells),
        'main':receipt['actual_model_usage']['main_opportunities'],
        'docker_attempts':sum(r.get('docker_attempts',0) for r in cells),
        'independent_scorer_calls':sum(r.get('scorer_calls',0) for r in cells)})
assert {k:sum(r[k] for r in rows) for k in ('cells','main','docker_attempts','independent_scorer_calls')}==dict(cells=258,main=816,docker_attempts=498,independent_scorer_calls=258)
write('FULL-FAMILY-READBACK.json',{'source':'original frozen full-family controller attempts and receipts','families':rows,
    'totals':{k:sum(r[k] for r in rows) for k in ('cells','main','docker_attempts','independent_scorer_calls')},
    'qualification':'Synthetic provider engineering; native entry peers replace only final OS spawn. Not actual model or scientific validation.'})
write('SUMMARY.json',{'schema':'ordinary-native-provider-dispatch-evidence-v1',
    'source_commits':sorted({c['check']['source_commit'] for c in checks}),
    'checkpoints':len(checks),'raw_members':len(members),'all_raw_bytes_equal_originals':True,
    'exact_tested_source_zip_matches_every_frozen_disk_hash':True,
    'scope':'43 singleton driver slot unions;30 ordinary combination IDs across11 families; separate Q3.2 prospective execution. Exact executed checks are in CHECKPOINTS.json.',
    'separate_owners':['M4/M5 v4','C4 full/LOO','15 build/phase obligations'],
    'older_checkpoint':{'commit':'8918b41','outer_zip_sha256':'5e83b1c4c5569186a3d68ab930b4729513ac77b384c4942a7df9656fd0996dea',
        'qualification':'67 tests at6e0221f: original runtime bytes archived, source-before==after, but tested train_controller.py mixed disk line endings not reconstructed from normalized Git. Original reconstruction failure retained.'},
    'C5':'Selection and separate validation remain outstanding; this provider port does not complete them.',
    'real_model_or_api_calls':0,'validation_opened':False,'scientific_effectiveness_proven':False})
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
