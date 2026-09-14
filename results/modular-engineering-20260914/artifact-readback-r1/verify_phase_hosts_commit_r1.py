"""Read back committed raw evidence and original catalogue/source bindings."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

work = Path(__file__).resolve().parent
tree = work.parent/'artifact-evidence-provenance'
relative = Path('results/modular-engineering-20260914/phase-host-artifacts-r1')
root, stage = tree/relative, work/'phase-host-artifacts-staging-r1'
sys.path.insert(0, str(tree))
from research_loop.modular.artifact_catalogue import ArtifactCatalogue
from research_loop.modular.artifact_source_archive import ArchivedSourceResolver
from research_loop.modular.contracts import DataIdentity

head = subprocess.check_output(['git','rev-parse','HEAD'], cwd=tree, text=True).strip()
paths = sorted(p for p in stage.rglob('*') if p.is_file())
assert len(paths) == 1717
request = ''.join(head+':'+(relative/p.relative_to(stage)).as_posix()+'\n' for p in paths).encode()
raw = subprocess.run(['git','cat-file','--batch'], cwd=tree, input=request,
                     stdout=subprocess.PIPE, check=True).stdout
offset, files = 0, []
for path in paths:
    end = raw.index(b'\n', offset)
    _, kind, size = raw[offset:end].split()
    assert kind == b'blob'
    start, size = end+1, int(size)
    value = raw[start:start+size]
    assert raw[start+size:start+size+1] == b'\n'
    offset = start+size+1
    assert value == path.read_bytes() == (root/path.relative_to(stage)).read_bytes()
    files.append({'path': (relative/path.relative_to(stage)).as_posix(),
                  'bytes': size, 'sha256': hashlib.sha256(value).hexdigest()})
assert offset == len(raw)
scope = json.loads((root/'SCOPE.json').read_bytes())
checks = {r['prefix']:r for r in scope['checks']}
reads = []
for witness in scope['runtime_witnesses']:
    directory = root/'runtime'/witness['prefix']/witness['runtime']/'runtime'
    path = directory/'artifacts.jsonl'
    original = path.read_bytes()
    first = json.loads(original.splitlines()[0])['descriptor']
    resolver = ArchivedSourceResolver(root/'checks'/(witness['prefix']+'-sources.zip'),
        checks[witness['prefix']]['source_archive_sha256'], tree)
    reader = ArtifactCatalogue(path, identity=DataIdentity(**first['identity']),
        **first['binding'], producer_source=first['producer_source'], source_resolver=resolver)
    reader.verify()
    assert len(reader.records()) == witness['descriptors'] and path.read_bytes() == original
    reads.append({'prefix': witness['prefix'], 'runtime': witness['runtime'],
                  'descriptors': witness['descriptors'], 'historical_semantic_replay_executed': False})
result = {'schema':'phase-host-committed-verification-v1', 'head':head,
          'git_disk_staging_identical':True, 'files':files, 'historical_reads':reads,
          'scientific_effectiveness_proven':False}
with (work/'phase-hosts-committed-verification-r1.json').open('x', encoding='utf-8', newline='\n') as stream:
    stream.write(json.dumps(result, indent=2)+'\n')
print(json.dumps({'head':head, 'committed_files_verified':len(files),
    'catalogues_read':len(reads), 'descriptors_verified':sum(r['descriptors'] for r in reads)}))
