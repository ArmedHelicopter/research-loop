from pathlib import Path
import hashlib, json, os, shutil, zipfile

BASE=Path(r'E:\_ryanDev\AI\research-loop-modular'); WORK=BASE/'work'
PREFIX=WORK/'headless-lineage-final-gate-root-r1'
STAGE=WORK/'headless-lineage-final-gate-archive-r1'
PRIVATE=BASE/'retained-private-evidence'/'headless-lineage-final-gate-r1'
OUT=PRIVATE/'selected-nonlinked-test-roots-without-credentials.zip'
ROOTS=('test_four_headless_lineage_std0','test_lineage_closure_rereads_t0','test_null_headless_binding_is_0','test_partial_signed_native_clo0','test_per_panel_headless_worker0')

def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def put(p,x):p.write_text(json.dumps(x,indent=2,sort_keys=True)+'\n',encoding='utf8',newline='\n')
def linked(p):return p.is_symlink() or bool(getattr(p.stat(follow_symlinks=False),'st_file_attributes',0)&0x400)
def credential(r):
 n=r.name.lower(); return n=='auth.json' or n.endswith('.key') or 'credential' in n or 'secret' in n or 'authority' in n
def scan(root):
 rows=[]; excluded=[]
 for current,dirs,names in os.walk(root,followlinks=False):
  current=Path(current); kept=[]
  for n in dirs:
   p=current/n
   if linked(p): raise RuntimeError('linked child rejected: '+str(p))
   kept.append(n)
  dirs[:]=kept
  for n in sorted(names):
   p=current/n; rel=p.relative_to(PREFIX)
   if linked(p):raise RuntimeError('linked file rejected: '+str(p))
   s=p.stat()
   if credential(rel):excluded.append({'path':rel.as_posix(),'bytes':s.st_size,'mtime_ns':s.st_mtime_ns});continue
   rows.append({'source':str(p),'path':rel.as_posix(),'bytes':s.st_size,'mtime_ns':s.st_mtime_ns,'sha256':sha(p)})
 return rows,excluded
def main():
 before=json.loads((WORK/'headless-lineage-final-gate-root-r1-before.json').read_bytes())
 closed=json.loads((WORK/'headless-lineage-final-gate-root-r1-closed.json').read_bytes())
 members=json.loads((WORK/'headless-lineage-final-gate-root-r1-source-members.json').read_bytes())
 assert closed['commit']=='8abe622acb2417a5008a66466316663e2885972c' and closed['exit_code']==0 and closed['source_unchanged'] and closed['source_count']==778
 assert closed['junit']=={'tests':20,'failures':0,'errors':0,'skipped':0} and before['source_before']==closed['source_after']
 srczip=WORK/'headless-lineage-final-gate-root-r1-sources.zip'
 assert sha(srczip)==members['archive_sha256']
 with zipfile.ZipFile(srczip) as z:
  assert z.testzip() is None
  assert [(i.filename,i.file_size,hashlib.sha256(z.read(i.filename)).hexdigest()) for i in z.infolist()]==[(x['path'],x['bytes'],x['sha256']) for x in members['members']]
 assert not STAGE.exists() and not PRIVATE.exists()
 assert all((PREFIX/r).is_dir() and not linked(PREFIX/r) for r in ROOTS)
 STAGE.mkdir(); PRIVATE.mkdir(parents=True)
 artifacts={'before.json':WORK/'headless-lineage-final-gate-root-r1-before.json','closed.json':WORK/'headless-lineage-final-gate-root-r1-closed.json','source-members.json':WORK/'headless-lineage-final-gate-root-r1-source-members.json','sources.zip':srczip,'checks.xml':WORK/'headless-lineage-final-gate-root-r1.xml','gate-helper.py':WORK/'run_lineage_final_gate_root_r1.py','useful-check-helper.py':WORK/'run_frozen_useful_checks.py','archive-helper.py':Path(__file__)}
 copied=[]
 for name,p in artifacts.items():
  q=STAGE/name;shutil.copyfile(p,q);assert p.read_bytes()==q.read_bytes();copied.append({'path':name,'bytes':q.stat().st_size,'sha256':sha(q)})
 rows=[];excluded=[];coverage=[]
 for r in ROOTS:
  got,cut=scan(PREFIX/r);rows+=got;excluded+=cut;coverage.append({'root':r,'included_files':len(got),'included_bytes':sum(x['bytes'] for x in got),'excluded_credential_files':len(cut)})
 rows.sort(key=lambda x:x['path']);excluded.sort(key=lambda x:x['path'])
 with zipfile.ZipFile(OUT,'x',zipfile.ZIP_DEFLATED) as z:
  for x in rows:z.writestr(x['path'],Path(x['source']).read_bytes())
 with zipfile.ZipFile(OUT) as z:
  assert z.testzip() is None and z.namelist()==[x['path'] for x in rows]
  for x in rows:
   raw=z.read(x['path']);p=Path(x['source']);assert len(raw)==x['bytes'] and hashlib.sha256(raw).hexdigest()==x['sha256'] and sha(p)==x['sha256'] and p.stat().st_mtime_ns==x['mtime_ns']
 assert not any(credential(Path(n)) for n in zipfile.ZipFile(OUT).namelist())
 retained={'schema':'headless-lineage-final-gate-retained-private-v1','roots':list(ROOTS),'coverage':coverage,'files':rows,'excluded_credentials':excluded,'zip':{'path':str(OUT),'sha256':sha(OUT),'bytes':OUT.stat().st_size},'original_bytes_and_mtime_unchanged':True,'links_followed':False}
 put(PRIVATE/'retained-manifest.json',retained)
 public={'schema':'headless-lineage-final-gate-archive-v1','closed_gate':{'commit':closed['commit'],'junit':closed['junit'],'wall_seconds':closed['wall_seconds'],'source_count':closed['source_count'],'source_unchanged':closed['source_unchanged']},'source_zip_verified':{'sha256':sha(srczip),'members':len(members['members']),'crc_ok':True,'member_hashes_match_manifest':True},'copied_artifacts':copied,'metadata_coverage':coverage,'retained_private':{'path':str(OUT),'sha256':sha(OUT),'manifest_sha256':sha(PRIVATE/'retained-manifest.json'),'roots':list(ROOTS),'file_count':len(rows),'excluded_credential_count':len(excluded),'links_followed':False},'limits':['Closed synthetic engineering lineage gate; passing tests are execution evidence only.','No model, API, Docker, VAL, or ground-truth execution in this archive step.','Credential/authority files were excluded from retained raw copies.'],'self_excluding':True}
 put(STAGE/'published-manifest.json',public)
 m=json.loads((STAGE/'published-manifest.json').read_bytes());assert sha(OUT)==m['retained_private']['sha256'] and sha(PRIVATE/'retained-manifest.json')==m['retained_private']['manifest_sha256']
 assert all(sha(Path(x['source']))==x['sha256'] and Path(x['source']).stat().st_mtime_ns==x['mtime_ns'] for x in rows)
 print(json.dumps({'stage':str(STAGE),'private_zip':str(OUT),'published_manifest_sha256':sha(STAGE/'published-manifest.json'),'retained_manifest_sha256':sha(PRIVATE/'retained-manifest.json'),'roots':len(ROOTS),'files':len(rows),'excluded_credentials':len(excluded),'coverage':coverage}))
if __name__=='__main__':main()
