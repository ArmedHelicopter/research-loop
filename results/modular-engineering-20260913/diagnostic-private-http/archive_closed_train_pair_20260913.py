"""Archive interrupted-agent deliveries after root finishes their closed local checks."""
from pathlib import Path
import hashlib,json,subprocess,zipfile,shutil
from xml.etree import ElementTree as ET
B=Path('E:/_ryanDev/AI/research-loop-modular');W=B/'work'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for tree,slug,base,reports,runs,metadata in [
 ('cal-ports','diagnostic-private-http','4cbfe2c', ['cal-ports-checks/red-r1.xml','cal-ports-checks/root-r1.xml','cal-ports-checks/root-r2.xml','cal-ports-checks/worker-r1.xml'], ['cal-ports-checks/root-r1','cal-ports-checks/root-r2','cal-ports-checks/worker-r1'], ['cal-ports-checks/source-before-root-r1.json','cal-ports-checks/closed-root-r1.json','cal-ports-checks/closed-root-r2.json','cal-ports-checks/local-preflight-r1.json']),
 ('exploration-scheduler-combo','exploration-scheduler-combination','eff3a84', ['es-red.xml','es-grid-r1.xml','es-root-r1.xml','es-root-r2.xml'], ['es-grid-r1-temp','es-root-r1','es-root-r2'], ['es-source-before-root-r1.json','es-closed-root-r1.json','es-closed-root-r2.json'])]:
 r=B/tree;head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=r,text=True).strip();assert not subprocess.check_output(['git','status','--porcelain'],cwd=r)
 d=r/'results/modular-engineering-20260913'/slug;assert not d.exists();plans={};suites={};archives={}
 for name in reports+metadata:
  p=W/name;assert p.is_file();plans[Path(name).name]=(p,sha(p))
  if p.suffix=='.xml':suites[p.name]=ET.parse(p).getroot().find('testsuite').attrib
 changed=subprocess.check_output(['git','diff','--name-only',base,head,'--','research_loop','evaluation','tests','docs'],cwd=r,text=True).splitlines()
 for name in changed:plans['source/'+name]=(r/name,sha(r/name))
 for name in runs:
  root=W/name;assert root.is_dir();files={}
  for p in root.rglob('*'):
   if not p.is_file() or p.is_symlink() or p.is_junction():continue
   rel=p.relative_to(root)
   if any(x.endswith('current') or x in {'store','private-store','reference-store','snapshot','exported','export'} for x in rel.parts):continue
   if p.suffix=='.key' or p.name.startswith('key-'):continue
   # Every selected directory is generated solely by the named synthetic pytest fixture.
   files[rel.as_posix()]=sha(p)
  archives[Path(name).name]=(root,files)
 d.mkdir(parents=True)
 for name,(p,h) in plans.items():
  assert sha(p)==h;target=d/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target);assert sha(target)==h
 zips={}
 for name,(root,files) in archives.items():
  target=d/(name+'.zip')
  with zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED) as z:
   for rel,h in files.items():assert sha(root/rel)==h;z.write(root/rel,rel)
  with zipfile.ZipFile(target) as z:assert {i.filename:hashlib.sha256(z.read(i)).hexdigest() for i in z.infolist()}==files
  (d/(name+'.members.json')).write_text(json.dumps(files,indent=2)+'\n');zips[name]={'sha256':sha(target),'members':len(files)}
 v={'source_commit':head,'base_commit':base,'source_files':{n:h for n,(p,h) in plans.items() if n.startswith('source/')},'reports':suites,'synthetic_archives':zips,'actual_paid_calls':0,'actual_private_reference_payloads_copied':False,'validation_accessed':False,'scientific_effectiveness_proven':False,'scope':'Named local synthetic fixtures only; complete original failures retained. Source after interrupted agent was committed and checked by root.'}
 (d/'FINAL-VERIFICATION.json').write_text(json.dumps(v,indent=2)+'\n');shutil.copyfile(Path(__file__),d/Path(__file__).name)
 files={p.relative_to(d).as_posix():sha(p) for p in d.rglob('*') if p.is_file()};(d/'SHA256.json').write_text(json.dumps(files,indent=2)+'\n')
 print(json.dumps({'tree':tree,'head':head,'archive_files':len(files)+1,'zip_members':sum(len(f) for _,f in archives.values()),'reports':suites}),flush=True)
