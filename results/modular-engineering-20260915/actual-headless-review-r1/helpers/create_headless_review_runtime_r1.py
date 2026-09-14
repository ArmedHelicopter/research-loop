"""Create a sparse no-data consumer checkout with the exact tested source bytes."""
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

WORK = Path(__file__).parent
ROOT = WORK.parent / 'artifact-evidence-provenance'
TREE = WORK.parent / 'headless-review-runtime'
PREFIX = WORK / 'headless-review-adapter-root-r1'
check = json.loads(Path(str(PREFIX) + '-closed.json').read_bytes())
members = json.loads(Path(str(PREFIX) + '-source-members.json').read_bytes())
archive = Path(str(PREFIX) + '-sources.zip')
assert check['exit_code'] == 0 and check['source_unchanged']
assert check['commit'] == 'a334cd63fbb61f767b34656bb10844ac0d73e692' == members['commit']
assert hashlib.sha256(archive.read_bytes()).hexdigest() == members['archive_sha256']
assert not TREE.exists()

def git(*args, cwd=TREE):
    return subprocess.check_output(['git', *args], cwd=cwd, stderr=subprocess.STDOUT)

git('worktree', 'add', '--no-checkout', '-b', 'codex/headless-review-runtime', str(TREE), check['commit'], cwd=ROOT)
git('sparse-checkout', 'set', '--no-cone', '/*', '!/results/', '!/data/')
git('checkout', 'codex/headless-review-runtime')
assert not (TREE / 'data').exists() and not (TREE / 'results').exists()
changed = []
with zipfile.ZipFile(archive) as source:
    assert set(source.namelist()) == set(check['source_after'])
    for name, expected in check['source_after'].items():
        path = TREE / name
        assert path.resolve().is_relative_to(TREE.resolve()) and path.is_file() and not path.is_symlink()
        raw = source.read(name)
        assert hashlib.sha256(raw).hexdigest() == expected
        if path.read_bytes() != raw:
            path.write_bytes(raw)
            changed.append(name)
assert not git('status', '--porcelain').strip()
assert all(hashlib.sha256((TREE / n).read_bytes()).hexdigest() == p for n, p in check['source_after'].items())
receipt = {'schema': 'frozen-consumer-source-copy-v1', 'source_commit': check['commit'],
    'tree': str(TREE), 'source_archive_sha256': members['archive_sha256'],
    'source_count': len(check['source_after']), 'byte_synchronized_files': changed,
    'data_present': False, 'model_calls': 0, 'validation_access': False, 'git_clean': True}
out = WORK / 'headless-review-source-byte-sync-r1.json'
with out.open('x', encoding='utf-8') as f:
    json.dump(receipt, f, indent=2)
print(json.dumps({k:v for k,v in receipt.items() if k != 'byte_synchronized_files'}))
