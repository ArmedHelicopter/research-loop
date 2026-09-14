"""Preserve closed Q8.6 evidence, including failed development checks."""
import hashlib
import json
import zipfile
from pathlib import Path

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
ROOT = BASE / 'artifact-evidence-provenance'
OUT = ROOT / 'results/modular-engineering-20260915/research-version-artifacts-r1'
FINAL = BASE / 'work/q86-root-frozen-r1'
WORKER = BASE / 'work/q86-repair-frozen-r1'

def sha(raw): return hashlib.sha256(raw).hexdigest()
def write(path, body):
    with path.open('xb') as stream: stream.write((json.dumps(body, indent=2) + '\n').encode())
def files(root):
    if not root.exists(): return
    for path in sorted(root.iterdir()):
        if path.is_symlink() or path.is_junction(): continue
        if path.is_dir(): yield from files(path)
        elif path.is_file(): yield path
def frozen(prefix, source_root):
    closed = json.loads(Path(str(prefix)+'-closed.json').read_bytes())
    assert closed['exit_code'] == 0 and closed['source_unchanged']
    assert closed['junit']['failures'] == closed['junit']['errors'] == closed['junit']['skipped'] == 0
    for relative, digest in closed['source_after'].items(): assert sha((source_root/relative).read_bytes()) == digest, relative
    return closed

worker = frozen(WORKER, BASE/'research-version-provenance-repair')
closed = frozen(FINAL, ROOT)
OUT.mkdir(parents=True, exist_ok=False)
(OUT/'.gitattributes').write_bytes(b'* -text\n')
originals, groups = [], []
def original(path, name=None):
    raw = path.read_bytes(); target=OUT/(name or path.name)
    with target.open('xb') as stream: stream.write(raw)
    originals.append({'file':target.name,'original_path':str(path),'sha256':sha(raw),'bytes':len(raw)})

prefixes = [Path('E:/_codex_tasks/research-version-artifacts/q86-frozen-r4'), WORKER, FINAL,
    *(BASE/'work'/name for name in ('q86-repair-dev-r1','q86-repair-grid-r1','q86-runner-dev-r1','q86-repair-dev-r2'))]
for prefix in prefixes:
    source_manifest = Path(str(prefix)+'-source-members.json')
    if source_manifest.exists():
        meta=json.loads(source_manifest.read_bytes()); archive=Path(str(prefix)+'-sources.zip')
        assert sha(archive.read_bytes()) == meta['archive_sha256']
        with zipfile.ZipFile(archive) as z:
            assert z.testzip() is None
            assert set(z.namelist()) == {row['path'] for row in meta['members']}
            for row in meta['members']:
                raw=z.read(row['path']); assert len(raw)==row['bytes'] and sha(raw)==row['sha256']
    for suffix in ('-before.json','-closed.json','.xml','-sources.zip','-source-members.json','-output.txt'):
        path=Path(str(prefix)+suffix)
        if path.exists(): original(path)
    runtime_root=prefix if prefix in (prefixes[0],WORKER,FINAL) else Path(str(prefix)+'-temp')/'pytest'
    members=list(files(runtime_root))
    roots=sorted({p.parent for p in members if p.name.startswith('research-version-') and (p.name.endswith('.json') or p.name.endswith('.json.partial'))})
    selected=[]; specimens=[]
    for index, directory in enumerate(roots):
        # Include only the actual sidecar files, never an enclosing test dataset.
        direct=[p for p in directory.iterdir() if p.is_file() and not p.is_symlink() and not p.is_junction()
                and (p.suffix in ('.json','.jsonl','.py') or p.name.endswith('.json.partial'))]
        for path in sorted(direct): selected.append((path, f'specimens/{index:03d}/'+path.name))
        specimens.append({'index':index,'original_root':str(directory),'files':len(direct),
            'classification':'retained_test_specimen_not_an_independent_scientific_sample'})
    # Controller plans bind all original returned cell and trace digests.
    for path in members:
        if path.name=='controller-attempt.json' and 'run' in path.relative_to(runtime_root).parts:
            selected.append((path,'controllers/'+path.relative_to(runtime_root).as_posix()))
    if selected:
        archive=OUT/(prefix.name+'-runtime.zip'); snapshots=[]
        with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
            for path, name in selected:
                raw=path.read_bytes(); mtime=path.stat().st_mtime_ns
                z.writestr(name,raw); snapshots.append({'path':name,'original_path':str(path),'bytes':len(raw),'sha256':sha(raw),'mtime_ns':mtime})
        with zipfile.ZipFile(archive) as z:
            assert z.testzip() is None
            for row in snapshots:
                raw=z.read(row['path']); path=Path(row['original_path'])
                assert len(raw)==row['bytes'] and sha(raw)==row['sha256']
                assert path.read_bytes()==raw and path.stat().st_mtime_ns==row['mtime_ns']
        originals.append({'file':archive.name,'sha256':sha(archive.read_bytes()),'bytes':archive.stat().st_size})
        groups.append({'prefix':str(prefix),'archive':archive.name,'specimens':specimens,'members':snapshots,
            'original_source_archive_retained':source_manifest.exists(),
            'scope':'exact retained bytes; historical/development specimens are not reevaluated with the repaired reader'})

