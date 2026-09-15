"""Retain reviewed structural diagnoses without changing their closed originals."""
import hashlib
import json
from pathlib import Path

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
WORK = BASE / 'work'
DEST = BASE / 'artifact-evidence-provenance/results/modular-engineering-20260915/grok-stack-metadata-followup-r1'
PINS = {
    'grok130-initialize-stack-r2-startup-metadata-diagnosis-r1.md': 'bbff3ed31e20f4fa209c07ab3f9b41fffb589ad5da91dc8216c894ede30ce39c',
    'grok130-initialize-stack-r2-metadata-v3.json': '87b7a88416fa3f4641a9745f5a74ceac994fa5299c48516cfb5a330d0d7a3200',
    'grok-r2-model-binding-next-step-r1.md': 'ba0a1beb6a4617b554f9afc2743afcd45a19a44e813a8d84cc4b858c13a1a130',
}

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def stamp(path):
    return (sha(path.read_bytes()), path.stat().st_size, path.stat().st_mtime_ns)

def main():
    assert not DEST.exists(), 'archive is immutable'
    originals = {name: (WORK / name).read_bytes() for name in PINS}
    assert all(sha(raw) == PINS[name] for name, raw in originals.items())
    before = {name: stamp(WORK / name) for name in PINS}
    DEST.mkdir(parents=True)
    (DEST / '.gitattributes').write_bytes(b'* -text\n')
    for name, raw in originals.items():
        (DEST / name).write_bytes(raw)
    (DEST / Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    (DEST / 'README.md').write_text('''# Closed startup metadata follow-up

The retained r2 initialize response was followed by four models/update,
one settings/update and one announcements/update notifications. The narrow
initialize-only harness rejected all method frames; the existing normal ACP
transport recognizes these notification families. The four selected-model IDs
equal `grok-4.6`, which matches the frozen M4/M5 expected identifier.

The diagnostic used pinned CLI 1.0.30; the original M4/M5 runtime uses a
different pinned binary. This observation alone does not establish that the
normal production path or a model call works. No gate was relaxed. A separate
normal-path control is the next check, within the already authorized existing
Grok CLI use; no Daybreak, new paid API or additional approval is required.

The native capture reports 400 candidate frames; the stricter structural
sanitizer counts 399 actual frame lines. Both original counts are preserved.
The snapshot does not identify a lock owner, prove debugger-caused recovery,
or prove independent detach. Usage and settlement remain unknown, not zero.

These are byte-for-byte copies of the reviewed reports and metadata. They
contain no raw JSON values other than the separately approved model ID, raw
stacks, credentials or benchmark data. The original noncredential raw streams
are in the private retention archive referenced by the sibling
[closed r2 archive](../grok-initialize-stack-r2/README.md). The earlier report's
model-value uncertainty is resolved only by the separately retained later
model-binding report; its original text is not rewritten.
''', encoding='utf-8', newline='\n')
    files = [{'path': p.name, 'sha256': sha(p.read_bytes()), 'bytes': p.stat().st_size}
             for p in sorted(DEST.iterdir()) if p.is_file()]
    body = {'schema': 'grok-stack-metadata-followup-published-v1', 'files': files,
            'originals_unchanged': before == {name: stamp(WORK / name) for name in PINS}}
    assert body['originals_unchanged']
    with (DEST / 'published-manifest.json').open('xb') as out:
        out.write((json.dumps(body, indent=2) + '\n').encode())
    print(json.dumps({'archive': str(DEST), 'public_files': len(files) + 1}))

if __name__ == '__main__':
    main()
