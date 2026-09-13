"""Preserve the completed integrated mechanism scheduling checkpoint."""
import hashlib,json,shutil,subprocess
from pathlib import Path
TREE=Path('E:/_ryanDev/AI/research-loop-modular/integration');WORK=TREE.parent/'work'
OUT=TREE/'results/modular-engineering-20260913/mechanism-scheduling-root'
def read(p):return json.loads(p.read_bytes())
def write(p,b):p.write_text(json.dumps(b,indent=2)+'\n',encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=TREE,text=True).strip()
closed=read(WORK/'mechanism-scheduling-integrated-r1-closed.json')
assert closed['commit']==head and closed['source_unchanged'] and closed['exit_code']==0
assert closed['junit']['tests']>0 and all(closed['junit'][k]==0 for k in ('failures','errors','skipped'))
source=read(WORK/'mechanism-scheduling-source-committed-root-r1.json')
assert source['head']==head and source['disk_equals_git'] and source['zip_hashes_match']
OUT.mkdir(parents=True,exist_ok=False)
for suffix in ('-before.json','-closed.json','.xml'):
 p=WORK/('mechanism-scheduling-integrated-r1'+suffix);shutil.copyfile(p,OUT/p.name)
for name in ('mechanism-scheduling-root-source-review-r1.md','mechanism-scheduling-source-committed-root-r1.json',
 'resolve_mechanism_scheduling_scorer_integration.py'):
 shutil.copyfile(WORK/name,OUT/name)
shutil.copyfile(__file__,OUT/Path(__file__).name)
write(OUT/'FINAL-VERIFICATION.json',{'source_commit':head,'source_files':closed['source_count'],
 'source_unchanged':True,'junit':closed['junit'],'junit_sha256':closed['report_sha256'],
 'coverage':'31 of 36 pair controllers; 2 of 5 triple controllers; synthetic engineering only',
 'complete_grid':{'cells':24,'scripted_model_calls':72,'source_qualifications':48,
 'actual_docker':72,'actual_scorer_process_calls':24,'retrieval_calls':24},
 'focused_scheduler_variants':5,'successful_variant_scores':4,
 'source_archive':{'files':11,'indexed':10,'zip_members':2124,'isolated_checks':114},
 'root_scope':'complete grid; real scheduler variants; persistent queue/journal attacks; exact scorer family scopes; legacy prediction process; labels',
 'limitations':['scripted model and scorer responses','selected-cell adversarial coverage','unknown realized source costs retained','no concurrent-host throughput estimate'],
 'new_generation_calls':0,'validation_opened':False,'scientific_effectiveness_proven':False})
write(OUT/'SHA256.json',{p.name:sha(p) for p in OUT.iterdir() if p.is_file()})
print(json.dumps({'root_files':len(list(OUT.iterdir())),'junit':closed['junit']}))
