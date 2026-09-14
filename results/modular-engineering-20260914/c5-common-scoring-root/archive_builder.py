"""Exact frozen check bytes and allowlisted native readiness observations."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

BASE=Path('E:/_ryanDev/AI/research-loop-modular')
DEST=BASE/'integration/results/modular-engineering-20260914'
sha=lambda raw:hashlib.sha256(raw).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')


def close_index(out):
    (out/'.gitattributes').write_text('* -text\n',encoding='utf-8')
    shutil.copyfile(__file__,out/'archive_builder.py')
    write(out/'archive-integrity.json',{p.relative_to(out).as_posix():{'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size}
        for p in out.rglob('*') if p.is_file()})


def checks(name, prefixes, text):
    out=DEST/name;out.mkdir(parents=True,exist_ok=False)
    members={};excluded=[];missing=[]
    for prefix in prefixes:
        root=BASE/'work'/prefix
        closure=json.loads(Path(str(root)+'-closed.json').read_bytes())
        assert closure['source_unchanged']
        for suffix in ('-before.json','-closed.json','.xml','-stdout.txt','-sources.zip','-source-members.json'):
            source=Path(str(root)+suffix)
            if suffix=="-stdout.txt" and not source.exists():
                missing.append(str(source));continue
            shutil.copyfile(source,out/(prefix+suffix))
        members[prefix+'-sources']=json.loads(Path(str(root)+'-source-members.json').read_bytes())['members']
        rows=[]
        with zipfile.ZipFile(out/(prefix+'-originals.zip'),'x',zipfile.ZIP_DEFLATED) as z:
            for path in sorted(root.rglob('*')):
                if not path.is_file():continue
                relative=path.relative_to(root).as_posix()
                if (path.is_symlink() or not path.resolve().is_relative_to(root.resolve())
                        or path.name in {'auth.json','login.json'} or '__pycache__' in path.parts
                        or path.suffix in {'.key','.pyc'}
                        or (path.suffix=='.exe' and not (path.name=='synthetic-grok.exe' and path.stat().st_size<1024))):
                    excluded.append(prefix+'/'+relative);continue
                raw=path.read_bytes();z.writestr(relative,raw)
                rows.append({'path':relative,'bytes':len(raw),'sha256':sha(raw)})
        members[prefix+'-originals']=rows
    write(out/'archive-members.json',members);write(out/'excluded-paths.json',excluded);write(out/'unavailable-stdout.json',missing)
    (out/'SCOPE.md').write_text(text,encoding='utf-8');close_index(out)


checks('c5-common-scoring-root',['c5-common-scoring-root-r1'],'# Root common TRAIN scorer integration\n\nFrozen b31acf24ecac2d56548c6e9b5dcc06fd405694e0 passed23/23 in31.609s;\n639 exact source hashes unchanged. Actual independent scorer subprocess with\nsynthetic signed candidates from both primary benchmarks, panel tampering and\nlabel checks. No model/API calls, real common grid or validation acceptance.\n')
print('Root common scorer archive created')
