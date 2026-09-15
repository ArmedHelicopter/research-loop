"""Prepared-only archive builder. Run only after a separate publication decision."""
from __future__ import annotations
import hashlib, json, os, pathlib, shutil, zipfile

BASE=pathlib.Path(r"E:\_ryanDev\AI\research-loop-modular")
WORK=pathlib.Path(r"E:\_ryanDev\AI\research-loop-modular\work")
DIAG=WORK/'actual-m4m5-acp-initialize-diagnostic-r1'
SOURCE_STUDY=WORK/'actual-m4m5-headless-next-diagnostic-r1.md'
ROOT=pathlib.Path(__file__).resolve().parent
STAGE=ROOT/'public-staging'
PRIVATE=BASE/'retained-private-evidence'/'actual-m4m5-acp-initialize-diagnostic-r1'

def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()

def linked(p):
 return p.is_symlink() or bool(getattr(p.stat(follow_symlinks=False),'st_file_attributes',0)&0x400)

def files(root, pruned):
 for current,dirs,names in os.walk(root,followlinks=False):
  current=pathlib.Path(current); kept=[]
  for name in dirs:
   child=current/name
   if linked(child): pruned.append(child.relative_to(root).as_posix())
   else: kept.append(name)
  dirs[:]=kept
  for name in sorted(names):
   p=current/name
   if linked(p): pruned.append(p.relative_to(root).as_posix()); continue
   yield p

def excluded(p): return p.name.lower()=='auth.json' or p.suffix.lower()=='.key'

def manifest(root, pruned):
 out=[]; excluded_names=[]
 for p in files(root, pruned):
  rel=p.relative_to(root).as_posix(); s=p.stat()
  if excluded(p):
   excluded_names.append({'path':rel,'bytes':s.st_size,'mtime_ns':s.st_mtime_ns}); continue
  out.append({'path':rel,'bytes':s.st_size,'mtime_ns':s.st_mtime_ns,'sha256':digest(p)})
 return out,excluded_names

def main():
 if STAGE.exists() or PRIVATE.exists(): raise RuntimeError('refuse reuse of archive output')
 if not DIAG.is_dir() or not SOURCE_STUDY.is_file(): raise RuntimeError('required input missing')
 pruned=[]; before, exclusions=manifest(DIAG, pruned)
 PRIVATE.mkdir(); STAGE.mkdir()
 z=PRIVATE/'diagnostic-private-without-credentials.zip'
 with zipfile.ZipFile(z,'w',zipfile.ZIP_DEFLATED) as a:
  for p in files(DIAG, pruned):
   if not excluded(p): a.write(p, 'diagnostic/'+p.relative_to(DIAG).as_posix())
 # The public stage contains only redacted/public metadata and no private home copies.
 selected=['RESULT.md','receipt.incomplete.json','frozen-prelaunch.json','command.safe.json',
           'source-home-before-after.json','log-event-timeline.safe.json',
           'private-runtime-log-hashes.json','wrapper-receipt-audit-r1.md',
           'wrapper-receipt-audit-r2-correction.md',
           'run_acp_initialize_only.py','salvage_incomplete_receipt.py']
 for name in selected:
  p=DIAG/name
  if p.is_file(): shutil.copy2(p,STAGE/name)
 shutil.copy2(SOURCE_STUDY,STAGE/SOURCE_STUDY.name)
 (STAGE/'README.md').write_text('''# ACP initialize-only diagnostic archive\n\n## Correction controls interpretation\n\n`wrapper-receipt-audit-r2-correction.md` is controlling: the nested native `exec_command` result was dropped because the orchestration emitted only `r.output`. No session id was retained. A yield boundary is not process termination; launch cleanup, exit, timeout, and settlement are unproven.\n\n`RESULT.md` and `receipt.incomplete.json` are preserved historical evidence and contain earlier wrapper-timeout/ended wording. They are explicitly superseded for interpretation by correction r2 and are not rewritten.\n\nThe archive contains no retry. Usage and settlement remain unknown.\n''',encoding='utf8',newline='\n')
 after,_=manifest(DIAG, [])
 if before!=after: raise RuntimeError('diagnostic input changed during archive')
 entries=[]
 with zipfile.ZipFile(z) as a:
  for i in sorted(a.infolist(),key=lambda q:q.filename):
   data=a.read(i.filename); entries.append({'path':i.filename,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
 published=[]
 for p in files(STAGE,[]): published.append({'path':p.relative_to(STAGE).as_posix(),'bytes':p.stat().st_size,'sha256':digest(p)})
 (PRIVATE/'retained-manifest.json').write_text(json.dumps({'source_manifest':before,'credential_exclusions':exclusions,'pruned_links':sorted(set(pruned)),'zip_entries':entries,'zip_sha256':digest(z),'original_unchanged':before==after},indent=2,sort_keys=True),encoding='utf8')
 (STAGE/'published-manifest.json').write_text(json.dumps({'interpretation_control':'wrapper-receipt-audit-r2-correction.md','historical_records_superseded_for_interpretation':['RESULT.md','receipt.incomplete.json'],'published_files':published,'source_study':{'path':str(SOURCE_STUDY),'sha256':digest(SOURCE_STUDY)},'private_zip_sha256':digest(z),'credential_exclusions_count':len(exclusions),'pruned_links':sorted(set(pruned)),'self_excluding':True},indent=2,sort_keys=True),encoding='utf8')
 if not before==after: raise RuntimeError('diagnostic changed during archive')
 if any(excluded(pathlib.Path(n)) for n in zipfile.ZipFile(z).namelist()): raise RuntimeError('credential name in zip')
 print(json.dumps({'stage':str(STAGE),'private_zip':str(z),'published_manifest_sha256':digest(STAGE/'published-manifest.json'),'retained_manifest_sha256':digest(PRIVATE/'retained-manifest.json'),'files':len(before),'excluded_credentials':len(exclusions),'pruned_links':len(set(pruned))}))

if __name__=='__main__': main()
