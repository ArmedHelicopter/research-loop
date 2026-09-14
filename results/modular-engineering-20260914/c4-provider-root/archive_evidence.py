"""Preserve the four distinct root checks, fixes and original synthetic records."""
import hashlib,json,os,shutil,stat,subprocess,zipfile
from pathlib import Path
tree=Path('E:/_ryanDev/AI/research-loop-modular/integration');work=tree.parent/'work'
out=tree/'results/modular-engineering-20260914/c4-provider-root'
names=('c4-integrated-root-r1','c4-integrated-root-r2','c4-provider-c5-integrated-root-r3','provider-broker-integrated-root-r4')
expected=((21,1),(26,0),(143,1),(104,0));sha=lambda raw:hashlib.sha256(raw).hexdigest()
def write(path,body):path.write_bytes((json.dumps(body,indent=2)+'\n').encode())
assert not subprocess.check_output(['git','status','--porcelain'],cwd=tree).strip()
checks=[]
for name,(count,failed) in zip(names,expected,strict=True):
    b=json.loads((work/(name+'-closed.json')).read_bytes())
    assert b['source_unchanged'] and b['junit']=={'tests':count,'failures':failed,'errors':0,'skipped':0}
    checks.append({k:v for k,v in b.items() if k!='source_after'})
assert not subprocess.check_output(['git','diff','--name-only',checks[-1]['commit'],'HEAD','--','research_loop','evaluation','tests'],cwd=tree).strip()
out.mkdir(parents=True,exist_ok=False);(out/'.gitattributes').write_bytes(b'* -text\n')
members={};exclusions={}
for name in names:
    for suffix in ('-before.json','-closed.json','.xml','-stdout.txt'):
        source=work/(name+suffix)
        if source.is_file():shutil.copyfile(source,out/source.name)
    base=work/name;rows=[];excluded=[]
    with zipfile.ZipFile(out/(name+'.zip'),'x',zipfile.ZIP_DEFLATED) as archive:
        for current,dirs,files in os.walk(base,topdown=True,followlinks=False):
            parent=Path(current)
            for folder in list(dirs):
                path=parent/folder;info=path.stat(follow_symlinks=False)
                if (path.is_symlink() or getattr(info,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400)
                        or folder in {'__pycache__','.pytest_cache','cache','store','private-scorer-store','.codex','memtrace'}):
                    dirs.remove(folder);excluded.append(path.relative_to(base).as_posix()+'/')
            for filename in sorted(files):
                path=parent/filename;rel=path.relative_to(base).as_posix();info=path.stat(follow_symlinks=False)
                if (path.is_symlink() or getattr(info,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400)
                        or filename in {'auth.json','login-backup.json'} or filename.startswith('key-')
                        or path.suffix in {'.key','.pyc'}):
                    excluded.append(rel);continue
                raw=path.read_bytes();archive.writestr(rel,raw)
                rows.append({'path':rel,'sha256':sha(raw),'bytes':len(raw)})
    with zipfile.ZipFile(out/(name+'.zip')) as archive:
        assert len(archive.namelist())==len(rows) and set(archive.namelist())=={r['path'] for r in rows}
        for row in rows:
            raw=archive.read(row['path']);assert sha(raw)==row['sha256'] and len(raw)==row['bytes']
    members[name]=rows;exclusions[name]=excluded
write(out/'archive-members.json',members);write(out/'exclusions.json',exclusions);write(out/'checks.json',checks)
for name in ('c4-imported-archive-verified-r1.json','c5-imported-root-archive-r1.json','imported-provider-archives-root-r1.json',
             'c4-root-overlap-observations-r1.json','summarize_c4_overlap_observations_r1.py',
             'provider-route-coverage-r1.json','provider-route-coverage-r1.md',
             'integration-stale-sequencer-c5-r1.json'):
    shutil.copyfile(work/name,out/name)
shutil.copyfile(__file__,out/'archive_evidence.py')
(out/'README.md').write_bytes(b'''# Root C4, provider foundation and C5 preparation checkpoint

Four distinct frozen root checks are retained. The first ran 21 tests and
failed the universal C4 positive-overlap assertion. The second passed 26 after
ready-batch reservation was fixed. The expanded merged check passed 142 of 143;
its sole failure was a real Docker container-name collision in two simultaneous
equal timeout jobs. The final focused check passed 104 with source a1b4151 and
all 617 tracked source/document hashes unchanged. This is accumulated coverage,
not a claim that all 143 cases were freshly rerun at the final source.

All three C4 runs executed nine canonical history builds, 22 target cells,
169 scripted model calls, 80 Docker jobs and 22 independent process scores.
M8 is target-only and M9 history-only. All legal leave-one-out procedures, B0,
the useful ordinary control and both structural minus-M2 rows remain recorded.
The first observation had eight zero-overlap phases among 16 M8 target phases;
the repaired second observation had none. Host conditions were not controlled,
so these timing observations do not establish throughput benefit.

Ready capacity is persisted before submitting a worker batch. The regression
checks submission ordering directly, without relying on a thread-start delay.
Container names now have per-invocation nonces. A fixed-clock 32-invocation
test checks unique names and exact timeout-cleanup ownership; the actual Docker
timeout test also fixes the clock and requires both jobs to clean up. Original
failures, intervals, conflict output and source identities remain available.

The merged provider core/preflight retains original native request/response,
reservation, usage and exact per-cell call scopes. A new terminal snapshot
records historical observed lower bounds without claiming current originals,
complete costs or scoring eligibility. The phase abort union and the remaining
native controllers are downstream work, not completed by this archive.

C5 structural preparation replays eight synthetic M4/M5 TRAIN journals and
freezes a 32-cell synthetic identity grid. It cannot select a scientific winner,
lease validation, accept or deploy. This narrow source adapter does not complete
C5 or remove broader source/combination obligations.

All model records in the four ZIPs are synthetic; actual restricted Docker and
independent scorer processes ran where required. Opaque auth/key files, private
reference fixture stores, caches and linked paths are excluded. No real model
generation or real validation access occurred. Real material authoring, scorer
calibration, TRAIN effects, joint selection and validation acceptance remain
unfinished. Original source archives were separately checked against Git and
every nested member manifest; those proofs are retained here.
''')
write(out/'archive-integrity.json',{p.relative_to(out).as_posix():{'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size}
                                   for p in out.rglob('*') if p.is_file()})
print(json.dumps({'files':len(list(out.rglob('*'))),'zip_members':sum(len(v) for v in members.values()),
                 'excluded_paths':sum(len(v) for v in exclusions.values()),'checks':checks}))
