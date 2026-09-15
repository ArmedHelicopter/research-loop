"""Retain a completed source study without modifying its original evidence."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

WORK = Path(__file__).parent
ROOT = WORK.parent/'artifact-evidence-provenance'
STAGE = WORK/'grok-startup-source-study-r3'
DEST = ROOT/'results/modular-engineering-20260915/grok-startup-source-study-r3'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
manifest = json.loads((STAGE/'manifest.json').read_bytes())
assert sha(STAGE/'manifest.json') == '87ed8a7bf7cc68222c918decd7c1dca3870755f1db577f89202a978084047aab'
assert sha(STAGE/'README.md') == manifest['readme_sha256']
assert sha(STAGE/'source-provenance.json') == manifest['source_provenance_sha256']
sources = json.loads((STAGE/'source-provenance.json').read_bytes())
for row in manifest['notes'] + sources['files']:
    assert sha(STAGE/row['path']) == row['sha256'] and (STAGE/row['path']).stat().st_size == row['bytes']
assert not DEST.exists()
DEST.mkdir(parents=True)
for path in STAGE.iterdir():
    assert path.is_file() and not path.is_symlink() and not path.is_junction()
    shutil.copyfile(path, DEST/path.name)
shutil.copyfile(Path(__file__), DEST/'publish-helper.py')
(DEST/'.gitattributes').write_bytes(b'* -text\n')
rows = [{'path':p.name,'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(DEST.iterdir())]
(DEST/'delivery-manifest.json').write_text(json.dumps({'schema':'grok-source-study-delivery-v1',
    'self_excluding':True,'files':rows},indent=2)+'\n',encoding='utf-8',newline='\n')
subprocess.check_call(['git','add','--sparse',DEST.relative_to(ROOT).as_posix()],cwd=ROOT)
for path in DEST.iterdir():
    assert subprocess.check_output(['git','show',':'+path.relative_to(ROOT).as_posix()],cwd=ROOT) == path.read_bytes()
print(json.dumps({'files':len(rows)+1,'staged_git_bytes_equal_disk':True,
                  'delivery_manifest_sha256':sha(DEST/'delivery-manifest.json')}))
