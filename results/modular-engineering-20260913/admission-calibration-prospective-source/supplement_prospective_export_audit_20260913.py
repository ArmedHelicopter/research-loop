from pathlib import Path
import hashlib,json,shutil
B=Path('E:/_ryanDev/AI/research-loop-modular');W=B/'work';D=B/'integration/results/modular-engineering-20260913/admission-calibration-prospective-source'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();copied={}
for run in ('combo-export-grid-r1','combo-export-grid-r2','combo-export-final-r1'):
 for case in (W/run).iterdir():
  if not case.is_dir() or case.is_symlink() or case.is_junction() or case.name.endswith('current'):continue
  p=case/'export-audit/exports.jsonl'
  if p.is_file():
   name='prospective-source/export-audits/'+run+'/'+case.name+'/exports.jsonl';out=D/name;out.parent.mkdir(parents=True,exist_ok=True);assert not out.exists();shutil.copyfile(p,out);assert sha(p)==sha(out);copied[name]={'source':str(p),'sha256':sha(p)}
assert len(copied)>=9
meta={'reason':'Supplement original export-completion journals omitted by the runtime ZIP whitelist. Intentionally truncated failure-case journals remain unmodified.','files':copied,'previous_index_sha256':sha(D/'SHA256.json')}
(D/'EXPORT-AUDIT-SUPPLEMENT.json').write_text(json.dumps(meta,indent=2)+'\n');shutil.copyfile(Path(__file__),D/Path(__file__).name)
files={p.relative_to(D).as_posix():sha(p) for p in D.rglob('*') if p.is_file() and p.name!='SHA256.json'};(D/'SHA256.json').write_text(json.dumps(files,indent=2)+'\n');print(json.dumps({'audit_journals':len(copied),'indexed_files':len(files),'total_files':len(files)+1}))
