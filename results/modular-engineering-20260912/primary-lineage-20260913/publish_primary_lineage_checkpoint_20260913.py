"""Archive the closed primary audit and lineage engineering delivery."""
import hashlib,json,shutil,subprocess,zipfile
from pathlib import Path
import xml.etree.ElementTree as ET
BASE=Path('E:/_ryanDev/AI/research-loop-modular'); ROOT=BASE/'integration'; WORK=BASE/'work'
ARC=ROOT/'results/modular-engineering-20260912'; DEST=ARC/'primary-lineage-20260913'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_bytes())
def write(p,value):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8',newline='\n') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
assert head.startswith('73a6c2d')
assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()
report_path=WORK/'primary-lineage-root-r1.xml'
suite=ET.parse(report_path).getroot().find('testsuite')
assert all(suite.attrib[k]=='0' for k in ('failures','errors','skipped'))
old=read(ARC/'SHA256.json');assert len(old)==1524
assert all(sha(ARC/p)==v for p,v in old.items())
DEST.mkdir();origins={}
def add(p,name,expected=None):
    value=sha(p);assert expected is None or value==expected,str(p)
    target=DEST/name;target.parent.mkdir(parents=True,exist_ok=True);assert not target.exists()
    shutil.copyfile(p,target);assert sha(target)==value
    origins[name]={'source':str(p),'sha256':value}
primary=read(ROOT/'docs/primary-process-qualification-verification.json')
add(ROOT/'docs/primary-process-qualification-verification.json','primary/verification.json')
for group in ('artifacts','junit'):
    for row in primary[group]:
        p=Path(row['path'])
        # All declared private paths here contain opaque audit/allocation metadata only.
        if 'custody-private' in p.parts:
            assert p.name in {'intent.json','process-audit.json','prospective-split.json','seal-receipt.json'}
        add(p,'primary/'+p.name,row['sha256'])
lc=read(WORK/'lc-verification.json');add(WORK/'lc-verification.json','lineage/verification.json')
for name,row in lc['reports'].items():add(Path(row['path']),'lineage/'+name,row['sha256'])
add(WORK/'lc-legacy-evidence.py','lineage/lc-legacy-evidence.py',lc['red_provenance']['lc-root-red.xml']['sha256'])
receipt=lc['final_grid_receipt'];add(Path(receipt['path']),'lineage/final-controller-receipt.json',receipt['sha256'])
for name in ('verify_primary_seal_root_20260913.py','verify_primary_seal_root_20260913_r2.py','primary-seal-root-verification-r2.json',
             'primary-lineage-root-r1.xml','train-export-retrieval-archive-index-verification.json'):
    add(WORK/name,name)
source_paths=set(primary['source_sha256'])|set(lc['source_sha256'])|{'tests/test_primary_process_qualification.py'}
for relative in sorted(source_paths):
    add(ROOT/relative,'integrated-source/'+relative)
for relative,value in primary['source_sha256'].items():
    add(BASE/'primary-process-qualification'/relative,'primary-frozen-source/'+relative,value)
for relative,value in lc['source_sha256'].items():
    add(BASE/'lineage-combination-driver'/relative,'lineage-frozen-source/'+relative,value)
# A closed, entirely synthetic full 34-cell run; task/reference fixtures are synthetic.
grid=Path(receipt['path']).parent.parent
assert grid==WORK/'lc-final-r2-tmp/lineage-grid0'
members={}
with zipfile.ZipFile(DEST/'lineage/final-synthetic-grid.zip','x',zipfile.ZIP_DEFLATED) as output:
    for p in sorted(grid.rglob('*')):
        assert not p.is_symlink() and not p.is_junction(),str(p)
        if not p.is_file():continue
        name=p.relative_to(grid).as_posix();members[name]=sha(p);output.write(p,name)
assert sha(Path(receipt['path']))==receipt['sha256']
with zipfile.ZipFile(DEST/'lineage/final-synthetic-grid.zip') as archived:
    assert set(archived.namelist())==set(members)
    for name,value in members.items():assert hashlib.sha256(archived.read(name)).hexdigest()==value
write(DEST/'lineage/final-synthetic-grid-hashes.json',members)
write(DEST/'checkpoint.json',{'schema':'primary-lineage-engineering-checkpoint-v1','source_commit':head,
    'root_report':dict(suite.attrib),'primary_counts':primary['total_counts'],
    'primary_source_counts':{s:v['counts'] for s,v in primary['source_counts'].items()},
    'old_train_retained':81,'SAB_validation_records_on_hold':18,'primary_validation_payload_read':False,
    'lineage_controller_cells':receipt['expected_cells'],'lineage_synthetic_grid_files':len(members),
    'complete_pair_contrasts':{'pair:M2+M5':'estimated_synthetic_only','pair:M3+M5':'estimated_synthetic_only'},
    'structural_contrasts':{'pair:M2+M3':'not_identifiable','triple:M2+M3+M5':'not_identifiable'},
    'lineage_independent_process_scorer':'separate_implementation_in_progress',
    'new_paid_calls':0,'scientific_effectiveness':'not_established','validation_acceptance':'not_run',
    'pruned_combinations':[],'BLADE_validation_group_count':1,
    'multi_stage_fresh_primary_validation_group_sufficiency':'insufficient'})
add(Path(__file__),Path(__file__).name);write(DEST/'ORIGINS.json',origins)
current=dict(old)
for p in DEST.rglob('*'):
    if p.is_file():
        relative=p.relative_to(ARC).as_posix();assert relative not in current;current[relative]=sha(p)
assert all(sha(ARC/p)==v for p,v in old.items())
(ARC/'SHA256.json').write_text(json.dumps(dict(sorted(current.items())),indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps({'old_files_unchanged':len(old),'indexed_files':len(current),'new_files':len(current)-len(old),
    'synthetic_zip_members':len(members),'root_tests':dict(suite.attrib)}))
