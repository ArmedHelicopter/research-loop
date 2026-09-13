"""Archive reviewed closed deliveries; every path is explicitly bounded to synthetic runs."""
from pathlib import Path
import hashlib,json,subprocess,shutil,zipfile
from xml.etree import ElementTree as ET
B=Path('E:/_ryanDev/AI/research-loop-modular');W=B/'work';R=B/'integration'
D=R/'results/modular-engineering-20260913/admission-calibration-prospective-source'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_bytes())
git=lambda r,*a:subprocess.check_output(['git',*a],cwd=r)
copies={};groups={};junit={}
def plan(path,name,expected=None):
 p=Path(path);assert p.is_file() and not p.is_symlink() and not p.is_junction(),str(p)
 h=sha(p);assert expected is None or h==expected,str(p);row={'source':str(p),'sha256':h,'bytes':p.stat().st_size}
 assert name not in copies or copies[name]==row;copies[name]=row
 if p.suffix=='.xml':junit[name]=ET.parse(p).getroot().find('testsuite').attrib

def group(name,root,files):
 root=Path(root);rows={}
 for p in sorted(set(files)):
  assert p.is_relative_to(root) and p.is_file() and not p.is_symlink() and not p.is_junction()
  rows[p.relative_to(root).as_posix()]={'sha256':sha(p),'bytes':p.stat().st_size}
 assert rows and name not in groups;groups[name]=(root,rows)

def runtime(name,root):
 root=Path(root);paths=[p for p in (root/'run').rglob('*') if p.is_file()]
 for glob in ('port/ledger.json','solver/ledger.json','client*.jsonl','worker*.jsonl','independent-fixture-authority.json','signed-fixture-primary-scores.json','source-verification.json'):
  paths.extend(root.glob(glob))
 for worker in root.glob('worker*'):
  if worker.is_dir():
   for rel in ('client.jsonl','server.jsonl','evaluator/ledger.json'):
    if (worker/rel).is_file():paths.append(worker/rel)
 # Controller exports and source audit metadata are non-payload receipts only.
 for name2 in ('export','exported'):
  if (root/name2).is_dir():paths.extend((root/name2).rglob('*receipt*.json'))
 if paths:group(name,root,paths)

assert not D.exists();assert not git(R,'status','--porcelain').strip()
root_commit=git(R,'rev-parse','HEAD').decode().strip()
ac=read(W/'ac-verification.json');plan(W/'ac-verification.json','admission/verification.json')
for p,h in ac['source_after'].items():plan(B/'adm-combo'/p,'admission/source/'+p,h)
for row in ac['reports']:
 path=Path(row.get('path',row.get('file','')));plan(path,'admission/reports/'+path.name,row['sha256'])
for n,row in enumerate(ac['closed_controller_runs']):
 p=Path(row['path']);assert sha(p)==row['sha256'];runtime('admission-'+str(n),p.parent.parent)

cal=W/'cal-pilot-checks';delivery=read(cal/'delivery-manifest-r2.json')
plan(cal/'delivery-manifest-r2.json','calibration/delivery-manifest-r2.json')
for row in delivery['files']:plan(row['path'],'calibration/'+Path(row['path']).name,row['sha256'])
plan(B/'cal-pilot/docs/calibration-pilot-verification.json','calibration/verification.json')
for row in read(B/'cal-pilot/docs/calibration-pilot-verification.json')['tests']:
 plan(row['path'],'calibration/reports/'+Path(row['path']).name,row['sha256'])
for row in read(cal/'synthetic-denominators-r2.json')['journals']:
 plan(row['path'],'calibration/synthetic-journals/'+Path(row['path']).relative_to(cal).as_posix(),row['sha256'])
