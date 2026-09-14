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


checks('c5-common-scoring',['c5-common-scoring-r1','c5-common-scoring-r2'],'''# Common C5 TRAIN scoring boundary

Source2dfad0c closed43/44; the actual scorer startup rejected a fixture that
hashed JSON string encoding instead of the raw UTF-8 task handle. Source712d242
changes only that fixture and closed44/44 in35.922s,639 source files unchanged.
It includes a real scorer subprocess and two synthetic signed candidates, one
per primary benchmark, plus complete common panel contract and label checks.
Independent source review found no blocker within this boundary. Original
failed source, output and evidence remain here.

No model calls, actual common module builds, complete common execution grid,
authenticated TRAIN selection, validation or scientific efficacy are claimed.
The runtime must replay actual build and target originals before signing inputs.
''')
checks('grok130-root-checks',['grok130-root-integration-r1','grok130-root-inventory-r1'],'''# Root native deployment integration checks

Sourcefe77ef1 closed30/30,635 source files unchanged,27.046s. Sourcefcd175c
closed39/39,635 unchanged,21.172s, covering the later response-before-inventory
repair. Both use synthetic ACP peers below the native spawn seam and label
checks; neither check made a real model request. The separate native-readiness
archive records actual attempts, including the dispatched request with unknown
usage. Do not infer real readiness from these synthetic checks.
''')

out=DEST/'grok130-readiness';out.mkdir(exist_ok=False)
source_map={};observations=[]
for run,prefix in [('r1','grok130-root-integration-r1'),('r2','grok130-root-inventory-r1')]:
    root=BASE/'work'/('grok130-readiness-'+run)
    envelope=json.loads((root/'envelope.json').read_bytes())
    closure=json.loads((root/'closure.json').read_bytes())
    for name in ('driver.py','envelope.json','launch-reserved.json','closure.json'):
        shutil.copyfile(root/name,out/(run+'-'+name))
    if (root/'prompt-reservation.json').exists():
        shutil.copyfile(root/'prompt-reservation.json',out/(run+'-prompt-reservation.json'))
    with zipfile.ZipFile(BASE/'work'/(prefix+'-sources.zip')) as z:
        for i,(name,expected) in enumerate(envelope['frozen_files'].items()):
            path=Path(name)
            if path.suffix=='.exe':continue
            raw=path.read_bytes()
            if sha(raw)!=expected:
                member=path.relative_to(BASE/'integration').as_posix()
                raw=z.read(member)
            assert sha(raw)==expected
            target=run+'-source-'+str(i)+'-'+path.name
            (out/target).write_bytes(raw)
            source_map[target]={'original_path':name,'sha256':expected}
    frame_index=[]
    for i,line in enumerate((root/'native/stdout.private.jsonl').read_bytes().splitlines()):
        row=json.loads(line);params=row.get('params',{});result=row.get('result',{})
        frame_index.append({'index':i,'sha256':sha(line),'keys':sorted(row),
            'id':row.get('id'),'method':row.get('method'),
            'params_keys':sorted(params) if isinstance(params,dict) else None,
            'result_keys':sorted(result) if isinstance(result,dict) else None})
    write(out/(run+'-frame-index.json'),frame_index)
    requests=[json.loads(line) for line in (root/'native/requests.private.jsonl').read_bytes().splitlines()]
    methods=dict(Counter(r['method'] for r in requests))
    assert methods.get('session/prompt',0)==closure['prompt_requests_reserved']
    observations.append({'run':run,'methods':methods,'source_unchanged':closure['source_unchanged'],
        'accepted':closure['accepted'],'faults':closure['faults'],'known_usage':closure['known_usage'],
        'native_stream_sha256':sha((root/'native/stdout.private.jsonl').read_bytes())})
write(out/'frozen-source-map.json',source_map);write(out/'observations.json',observations)
shutil.copyfile(BASE/'work/grok130-import-committed-verification-r1.json',out/'imported-archive-verification.json')
review=BASE/'work/grok130-reload-source-r1'
for name in ('app.rs','session_setup.rs','source-provenance.json'):
    shutil.copyfile(review/name,out/('public-source-'+name))
(out/'FINDING.md').write_text('''# Actual isolated Grok1.0.30 readiness observations

Both attempts used separate once-only launch reservations, source/config/exe
pins and fresh opaque copies of the authorized login. Global login metadata
stayed unchanged; no login contents or hashes are part of this archive.

r1:5.703s, initialize/session-new returned; no inventory had arrived before the
old immediate check. preprompt_inventory_missing,0 billing,0 prompt. Its exact
source is recovered from the pre-check disk-source ZIP where integration later
changed; every recovered byte matches the original envelope hash.

r2:10.109s, after the independently tested ordering fix. Two explicit empty-tool
inventory updates and same-process included-subscription/no-topup gate passed.
One MAIN prompt reservation/write occurred. Then an unsolicited response with
id skills-reload caused rpc_binding rejection. No terminal usage was observed:
MAIN usage and possible initial TITLE/all-settlement totals remain UNKNOWN.
The failed attempt is spent; it is not a zero-cost success or retryable slot.

The captured response was {"jsonrpc":"2.0","id":"skills-reload",
"result":{"result":{"reloaded":1}}}. The pinned public source in app.rs
contains a filesystem watcher injecting internal reload requests with this ID;
agent_ops.rs counts resident sessions when dispatching ReloadSkills. The
session_setup.rs implementation reloads skills from disk and updates the
baseline. Thus this may affect context, and is not treated as an ignorable
notification merely to pass readiness. Public source is not proven identical
to this binary. No third real probe or permissive handler is part of this archive.

Native raw streams, refreshed login copies and account RPC bodies remain at
their original private paths. This archive contains frame hashes/structure,
allowlisted closure, exact source/config bytes and reviewed public source.
No benchmark materials, validation access or scientific result was produced.
''',encoding='utf-8')
close_index(out)
print(json.dumps({'archives_created':['c5-common-scoring','grok130-root-checks','grok130-readiness'],
                  'actual_prompt_writes':1,'actual_main_usage':'unknown'}))
