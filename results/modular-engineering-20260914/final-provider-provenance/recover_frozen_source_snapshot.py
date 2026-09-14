"""Recover old source bytes only when an existing frozen SHA verifies them."""
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

tree, prefix = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
before = json.loads(Path(str(prefix) + '-before.json').read_bytes())
head = before['commit']
archive = Path(str(prefix) + '-recovered-sources.zip')
manifest = Path(str(prefix) + '-recovered-source-members.json')
assert not archive.exists() and not manifest.exists()
names = list(before['source_before'])
requests = ''.join(head + ':' + name + '\n' for name in names).encode()
raw = subprocess.check_output(['git', 'cat-file', '--batch'], input=requests, cwd=tree)
offset, blobs = 0, {}
for name in names:
    end = raw.index(b'\n', offset)
    header = raw[offset:end].split()
    assert len(header) == 3 and header[1] == b'blob', name
    size = int(header[2]); offset = end + 1
    blobs[name] = raw[offset:offset + size]
    assert raw[offset + size:offset + size + 1] == b'\n'
    offset += size + 1
assert offset == len(raw)
sha = lambda data: hashlib.sha256(data).hexdigest()
rows, unresolved = [], []
with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as output:
    for name, expected in before['source_before'].items():
        original = blobs[name]
        lf = original.replace(b'\r\n', b'\n')
        candidates = [('git_blob', original), ('git_normalized_lf', lf),
                      ('git_normalized_crlf', lf.replace(b'\n', b'\r\n'))]
        for kind, value in tuple(candidates):
            candidates.append((kind + '_bom', b'\xef\xbb\xbf' + value.removeprefix(b'\xef\xbb\xbf')))
            candidates.append((kind + '_without_bom', value.removeprefix(b'\xef\xbb\xbf')))
        if (tree / name).is_file():
            candidates.insert(0, ('retained_disk_bytes', (tree / name).read_bytes()))
        match = next(((kind, value) for kind, value in candidates if sha(value) == expected), None)
        if match is None:
            unresolved.append(name)
            continue
        kind, value = match
        output.writestr(name, value)
        rows.append({'path': name, 'bytes': len(value), 'sha256': expected, 'recovery_method': kind})
body = {'commit': head, 'original_source_manifest_sha256': sha(Path(str(prefix) + '-before.json').read_bytes()),
        'archive_sha256': sha(archive.read_bytes()), 'members': rows, 'unresolved': unresolved,
        'scope': 'recovered bytes equal pre-existing tested disk hashes; no source-equivalence assumption'}
manifest.write_bytes((json.dumps(body, indent=2) + '\n').encode())
print(json.dumps({'commit': head, 'recovered': len(rows), 'unresolved': unresolved, 'archive_sha256': body['archive_sha256']}))
assert not unresolved, 'preserved partial recovery; do not claim exact source closure'
