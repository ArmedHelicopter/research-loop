"""Publish the failed actual factorial without changing any original record."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

WORK=Path(__file__).parent
ROOT=WORK.parent/'artifact-evidence-provenance'
STAGE=WORK/'actual-m4m5-headless-archive-r1'
DEST=ROOT/'results/modular-engineering-20260915/actual-m4m5-headless-r1'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p): return json.loads(p.read_bytes())

assert sha(STAGE/'published-manifest.json')=='e39da470db19bb31ec9413a3405be1920eccd11581528b69b3eacdbbdd021652'
manifest=read(STAGE/'published-manifest.json')
for row in manifest['copied_artifacts']:
    p=STAGE/row['path']; assert sha(p)==row['sha256'] and p.stat().st_size==row['bytes']
private=manifest['retained_private']; archive=Path(private['path']); pm=archive.parent/'retained-manifest.json'
assert sha(archive)==private['zip_sha256'] and sha(pm)==private['manifest_sha256']
saved=read(pm)
with zipfile.ZipFile(archive) as z:
    assert len(z.namelist())==len(saved['files'])==109
    assert set(z.namelist())=={r['path'] for r in saved['files']}
    for row in saved['files']:
        p=Path(row['source']); raw=z.read(row['path'])
        assert hashlib.sha256(raw).hexdigest()==row['sha256'] and len(raw)==row['bytes']
        assert sha(p)==row['sha256'] and p.stat().st_mtime_ns==row['mtime_ns']
assert read(STAGE/'summary.json')['scored_cells']==0
attempt=read(STAGE/'controller-attempt.json')
assert len(attempt['cells'])==8 and [r['status'] for r in attempt['cells']]==['failed']+['blocked']*7
assert not DEST.exists(); DEST.mkdir(parents=True)
for p in STAGE.iterdir():
    assert p.is_file() and not p.is_symlink() and not p.is_junction()
    shutil.copyfile(p,DEST/p.name)
for src,name in [(pm,'retained-private-manifest.json'),
                 (WORK/'actual-m4m5-headless-source-copy-r1.json','runtime-source-copy.json'),
                 (WORK/'actual-m4m5-headless-native-diagnosis-r1.md','native-diagnosis.md'),
                 (Path(__file__),'publish-helper.py')]:
    shutil.copyfile(src,DEST/name)
(DEST/'.gitattributes').write_bytes(b'* -text\n')
(DEST/'README.md').write_text('''# Actual TRAIN M4/M5 factorial r1: inconclusive

The frozen panel used one DiscoveryBench and one BLADE TRAIN identity from
the current primary split, with baseline, M4, M5, and M4+M5 arms. The source
was `2113371268b30411712273623371cbcf49e0ccc8`; the separate
[20-check engineering gate](../headless-descriptor-primary-r1/README.md)
passed before this actual attempt. No validation item was opened.

The first solver reservation launched Grok 4.6 CLI. It timed out before any
stream event or usable model response was captured. One cell failed and the
other seven remained blocked in the original eight-cell denominator. There
were zero evaluator reservations and zero scores. Actual MAIN dispatch and
token usage are unknown; zero known tokens must not be read as zero usage.
Title/all-opportunity settlement is also unknown. The additional paid API
budget was zero. This result cannot establish any singleton or combination
effect, and no combination was pruned.

The parent process completed its closure, and source/input hashes stayed
unchanged. Its zero exit code reports controller completion, not scientific
or model success. The CLI's later zero exit status also does not override its
timeout and cleanup failure. `native-diagnosis.md` records the observed ACP
initialization prefix and distinguishes it from the later cleanup symptom;
the precise internal cause remains unresolved.

`preparation.json`, `controller.json`, and `runtime-source-copy.json` bind the
frozen source, exact two-item public export, independent scorer descriptor,
and call limits (40 solver, eight evaluator, eight Docker opportunities).
`controller-attempt.json` preserves all eight cells. `failure-prefix-graph.json`
is a small metadata view of the recorded failed/blocked allocation; it does
not invent module outputs or successful consumption edges.

The private archive preserves 109 files from the run, preparation, and scorer
private root, excluding seven authentication/key files. Every retained file
was compared with its original hash and mtime and with the ZIP member bytes.
`published-manifest.json` is the unchanged staging manifest;
`delivery-manifest.json` covers this published directory except itself.
This is preserved failed-run evidence, not a complete benchmark result or a
standalone credential-bearing reproduction bundle. The run is closed and was
not restarted or reclassified.
''',encoding='utf-8',newline='\n')
rows=[{'path':p.name,'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(DEST.iterdir()) if p.is_file()]
(DEST/'delivery-manifest.json').write_text(json.dumps({'schema':'actual-m4m5-headless-delivery-v1',
    'self_excluding':True,'files':rows},indent=2)+'\n',encoding='utf-8',newline='\n')
subprocess.check_call(['git','add','--sparse',str(DEST.relative_to(ROOT))],cwd=ROOT)
for p in DEST.iterdir():
    assert subprocess.check_output(['git','show',':'+p.relative_to(ROOT).as_posix()],cwd=ROOT)==p.read_bytes()
result={'schema':'actual-m4m5-headless-staged-verification-v1','files':len(rows)+1,
    'manifest_sha256':sha(DEST/'delivery-manifest.json'),'git_bytes_equal_disk':True,
    'private_originals_and_zip_verified':109,'excluded_credentials':7,'validation_opened':False}
with (WORK/'actual-m4m5-headless-staged-verification-r1.json').open('x',encoding='utf-8') as out: json.dump(result,out,indent=2)
print(json.dumps(result))
