"""Archive the closed root integration check without rewriting earlier evidence."""
import hashlib,json,shutil,subprocess,sys
from pathlib import Path
TREE=Path('E:/_ryanDev/AI/research-loop-modular/integration');WORK=TREE.parent/'work'
OUT=TREE/'results/modular-engineering-20260913/state-improvement-root'
def read(p):return json.loads(p.read_bytes())
def write(p,b):p.write_text(json.dumps(b,indent=2)+'\n',encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=TREE,text=True).strip()
closed=read(WORK/'state-improvement-integrated-r1-closed.json')
assert closed['commit']==head and closed['source_unchanged'] and closed['exit_code']==0
assert closed['junit']=={'tests':27,'failures':0,'errors':0,'skipped':0}
subprocess.run([sys.executable,str(WORK/'verify_committed_archive.py'),str(TREE),
 'results/modular-engineering-20260913/state-improvement-prospective',
 str(WORK/'state-improvement-source-committed-root-r2.json')],check=True)
OUT.mkdir(parents=True,exist_ok=False)
for suffix in ('-before.json','-closed.json','.xml'):
 p=WORK/('state-improvement-integrated-r1'+suffix);shutil.copyfile(p,OUT/p.name)
for name in ('state-improvement-root-source-review-r1.md','state-improvement-root-source-review-r2.md',
 'state-improvement-source-committed-root-r2.json','resolve_state_improvement_scorer_integration.py'):
 shutil.copyfile(WORK/name,OUT/name)
shutil.copyfile(__file__,OUT/Path(__file__).name)
write(OUT/'FINAL-VERIFICATION.json',{'source_commit':head,'source_files':closed['source_count'],
 'source_unchanged':True,'junit':closed['junit'],'junit_sha256':closed['report_sha256'],
 'coverage':'25 of 36 pair controllers; 2 of 5 triple controllers; synthetic engineering only',
 'complete_grid':{'actual_history_builds':11,'target_cells':22,'structural_exclusions':2,
 'scripted_model_calls':55,'source_qualifications':66,'actual_target_docker':22,'actual_scorer_process_calls':22},
 'inherited_history_separately_reported':{'scripted_model_calls':2,'actual_docker':1},
 'source_archive':{'files':35,'indexed':34,'zip_members':13701,'closure_count':8,
 'accumulated_distinct_checks':95,'fresh_final_source_95_check_run':False},
 'root_scope':'full builds/targets; proxy bypass, rehashed order and Docker limits; merged family scopes; legacy prediction scorer; labels',
 'new_generation_calls':0,'validation_opened':False,'scientific_effectiveness_proven':False})
write(OUT/'SHA256.json',{p.name:sha(p) for p in OUT.iterdir() if p.is_file()})
print(json.dumps({'root_files':len(list(OUT.iterdir())),'junit':closed['junit']}))
