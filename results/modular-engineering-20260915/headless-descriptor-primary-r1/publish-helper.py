"""Publish a closed source gate and verify both staged and retained bytes."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

WORK = Path(__file__).parent
ROOT = WORK.parent / 'artifact-evidence-provenance'
STAGE = WORK / 'headless-descriptor-primary-archive-r1'
DEST = ROOT / 'results/modular-engineering-20260915/headless-descriptor-primary-r1'


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path): return json.loads(path.read_bytes())


manifest = read(STAGE/'published-manifest.json')
assert sha(STAGE/'published-manifest.json') == 'eea595cb6be2bdfc91de88190e696839ceb75912de0ba67c070295ec08082da2'
assert manifest['closed_gate']['junit'] == {'tests':20,'failures':0,'errors':0,'skipped':0}
for row in manifest['copied_artifacts']:
    p=STAGE/row['path']; assert sha(p)==row['sha256'] and p.stat().st_size==row['bytes']
private=manifest['retained_private']; archive=Path(private['path']); private_manifest=archive.parent/'retained-manifest.json'
assert sha(archive)==private['sha256'] and sha(private_manifest)==private['manifest_sha256']
with zipfile.ZipFile(archive) as z:
    assert len(z.namelist()) == private['file_count'] == 1819
    assert len(set(z.namelist())) == len(z.namelist())
    assert z.testzip() is None
assert not DEST.exists(); DEST.mkdir(parents=True)
for path in STAGE.iterdir():
    assert path.is_file() and not path.is_symlink() and not path.is_junction()
    shutil.copyfile(path, DEST/path.name)
shutil.copyfile(private_manifest, DEST/'retained-private-manifest.json')
shutil.copyfile(WORK/'run_frozen_checks_with_source.py', DEST/'source-archive-check-helper.py')
shutil.copyfile(Path(__file__), DEST/'publish-helper.py')
(DEST/'.gitattributes').write_bytes(b'* -text\n')
(DEST/'README.md').write_text('''# Pure evaluator descriptor and primary controller gate

Frozen source `2113371268b30411712273623371cbcf49e0ccc8` passed 20 checks
in 318.234 seconds. All 775 source/document files were byte-identical before
and after. This gate covers exact descriptor parity without opening a ledger,
strict recovery declarations, the actual eight-cell solver/Docker/private
stdio scorer lifecycle, and ten label-isolation checks.

Model and account responses were synthetic; Docker and scoring subprocesses
were real. The eight-cell positive case recorded 40 synthetic solver calls
and eight synthetic evaluator calls. This is engineering evidence, not an
actual benchmark effect or validation result.

`published-manifest.json` preserves the original staging manifest unchanged.
The private retained archive has 1,819 noncredential files from ten explicit
test roots; 65 authentication/key files were excluded. Original bytes and
mtime were checked by the archival helper. The private manifest preserves
every included descriptor and each exclusion. No pytest current-directory
link was followed. `delivery-manifest.json` covers every published file
other than itself; source bytes and JUnit originals are included here.

The actual TRAIN runtime is frozen separately at this source commit. Later
lineage controller changes do not retroactively change this gate or runtime.
''',encoding='utf-8',newline='\n')
rows=[{'path':p.name,'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(DEST.iterdir()) if p.is_file()]
(DEST/'delivery-manifest.json').write_text(json.dumps({'schema':'headless-descriptor-gate-delivery-v1',
    'self_excluding':True,'files':rows},indent=2)+'\n',encoding='utf-8',newline='\n')
for row in rows: assert sha(DEST/row['path']) == row['sha256']
subprocess.check_call(['git','add','--sparse',str(DEST.relative_to(ROOT))],cwd=ROOT)
for p in DEST.iterdir():
    blob=subprocess.check_output(['git','show',':'+p.relative_to(ROOT).as_posix()],cwd=ROOT)
    assert blob==p.read_bytes()
receipt={'schema':'headless-descriptor-delivery-verification-v1','files':len(rows)+1,
    'delivery_manifest_sha256':sha(DEST/'delivery-manifest.json'),'staged_git_bytes_equal_disk':True,
    'retained_zip_verified':True,'retained_files':1819,'excluded_credential_files':65}
with (WORK/'headless-descriptor-primary-staged-verification-r1.json').open('x',encoding='utf-8') as out:
    json.dump(receipt,out,indent=2)
print(json.dumps(receipt))
