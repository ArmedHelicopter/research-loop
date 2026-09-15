"""Retain the closed normal TRAIN control without exposing private streams."""
import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
WORK = BASE / 'work'
SOURCE = WORK / 'grok-normal-train-control-r1'
DEST = BASE / 'artifact-evidence-provenance/results/modular-engineering-20260915/grok-normal-train-control-r1'
PRIVATE = BASE / 'retained-private-evidence/grok-normal-train-control-r1'
HELPER = WORK / 'prepare_headless_lineage_full4_archive_r1.py'

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def read(path):
    return json.loads(path.read_bytes())

def write(path, body):
    with path.open('xb') as out:
        out.write((json.dumps(body, indent=2) + '\n').encode())

def stamp(path):
    return {'sha256': sha(path.read_bytes()), 'bytes': path.stat().st_size, 'mtime_ns': path.stat().st_mtime_ns}

def main():
    assert not DEST.exists() and not PRIVATE.exists()
    completion = read(WORK / 'grok-normal-train-control-r1-native-completion.json')
    assert completion['schema'] == 'native-command-completion-v1'
    assert completion['result']['exit_code'] == 0 and 'session_id' not in completion['result']
    assert read(WORK / 'grok-normal-train-control-r1-native-start.json') == completion['result']
    closure = read(SOURCE / 'closure.json')
    assert closure['status'] == 'terminal_unknown_or_failed' and closure['source_unchanged']
    assert closure['global_auth_metadata_unchanged'] and closure['response_sha256'] is None
    call = SOURCE / 'control-model/calls/0001-m4_plan'
    observer = read(call / 'observer-receipt.private.json')
    assert observer['faults'] == ['account_preflight_failed']
    assert observer['prompt_process_launched'] is False and observer['accepted'] is False
    ledger = read(SOURCE / 'control-model/ledger.json')
    assert len(ledger['calls']) == 1 and ledger['calls'][0]['status'] == 'unknown_or_failed'
    spec = importlib.util.spec_from_file_location('control_retention', HELPER)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    originals = sorted(module.regular_files(SOURCE))
    copies = [SOURCE / 'control.py', SOURCE / 'closure.json',
              WORK / 'grok-normal-train-control-r1-native-start.json',
              WORK / 'grok-normal-train-control-r1-native-completion.json',
              WORK / 'grok-normal-train-control-r1-plan.md',
              WORK / 'grok-normal-train-control-r1-predispatch-diagnosis-r1.md',
              WORK / 'grok-normal-train-control-r1.log', Path(__file__), HELPER]
    inputs = sorted(set(originals + copies))
    before = {str(p): stamp(p) for p in inputs}
    PRIVATE.mkdir(parents=True)
    archive = PRIVATE / 'originals-without-credentials.zip'
    members = module.add_zip(archive, ((p.relative_to(SOURCE).as_posix(), p.read_bytes(), str(p)) for p in originals))
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None and z.namelist() == [r['path'] for r in members]
        for row in members:
            raw = z.read(row['path'])
            assert sha(raw) == row['sha256'] == before[row['origin']]['sha256'] and len(raw) == row['byte_count']
    write(PRIVATE / 'retention-manifest.json', {'schema': 'normal-train-control-retention-v1',
          'archive_sha256': sha(archive.read_bytes()), 'members': members,
          'excluded_credentials': module.EXCLUSIONS, 'pruned_reparse_paths': sorted(module.PRUNED_LINKS)})
    DEST.mkdir(parents=True)
    (DEST / '.gitattributes').write_bytes(b'* -text\n')
    for path in copies:
        (DEST / path.name).write_bytes(path.read_bytes())
    (DEST / 'README.md').write_text('''# Closed normal Grok TRAIN control r1

One previously exported public TRAIN m4_plan request was frozen for one fresh
normal headless opportunity. The original exec command completed directly
with exit 0 in 2.512 seconds; no native session ID was issued. The driver
closed with `terminal_unknown_or_failed`, not a successful model result.

The inspect child completed, but the copied login failed the existing expiry
predicate before the first account GET. The sole observer fault is
`account_preflight_failed`, and `prompt_process_launched=false`. One reserved
opportunity remains in the denominator. There was no prompt dispatch; MAIN
usage is absent, and title/all-opportunity settlement remains unknown.

Source pins and global auth metadata were unchanged. Private requests,
manifest, observer, reservation, ledger and noncredential originals are
retained with per-member hashes; credentials are excluded. Public copies are
the driver, closure, original command completion and source diagnosis. This
is execution evidence, not module effectiveness or VAL acceptance.

The prepared plan is retained in its original pre-execution wording. The
diagnosis's phrase "newly frozen and authorized control" adds no user-approval
requirement: existing Grok CLI 4.6 use is already authorized. A supported
legitimate credential refresh may permit a fresh control within that scope;
the expired record and this terminal reservation must not be altered/reused.
No Daybreak or added paid API is required by this experiment.
''', encoding='utf-8', newline='\n')
    assert before == {str(p): stamp(p) for p in inputs}
    files = [{'path': p.name, 'sha256': sha(p.read_bytes()), 'bytes': p.stat().st_size} for p in sorted(DEST.iterdir())]
    write(DEST / 'published-manifest.json', {'schema': 'normal-train-control-published-v1', 'files': files})
    print(json.dumps({'archive': str(DEST), 'public_files': len(files) + 1, 'private_noncredential_members': len(members)}))

if __name__ == '__main__':
    main()
