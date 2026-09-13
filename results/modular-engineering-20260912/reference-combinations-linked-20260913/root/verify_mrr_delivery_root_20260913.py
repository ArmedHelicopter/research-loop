import hashlib
import io
import json
import subprocess
import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path

BASE=Path('E:/_ryanDev/AI/research-loop-modular')
ROOT=BASE/'retrieval-review-combinations'
PREFIX='results/modular-engineering-20260913/retrieval-review-combinations'
ARCHIVE=ROOT/PREFIX
HEAD='177660c432e5d7904025bf6579b150d48a988c74'
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()==HEAD
assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()
manifest=json.loads((ARCHIVE/'ARTIFACT-MANIFEST.json').read_bytes())
final=json.loads((ARCHIVE/'FINAL-VERIFICATION.json').read_bytes())
assert sha(ARCHIVE/'FINAL-VERIFICATION.json')=='99158ecb75c6c862423807d66a3306f93d59fbca13e31788752840a3ae1ec6d5'
assert final['artifact_manifest_sha256']==sha(ARCHIVE/'ARTIFACT-MANIFEST.json')
assert len(manifest['files'])==404
for relative,expected in manifest['files'].items(): assert sha(ARCHIVE/relative)==expected,relative
paths={p.relative_to(ROOT).as_posix():sha(p) for p in ARCHIVE.rglob('*') if p.is_file()}
assert len(paths)==406
raw=subprocess.check_output(['git','archive',HEAD,PREFIX],cwd=ROOT)
with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
    blobs={m.name:hashlib.sha256(tar.extractfile(m).read()).hexdigest() for m in tar if m.isfile()}
assert blobs==paths
junit=ARCHIVE/'reports/retrieval-combinations-final07.xml'
assert sha(junit)==final['junit_sha256']
suite=ET.parse(junit).getroot().find('testsuite')
assert suite.attrib['tests']=='81' and all(suite.attrib[k]=='0' for k in ('failures','errors','skipped'))
for name,expected in final['final_tests']['git_blob_sha256'].items():
    blob=subprocess.check_output(['git','show',final['source_commit']+':'+name],cwd=ROOT)
    assert hashlib.sha256(blob).hexdigest()==expected,name
assert final['grid_denominator']=={'pair:M4+M6':8,'pair:M5+M6':8,'triple:M4+M5+M6':16}
assert final['mechanism_endpoint_independently_scored'] is False
out=BASE/'work/mrr-delivery-root-verification-r1.json'
assert not out.exists()
record={'schema':'retrieval-review-root-delivery-verification-v1','head':HEAD,
    'source_commit':final['source_commit'],'artifact_count':406,'original_manifest_files':404,
    'disk_and_HEAD_raw_bytes_equal':True,'source_commit_blobs_verified':5,'junit':dict(suite.attrib),
    'archive_hashes':paths,'scientific_validity':'not_measured','new_external_calls':0}
out.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'path':str(out),'sha256':sha(out),'archive_files':406,'tests':dict(suite.attrib)}))
