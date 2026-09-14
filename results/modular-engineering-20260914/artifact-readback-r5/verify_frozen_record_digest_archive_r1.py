"""Compare committed bytes with preserved stage and original source snapshots."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

work = Path(__file__).resolve().parent
tree = work.parent / 'artifact-evidence-provenance'
relative = Path('results/modular-engineering-20260914/frozen-record-digest-r1')
root = tree / relative
stage = work / 'frozen-record-digest-staging-r1'
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=tree, text=True).strip()
assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=tree).strip()
sys.path.insert(0, str(tree))
from research_loop.modular.artifact_catalogue import ArtifactCatalogue
from research_loop.modular.artifact_source_archive import ArchivedSourceResolver
from research_loop.modular.contracts import DataIdentity, FrozenRecord

paths = sorted(p for p in stage.rglob('*') if p.is_file())
assert len(paths) == 188
request = ''.join(head + ':' + (relative / p.relative_to(stage)).as_posix() + '\n' for p in paths).encode()
raw = subprocess.run(['git', 'cat-file', '--batch'], cwd=tree, input=request, stdout=subprocess.PIPE, check=True).stdout
offset = 0
files = []
for path in paths:
    end = raw.index(b'\n', offset)
    header = raw[offset:end].split()
    assert len(header) == 3 and header[1] == b'blob'
    size = int(header[2]); begin = end + 1
    value = raw[begin:begin + size]
    assert raw[begin + size:begin + size + 1] == b'\n'
    offset = begin + size + 1
    assert value == path.read_bytes() == (root / path.relative_to(stage)).read_bytes()
    files.append({'path': (relative / path.relative_to(stage)).as_posix(), 'bytes': size,
                  'sha256': hashlib.sha256(value).hexdigest()})
assert offset == len(raw)
scope = json.loads((root / 'SCOPE.json').read_bytes())
resolver = ArchivedSourceResolver(root / 'checks/frozen-record-digest-r1-sources.zip',
                                 scope['source_archive_sha256'], Path(scope['original_tree']))
for row in scope['catalogues']:
    path = root / row['path']; original = path.read_bytes()
    first = json.loads(original.splitlines()[0])['descriptor']
    reader = ArtifactCatalogue(path, identity=DataIdentity(**first['identity']), **first['binding'],
                               producer_source=first['producer_source'], source_resolver=resolver)
    records = reader.records()
    assert len(records) == row['descriptors']
    seal = FrozenRecord.from_dict(json.loads(reader.seal_path.read_bytes()))
    reader.verify(seal)
    assert seal.content_hash == row['seal_digest']
    assert path.read_bytes() == original
report = {'schema': 'frozen-record-digest-committed-verification-v1', 'head': head,
          'git_disk_staging_identical': True, 'files': files, 'catalogues': scope['catalogues'],
          'historical_stage_semantic_replay_executed': False,
          'scientific_effectiveness_proven': False, 'validation_acceptance': False}
out = work / 'frozen-record-digest-committed-verification-r1.json'
with out.open('x', encoding='utf-8', newline='\n') as stream:
    stream.write(json.dumps(report, indent=2) + '\n')
print(json.dumps({'head': head, 'committed_files_verified': len(files),
                  'catalogues': len(scope['catalogues']),
                  'descriptors': sum(r['descriptors'] for r in scope['catalogues'])}))
