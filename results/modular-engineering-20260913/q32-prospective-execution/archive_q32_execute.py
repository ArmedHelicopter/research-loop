import hashlib,json,subprocess,xml.etree.ElementTree as ET,zipfile,shutil
from pathlib import Path

root=Path('E:/_ryanDev/AI/research-loop-modular/q32-execute')
work=root.parent/'work'
out=root/'results/modular-engineering-20260913/q32-prospective-execution'
out.mkdir(parents=True,exist_ok=True)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
write=lambda p,data:p.write_text(json.dumps(data,sort_keys=True,indent=2)+'\n',encoding='utf-8',newline='\n')
reports={}
for name in ['red','preflight','final01','final02','final03']:
    src=work/f'q32-execute-{name}.xml'
    shutil.copyfile(src,out/src.name)
    reports[name]={'sha256':sha(src),'suite':ET.parse(src).getroot()[0].attrib}
for p in work.glob('q32-execute-final0*-source-*.json'):
    shutil.copyfile(p,out/p.name)
for name in ('q32_source_manifest.py','archive_q32_execute.py'):
    shutil.copyfile(work/name,out/name)
members={}
for round in ('final01','final02','final03'):
    base=work/f'q32-execute-{round}-temp'
    archive=out/f'{round}-actual-artifacts.zip'
    hashes={}
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as stream:
        for p in sorted(base.rglob('*')):
            if not p.is_file() or p.is_symlink() or any(part.endswith('current') for part in p.relative_to(base).parts):
                continue
            rel=p.relative_to(base).as_posix()
            hashes[rel]=sha(p)
            stream.write(p,rel)
    with zipfile.ZipFile(archive) as stream:
        assert {i.filename:hashlib.sha256(stream.read(i)).hexdigest() for i in stream.infolist()}==hashes
    write(out/f'{round}-archive-members.json',hashes)
    members[round]={'files':len(hashes),'archive_sha256':sha(archive),'member_manifest_sha256':sha(out/f'{round}-archive-members.json')}
source_commits=['00399dc','04f12c5','248306e','e7a5012']
source_files=['docs/Q32-PROSPECTIVE-EXECUTION.md','research_loop/modular/q32_execution.py','evaluation/modular/q32_execution_verifier.py','tests/test_q32_prospective_execution.py']
source={}
for commit in source_commits:
    full=subprocess.check_output(['git','rev-parse',commit],cwd=root,text=True).strip()
    rows={}
    for p in source_files:
        data=subprocess.run(['git','show',f'{full}:{p}'],cwd=root,capture_output=True)
        if data.returncode==0:rows[p]=hashlib.sha256(data.stdout).hexdigest()
    source[full]=rows
write(out/'source-git-blob-manifests.json',source)
before=out/'q32-execute-final03-source-before.json'
after=out/'q32-execute-final03-source-after.json'
assert before.read_bytes()==after.read_bytes()
assert (out/'q32-execute-final02-source-before.json').read_bytes()==(out/'q32-execute-final02-source-after.json').read_bytes()
grid={}
base=work/'q32-execute-final03-temp'
for p in base.rglob('panel-result.json'):
    d=json.loads(p.read_text())
    if d.get('cell_count')!=4:continue
    rows=d['results']
    name='execution_failure' if any(r['status']=='failed' for c in rows for r in c['rows']) else 'success'
    grid[name]={'cells':4,'measurement_denominator':12,'model_attempts':sum(c['model_attempts'] for c in rows),
        'docker_attempts':sum(c['execution_attempts'] for c in rows),
        'statuses':{s:sum(r['status']==s for c in rows for r in c['rows']) for s in ('succeeded','failed','blocked')},
        'rows':[{'cell':c['cell'],'model_attempts':c['model_attempts'],'execution_attempts':c['execution_attempts'],
                 'measurements':[{'ordinal':r['ordinal'],'plan_id':r['plan_id'],'observable':r['measurement']['observable'],
                    'status':r['status'],'observation':r['observation'],'execution_digest':r['execution_digest']} for r in c['rows']]} for c in rows]}
assert set(grid)=={'success','execution_failure'}
write(out/'actual-grids.json',grid)
report={'schema':'q32-prospective-execution-engineering-evidence-v1','source_commit':source_commits[-1],
    'source_commit_full':subprocess.check_output(['git','rev-parse','e7a5012'],cwd=root,text=True).strip(),
    'base_commit':'1fc1c8f69c6eb9e415bef224f432b61d09e4e4de','reports':reports,'archives':members,
    'source_file_count':len(json.loads(before.read_text())),'source_before_sha256':sha(before),'source_after_sha256':sha(after),
    'grid_file_sha256':sha(out/'actual-grids.json'),'new_success_cells':4,'new_execution_failure_cells':4,
    'new_primary_grid_measurement_denominator':24,'new_primary_grid_fixture_model_calls':32,'new_primary_grid_docker_attempts':24,
    'additional_new_docker_attempts':6,'additional_failure_fixture_broker_attempts':1,'producer_failure_fixture_calls':2,
    'rehashed_grid_counterexamples':48,'blocked_plan_substitution_counterexamples':1,
    'scope':'Q3.2 explicit execution phase; M4 fixed on; two variants times two benchmarks',
    'historical_regression':'final02 includes unchanged planning-only path and old 20-cell linked prediction grid plus its failure grid; not new experiments',
    'scientific_validated':False,'programme_complete':False,'independent_data_qualification':'not_established',
    'limitations':['Caller supplies unverified plan and numeric measurement meaning.','Same CSV-derived measurements are not independent data.',
       'Declared-range membership has no calibrated scientific support/elimination interpretation.',
       'No real paid calls, validation, private reference payloads or scientific scoring used.',
       'Model token threshold stops later calls after returned usage; in-flight overshoot/unknown cost remains visible.',
       'The original planning_only and caller-supplied support restrictions remain unchanged.']}
write(out/'FINAL-VERIFICATION.json',report)
write(out/'artifact-sha256.json',{p.name:sha(p) for p in sorted(out.iterdir()) if p.is_file() and p.name!='artifact-sha256.json'})
print(json.dumps({'files':len(list(out.iterdir())),'final_sha256':sha(out/'FINAL-VERIFICATION.json'),'junit_sha256':reports['final03']['sha256'],'source':report['source_before_sha256'],'archives':members}))
