"""Archive one closed source-captured engineering checkpoint on task storage."""
import hashlib,json,sys,zipfile
from pathlib import Path

work=Path('E:/_ryanDev/AI/research-loop-modular/work').resolve()
prefix=Path(sys.argv[1]).resolve()
assert prefix.parent==work and prefix.is_dir()
before=json.loads(Path(str(prefix)+'-before.json').read_bytes())
closed=json.loads(Path(str(prefix)+'-closed.json').read_bytes())
sources=json.loads(Path(str(prefix)+'-source-members.json').read_bytes())
assert closed['source_unchanged'] and closed['new_paid_calls']==0
assert before['commit']==closed['commit']==sources['commit']
assert {r['path']:r['sha256'] for r in sources['members']}==before['source_before']
source_zip=Path(str(prefix)+'-sources.zip')
assert hashlib.sha256(source_zip.read_bytes()).hexdigest()==sources['archive_sha256']
archive=Path(str(prefix)+'-closed-originals-r5.zip')
manifest=Path(str(prefix)+'-closed-originals-r5.json')
assert not archive.exists() and not manifest.exists()
rows=[];excluded=[]
def put(output,name,raw):
    output.writestr(name,raw); rows.append({'path':name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as output:
    files=sorted(set([*prefix.rglob('*'),*(Path(str(prefix)+suffix) for suffix in
        ('-before.json','-closed.json','-source-members.json','.xml','.stdout.txt','.stderr.txt','-wall.json','-processes.json','-performance-r1.json','-watchdog-config.json','-watchdog.jsonl','-watchdog.stdout.txt','-watchdog.stderr.txt','-cleanup.json'))]))
    for path in files:
        if not path.is_file(): continue
        name=path.relative_to(work).as_posix()
        if path.is_symlink(): excluded.append({'path':name,'reason':'duplicate symbolic fixture alias'}); continue
        assert work in path.resolve().parents
        if (path.name=='auth.json' or path.suffix in {'.key','.exe','.pyc','.lock'}
                or any(part in {'__pycache__','.pytest_cache','.venv','venv','keys','auth'} for part in path.parts)):
            excluded.append({'path':name,'reason':'authentication/key/cache/runtime excluded'}); continue
        assert path.suffix in {'.json','.jsonl','.txt','.xml','.py','.md','.csv','.toml','.sha256','.previous',
            '.sqlite','.sqlite3','.db','.sqlite-wal','.sqlite-shm'},str(path)
        put(output,name,path.read_bytes())
    with zipfile.ZipFile(source_zip) as original:
        for row in sources['members']:
            raw=original.read(row['path']); assert hashlib.sha256(raw).hexdigest()==row['sha256'],row['path']
            put(output,'tested-source/'+row['path'],raw)
    for name in ('run_frozen_useful_checks.py','run_frozen_checks_with_source.py','archive_build_phase_check_r1.py','archive_build_phase_check_r2.py','archive_build_phase_check_r3.py','archive_build_phase_check_r4.py','archive_build_phase_check_r5.py','start_native_execution_complete_r2.ps1','start_single_build_phase_check_r1.ps1','watch_native_phase_deadline_r1.ps1'):
        if (work/name).exists(): put(output,'commands/'+name,(work/name).read_bytes())
with zipfile.ZipFile(archive) as output:
    assert output.testzip() is None and len(output.namelist())==len(set(output.namelist()))==len(rows)
    for row in rows: assert hashlib.sha256(output.read(row['path'])).hexdigest()==row['sha256']
body={'schema':'build-phase-closed-original-archive-v1','archive':str(archive),'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files_verified_from_zip':len(rows),'source_archive':str(source_zip),'source_archive_sha256':sources['archive_sha256'],'scope':'allowlisted synthetic engineering evidence only; zero real model/API/VAL calls','source_encoding':'exact pre-check disk bytes verified against source_before','standalone_full_replay_environment':False,'original_paths_unchanged':True,'replay_boundary':'authentication, keys, caches and runtime excluded; full original tree remains local unchanged','files':rows,'exclusions':excluded,'closure':{k:closed[k] for k in ('commit','source_count','exit_code','wall_seconds','junit','report_sha256')}}
manifest.write_text(json.dumps(body,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:body[k] for k in ('archive','archive_sha256','files_verified_from_zip','source_archive_sha256','closure')}))
