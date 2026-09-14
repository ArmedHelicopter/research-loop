"""Verify committed deployment artifacts against original caller pins and source bytes."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

work = Path(__file__).resolve().parent
tree = work.parent/'artifact-evidence-provenance'
relative = Path('results/modular-engineering-20260914/joint-deployment-artifacts-r1')
root = tree/relative; stage = work/'joint-deployment-artifacts-staging-r1'
head = subprocess.check_output(['git','rev-parse','HEAD'],cwd=tree,text=True).strip()
assert not subprocess.check_output(['git','status','--porcelain'],cwd=tree).strip()
sys.path[:0] = [str(tree),str(tree/'tests')]
from research_loop.modular.artifact_source_archive import ArchivedSourceResolver
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.joint_deployment_artifacts import verify_joint_deployment_artifacts
from test_joint_deployment import KEYS, ROLLBACK

paths = sorted(p for p in stage.rglob('*') if p.is_file())
assert len(paths)==143
request = ''.join(head+':'+(relative/p.relative_to(stage)).as_posix()+'\n' for p in paths).encode()
raw = subprocess.run(['git','cat-file','--batch'],cwd=tree,input=request,stdout=subprocess.PIPE,check=True).stdout
offset = 0; files = []
for path in paths:
    end = raw.index(b'\n',offset); header = raw[offset:end].split()
    assert len(header)==3 and header[1]==b'blob'
    size = int(header[2]); begin = end+1; value = raw[begin:begin+size]
    assert raw[begin+size:begin+size+1]==b'\n'; offset=begin+size+1
    assert value==path.read_bytes()==(root/path.relative_to(stage)).read_bytes()
    files.append({'path':(relative/path.relative_to(stage)).as_posix(),'bytes':size,'sha256':hashlib.sha256(value).hexdigest()})
assert offset==len(raw)
scope = json.loads((root/'SCOPE.json').read_bytes())
resolver = ArchivedSourceResolver(root/'checks'/(scope['source_prefix']+'-sources.zip'),
                                 scope['source_archive_sha256'],Path(scope['original_tree']))
databases = []
for row in scope['databases']:
    path = root/row['path']; original = path.read_bytes()
    report = verify_joint_deployment_artifacts(path,domain='train',checkpoint=FrozenRecord.from_dict(row['checkpoint']),
        acceptance_keys=KEYS,rollback_keys=ROLLBACK,source_resolver=resolver,
        component_source_roots={f'M{i}':path.parent/'builds' for i in range(1,10)})
    body = report.data()
    assert report.content_hash==row['report_digest'] and len(body['events'])==row['events']
    assert len(body['pending_attempts'])==row['pending'] and body['optimizer_visible'] is False
    assert body['component_sources_verified'] is True and path.read_bytes()==original
    databases.append(row)
result = {'schema':'joint-deployment-committed-verification-v1','head':head,
          'git_disk_staging_identical':True,'files':files,'databases':databases,
          'actual_sql_transition_replay_verified':True,'component_source_bytes_verified':True,
          'historical_code_executed':False,'scientific_effectiveness_proven':False,'validation_acceptance':False}
out = work/'joint-deployment-committed-verification-r1.json'
with out.open('x',encoding='utf-8',newline='\n') as stream: stream.write(json.dumps(result,indent=2)+'\n')
print(json.dumps({'head':head,'committed_files_verified':len(files),'databases':len(databases),
    'counts':{key:sum(row[key] for row in databases) for key in ('events','started','committed','failed','pending')}}))
