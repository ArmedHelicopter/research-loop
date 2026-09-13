"""Archive the closed root integration checkpoint without rewriting prior runs."""
import hashlib,json,shutil,subprocess
from pathlib import Path
TREE=Path('E:/_ryanDev/AI/research-loop-modular/integration');WORK=TREE.parent/'work'
OUT=TREE/'results/modular-engineering-20260913/mechanism-improvement-triple147-root'
def read(p):return json.loads(p.read_bytes())
def write(p,b):p.write_text(json.dumps(b,indent=2)+'\n',encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=TREE,text=True).strip()
closed=read(WORK/'mechanism-improvement-triple147-integrated-r1-closed.json')
assert closed['commit']==head and closed['source_unchanged'] and closed['exit_code']==0
assert closed['junit']=={'tests':50,'failures':0,'errors':0,'skipped':0}
for name in ('mechanism-improvement-source-committed-root-r1.json','triple147-source-committed-root-r1.json'):
    p=read(WORK/name);assert p['head']==head and p['disk_equals_git'] and p['zip_hashes_match']
OUT.mkdir(parents=True,exist_ok=False)
for suffix in ('-before.json','-closed.json','.xml'):
    p=WORK/('mechanism-improvement-triple147-integrated-r1'+suffix);shutil.copyfile(p,OUT/p.name)
for name in ('mechanism-improvement-source-committed-root-r1.json','triple147-source-committed-root-r1.json',
             'resolve_mechanism_improvement_scorer_integration.py','resolve_triple147_scorer_integration.py',
             'mechanism-improvement-triple147-root-review-r1.md'):
    shutil.copyfile(WORK/name,OUT/name)
shutil.copyfile(__file__,OUT/Path(__file__).name)
write(OUT/'FINAL-VERIFICATION.json',{'source_commit':head,'source_files':closed['source_count'],
    'source_unchanged':True,'junit':closed['junit'],'junit_sha256':closed['report_sha256'],
    'coverage':'34 of36 pair controllers;3 of5 required triple controllers; synthetic engineering only',
    'mechanism_improvement_grid':{'cells':24,'canonical_builds':6,'arm_bindings':12,'scripted_model_calls':78,
        'qualification_calls':76,'retrieval_operations':24,'docker_executions':24,'scorer_process_calls':24},
    'triple147_grid':{'cells':16,'scripted_model_calls':48,'qualification_calls':32,
        'docker_executions':48,'scorer_process_calls':16,'descriptive_components':7,
        'confidence_intervals':'null_insufficient_independent_groups'},
    'source_archives':[{'files':25,'indexed':24,'zip_members':11686,'current_accumulated_checks':95,
        'not_fresh_final_source_suite':True,'original_red_closures':2},
        {'files':11,'indexed':10,'zip_members':1483,'isolated_checks':103}],
    'root_scope':'full grids; exact merged scorer scopes; original-response ordering; coherent Docker attacks; normalized triple terms; labels',
    'limitations':['scripted model and scorer responses','caller-trusted pinned records and signing keys',
        'selected-cell adversarial coverage','adapted primary metrics','unknown source costs preserved'],
    'new_generation_calls':0,'validation_opened':False,'scientific_effectiveness_proven':False})
write(OUT/'SHA256.json',{p.name:sha(p) for p in OUT.iterdir() if p.is_file()})
print(json.dumps({'files':len(list(OUT.iterdir())),'junit':closed['junit']}))
