"""Retain the closed integrated state/scheduling checks and original source review."""
import hashlib,json,shutil,subprocess,sys
from pathlib import Path
TREE=Path('E:/_ryanDev/AI/research-loop-modular/integration');WORK=TREE.parent/'work'
OUT=TREE/'results/modular-engineering-20260913/state-scheduling-root'
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_bytes())
def write(path,body):path.write_text(json.dumps(body,indent=2)+'\n',encoding='utf-8')
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=TREE,text=True).strip()
closed=read(WORK/'state-scheduling-integrated-r1-closed.json')
assert closed['commit']==head and closed['source_unchanged'] and closed['exit_code']==0
assert closed['junit']['tests']>0 and all(closed['junit'][k]==0 for k in ('failures','errors','skipped'))
subprocess.run([sys.executable,str(WORK/'verify_committed_archive.py'),str(TREE),
    'results/modular-engineering-20260913/state-scheduling-prospective',
    str(WORK/'state-scheduling-source-committed-root-r2.json')],check=True)
OUT.mkdir(parents=True,exist_ok=False)
for suffix in ('-before.json','-closed.json','.xml'):
    path=WORK/('state-scheduling-integrated-r1'+suffix);shutil.copyfile(path,OUT/path.name)
for name in ('state-scheduling-root-source-review-r1.md','state-scheduling-source-committed-root-r2.json'):
    shutil.copyfile(WORK/name,OUT/name)
shutil.copyfile(__file__,OUT/Path(__file__).name)
write(OUT/'FINAL-VERIFICATION.json',{'source_commit':head,'source_files':closed['source_count'],
    'source_unchanged':True,'junit':closed['junit'],'junit_sha256':closed['report_sha256'],
    'coverage':'22 of 36 pair controllers; 2 of 5 triple controllers; synthetic engineering only',
    'complete_grid':{'cells':24,'scripted_model_calls':48,'actual_docker':72,'actual_primary_scorer_process_calls':24,'source_qualifications':48},
    'root_scope':'full prospective grid; actual dependency, conflict, reverse-order, timeout and container-overlap variants; strict family and existing prediction scorer scopes; label isolation',
    'source_archive':{'files':16,'indexed':15,'zip_members':4315},
    'limitations':['synthetic solver/source/scorer responses','selected-cell attack coverage','no throughput estimate under concurrent workload'],
    'new_generation_calls':0,'validation_opened':False,'scientific_effectiveness_proven':False})
write(OUT/'SHA256.json',{p.name:sha(p) for p in OUT.iterdir() if p.is_file()})
print(json.dumps({'root_files':len(list(OUT.iterdir())),'junit':closed['junit']}))
