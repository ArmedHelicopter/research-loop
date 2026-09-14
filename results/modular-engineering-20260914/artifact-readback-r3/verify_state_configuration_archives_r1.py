"""Read every committed graph evidence blob and reconstruct archived references."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

work = Path(__file__).resolve().parent
tree = work.parent/'artifact-evidence-provenance'
sys.path.insert(0,str(tree))
from research_loop.modular.artifact_catalogue import ArtifactCatalogue
from research_loop.modular.artifact_source_archive import ArchivedSourceResolver
from research_loop.modular.contracts import DataIdentity, FrozenRecord

R = FrozenRecord.from_dict
head = subprocess.check_output(['git','rev-parse','HEAD'],cwd=tree,text=True).strip()
results = []; files = []
for prefix in ('state-configuration-edges-r1','state-configuration-edges-r2'):
    rel = Path('results/modular-engineering-20260914')/prefix
    root = tree/rel; stage = work/(prefix+'-staging-r1')
    paths = sorted(p for p in stage.rglob('*') if p.is_file())
    assert len(paths) == len([p for p in root.rglob('*') if p.is_file()])
    requests = ''.join(head+':'+(rel/p.relative_to(stage)).as_posix()+'\n' for p in paths).encode()
    raw = subprocess.run(['git','cat-file','--batch'],cwd=tree,input=requests,stdout=subprocess.PIPE,check=True).stdout
    offset = 0
    for path in paths:
        end = raw.index(b'\n',offset); _,kind,size = raw[offset:end].split()
        assert kind == b'blob'; size=int(size); start=end+1
        data=raw[start:start+size]; assert raw[start+size:start+size+1] == b'\n'; offset=start+size+1
        assert data == path.read_bytes() == (root/path.relative_to(stage)).read_bytes()
        files.append({'path':(rel/path.relative_to(stage)).as_posix(),'bytes':size,'sha256':hashlib.sha256(data).hexdigest()})
    assert offset == len(raw)
    scope=json.loads((root/'SCOPE.json').read_bytes()); readers={}; count=0
    resolver=ArchivedSourceResolver(root/'checks'/(prefix+'-sources.zip'),scope['source_archive_sha256'],tree)
    for row in scope['catalogues']:
        path=root/row['path']; first=json.loads(path.read_bytes().splitlines()[0])['descriptor']
        reader=ArtifactCatalogue(path,identity=DataIdentity(**first['identity']),**first['binding'],
            producer_source=first['producer_source'],source_resolver=resolver)
        records=reader.records(); assert len(records) == row['descriptors']
        reader.verify(R(json.loads(reader.seal_path.read_bytes())))
        readers[row['path']]={r.content_hash:r for r in records}; count+=len(records)
    links=json.loads((root/'REVERSE-LINKS.json').read_bytes())['links']
    for edge in links:
        source=readers[edge['source_catalogue']][edge['source_descriptor']]
        target=readers[edge['target_catalogue']][edge['target_descriptor']]
        payload=target.data()['payload']['canonical']
        assert payload['relation'] == edge['relation'] == 'configured_by'
        assert payload['source']['descriptor_digest'] == source.content_hash
        assert payload['source']['candidate'] == source.data()['payload']['canonical']['canonical']
        assert payload['source']['identity'] == edge['source_identity'] != edge['target_identity']
        assert payload['target']['cell']['identity'] == edge['target_identity']
    assert len(links) == 22 and len(readers) == 33
    results.append({'prefix':prefix,'files':len(paths),'catalogues':len(readers),'descriptors':count,
        'configuration_edges':len(links),'historical_semantic_replay_executed':False})
result={'schema':'state-configuration-committed-verification-v1','head':head,
    'git_disk_staging_identical':True,'archives':results,'files':files,
    'scientific_effectiveness_proven':False,'validation_acceptance':False}
with (work/'state-configuration-committed-verification-r1.json').open('x',encoding='utf-8',newline='\n') as stream:
    stream.write(json.dumps(result,indent=2)+'\n')
print(json.dumps({'head':head,'committed_files_verified':len(files),'archives':results}))
