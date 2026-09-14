"""Refresh only the new worktree index after exact CRLF/LF source copying."""
import hashlib
import json
from pathlib import Path
import subprocess

WORK = Path(__file__).parent
TREE = WORK.parent / 'headless-review-runtime'
check = json.loads((WORK / 'headless-review-adapter-root-r1-closed.json').read_bytes())
members = json.loads((WORK / 'headless-review-adapter-root-r1-source-members.json').read_bytes())

def git(*args):
    return subprocess.check_output(['git', *args], cwd=TREE, stderr=subprocess.STDOUT)

assert git('rev-parse', 'HEAD').decode().strip() == check['commit']
assert not (TREE / 'data').exists() and not (TREE / 'results').exists()
assert all(hashlib.sha256((TREE / n).read_bytes()).hexdigest() == p for n, p in check['source_after'].items())
before = git('status', '--porcelain').decode().splitlines()
# Git's text-conversion comparison finds no content diff, but the index still
# reports the copied files as dirty by stat. Update the index without file writes.
git('-c', 'core.safecrlf=false', 'diff', '--quiet')
git('diff', '--cached', '--quiet', 'HEAD')
git('add', '--update')
git('diff', '--cached', '--quiet', 'HEAD')
assert not git('status', '--porcelain').strip()
assert all(hashlib.sha256((TREE / n).read_bytes()).hexdigest() == p for n, p in check['source_after'].items())
receipt = {'schema': 'frozen-consumer-source-copy-v1', 'source_commit': check['commit'],
    'tree': str(TREE), 'source_archive_sha256': members['archive_sha256'],
    'source_count': len(check['source_after']), 'index_stat_refresh_paths': before,
    'initial_preparation_failed': 'post-copy clean-index assertion; source bytes already matched all frozen inputs',
    'repair': 'Git index-only update after no-content-diff checks; all source bytes unchanged',
    'initial_helper_sha256': hashlib.sha256((WORK / 'create_headless_review_runtime_r1.py').read_bytes()).hexdigest(),
    'data_present': False, 'model_calls': 0, 'validation_access': False, 'git_clean': True}
out = WORK / 'headless-review-source-byte-sync-r1.json'
with out.open('x', encoding='utf-8') as f:
    json.dump(receipt, f, indent=2)
print(json.dumps({k:v for k,v in receipt.items() if k != 'index_stat_refresh_paths'}))
