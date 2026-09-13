"""Archive the frozen merged authoring seam using only its synthetic test root."""
import hashlib, json, shutil, subprocess, zipfile
from pathlib import Path
tree=Path('E:/_ryanDev/AI/research-loop-modular/integration'); work=tree.parent/'work'
prefix='authoring-integrated-root-r1'; base=work/prefix
out=tree/'results/modular-engineering-20260914/authoring-root'
sha=lambda raw:hashlib.sha256(raw).hexdigest()
def write(path, value):path.write_bytes((json.dumps(value,indent=2)+'\n').encode())
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=tree,text=True).strip()
assert not subprocess.check_output(['git','status','--porcelain'],cwd=tree).strip()
closed=json.loads((work/(prefix+'-closed.json')).read_bytes())
assert closed['commit']==head and closed['source_unchanged'] and closed['source_count']==585
assert closed['exit_code']==0 and closed['junit']=={'tests':36,'failures':0,'errors':0,'skipped':0}
out.mkdir(parents=True,exist_ok=False);(out/'.gitattributes').write_bytes(b'* -text\n')
for suffix in ('-before.json','-closed.json','.xml'):shutil.copyfile(work/(prefix+suffix),out/(prefix+suffix))
for name in ('m9-integrated-checkout-byte-repair-r1.json','m9-known-cost-integrated-archive-root-r1.json',
             'authoring-integrated-archive-root-r1.json','initialize-only-integrated-archive-root-r1.json'):
    shutil.copyfile(work/name,out/name)
rows=[];excluded=[]
with zipfile.ZipFile(out/'original-synthetic-evidence.zip','x',zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(base.rglob('*')):
        if not path.is_file():continue
        relative=path.relative_to(base).as_posix()
        linked=any(p.is_symlink() or p.is_junction() for p in (path,*path.parents) if p.is_relative_to(base))
        permitted=(not linked and path.suffix in {'.json','.jsonl','.txt','.bin','.csv','.toml'}
                   and not path.name.startswith(('key-','auth.')) and path.name!='synthetic-auth'
                   and 'store' not in path.relative_to(base).parts)
        if not permitted:excluded.append(relative);continue
        raw=path.read_bytes();archive.writestr(relative,raw)
        rows.append({'path':relative,'sha256':sha(raw),'bytes':len(raw)})
with zipfile.ZipFile(out/'original-synthetic-evidence.zip') as archive:
    assert len(archive.namelist())==len(rows) and all(sha(archive.read(row['path']))==row['sha256'] for row in rows)
write(out/'archive-members.json',{'original-synthetic-evidence':rows})
write(out/'excluded-paths.json',excluded)
write(out/'checks.json',{k:v for k,v in closed.items() if k!='source_after'})
shutil.copyfile(__file__,out/'archive_evidence.py')
(out/'README.md').write_bytes(b'''# Integrated private material-authoring engineering check

The merged source passed 36 checks with 585 source/document hashes unchanged.
The authoring worker uses four synthetic reference publications, real private
rendering and signatures, and a synthetic ACP peer over owned subprocess pipes.
The successful authoring fixture preserves all 36 categories and 72 evaluator
opportunities: 28 provisional materials are ready and eight remain unresolved.
Its ready inventory has 140 future review/evaluator entries. No review request
is dispatched by the authoring step. All authored expected targets remain unknown.

The existing diagnostic worker seam and coherent native-binding rejection cases
also pass. Fault cases preserve denominators, known main usage and terminal
dispatch state. Fixtures use no actual login, model generation or validation.
Native wire records here contain only synthetic fixture text. Key files and
the separate synthetic reference store are excluded and indexed as omissions.

This archive also preserves independent byte verification of the source
authoring and initialize-only archives, and the original M9 checkout text
normalization mismatch repaired by restoring the exact committed file bytes.
Real authoring remains unsuccessful at the older CLI initialization stage;
these engineering checks do not claim material quality, calibration or effects.
''')
write(out/'archive-integrity.json',{p.relative_to(out).as_posix():{'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for p in out.rglob('*') if p.is_file()})
print(json.dumps({'source':head,'files':len(list(out.iterdir())),'zip_members':len(rows),'excluded':len(excluded)}))
