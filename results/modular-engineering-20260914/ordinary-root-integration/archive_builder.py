"""Retain the closed root integration delta, exact sources and synthetic originals."""
import hashlib,json,shutil,zipfile
from pathlib import Path
BASE=Path('E:/_ryanDev/AI/research-loop-modular')
PREFIX=BASE/'work/ordinary-root-integration-r1'
OUT=BASE/'integration/results/modular-engineering-20260914/ordinary-root-integration'
OUT.mkdir(parents=True,exist_ok=False)
sha=lambda raw:hashlib.sha256(raw).hexdigest()
def write(name,value):(OUT/name).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
closure=json.loads(Path(str(PREFIX)+'-closed.json').read_bytes())
assert closure['source_unchanged'] and closure['exit_code']==0 and closure['junit']['tests']==78
for suffix in ('-before.json','-closed.json','.xml','-stdout.txt','-sources.zip','-source-members.json'):
    shutil.copyfile(Path(str(PREFIX)+suffix),OUT/('checkpoint'+suffix))
members={'checkpoint-sources':json.loads((OUT/'checkpoint-source-members.json').read_bytes())['members']}
rows=[];excluded=[]
with zipfile.ZipFile(OUT/'originals.zip','x',zipfile.ZIP_DEFLATED) as z:
    for path in sorted(PREFIX.rglob('*')):
        if not path.is_file():continue
        name=path.relative_to(PREFIX).as_posix()
        if (path.is_symlink() or not path.resolve().is_relative_to(PREFIX.resolve())
                or path.name in {'auth.json','login.json'} or '__pycache__' in path.parts
                or path.suffix in {'.pyc','.key'}
                or (path.suffix=='.exe' and not (path.name=='synthetic-grok.exe' and path.stat().st_size<1024))):
            excluded.append(name);continue
        raw=path.read_bytes();z.writestr(name,raw);rows.append({'path':name,'bytes':len(raw),'sha256':sha(raw)})
members['originals']=rows
write('archive-members.json',members);write('excluded-paths.json',excluded)
shutil.copyfile(BASE/'work/ordinary-import-committed-verification-r1.json',OUT/'imported-archive-verification.json')
shutil.copyfile(__file__,OUT/'archive_builder.py')
(OUT/'.gitattributes').write_text('* -text\n',encoding='utf-8')
(OUT/'SCOPE.md').write_text('''# Root ordinary provider integration checkpoint

Frozen d40c6cd570e66d9137bc56f0cdce9fe079644a8a passed78/78 in369.078s,
with632 tracked source hashes unchanged. Checks cover43 singleton slot unions,
actual normal/linked/unknown singleton dispatch, Q3.2 native execution and its
configuration/projection/late-cell faults, all11 family configuration bindings,
last-score/final-accounting provenance failures and label isolation. This tests
the imported native ordinary ports with the root provider replay changes.

The independently closed full11-family82-check source9c2b2c9 and Q3.2 final
14-check sourcedb11758 are retained in their original archive. Their full
engineering grid records258 cells,816 synthetic MAIN opportunities,498 Docker
attempts and258 scorer calls. The root78-check delta does not repeat that whole
grid and does not upgrade every43 singleton configuration into an executed Q.

The two imported ordinary archives were checked against manifest/ZIP contents
and all24 committed Git blobs. The older67-case mixed-line-ending source
reconstruction limitation remains explicit in that archive. No real model/API
calls or validation acceptance occurred in any of these engineering checks.
Retrieval/review's scientific endpoint gap, C5 execution/selection/acceptance and
the separate Q6.3 metaprogram obligation remain unresolved where recorded.
''',encoding='utf-8')
write('archive-integrity.json',{p.name:{'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size}
    for p in OUT.iterdir() if p.is_file()})
diagnostic=BASE/'integration/results/modular-engineering-20260914/grok-initialize-wct'
shutil.copytree(BASE/'work/grok-initialize-wct-archive-r1',diagnostic)
print(json.dumps({'ordinary_files':len(list(OUT.iterdir())),'ordinary_zip_members':sum(map(len,members.values())),
                  'diagnostic_files':len(list(diagnostic.iterdir()))}))
