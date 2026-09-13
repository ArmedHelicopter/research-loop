"""Publish synthetic controller evidence without custody stores or key bytes."""
import hashlib,json,shutil,subprocess,zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

tree=Path('E:/_ryanDev/AI/research-loop-modular/m4m5-useful-controls')
work=tree.parent/'work'
out=tree/'results/modular-engineering-20260913/m4-m5-useful-controls'
out.mkdir(parents=True,exist_ok=False)
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,b): p.write_text(json.dumps(b,ensure_ascii=True,indent=2)+'\n',encoding='utf-8')
reports={}; zip_index={}; denominator={}
prefixes=['useful-controls-red-r1','useful-controls-grid-r1','useful-controls-final-r1','useful-controls-final-r2']
for name in prefixes:
    report=work/(name+'.xml')
    shutil.copyfile(report,out/report.name)
    suites=list(ET.parse(report).getroot().iter('testsuite'))
    reports[name]={k:sum(int(s.get(k,0)) for s in suites) for k in ('tests','failures','errors','skipped')}
    for suffix in ('-before.json','-closed.json'):
        p=work/(name+suffix)
        if p.exists(): shutil.copyfile(p,out/p.name)
    if name=='useful-controls-red-r1': continue
    roots=[]
    for p in (work/name).iterdir():
        if p.is_dir() and not p.is_symlink() and not p.is_junction() and not p.name.endswith('current'):
            if any(p.name.startswith(s) for s in ('test_eight_cell_useful','test_replay_rejects_useful','test_malformed_reviews','test_new_recipe_keeps')):
                roots.append(p)
    members={}; rows=[]
    with zipfile.ZipFile(out/(name+'.zip'),'w',zipfile.ZIP_DEFLATED) as z:
        for root in sorted(roots):
            for p in sorted(root.rglob('*')):
                if not p.is_file() or p.is_symlink() or p.suffix=='.key': continue
                rel=p.relative_to(root)
                if any(q in ('primary','legacy','store','__pycache__') for q in rel.parts): continue
                if any((root/Path(*rel.parts[:i])).is_symlink() or (root/Path(*rel.parts[:i])).is_junction() for i in range(1,len(rel.parts))): continue
                if len(rel.parts)>1 and rel.parts[0] not in ('run','port','export','export-audit','cell-00','cell-01'): continue
                if len(rel.parts)==1 and p.suffix not in ('.json','.jsonl','.csv'): continue
                member=(Path(root.name)/rel).as_posix(); z.write(p,member); members[member]=sha(p)
            attempt=root/'run/controller-attempt.json'
            if attempt.exists():
                b=json.loads(attempt.read_text(encoding='utf-8'))
                rows.append({'case':root.name,'status':b['status'],'planned_cells':len(b['cells']),
                    'cell_statuses':{s:sum(c['status']==s for c in b['cells']) for s in ('succeeded','failed','blocked','not_started')},
                    'model_usage':b['actual_model_usage'],'scorer_calls':b['actual_scorer_calls']})
    with zipfile.ZipFile(out/(name+'.zip')) as z:
        assert set(z.namelist())==set(members)
        assert all(hashlib.sha256(z.read(n)).hexdigest()==h for n,h in members.items())
    write(out/(name+'-zip-members.json'),members)
    zip_index[name]={'sha256':sha(out/(name+'.zip')),'members':len(members)}
    denominator[name]=rows
write(out/'DENOMINATORS.json',denominator)
shutil.copyfile(__file__,out/'archive_useful_controls.py')
shutil.copyfile(work/'run_frozen_useful_checks.py',out/'run_frozen_useful_checks.py')
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=tree,text=True).strip()
write(out/'FINAL-VERIFICATION.json',{'source_commit':head,'reports':reports,'zips':zip_index,
    'scope':'synthetic engineering; only new recipe case sidecars included in ZIPs; existing regression reports retained',
    'excluded':['private fixture stores','legacy fixture preparation','primary fixture preparation','key bytes','symlinks'],
    'red_before_manifest':'not recorded; clean contract-only commit df91611a093951493a9a9b79fb18c2a84ef5ef06',
    'new_paid_calls':0,'validation_opened':False,'scientific_effectiveness_proven':False})
write(out/'SHA256.json',{p.name:sha(p) for p in sorted(out.iterdir()) if p.is_file()})
print(json.dumps({'files':len(list(out.iterdir())),'reports':reports,'zips':zip_index}))
