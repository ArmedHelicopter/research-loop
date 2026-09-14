"""Retain the bounded fresh-observation regression, including failed attempts."""
import hashlib
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

tree = Path(r'E:\_ryanDev\AI\research-loop-modular\integration')
work = tree.parent / 'work'
base = Path(r'C:\codex-modular-checks')
out = tree / 'results/modular-engineering-20260914/provider-observation'
sha = lambda raw: hashlib.sha256(raw).hexdigest()
write = lambda path, body: path.write_bytes((json.dumps(body, indent=2)+'\n').encode())
assert not subprocess.check_output(['git','status','--porcelain'], cwd=tree).strip()
head = subprocess.check_output(['git','rev-parse','HEAD'],cwd=tree,text=True).strip()
checks = [('red-r1',4,4), ('green-r1',67,1), ('green-r2',67,0)]
closed_rows = []
out.mkdir(parents=True, exist_ok=False)
(out/'.gitattributes').write_bytes(b'* -text\n')
excluded = {}
for name, total, failures in checks:
    prefix = base / ('provider-observation-'+name)
    before = json.loads(Path(str(prefix)+'-before.json').read_bytes())
    closed = json.loads(Path(str(prefix)+'-closed.json').read_bytes())
    assert closed['source_unchanged'] and closed['junit'] == {'tests':total,'failures':failures,'errors':0,'skipped':0}
    closed_rows.append({k:v for k,v in closed.items() if k != 'source_after'})
    with zipfile.ZipFile(Path(str(prefix)+'-sources.zip')) as archive:
        assert {n:sha(archive.read(n)) for n in archive.namelist()} == before['source_before']
    for suffix in ('-before.json','-closed.json','.xml','-stdout.txt','-sources.zip','-source-members.json'):
        source = Path(str(prefix)+suffix)
        assert source.exists(), source
        shutil.copyfile(source,out/source.name)
    omitted=[]
    with zipfile.ZipFile(out/(prefix.name+'-originals.zip'),'x',zipfile.ZIP_DEFLATED) as archive:
        for current, dirs, files in os.walk(prefix,topdown=True,followlinks=False):
            parent=Path(current)
            for name in list(dirs):
                path=parent/name
                if (path.is_symlink() or getattr(path.stat(follow_symlinks=False),'st_file_attributes',0)&0x400
                        or name in {'__pycache__','.pytest_cache','cache','store','private-scorer-store','.codex','memtrace'}):
                    dirs.remove(name); omitted.append(path.relative_to(prefix).as_posix()+'/')
            for name in sorted(files):
                path=parent/name; relative=path.relative_to(prefix).as_posix()
                if (path.is_symlink() or getattr(path.stat(follow_symlinks=False),'st_file_attributes',0)&0x400
                        or name in {'auth.json','login-backup.json'} or name.startswith('key-')
                        or path.suffix in {'.key','.pyc','.exe'}):
                    omitted.append(relative); continue
                archive.writestr(relative,path.read_bytes())
    excluded[prefix.name]=omitted
for path in (__file__, work/'run_frozen_useful_checks.py', work/'run_frozen_checks_with_source.py'):
    path=Path(path); shutil.copyfile(path,out/path.name)
members={}
for path in out.glob('*.zip'):
    with zipfile.ZipFile(path) as archive:
        assert len(archive.namelist()) == len(set(archive.namelist()))
        members[path.name]=[{'path':n,'bytes':len(archive.read(n)),'sha256':sha(archive.read(n))} for n in archive.namelist()]
write(out/'archive-members.json',members)
write(out/'exclusions.json',excluded)
write(out/'checkpoint.json',{'integration_head':head,'checks':closed_rows,'new_paid_calls':0,
    'validation_opened':False,'scientific_effectiveness_proven':False,
    'independent_review':'build_provider_phase reviewed production 78481b6; no concrete correctness issue found'})
(out/'README.md').write_bytes(b'''# One fresh provider inspection per phase verification

The old PhaseProviderSession verified each original twice: configuration()
called inspect(), followed by another inspect(). The new method returns an
immutable configuration and call tuple from one fresh strict inspection.
This is local observation only: it is neither a persistent cache nor sealing,
scoring, or acceptance authority. Every later verification rereads originals.

The four red cases replayed two calls as [1,2,1,2] instead of [1,2]. Production
78481b6 repaired this. The first repaired check passed 66/67; one new fixture
used calls_root instead of the real Codex call_root. 0c5c63e fixed only that
fixture path. The final frozen check passed 67/67, with all 618 source hashes
unchanged. Tests cover both provider types and later response/configuration
drift, followed by terminal refusal without another model call. The source ZIP
is captured before each run and checked against the original before manifest.

This proves the repeated replay was removed at that seam, not an end-to-end
throughput improvement. All model peers are synthetic. No real Grok request,
API purchase, validation score, or module effectiveness result is produced.
Original failures are retained. Keys, private stores, caches, profile material
and executables are excluded explicitly; these ZIPs are not standalone
authenticated replay environments. Complete originals remain locally.
''')
write(out/'archive-integrity.json',{p.relative_to(out).as_posix():{'bytes':p.stat().st_size,'sha256':sha(p.read_bytes())}
    for p in sorted(out.rglob('*')) if p.is_file()})
print(json.dumps({'archive':str(out),'files':sum(p.is_file() for p in out.rglob('*')),
    'zip_members':sum(len(rows) for rows in members.values())}))
