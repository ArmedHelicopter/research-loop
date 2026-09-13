from pathlib import Path
import hashlib, io, json, subprocess, tarfile, zipfile
from xml.etree import ElementTree as ET

base=Path('E:/_ryanDev/AI/research-loop-modular');work=base/'work'
sha=lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
git=lambda tree,*args:subprocess.check_output(['git',*args],cwd=tree)
ac=json.loads((work/'ac-verification.json').read_text())
tree=base/'adm-combo'
assert git(tree,'rev-parse','HEAD').decode().strip()==ac['commit']
assert not git(tree,'status','--porcelain')
assert ac['source_before']==ac['source_after']
assert all(sha(tree/name)==value for name,value in ac['source_after'].items())
for row in ac['reports']:
    assert sha(row['path'])==row['sha256']
    suite=ET.parse(row['path']).getroot().find('testsuite')
    assert all(suite.attrib[k]==row[k] for k in ('tests','failures','errors','skipped','time'))
for row in ac['closed_controller_runs']:assert sha(row['path'])==row['sha256']

tree=base/'m6-public';prefix='results/modular-engineering-20260913/m6-public-input';root=tree/prefix
head='a53d1cebd3073c56dac4dba2cd5f3b12522e7a29'
assert git(tree,'rev-parse','HEAD').decode().strip()==head
assert not git(tree,'status','--porcelain')
manifest=json.loads((root/'ARTIFACT-MANIFEST.json').read_text())
final=json.loads((root/'FINAL-VERIFICATION.json').read_text())
assert sha(root/'ARTIFACT-MANIFEST.json')==final['artifact_manifest_sha256']
assert all(sha(root/name)==value for name,value in manifest['files'].items())
files={p.relative_to(tree).as_posix():sha(p) for p in root.rglob('*') if p.is_file()}
assert len(files)==35
with tarfile.open(fileobj=io.BytesIO(git(tree,'archive',head,prefix))) as tar:
    committed={m.name:hashlib.sha256(tar.extractfile(m).read()).hexdigest() for m in tar if m.isfile()}
assert files==committed
assert all(sha(base/'integration'/name)==value for name,value in files.items())
members={}
for path in root.glob('*-runtime.zip'):
    hashes=json.loads(path.with_name(path.stem+'-members.json').read_text())
    with zipfile.ZipFile(path) as archive:
        assert len(archive.namelist())==len(set(archive.namelist()))
        assert set(archive.namelist())==set(hashes)
        assert all(hashlib.sha256(archive.read(n)).hexdigest()==h for n,h in hashes.items())
    members[path.name]=len(hashes)
assert sum(members.values())==3416
result={'admission_commit':ac['commit'],'admission_source_files':len(ac['source_after']),
        'admission_original_reports':len(ac['reports']),'admission_controller_receipts':len(ac['closed_controller_runs']),
        'm6_commit':head,'m6_archive_files':len(files),'m6_zip_members':members,
        'new_paid_calls':0,'private_reference_payloads_read':0,'validation_payloads_read':0}
out=work/'admission-m6-deliveries-root-verification-r1.json';assert not out.exists()
out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(result))
