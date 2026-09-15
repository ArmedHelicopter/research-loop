from pathlib import Path
import hashlib,json,os,zipfile,shutil
B=Path(r'E:\_ryanDev\AI\research-loop-modular');W=B/'work'; RUN=W/'actual-m4m5-headless-run-r1'; PREP=W/'actual-m4m5-headless-preparation-r1'; PRIV=B/'custody-private/actual-m4m5-headless-r1'; STAGE=W/'actual-m4m5-headless-archive-r1'; RET=B/'retained-private-evidence/actual-m4m5-headless-r1'
def h(p):
 x=hashlib.sha256();
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):x.update(b)
 return x.hexdigest()
def linked(p): return p.is_symlink() or bool(getattr(p.stat(follow_symlinks=False),'st_file_attributes',0)&0x400)
def secret(p):
 n=p.name.lower();return n=='auth.json' or n.endswith('.key') or 'credential' in n or 'secret' in n
def collect(root,label):
 rows=[]; skip=[]
 for cur,ds,fs in os.walk(root,followlinks=False):
  cur=Path(cur); ds[:]=[d for d in ds if not linked(cur/d)]
  if len(ds)!=len([d for d in ds if not linked(cur/d)]):raise RuntimeError('linked directory')
  for n in sorted(fs):
   p=cur/n; rel=Path(label)/p.relative_to(root)
   if linked(p):raise RuntimeError('linked file')
   if secret(rel):skip.append(rel.as_posix());continue
   s=p.stat();rows.append({'source':str(p),'path':rel.as_posix(),'sha256':h(p),'bytes':s.st_size,'mtime_ns':s.st_mtime_ns})
 return rows,skip
def put(p,o):p.write_text(json.dumps(o,indent=2,sort_keys=True)+'\n',encoding='utf8',newline='\n')
def main():
 assert not STAGE.exists() and not RET.exists()
 summary=json.loads((RUN/'summary.json').read_bytes()); attempt=json.loads((RUN/'controller/controller-attempt.json').read_bytes())
 assert summary['solver_reservations']==1 and summary['scored_cells']==0 and summary['evaluator_reservations']==0 and summary['solver_usage_incomplete'] and summary['known_solver_main_tokens']==0
 assert len(attempt['cells'])==8 and attempt['cells'][0]['status']=='failed' and all(x['status']=='blocked' for x in attempt['cells'][1:])
 rows=[];skip=[]
 for root,label in ((RUN,'run'),(PREP,'preparation'),(PRIV,'private')):
  a,b=collect(root,label);rows+=a;skip+=b
 rows.sort(key=lambda x:x['path']);skip.sort();STAGE.mkdir();RET.mkdir(parents=True)
 z=RET/'full-run-preparation-private-without-credentials.zip'
 with zipfile.ZipFile(z,'x',zipfile.ZIP_DEFLATED) as out:
  for r in rows:out.writestr(r['path'],Path(r['source']).read_bytes())
 with zipfile.ZipFile(z) as out:
  assert out.namelist()==[r['path'] for r in rows]
  for r in rows:
   raw=out.read(r['path']);p=Path(r['source']);assert hashlib.sha256(raw).hexdigest()==r['sha256'] and len(raw)==r['bytes'] and h(p)==r['sha256'] and p.stat().st_mtime_ns==r['mtime_ns']
 ret={'schema':'actual-m4m5-headless-retained-private-v1','files':rows,'excluded_credentials':skip,'zip':{'path':str(z),'sha256':h(z),'bytes':z.stat().st_size},'original_bytes_and_mtime_unchanged':True,'links_followed':False}
 put(RET/'retained-manifest.json',ret)
 copies={'summary.json':RUN/'summary.json','parent-closure.json':RUN/'parent-closure.json','controller-attempt.json':RUN/'controller/controller-attempt.json','controller-receipt.json':RUN/'controller/controller-receipt.json','preparation.json':PREP/'preparation.json','controller.json':PREP/'controller.json','solver-spec.json':PREP/'solver-spec.json','material-map.json':W/'actual-m4m5-train-material-map-r1.json','runner-source.py':W/'run_actual_m4m5_headless_r1.py','archive-helper.py':Path(__file__)}
 copied=[]
 for n,s in copies.items():
  d=STAGE/n;shutil.copyfile(s,d);assert s.read_bytes()==d.read_bytes();copied.append({'path':n,'sha256':h(d),'bytes':d.stat().st_size})
 graph={'schema':'actual-m4m5-headless-failure-prefix-graph-v1','nodes':[{'id':'solver-reservation-1','kind':'reservation','actual_main_dispatch':'unknown','known_main_tokens':0},{'id':'cell-1','kind':'planned_cell','status':'failed'},{'id':'cells-2-through-8','kind':'planned_cells','status':'blocked'}],'edges':[{'from':'solver-reservation-1','to':'cell-1','relation':'attempt_recorded_for'},{'from':'cell-1','to':'cells-2-through-8','relation':'usage_incomplete_blocked_following_allocation'}],'nonclaims':['No score or evaluator receipt exists.','No module-effect or valid-all-cell conclusion follows.','No unrecorded consumption edge is asserted.']}
 put(STAGE/'failure-prefix-graph.json',graph);copied.append({'path':'failure-prefix-graph.json','sha256':h(STAGE/'failure-prefix-graph.json'),'bytes':(STAGE/'failure-prefix-graph.json').stat().st_size})
 pub={'schema':'actual-m4m5-headless-archive-v1','summary':{'status':summary['status'],'solver_reservations':1,'actual_main_dispatch':'unknown','known_solver_main_tokens':0,'solver_usage_incomplete':True,'scored_cells':0,'evaluator_reservations':0,'validation_opened':False,'first_failed_cells':1,'blocked_cells':7},'copied_artifacts':copied,'retained_private':{'zip_sha256':h(z),'manifest_sha256':h(RET/'retained-manifest.json'),'file_count':len(rows),'excluded_credential_count':len(skip),'path':str(z)},'self_excluding':True,'limits':['Closed failed run evidence only; no retry.','Zero scores means no module-effect conclusion.','Native replay failed because the CLI response was empty; it is not a valid all-cell result.']}
 put(STAGE/'published-manifest.json',pub)
 assert all(h(STAGE/x['path'])==x['sha256'] for x in copied) and h(z)==pub['retained_private']['zip_sha256'] and h(RET/'retained-manifest.json')==pub['retained_private']['manifest_sha256']
 print(json.dumps({'stage':str(STAGE),'zip':str(z),'published':h(STAGE/'published-manifest.json'),'retained':h(RET/'retained-manifest.json'),'zip_sha256':h(z),'files':len(rows),'excluded':len(skip)}))
if __name__=='__main__':main()
