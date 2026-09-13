"""Archive the closed useful lineage review experiments, all synthetic."""
import hashlib,json,shutil,subprocess,zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

tree=Path('E:/_ryanDev/AI/research-loop-modular/lineage-useful-controls'); work=tree.parent/'work'
out=tree/'results/modular-engineering-20260913/lineage-useful-controls';out.mkdir(parents=True,exist_ok=False)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,b):p.write_text(json.dumps(b,ensure_ascii=True,indent=2)+'\n',encoding='utf-8')
reports={};archives={};denominators={}
for name in ('lineage-useful-red-r1','lineage-useful-grid-r1','lineage-useful-final-r1'):
    for suffix in ('.xml','-before.json','-closed.json'):
        shutil.copyfile(work/(name+suffix),out/(name+suffix))
    suites=list(ET.parse(work/(name+'.xml')).getroot().iter('testsuite'))
    reports[name]={k:sum(int(s.get(k,0)) for s in suites) for k in ('tests','failures','errors','skipped')}
    if name=='lineage-useful-red-r1':continue
    members={};rows=[];faults=[]
    with zipfile.ZipFile(out/(name+'.zip'),'w',zipfile.ZIP_DEFLATED) as z:
        for root in sorted((work/name).iterdir()):
            if not root.is_dir() or root.is_symlink() or root.is_junction() or root.name.endswith('current'):continue
            if not root.name.startswith(('test_all_58','lineage-process-grid','admission-grid')):continue
            for p in sorted(root.rglob('*')):
                if not p.is_file() or p.is_symlink() or p.suffix=='.key':continue
                rel=p.relative_to(root)
                if any(v in ('primary','legacy','store','lineage-references','__pycache__') for v in rel.parts):continue
                if any((root/Path(*rel.parts[:i])).is_symlink() or (root/Path(*rel.parts[:i])).is_junction() for i in range(1,len(rel.parts))):continue
                if len(rel.parts)>1 and rel.parts[0] not in ('run','port','solver','export','export-audit','scorers') and not rel.parts[0].startswith('worker'):continue
                if len(rel.parts)==1 and p.suffix not in ('.json','.jsonl'):continue
                member=(Path(root.name)/rel).as_posix();z.write(p,member);members[member]=sha(p)
            attempt=root/'run/controller-attempt.json'
            if attempt.exists():
                b=json.loads(attempt.read_text(encoding='utf-8'))
                rows.append({'case':root.name,'status':b['status'],'planned_cells':len(b['cells']),
                    'cell_statuses':{s:sum(c['status']==s for c in b['cells']) for s in ('succeeded','failed','blocked','not_started')},
                    'model_usage':b['actual_model_usage'],'scorer_calls':b['actual_scorer_calls']})
            path=root/'replay-mutations.json'
            if path.exists():faults.append({'case':root.name,'mutations':json.loads(path.read_text(encoding='utf-8'))})
    with zipfile.ZipFile(out/(name+'.zip')) as z:
        assert set(z.namelist())==set(members)
        assert all(hashlib.sha256(z.read(n)).hexdigest()==h for n,h in members.items())
    write(out/(name+'-zip-members.json'),members)
    archives[name]={'members':len(members),'sha256':sha(out/(name+'.zip'))}
    denominators[name]={'controllers':rows,'replay_faults':faults}
write(out/'DENOMINATORS.json',denominators)
shutil.copyfile(__file__,out/'archive_lineage_useful_controls.py')
shutil.copyfile(work/'run_frozen_useful_checks.py',out/'run_frozen_useful_checks.py')
write(out/'FINAL-VERIFICATION.json',{'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=tree,text=True).strip(),
    'reports':reports,'zips':archives,'scope':'synthetic engineering only; old and new registered recipes retain distinct panel bindings',
    'excluded':['private fixture reference stores','fixture preparation','key files','symlinks'],
    'new_paid_calls':0,'validation_opened':False,'scientific_effectiveness_proven':False})
write(out/'SHA256.json',{p.name:sha(p) for p in sorted(out.iterdir()) if p.is_file()})
print(json.dumps({'files':len(list(out.iterdir())),'reports':reports,'zips':archives}))
