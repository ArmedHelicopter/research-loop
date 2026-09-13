"""Preserve the merged native TRAIN seam and original integration byte failures."""
import hashlib,json,shutil,subprocess,zipfile
from pathlib import Path
tree=Path('E:/_ryanDev/AI/research-loop-modular/integration');work=tree.parent/'work'
prefix='grok-provider-integrated-root-r1';base=work/prefix
out=tree/'results/modular-engineering-20260914/grok-provider-root'
sha=lambda raw:hashlib.sha256(raw).hexdigest()
def write(path,body):path.write_bytes((json.dumps(body,indent=2)+'\n').encode())
closed=json.loads((work/(prefix+'-closed.json')).read_bytes())
assert closed['source_unchanged'] and closed['source_count']==588 and closed['exit_code']==0
assert closed['junit']=={'tests':33,'failures':0,'errors':0,'skipped':0}
assert not subprocess.check_output(['git','status','--porcelain'],cwd=tree).strip()
assert not subprocess.check_output(['git','diff','--name-only',closed['commit'],'HEAD','--','research_loop','evaluation','tests'],cwd=tree).strip()
out.mkdir(parents=True,exist_ok=False);(out/'.gitattributes').write_bytes(b'* -text\n')
for suffix in ('-before.json','-closed.json','.xml'):shutil.copyfile(work/(prefix+suffix),out/(prefix+suffix))
proofs=['grok-original-integrated-archive-r1.json','grok-original-integrated-archive-r2.json',
        'grok-repair-integrated-archive-r1.json','grok-original-integrated-byte-repair-r1.json',
        'grok-repair-integrated-checkout-repair-r1.json','grok-integrated-archive-byte-closure-r1.json',
        'grok-postcommit-check-premature-r1.json','grok-integrated-committed-archives-r1.json']
for name in proofs:shutil.copyfile(work/name,out/name)
rows=[];excluded=[];denominators={}
with zipfile.ZipFile(out/'original-synthetic-evidence.zip','x',zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(base.rglob('*')):
        if not path.is_file():continue
        relative=path.relative_to(base).as_posix();parts=path.relative_to(base).parts
        linked=any(p.is_symlink() or p.is_junction() for p in (path,*path.parents) if p.is_relative_to(base))
        permitted=(not linked and path.suffix in {'.json','.jsonl','.txt','.bin','.csv','.toml','.py'}
                   and not path.name.startswith(('key-','auth.')) and path.suffix!='.key'
                   and not set(parts)&{'store','private-scorer-store','.codex'})
        if not permitted:excluded.append(relative);continue
        raw=path.read_bytes();archive.writestr(relative,raw)
        rows.append({'path':relative,'sha256':sha(raw),'bytes':len(raw)})
        if path.name=='controller-attempt.json':denominators[relative]=json.loads(raw)
with zipfile.ZipFile(out/'original-synthetic-evidence.zip') as archive:
    assert len(archive.namelist())==len(rows) and all(sha(archive.read(r['path']))==r['sha256'] for r in rows)
write(out/'archive-members.json',{'original-synthetic-evidence':rows})
write(out/'excluded-paths.json',excluded);write(out/'denominators.json',denominators)
write(out/'checks.json',{k:v for k,v in closed.items() if k!='source_after'})
shutil.copyfile(__file__,out/'archive_evidence.py')
(out/'README.md').write_bytes(b'''# Merged Grok public TRAIN provider engineering closure

Source 834b3b6 passed 33 checks with 588 frozen source/document hashes unchanged.
All repaired native provider tests run together with the authoring and diagnostic
worker seams and label isolation. The merged fixture preserves distinct TRAIN,
diagnostic and authoring responses, identities and incomplete-usage scenarios.
Only the executable identity and OS spawn are synthetic: the default native
entry performs real fresh-context/configuration checks before each ACP peer.

The complete two-task M4/M5 v4 panel preserves 40 MAIN and 40 possible initial
title opportunities, eight actual Docker executions and eight independent
scores. Unknown MAIN and provenance-fault cases retain all eight rows, consume
only original attempted calls, retain known MAIN usage and stop later dispatch.
Original wire, reservation, source, configuration and response substitutions
are rejected before further calls. Title totals and settlement remain unknown.

The pre-repair and repaired source archives are both retained. Their original
ZIPs remain exact; this root closure includes the original checkout/index byte
mismatches, stat-cache-hidden conversion repairs and prematurely started Git
verification failure. The final bulk check proves all 1252 files, including both
ZIPs, match their manifests and committed bytes. Scoped -text rules retain the
original payload bytes; historical manifests are unchanged.

All raw records in this archive are synthetic engineering fixtures. Auth/key
files, synthetic private reference stores and linked fixture paths are excluded.
This provider version admits only the frozen eight-cell M4/M5 panel; other
controller families still require explicit provider portability work. No actual
model generation, validation access, calibration or scientific effect is claimed.
''')
write(out/'archive-integrity.json',{p.relative_to(out).as_posix():{'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for p in out.rglob('*') if p.is_file()})
print(json.dumps({'source':closed['commit'],'files':len(list(out.iterdir())),'zip_members':len(rows),'excluded':len(excluded)}))
