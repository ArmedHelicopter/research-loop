"""One reviewed authoring envelope, owned private worker, no automatic retry."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

REPO = Path('E:/_ryanDev/AI/research-loop-modular/grok-materials')
sys.path.insert(0, str(REPO))
from research_loop.modular.grok_acp_transport import ProcessTree

WORK = REPO.parent / 'work'
ROOT = WORK / 'material-authoring-actual-run-r1'
ENVELOPE = WORK / 'material-authoring-actual-preparation-r1/freeze/authoring-envelope.json'
EXPECTED = 'd922de6b0755cf1f6953a6cf3096808f6f97c44d7b415d882f8a0cc3ba229f02'
COMMIT = '5704c53db0ab3d0ade2e033f5fb4ef155d7a44dc'
REVIEW = WORK / 'material-authoring-root-metadata-review-r1.md'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(path, value):
    with Path(path).open('x', encoding='utf-8') as out:
        json.dump(value, out, sort_keys=True, separators=(',', ':'))
        out.flush(); os.fsync(out.fileno())
def git(*args):
    return subprocess.check_output(['git', *args], cwd=REPO, text=True).strip()

assert git('rev-parse', 'HEAD') == COMMIT and not git('status', '--porcelain')
assert sha(ENVELOPE) == EXPECTED and EXPECTED in REVIEW.read_text()
check = json.loads((WORK / 'material-authoring-frozen-check-r2/receipt.json').read_text())
assert check['pytest_exit'] == 0 and check['source_hashes_unchanged'] and check['commit'] == COMMIT
pins = json.loads((WORK / 'material-authoring-frozen-check-r2/before-source-sha256.json').read_text())
assert all(sha(REPO / path) == expected for path, expected in pins.items())
assert not ENVELOPE.with_suffix('.run-reservation.json').exists()
ROOT.mkdir(exist_ok=False)
command = [sys.executable, '-m', 'evaluation.modular.diagnostic_material_authoring', 'run',
    '--input', str(ENVELOPE), '--sha256', EXPECTED, '--output-directory', str(ROOT / 'private-output')]
frozen = {'schema': 'reviewed-authoring-parent-envelope-v1', 'commit': COMMIT,
    'authoring_envelope_sha256': EXPECTED, 'review_sha256': sha(REVIEW),
    'runner_sha256': sha(__file__), 'check_receipt_sha256': sha(WORK / 'material-authoring-frozen-check-r2/receipt.json'),
    'source_hashes': pins, 'parent_timeout_seconds': 600, 'native_timeout_seconds': 60,
    'main_opportunities': 4, 'possible_title_opportunities': 4, 'retry': False, 'command': command}
write(ROOT / 'frozen-parent-envelope.json', frozen)
write(ROOT / 'parent-reservation.json', {'parent_envelope_sha256': sha(ROOT / 'frozen-parent-envelope.json'),
    'authoring_envelope_sha256': EXPECTED, 'reserved_once': True})
env = {k: v for k, v in os.environ.items() if k.upper() in {'SYSTEMROOT', 'WINDIR', 'SYSTEMDRIVE',
    'COMSPEC', 'PATHEXT', 'PATH', 'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'OS'}}
env.update(PYTHONPATH=str(REPO), TEMP=str(ROOT), TMP=str(ROOT))
started = time.monotonic(); timed_out = False; code = None
with (ROOT / 'worker.stderr.private.bin').open('xb') as stderr:
    tree = ProcessTree(command, REPO, env, stderr)
    try:
        stdout, _ = tree.process.communicate(timeout=600)
        (ROOT / 'worker.stdout.private.bin').write_bytes(stdout)
        code = tree.process.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        (ROOT / 'worker.timeout-stdout.private.bin').write_bytes(exc.stdout or b'')
    finally:
        tree.close()
unchanged = all(sha(REPO / path) == expected for path, expected in pins.items())
outcome = ROOT / 'private-output/public-outcome.json'
receipt = {'schema': 'reviewed-authoring-parent-closure-v1', 'source_commit': COMMIT,
    'worker_exit': code, 'parent_timeout': timed_out, 'elapsed_seconds': time.monotonic() - started,
    'parent_tree_closed': True, 'source_hashes_unchanged': unchanged,
    'source_clean_after': not git('status', '--porcelain'),
    'authoring_envelope_sha256': EXPECTED, 'parent_envelope_sha256': sha(ROOT / 'frozen-parent-envelope.json'),
    'public_outcome': {'path': str(outcome), 'sha256': sha(outcome)} if outcome.exists() else None,
    'retry_allowed': False, 'separate_review_evaluator_requests': 0,
    'worker_stdout_sha256': sha(ROOT / 'worker.stdout.private.bin') if (ROOT / 'worker.stdout.private.bin').exists() else None,
    'worker_stderr_sha256': sha(ROOT / 'worker.stderr.private.bin')}
write(ROOT / 'public-parent-closure.json', receipt)
print(json.dumps(receipt))
raise SystemExit(int(timed_out or code != 0 or not unchanged))
