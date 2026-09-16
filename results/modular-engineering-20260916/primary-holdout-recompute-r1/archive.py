import hashlib,json,zipfile
from pathlib import Path
BASE=Path('E:/_ryanDev/AI/research-loop-modular');W=BASE/'work';R=BASE/'artifact-evidence-provenance'
D=R/'results/modular-engineering-20260916/primary-holdout-recompute-r1'
P=BASE/'custody-private/primary-holdout-recompute-20260916-r1'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(path):return json.loads(path.read_bytes())
assert not D.exists()
public=read(W/'primary-holdout-recompute-20260916-r1-public.json')
start=read(W/'primary-holdout-recompute-20260916-r1-native-start.json')
join=read(W/'primary-holdout-recompute-20260916-r1-native-join.json')
assert start['session_id']==join['native_session_id']==26628 and join['result']['exit_code']==0
assert public['source_commit']==join['source_commit'] and public['status']=='recomputed_equal'
for name,row in public['private_evidence_pins'].items():
    raw=(P/name).read_bytes();assert sha(raw)==row['sha256'] and len(raw)==row['bytes']
intent=read(P/'intent.json');D.mkdir(parents=True)
(D/'.gitattributes').write_bytes(b'* -text\n')
source_members=[]
with zipfile.ZipFile(D/'source-exact.zip','x',zipfile.ZIP_DEFLATED) as z:
    for name,digest in sorted(intent['source_before'].items()):
        raw=(R/name).read_bytes();assert sha(raw)==digest
        z.writestr(name,raw);source_members.append({'path':name,'sha256':digest,'bytes':len(raw)})
with zipfile.ZipFile(D/'source-exact.zip') as z:
    assert z.testzip() is None
    for row in source_members:assert sha(z.read(row['path']))==row['sha256']
(D/'source-members.json').write_text(json.dumps({'commit':public['source_commit'],'archive_sha256':sha((D/'source-exact.zip').read_bytes()),'members':source_members},indent=2)+'\n')
copies={
 'result.json':W/'primary-holdout-recompute-20260916-r1-public.json',
 'native-start.json':W/'primary-holdout-recompute-20260916-r1-native-start.json',
 'native-join.json':W/'primary-holdout-recompute-20260916-r1-native-join.json',
 'recompute.py':W/'recompute_primary_holdout_r1.py',
 'archive.py':Path(__file__),
}
for name,path in copies.items():
    (D/name).write_bytes(path.read_bytes());assert (D/name).read_bytes()==path.read_bytes()
(D/'README.md').write_text('''# Primary holdout recorded-evidence recomputation

A separate child recomputed the pinned process audit and observed-family partition:
308 TRAIN items, 95 validation items, 76 groups and 1,540 declared input bindings.
The original audit matched in every field except the separately recorded new observation time;
the original partition matched exactly. Recorded forced-TRAIN membership has zero overlap
with validation. Original source, audit and split bytes were unchanged. Native 26628 joined exit 0.

Private original metadata, recomputed records and this auditor's complete declared-input
read manifest remain in the pinned custody-private directory. No validation payload was
decoded or exported, and no lease, model call or network call was issued. This verifies
recorded exposure/relationships and source bytes. It does not establish universal historical
non-exposure, model pretraining absence, source independence beyond the recorded graph,
or scientific effect. Old gaps and false flags are preserved. Actual source qualification,
candidate freeze, calibration and isolated acceptance execution remain separate obligations.
''',encoding='utf-8')
files=[{'path':p.name,'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for p in sorted(D.iterdir())]
(D/'published-manifest.json').write_text(json.dumps({'schema':'primary-holdout-recompute-archive-v1','files':files},indent=2)+'\n')
print(json.dumps({'archive':str(D),'files':len(files)+1,'source_files':len(source_members),'manifest_sha256':sha((D/'published-manifest.json').read_bytes())}))
