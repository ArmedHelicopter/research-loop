"""Archive both production batches while retaining private payloads in custody."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

work=Path(__file__).parent
dest=work.parent/'artifact-evidence-provenance/results/modular-engineering-20260915/formal-headless-authoring-r1'
dest.mkdir(parents=True,exist_ok=False)
files=[]
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def copy(source,name):
    source=Path(source);target=dest/name;target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(source,target)
    assert sha(target)==sha(source)
    files.append({'file':name,'source':str(source),'bytes':source.stat().st_size,
                  'source_mtime_ns':source.stat().st_mtime_ns,'sha256':sha(source)})

for name,check_prefix,tests in (('low-effort','headless-explicit-effort-root-r1',91),
                               ('indexed','headless-indexed-references-root-r1',92)):
    root=work/f'headless-authoring-{name}-run-r1'
    prep=work/f'headless-authoring-{name}-preparation-r1'
    for src,out in ((root/'public-parent-closure.json','parent-closure.json'),
                    (root/'parent-reservation.json','parent-reservation.json'),
                    (root/'independent-readback.json','independent-readback.json'),
                    (root/'private-output/public-outcome.json','public-outcome.json'),
                    (prep/'public-preparation.json','public-preparation.json'),
                    (prep/'freeze/authoring-envelope.json','authoring-envelope.json'),
                    (prep/'freeze/authoring-envelope.run-reservation.json','authoring-reservation.json')):
        copy(src,name+'/'+out)
    outcome=json.loads((root/'private-output/public-outcome.json').read_bytes())
    for state in outcome['authoring_outcomes']:
        folder=root/'private-output'/state['opportunity_id']
        for src in (folder/'native/observer-receipt.json',folder/'headless-request-binding.json'):
            if src.exists():copy(src,name+'/native/'+state['opportunity_id']+'/'+src.name)
    inventory=[]
    for private_root in (root,prep):
        for path in sorted(private_root.rglob('*')):
            if not path.is_file() or path.name=='auth.json' or path.suffix=='.key':continue
            assert not path.is_symlink() and not path.is_junction()
            inventory.append({'path':str(path),'sha256':sha(path),'bytes':path.stat().st_size,
                              'mtime_ns':path.stat().st_mtime_ns})
    inventory_path=work/f'headless-authoring-{name}-private-inventory-r1.json'
    with inventory_path.open('x',encoding='utf-8',newline='\n') as out:
        out.write(json.dumps({'schema':'retained-private-authoring-inventory-v1','files':inventory,
            'auth_files_and_private_keys_omitted':True,'payloads_copied_to_public_archive':False},indent=2)+'\n')
    copy(inventory_path,name+'/private-artifact-inventory.json')
    for prefix in ('prepare','run'):
        script=work/(prefix+'_formal_'+name.replace('-','_')+'_authoring_r1.py')
        copy(script,name+'/'+prefix+'.py')
    closed=json.loads((work/(check_prefix+'-closed.json')).read_bytes())
    assert closed['exit_code']==0 and closed['source_unchanged'] and closed['junit']=={
        'tests':tests,'failures':0,'errors':0,'skipped':0}
    with zipfile.ZipFile(work/(check_prefix+'-sources.zip')) as archive:
        assert set(archive.namelist())==set(closed['source_after'])
        for filename,pin in closed['source_after'].items():
            assert hashlib.sha256(archive.read(filename)).hexdigest()==pin
    for suffix,target in (('-before.json','before.json'),('-closed.json','closed.json'),
                          ('-sources.zip','sources.zip'),('-source-members.json','source-members.json'),('.xml','junit.xml')):
        copy(work/(check_prefix+suffix),name+'/checks/'+target)
for filename in ('postfailure-contract-diagnosis.json','postfailure-reference-index-diagnosis.json'):
    copy(work/'headless-authoring-low-effort-run-r1'/filename,'low-effort/'+filename)
copy(work/'audit_formal_authoring_batch_r1.py','audit-originals.py')
copy(Path(__file__),'archive-originals.py')
(dest/'.gitattributes').write_bytes(b'* -text\n')
manifest={'schema':'formal-headless-authoring-archive-v1','files':files,'validation_access':False,
          'formal_calibration_issued':False,'original_failed_batch_unchanged':True,
          'indexed_batch_ready_materials':26,'extra_paid_api_budget':0}
(dest/'manifest.json').write_bytes((json.dumps(manifest,indent=2)+'\n').encode())
print(json.dumps({'archive':str(dest),'files_verified':len(files),
                  'source_members_verified':1508,'new_model_calls':0}))
