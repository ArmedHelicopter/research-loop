from pathlib import Path
import hashlib,json,subprocess,tarfile,zipfile,io
B=Path('E:/_ryanDev/AI/research-loop-modular');R=B/'integration';A=R/'results/modular-engineering-20260913'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();groups={};members_total=0;files_total=0;zip_total=0
for name in ('admission-calibration-prospective-source','q32-prospective-execution','diagnostic-private-http','exploration-scheduler-combination','m6-public-input'):
 d=A/name;files={p.relative_to(R).as_posix():sha(p) for p in d.rglob('*') if p.is_file()};prefix=d.relative_to(R).as_posix()
 raw=subprocess.check_output(['git','archive','HEAD',prefix],cwd=R)
 with tarfile.open(fileobj=io.BytesIO(raw)) as tar:committed={m.name:hashlib.sha256(tar.extractfile(m).read()).hexdigest() for m in tar if m.isfile()}
 assert committed==files,name
 if (d/'SHA256.json').exists():index=json.loads((d/'SHA256.json').read_text())
 elif (d/'artifact-sha256.json').exists():index=json.loads((d/'artifact-sha256.json').read_text())
 else:index=json.loads((d/'ARTIFACT-MANIFEST.json').read_text())['files']
 assert all(sha(d/n)==h for n,h in index.items()),name
 count=0;zip_count=0
 for zpath in d.rglob('*.zip'):
  candidates=[zpath.with_suffix('.members.json'),zpath.with_name(zpath.stem+'-members.json'),zpath.with_name(zpath.stem.replace('-actual-artifacts','-archive-members')+'.json')]
  candidates=[p for p in candidates if p.is_file()];assert len(set(candidates))==1,str(zpath);manifest=json.loads(candidates[0].read_text());expected={n:(v if isinstance(v,str) else v['sha256']) for n,v in manifest.items()}
  with zipfile.ZipFile(zpath) as z:
   assert len(z.namelist())==len(set(z.namelist()))
   actual={i.filename:hashlib.sha256(z.read(i)).hexdigest() for i in z.infolist()};assert actual==expected,str(zpath)
  count+=len(expected);zip_count+=1
 groups[name]={'files':len(files),'zip_files':zip_count,'zip_members':count};files_total+=len(files);members_total+=count;zip_total+=zip_count
assert not subprocess.check_output(['git','diff','dd8f3bf','HEAD','--','results/modular-engineering-20260912'],cwd=R)
value={'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip(),'groups':groups,'verified_disk_and_git_files':files_total,'verified_zips':zip_total,'verified_members':members_total,'prior_1981_file_archive_commit_unchanged':True}
out=B/'work/admission-q32-es-http-archive-root-verification-r1.json';assert not out.exists();out.write_text(json.dumps(value,indent=2)+'\n');print(json.dumps(value))
