"""Create the label-free r2 runtime using exactly the tested disk bytes."""
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

WORK = Path(__file__).parent
ROOT = WORK.parent/'artifact-evidence-provenance'
TREE = WORK.parent/'headless-review-recovery-runtime'
PREFIX = WORK/'headless-account-recovery-root-r1'
CHECK = Path(str(PREFIX)+'-closed.json')
assert hashlib.sha256(CHECK.read_bytes()).hexdigest() == 'cf1f7bf6a65f8021bc3595ecc6b4c36082b589cf4e906c6daac3af0276b48893'
check = json.loads(CHECK.read_bytes())
members = json.loads(Path(str(PREFIX)+'-source-members.json').read_bytes())
archive = Path(str(PREFIX)+'-sources.zip')
assert check['commit'] == members['commit'] == '02959f51896332037cfeb46ed9ebb548039b85b1'
assert check['exit_code'] == 0 and check['source_unchanged']
assert check['junit'] == {'tests':57, 'failures':0, 'errors':0, 'skipped':0}
assert hashlib.sha256(archive.read_bytes()).hexdigest() == members['archive_sha256']
assert not TREE.exists()

def git(*args, cwd=TREE):
    return subprocess.check_output(['git',*args], cwd=cwd, stderr=subprocess.STDOUT)

git('worktree','add','--no-checkout','-b','codex/headless-review-recovery-runtime',str(TREE),check['commit'],cwd=ROOT)
git('sparse-checkout','set','--no-cone','/*','!/results/','!/data/')
git('checkout','codex/headless-review-recovery-runtime')
assert not (TREE/'data').exists() and not (TREE/'results').exists()
changed = []
with zipfile.ZipFile(archive) as source:
    assert set(source.namelist()) == set(check['source_after'])
    for name, expected in check['source_after'].items():
        path = TREE/name
        assert path.resolve().is_relative_to(TREE.resolve()) and path.is_file() and not path.is_symlink()
        raw = source.read(name)
        assert hashlib.sha256(raw).hexdigest() == expected
        if path.read_bytes() != raw:
            path.write_bytes(raw)
            changed.append(name)
git('-c','core.safecrlf=false','diff','--quiet')
git('diff','--cached','--quiet','HEAD')
git('add','--update')  # refresh index stat only; no source byte normalization
git('diff','--cached','--quiet','HEAD')
assert not git('status','--porcelain').strip()
assert all(hashlib.sha256((TREE/n).read_bytes()).hexdigest() == pin for n,pin in check['source_after'].items())
receipt = {'schema':'frozen-consumer-source-copy-v2','source_commit':check['commit'],
    'tree':str(TREE),'source_archive_sha256':members['archive_sha256'],
    'engineering_check_sha256':hashlib.sha256(CHECK.read_bytes()).hexdigest(),
    'source_count':len(check['source_after']),'byte_synchronized_files':changed,
    'index_refresh':'no content changes staged; tested disk bytes preserved',
    'data_present':False,'model_calls':0,'validation_access':False,'git_clean':True}
out = WORK/'headless-review-source-byte-sync-r2.json'
with out.open('x',encoding='utf-8') as target:
    json.dump(receipt,target,indent=2)
print(json.dumps({k:v for k,v in receipt.items() if k != 'byte_synchronized_files'}))
