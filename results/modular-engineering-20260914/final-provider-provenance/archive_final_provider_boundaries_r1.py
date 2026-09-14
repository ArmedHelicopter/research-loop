"""Archive retained failures, exact tested sources and final native-boundary checks."""
import hashlib
import json
import os
import shutil
import stat
import subprocess
import zipfile
from pathlib import Path

tree = Path(r'E:\_ryanDev\AI\research-loop-modular\integration')
work = tree.parent / 'work'
old = Path(r'C:\Users\Administrator\.codex\tmp\modular-checks')
fresh = Path(r'C:\codex-modular-checks')
out = tree / 'results/modular-engineering-20260914/final-provider-provenance'
checks = [(old/'phase-abort-integrated-root-r1', 25, 0),
          (old/'m4m5-final-provenance-red-r1', 2, 2),
          (old/'m4m5-final-provenance-green-r1', 42, 7),
          (fresh/'m4m5-final-provenance-green-r2', 42, 0)]
sha = lambda b: hashlib.sha256(b).hexdigest()
write = lambda p,b: p.write_bytes((json.dumps(b, indent=2) + '\n').encode())
assert not subprocess.check_output(['git','status','--porcelain'],cwd=tree).strip()
head = subprocess.check_output(['git','rev-parse','HEAD'],cwd=tree,text=True).strip()
closures = []
for prefix,count,failed in checks:
    closed = json.loads(Path(str(prefix)+'-closed.json').read_bytes())
    assert closed['source_unchanged'] and closed['junit'] == {'tests':count,'failures':failed,'errors':0,'skipped':0}
    closures.append({k:v for k,v in closed.items() if k != 'source_after'})
out.mkdir(parents=True, exist_ok=False)
(out/'.gitattributes').write_bytes(b'* -text\n')
exclusions = {}
for prefix,_,_ in checks:
    before = json.loads(Path(str(prefix)+'-before.json').read_bytes())
    suffixes = ('-before.json','-closed.json','.xml','-stdout.txt','-sources.zip','-source-members.json',
                '-recovered-sources.zip','-recovered-source-members.json','-recovered-test-source.zip','-recovered-test-source.json')
    for suffix in suffixes:
        path = Path(str(prefix)+suffix)
        if path.exists(): shutil.copyfile(path,out/path.name)
    source_members = {}
    for suffix in ('-sources.zip','-recovered-sources.zip','-recovered-test-source.zip'):
        path = Path(str(prefix)+suffix)
        if not path.exists():continue
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                assert name not in source_members
                source_members[name] = sha(archive.read(name))
    assert source_members == before['source_before'], prefix.name
    omitted = []
    with zipfile.ZipFile(out/(prefix.name+'-originals.zip'),'x',zipfile.ZIP_DEFLATED) as archive:
        for current,dirs,files in os.walk(prefix,topdown=True,followlinks=False):
            parent = Path(current)
            for name in list(dirs):
                p=parent/name; info=p.stat(follow_symlinks=False)
                if (p.is_symlink() or getattr(info,'st_file_attributes',0)&0x400
                        or name in {'__pycache__','.pytest_cache','cache','store','private-scorer-store','.codex','memtrace'}):
                    dirs.remove(name); omitted.append(p.relative_to(prefix).as_posix()+'/')
            for name in sorted(files):
                p=parent/name; relative=p.relative_to(prefix).as_posix(); info=p.stat(follow_symlinks=False)
                if (p.is_symlink() or getattr(info,'st_file_attributes',0)&0x400
                        or name in {'auth.json','login-backup.json'} or name.startswith('key-')
                        or p.suffix in {'.key','.pyc','.exe'}):
                    omitted.append(relative); continue
                archive.writestr(relative,p.read_bytes())
    exclusions[prefix.name] = omitted

for stem in ('phase-provider-helper-closed-originals-r2','phase-provider-exact-tested-sources-r2'):
    source=work/(stem+'.zip'); manifest=json.loads((work/(stem+'.json')).read_bytes())
    assert sha(source.read_bytes()) == manifest['archive_sha256']
    rows={row['path']:row for row in manifest['members']}
    with zipfile.ZipFile(source) as archive:
        assert len(archive.namelist())==len(rows) and set(archive.namelist())==set(rows)
        for name,row in rows.items():
            raw=archive.read(name); assert sha(raw)==row['sha256'] and len(raw)==row['bytes']
    shutil.copyfile(source,out/source.name)
    shutil.copyfile(work/(stem+'.json'),out/(stem+'.json'))

