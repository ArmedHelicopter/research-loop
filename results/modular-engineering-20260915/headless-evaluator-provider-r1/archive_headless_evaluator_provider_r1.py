"""Retain the frozen private evaluator/primary factory gate with selected originals."""
from pathlib import Path
import hashlib
import json
import shutil
import zipfile

BASE=Path('E:/_ryanDev/AI/research-loop-modular');WORK=BASE/'work'
PREFIX=WORK/'headless-evaluator-provider-root-r1'
TARGET=BASE/'artifact-evidence-provenance/results/modular-engineering-20260915/headless-evaluator-provider-r1'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(path):return json.loads(path.read_bytes())
def write(path,value):
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,indent=2);stream.write('\n')
closed=read(Path(str(PREFIX)+'-closed.json'));before=read(Path(str(PREFIX)+'-before.json'))
assert closed['exit_code']==0 and closed['source_unchanged'] and before['source_before']==closed['source_after']
assert closed['commit'].startswith('cb939003') and not any(closed['junit'][k] for k in ('failures','errors','skipped'))
TARGET.mkdir(parents=True,exist_ok=False)
for suffix,name in (('-closed.json','closed.json'),('-before.json','before.json'),
                    ('-source-members.json','source-members.json'),('-sources.zip','sources.zip'),('.xml','checks.xml')):
    source=Path(str(PREFIX)+suffix);shutil.copyfile(source,TARGET/name)
    assert source.read_bytes()==(TARGET/name).read_bytes()
selected=('test_endpoint_port_native_and_0','test_postflight_failure_retain0',
          'test_prelaunch_refusal_retains0','test_primary_scorer_factory_co0')
rows=[]
for name in selected:
    root=PREFIX/name;assert root.is_dir() and not root.is_symlink()
    for p in sorted(root.rglob('*')):
        assert not p.is_symlink(),p
        if p.is_file():
            st=p.stat();rows.append({'source':str(p),'path':p.relative_to(PREFIX).as_posix(),
                'sha256':sha(p.read_bytes()),'bytes':st.st_size,'mtime_ns':st.st_mtime_ns})
archive=TARGET/'selected-synthetic-originals.zip'
with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as output:
    for row in rows:output.writestr(row['path'],Path(row['source']).read_bytes())
with zipfile.ZipFile(archive) as saved:
    assert saved.namelist()==[r['path'] for r in rows]
    for row in rows:
        p=Path(row['source']);raw=saved.read(row['path'])
        assert sha(raw)==row['sha256']==sha(p.read_bytes()) and len(raw)==row['bytes']
        assert p.stat().st_mtime_ns==row['mtime_ns']
write(TARGET/'selected-originals.json',{'scope':'synthetic OS/HTTP only; no actual Grok/API/VAL; fixture credentials synthetic',
    'selected_roots':selected,'files':rows,'zip_sha256':sha(archive.read_bytes()),'original_bytes_and_mtime_unchanged':True})
for name in ('run_frozen_checks_with_source.py','run_frozen_useful_checks.py',Path(__file__).name):
    shutil.copyfile(WORK/name,TARGET/name)
(TARGET/'.gitattributes').write_bytes(b'* -text\n')
write(TARGET/'summary.json',{'source_commit':closed['commit'],'junit':closed['junit'],
    'wall_seconds':closed['wall_seconds'],'source_files_unchanged':closed['source_count'],
    'selected_original_files':len(rows),'selected_original_roots':len(selected),
    'limits':['No actual Grok, API or VAL calls.', 'Primary factory and per-call replay only.',
              'Controller final scorer closure and lineage factory still need separate integration.'],
    'preliminary_checks':'First factory check retained 18 passes and 1 test assertion AttributeError; two actual synthetic scores completed. Corrected attribute plus additional source fixes passed 24 checks before this freeze. Preliminary checks are not added to this denominator.'})
print(json.dumps({'archive':str(TARGET),'junit':closed['junit'],'files':len(rows)}))
