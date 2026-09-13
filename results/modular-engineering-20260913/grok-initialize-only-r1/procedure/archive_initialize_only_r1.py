"""Explicit safe allowlist for terminal zero-prompt initialization probe."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

WORK = Path('E:/_ryanDev/AI/research-loop-modular/work')
REPO = WORK.parent / 'grok-materials'
OUT = REPO / 'results/modular-engineering-20260913/grok-initialize-only-r1'
OUT.mkdir(exist_ok=False)
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
copies = {}
for name in ('driver.py', 'fixture_peer.py', 'test_driver.py', 'frozen_check.py', 'run_actual_once.py'):
    copies['source/' + name] = WORK / 'init-only-driver-r1' / name
for name in ('before.json', 'after.json', 'receipt.json', 'stdout.bin', 'stderr.bin', 'pytest.xml'):
    copies['checks/frozen-r1/' + name] = WORK / 'init-only-driver-r1/frozen-check-r1' / name
copies['checks/preliminary-four-failures.xml'] = WORK / 'init-only-driver-r1/preliminary.xml'
for name in ('frozen-envelope.json', 'public-result.json', 'public-verification.json'):
    copies['actual/' + name] = WORK / 'init-only-r1' / name
copies['protocol/proposal.md'] = WORK / 'material-authoring-initialize-only-proposal-r1.md'
copies['protocol/prior-readonly-finding.md'] = WORK / 'material-authoring-startup-review-r1/READONLY-FINDING.md'
copies['procedure/archive_initialize_only_r1.py'] = Path(__file__)
copies['procedure/verify_grok_acp_archive.py'] = WORK / 'verify_grok_acp_archive.py'
envelope = json.loads((WORK / 'init-only-r1/frozen-envelope.json').read_text())
for p, expected in envelope['frozen_files'].items():
    assert sha(p) == expected
    path = Path(p)
    if path.is_relative_to(REPO):
        copies['source/dependencies/' + path.relative_to(REPO).as_posix()] = path
copies['actual/frozen-config.toml'] = WORK / 'init-only-r1/home/config.toml'
for name, source in copies.items():
    target = OUT / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
(OUT / 'README.md').write_text('''# Terminal initialize-only diagnosis

The one authorized native launch timed out before InitializeResponse. Exactly one
initialize frame was written; session/new, authenticate, account RPCs and model
prompts were zero. Shutdown began at 60.015 seconds and completed at 60.219 seconds.
Exit 0 was observed after tree shutdown and is not successful initialization.
Four frozen structural fixtures passed. Their four preliminary fixture byte-capture
failures remain preserved. Thirteen frozen pins and 26 original authoring private
artifacts remained unchanged; no owned native process remained in the scoped check.

Fresh shorter paths and an opaque copy of the refreshed private login were changed
conditions; neither has been shown to fix initialization or establish its cause.
Model/account/tools readiness and usage/settlement remain unverified or unknown.
No original material envelope was retried and no material/diagnostic prompt ran.

This allowlist contains source, synthetic checks, safe metadata and frozen config.
Native raw streams/logs, credentials and private authoring artifacts stay outside
Git. Their permitted hashes are recorded in the public verification. No auth-body
hash or credential body is included. Source commit before archival is 5e1b184.
''', encoding='utf-8')
entries = [{'path': p.relative_to(OUT).as_posix(), 'size': p.stat().st_size, 'sha256': sha(p)}
           for p in sorted(OUT.rglob('*')) if p.is_file()]
(OUT / 'payload-sha256.json').write_text(json.dumps(entries, indent=2) + '\n')
with zipfile.ZipFile(OUT / 'evidence.zip', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
    for item in entries:
        info = zipfile.ZipInfo(item['path'], date_time=(2026, 9, 14, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, (OUT / item['path']).read_bytes())
print(json.dumps({'archive_files': len(entries) + 2, 'zip_payloads': len(entries)}))
