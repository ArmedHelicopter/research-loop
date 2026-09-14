"""Read back committed public P0 bytes, catalogues and archived producer sources."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

work=Path(__file__).resolve().parent; tree=work.parent/'artifact-evidence-provenance'
rel=Path('results/modular-engineering-20260914/train-packet-artifacts-r1')
root=tree/rel; stage=work/'train-packet-artifacts-staging-r1'
sys.path.insert(0,str(tree))
from research_loop.modular.artifact_catalogue import ArtifactCatalogue
from research_loop.modular.artifact_source_archive import ArchivedSourceResolver
from research_loop.modular.contracts import DataIdentity, FrozenRecord

head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=tree,text=True).strip()
paths=sorted(p for p in stage.rglob('*') if p.is_file()); assert len(paths)==113
request=''.join(head+':'+(rel/p.relative_to(stage)).as_posix()+'\n' for p in paths).encode()
raw=subprocess.run(['git','cat-file','--batch'],cwd=tree,input=request,stdout=subprocess.PIPE,check=True).stdout
offset=0; files=[]
for p in paths:
    end=raw.index(b'\n',offset); header=raw[offset:end].split(); assert len(header)==3 and header[1]==b'blob'
    size=int(header[2]); begin=end+1; value=raw[begin:begin+size]; assert raw[begin+size:begin+size+1]==b'\n'
    offset=begin+size+1
    assert value==p.read_bytes()==(root/p.relative_to(stage)).read_bytes()
    files.append({'path':(rel/p.relative_to(stage)).as_posix(),'bytes':size,'sha256':hashlib.sha256(value).hexdigest()})
assert offset==len(raw)
scope=json.loads((root/'SCOPE.json').read_bytes()); reads=[]
resolver=ArchivedSourceResolver(root/'checks'/(scope['source_prefix']+'-sources.zip'),scope['source_archive_sha256'],tree)
for row in scope['catalogues']:
    path=root/row['path']; before=path.read_bytes(); first=json.loads(before.splitlines()[0])['descriptor']
    reader=ArtifactCatalogue(path,identity=DataIdentity(**first['identity']),**first['binding'],
        producer_source=first['producer_source'],source_resolver=resolver)
    records=reader.records(); assert len(records)==row['descriptors']
    binding=records[0].data()['payload']['canonical']
    for method in binding['producer_methods'].values():resolver.verify_snapshot(method['source'])
    assert reader.seal_path.is_file()==row['sealed']
    if row['sealed']:
        reader.verify(FrozenRecord.from_dict(json.loads(reader.seal_path.read_bytes())))
    else:assert len(records)==1 and row['state']=='incomplete'
    assert path.read_bytes()==before
    reads.append(row)
result={'schema':'train-packet-committed-verification-v1','head':head,'git_disk_staging_identical':True,
    'files':files,'catalogues':reads,'scientific_effectiveness_proven':False,'validation_acceptance':False,
    'historical_exporter_semantic_replay_executed':False}
with (work/'train-packet-committed-verification-r1.json').open('x',encoding='utf-8',newline='\n') as stream:
    stream.write(json.dumps(result,indent=2)+'\n')
print(json.dumps({'head':head,'committed_files_verified':len(files),'catalogues':len(reads),
    'descriptors':sum(row['descriptors'] for row in reads),'unsealed_prefixes':sum(not row['sealed'] for row in reads)}))