for name in ('run_frozen_useful_checks.py','run_frozen_checks_with_source.py','recover_frozen_source_snapshot.py',
             'recover_m4m5_red_test_source_r1.py','recover_m4m5_red_test_source_r2.py',
             'c4-provider-root-committed-archive-r1.json','grok-initialize-committed-archive-r1.json'):
    shutil.copyfile(work/name,out/name)
shutil.copyfile(__file__,out/Path(__file__).name)
members={}
for path in out.glob('*.zip'):
    with zipfile.ZipFile(path) as archive:
        assert len(archive.namelist())==len(set(archive.namelist()))
        members[path.stem]=[{'path':name,'bytes':len(archive.read(name)),'sha256':sha(archive.read(name))}
                            for name in archive.namelist()]
write(out/'archive-members.json',members)
write(out/'exclusions.json',exclusions)
write(out/'checkpoint.json',{'integration_head':head,'checks':closures,'exact_tested_sources_verified':True,
    'source_composition':'M4/M5 source equals acde220; only phase_provider.py/test_phase_provider.py differ and equal root25-pass75056cf',
    'independent_review':'grok_provider_independent_review read acde220: no concrete blocking defect; source review only',
    'real_provider_calls':0,'validation_opened':False,'scientific_effectiveness_proven':False})
(out/'README.md').write_text('''# Final native provider provenance checks

The M4/M5 controller previously released an estimated contrast after native
originals changed during the final score return or final accounting. Both
eight-cell regressions failed on 06254b2, retaining 40 MAIN calls and eight
independent scorer returns per case. acde220 adds post-score replay before cell
success and final original replay before contrast eligibility and reporting.
Historical authenticated scores remain available; provenance failure makes all
of them ineligible and the public contrast inconclusive. Native attempt and
receipt schemas are v2; legacy Codex receipts remain v1.

The first repaired check on the same frozen source passed 35/42: seven legacy
fixtures refused real ancestor MCP configuration because their new temporary
root was inside the user .codex directory. No production admission rule was
relaxed. A fresh C:/codex-modular-checks prefix outside that profile passed
42/42 on unchanged acde220. This retains the environment failure, rather than
replacing or renaming it as success. The source trees stayed unchanged during
every listed check. E: is an HDD; C: is NVMe; no throughput effect is inferred.

Root phase-abort integration separately passed 25/25 at 75056cf. Its originating
session binding and terminal accounting are independently exercised. Current
integration combines these two source closures. Relative to acde220, the only
changed production/test files are phase_provider.py and test_phase_provider.py,
whose bytes agree with that root phase checkpoint. This is source composition
evidence, not a claim that another combined root test run occurred.

Every tested .py/.md disk hash has matching source bytes in this archive. The
red source recovered 616 files from retained/Git/newline forms; the remaining
test was recovered by reversing three later assertions and restoring two
context CRLFs. Exact SHA equality with the pre-existing red manifest was
required. The failed initial recovery helpers remain alongside the successful
repair. New checks now capture disk source ZIPs before running. Imported helper
history retains its first failed attempt and exact source bytes separately.

All calls are synthetic native peers. Docker execution and scorer processes are
real engineering seams; there are no real Grok/API generations, validation reads
or scientific effectiveness results here. Auth, keys, executables, caches and
selected runtime stores are explicitly excluded. Complete originals remain at
their recorded local paths. These ZIPs are not standalone authenticated replay
environments. C5 selection, calibration, acceptance and the remaining native
controller checks are still outstanding.
''',encoding='utf-8')
write(out/'archive-integrity.json',{p.relative_to(out).as_posix():{'bytes':p.stat().st_size,'sha256':sha(p.read_bytes())}
                                 for p in sorted(out.rglob('*')) if p.is_file()})
print(json.dumps({'archive':str(out),'files':sum(p.is_file() for p in out.rglob('*')),
                  'zip_members':sum(len(rows) for rows in members.values()),
                  'excluded_paths':sum(len(rows) for rows in exclusions.values())}))
