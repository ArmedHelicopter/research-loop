"""Archive closed synthetic grids and check normal/drifting qualification contrasts."""
import hashlib, json, shutil, subprocess, zipfile
from collections import defaultdict
from pathlib import Path

TREE=Path('E:/_ryanDev/AI/research-loop-modular/integration')
WORK=TREE.parent/'work'
NAME='lineage-parity-integrated-r1'
OUT=TREE/'results/modular-engineering-20260913/lineage-parity-root'

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8'))
def write(path, body): path.write_text(json.dumps(body,ensure_ascii=True,indent=2)+'\n',encoding='utf-8')

closed=read(WORK/(NAME+'-closed.json'))
assert closed['exit_code']==0 and closed['source_unchanged'] is True
assert closed['junit']=={'tests':25,'failures':0,'errors':0,'skipped':0}
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=TREE,text=True).strip()==closed['commit']
OUT.mkdir(parents=True,exist_ok=False)
cases={
    'test_all_58_cells_use_actual_r0':(34,['not_identifiable','estimated','estimated','not_identifiable']),
    'test_all_58_cells_use_actual_r1':(24,['estimated']*3),
    'test_v3_admission_qualificatio0':(24,['inconclusive']*3),
    'admission-grid0':(24,['estimated']*3),
}
summary={}; members={}
with zipfile.ZipFile(OUT/(NAME+'.zip'),'w',zipfile.ZIP_DEFLATED) as archive:
    for case,(count,statuses) in cases.items():
        root=WORK/NAME/case
        receipt=read(root/'run/controller-receipt.json')
        attempt=read(root/'run/controller-attempt.json')
        assert receipt['expected_cells']==receipt['observed_cells']==receipt['scored_cells']==count
        assert receipt['actual_docker_attempts']==count and receipt['actual_scorer_calls']==count
        assert receipt['failed_cells']==receipt['blocked_cells']==0 and receipt['pruned_cells']==[]
        assert not receipt['validation_opened'] and not receipt['scientific_effectiveness_proven']
        assert [c['status'] for c in receipt['contrasts']]==statuses
        semantic_groups=defaultdict(set)
        for row in attempt['cells']:
            assert row['status']=='succeeded'
            cell=row['cell']
            if 'qualification_semantics_digest' in row:
                semantic_groups[(cell['coverage_id'],cell['task_digest'],cell['replicate'])].add(row['qualification_semantics_digest'])
        if case=='test_all_58_cells_use_actual_r1':
            assert len(semantic_groups)==6 and all(len(v)==1 for v in semantic_groups.values())
        if case=='test_v3_admission_qualificatio0':
            assert len(semantic_groups)==6 and all(len(v)>1 for v in semantic_groups.values())
            assert all(c['reason']=='v3_admission_qualification_semantic_drift' for c in receipt['contrasts'])
        summary[case]={'cells':count,'docker':receipt['actual_docker_attempts'],
            'source_calls':receipt['source_calls'],'scorer_calls':receipt['actual_scorer_calls'],
            'model_usage':receipt['actual_model_usage'],'contrast_statuses':statuses,
            'semantic_distinct_counts':sorted(len(v) for v in semantic_groups.values()),
            'controller_receipt_sha256':sha(root/'run/controller-receipt.json')}
        for p in sorted(root.rglob('*')):
            if not p.is_file() or p.is_symlink() or p.suffix=='.key' or p.name.startswith('key-'):continue
            rel=p.relative_to(root)
            if any(v in ('primary','legacy','store','lineage-references','__pycache__') for v in rel.parts):continue
            if any((root/Path(*rel.parts[:i])).is_symlink() or (root/Path(*rel.parts[:i])).is_junction() for i in range(1,len(rel.parts))):continue
            if len(rel.parts)>1 and rel.parts[0] not in ('run','port','solver','export','export-audit','scorers') and not rel.parts[0].startswith('worker'):continue
            if len(rel.parts)==1 and p.suffix not in ('.json','.jsonl'):continue
            member=(Path(case)/rel).as_posix(); archive.write(p,member);members[member]=sha(p)
with zipfile.ZipFile(OUT/(NAME+'.zip')) as archive:
    assert set(archive.namelist())==set(members)
    assert all(hashlib.sha256(archive.read(n)).hexdigest()==h for n,h in members.items())
for suffix in ('.xml','-before.json','-closed.json'):
    shutil.copyfile(WORK/(NAME+suffix),OUT/(NAME+suffix))
for name in ('lineage-parity-evidence-audit-r1.json','lineage-parity-evidence-audit-r2.json'):
    shutil.copyfile(WORK/name,OUT/name)
shutil.copyfile(__file__,OUT/Path(__file__).name)
shutil.copyfile(WORK/'run_frozen_useful_checks.py',OUT/'run_frozen_useful_checks.py')
write(OUT/'zip-members.json',members)
write(OUT/'DENOMINATORS.json',summary)
write(OUT/'FINAL-VERIFICATION.json',{
    'source_commit':closed['commit'],'junit':closed['junit'],'source_files':closed['source_count'],
    'source_unchanged':True,'zip_members':len(members),'zip_sha256':sha(OUT/(NAME+'.zip')),
    'total_actual_docker_cells':sum(v['docker'] for v in summary.values()),
    'total_scorer_opportunities':sum(v['scorer_calls'] for v in summary.values()),
    'total_fixture_model_calls':sum(v['model_usage']['model_calls'] for v in summary.values()),
    'normal_v3_admission_contrasts':'3 estimated with 6 semantically uniform task/pair groups',
    'drifting_v3_admission_contrasts':'3 inconclusive with all 24 scored cells retained',
    'historical_parity_report_claims':'not included as proof; original reports not located',
    'audit_r1':'wrong lookup path and member-count typo retained; r2 verifies actual integration archive',
    'exclusions':['private synthetic fixture reference stores','preparation files','keys','symlinks'],
    'new_paid_calls':0,'validation_opened':False,'scientific_effectiveness_proven':False,
    'scope':'synthetic functional integration; concurrency prevents throughput inference'} )
write(OUT/'SHA256.json',{p.name:sha(p) for p in sorted(OUT.iterdir()) if p.is_file()})
print(json.dumps({'files':len(list(OUT.iterdir())),'members':len(members),
    'cases':{k:{a:v[a] for a in ('cells','contrast_statuses','semantic_distinct_counts')} for k,v in summary.items()}}))