for name in ('probe.py','results.json','REPORT.md'):
    original(BASE/'work/research-version-independent-2a8b360e'/name,'independent-2a8b360e-'+name)
for name in ('q86-coherent-probe-r1.py','q86-archive-inventory-r1.json'):
    original(BASE/'work'/name)
original(BASE/'work/q86-coherent-probe-r1/results.json','coherent-probe-r1-results.json')
for group_name in ('research-version-independent-2a8b360e','q86-coherent-probe-r1'):
    origin=BASE/'work'/group_name; archive=OUT/(group_name+'-originals.zip'); snapshots=[]
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for path in files(origin):
            if path.suffix not in ('.json','.jsonl','.py','.md') and not path.name.endswith('.json.partial'): continue
            raw=path.read_bytes(); rel=path.relative_to(origin).as_posix(); z.writestr(rel,raw)
            snapshots.append({'path':rel,'original_path':str(path),'sha256':sha(raw),'bytes':len(raw),'mtime_ns':path.stat().st_mtime_ns})
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for row in snapshots:
            raw=z.read(row['path']); p=Path(row['original_path'])
            assert sha(raw)==row['sha256'] and p.read_bytes()==raw and p.stat().st_mtime_ns==row['mtime_ns']
    originals.append({'file':archive.name,'sha256':sha(archive.read_bytes()),'bytes':archive.stat().st_size})
    groups.append({'archive':archive.name,'members':snapshots,'scope':'original independent reproduction and coherent-copy evidence'})
original(Path(__file__))
frozen(WORKER,BASE/'research-version-provenance-repair'); frozen(FINAL,ROOT)
manifest={'schema':'research-version-artifact-archive-v1','source_commit':closed['commit'],'worker_commit':worker['commit'],
    'root_junit':closed['junit'],'worker_junit':worker['junit'],'originals':originals,'runtime_groups':groups,
    'runtime_members':[{'archive':group['archive'],**row} for group in groups for row in group.get('members',[])],
    'specimens':[{'archive':group['archive'],**row} for group in groups for row in group.get('specimens',[])],
    'archive_new_callbacks':0,'archive_new_model_calls':0,'archive_new_docker_calls':0,'scientific_validated':False,
    'limits':['Synthetic engineering checks do not establish scientific effects.',
              'Repeated and modified specimen copies are not independent benchmark observations.',
              'Development runs have no retroactively invented frozen source archive.',
              'Historical readers require independently retained inputs and original source bytes.',
              'Failed audit prefixes cannot be accepted as complete artifacts.']}
write(OUT/'manifest.json',manifest)
write(OUT/'verification.json',{'status':'verified_bytes','originals':len(originals),'runtime_groups':len(groups),
    'bytes_and_mtime_unchanged':True,'source_archives_verified':True,'scientific_validated':False})
print(json.dumps({'output':str(OUT),'originals':len(originals),'runtime_groups':len(groups),'root_junit':closed['junit']}))