preflight=read(cal/'actual-port-preflight-delivery-r1.json');plan(cal/'actual-port-preflight-delivery-r1.json','calibration/actual-port-preflight-delivery-r1.json')
for row in preflight['files']:plan(row['path'],'calibration/'+Path(row['path']).name,row['sha256'])
for p in git(B/'cal-pilot','diff','--name-only','57bed6e','4cbfe2c','--','evaluation','tests','docs').decode().splitlines():
 if 'calibration_pilot' in p or 'calibration-pilot' in p:plan(B/'cal-pilot'/p,'calibration/source/'+p)

combo=B/'combo-export'
for p in git(combo,'diff','--name-only','d168781','21ab5a3','--','research_loop','tests','docs').decode().splitlines():plan(combo/p,'prospective-source/source/'+p)
for name in ('combo-export-preflight-r1.xml','combo-export-grid-r1.xml','combo-export-grid-r2.xml','combo-export-provenance-r3.xml','combo-export-final-r1.xml','combo-export-source-before-r1.json','combo-export-grid-r1-closed.json','combo-export-source-before-final-r1.json','combo-export-final-closed-r1.json','combo-source-readonly-review.py','combo-source-readonly-review.xml'):
 plan(W/name,'prospective-source/reports/'+name)
for run_name in ('combo-export-grid-r1','combo-export-grid-r2','combo-export-final-r1'):
 root=W/run_name
 for n,p in enumerate(sorted(root.glob('test_all_three_actual_controll*'))):
  if p.is_dir() and not p.is_symlink() and not p.is_junction():runtime(run_name+'-'+str(n),p)
 # Preflight failures retain export-completion audit metadata and full blocked grid.
 for n,p in enumerate(sorted(root.glob('test_rejection_precedes_all_do*'))):
  if p.is_dir() and not p.is_symlink() and not p.is_junction():runtime(run_name+'-rejection-'+str(n),p)

for name in ('admission-m6-integrated-r1.xml','admission-m6-integrated-source-before-r1.json','admission-m6-integrated-closed-r1.json','cal-pilot-integrated-r1.xml','cal-pilot-integrated-source-before-r1.json','cal-pilot-integrated-closed-r1.json','admission-m6-deliveries-root-verification-r1.json','cal-pilot-delivery-root-verification-r1.json','verify_admission_m6_deliveries_root_20260913.py','verify_cal_pilot_delivery_root_20260913.py','combo-source-integrated-r1.xml','combo-source-integrated-r2.xml','combo-source-integrated-source-before-r1.json','combo-source-integrated-closed-r2.json'):
 plan(W/name,'root/'+name)
plan(Path(__file__),Path(__file__).name)
# All preflight completes before destination mutation.
for name,row in copies.items():
 p=Path(row['source']);assert sha(p)==row['sha256'];target=D/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target);assert sha(target)==row['sha256']
zip_receipts={}
for name,(root,rows) in groups.items():
 target=D/'synthetic-grids'/(name+'.zip');target.parent.mkdir(parents=True,exist_ok=True)
 with zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED) as z:
  for rel,row in rows.items():assert sha(root/rel)==row['sha256'];z.write(root/rel,rel)
 with zipfile.ZipFile(target) as z:assert {i.filename:hashlib.sha256(z.read(i)).hexdigest() for i in z.infolist()}=={n:r['sha256'] for n,r in rows.items()}
 (target.with_suffix('.members.json')).write_text(json.dumps(rows,indent=2)+'\n');zip_receipts[name]={'files':len(rows),'sha256':sha(target)}
(D/'DELIVERY.json').write_text(json.dumps({'root_source_commit':root_commit,'files':copies,'junit':junit,'synthetic_grids':zip_receipts,'new_paid_calls':0,'actual_private_payloads_in_archive':False,'scientific_calibration':False,'validation_eligible':False},indent=2)+'\n')
files={p.relative_to(D).as_posix():sha(p) for p in D.rglob('*') if p.is_file()};(D/'SHA256.json').write_text(json.dumps(files,indent=2)+'\n')
print(json.dumps({'root_source_commit':root_commit,'archive_files':len(files)+1,'synthetic_grids':len(groups),'synthetic_members':sum(len(r) for _,r in groups.values())}))
