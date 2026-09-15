from pathlib import Path
import hashlib, os, re, subprocess, time
CDB=Path(r"C:/Program Files (x86)/Windows Kits/10/Debuggers/x64/cdb.exe")
TIMEOUT=20
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def modules(raw): return sorted({m.decode('ascii','ignore').lower() for m in re.findall(rb'(?i)\b[a-z0-9_.-]+\.dll\b',raw)})
def frames(raw): return len(re.findall(rb'(?mi)^\s*[0-9a-f`]+\s+[0-9a-f`]+',raw))
def capture(pid, root, expected, alive):
 if type(pid) is not int or pid<=0 or sha(CDB)!=expected: raise RuntimeError('CDB/pid pin differs')
 root=Path(root); root.mkdir(parents=True,exist_ok=False); sym=root/'empty-symbol-path';sym.mkdir()
 log=root/'cdb.private.stack.log'; out=root/'cdb.private.stdout.bin';err=root/'cdb.private.stderr.bin'
 cmd=[str(CDB),'-pv','-p',str(pid),'-sins','-snul','-y',str(sym),'-noshell','-nosqm','-logo',str(log),'-c','~* k; qd']
 env={k:os.environ[k] for k in ('SystemRoot','WINDIR','COMSPEC','PATH')};env.update(_NT_SYMBOL_PATH='',_NT_ALT_SYMBOL_PATH='',_NT_DEBUGGER_EXTENSION_PATH='')
 started=time.monotonic(); timeout=False
 with out.open('xb') as so,err.open('xb') as se:
  p=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=so,stderr=se,cwd=root,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
  try: code=p.wait(timeout=TIMEOUT)
  except subprocess.TimeoutExpired: timeout=True;p.kill();code=p.wait(timeout=1)
 stdout_raw=out.read_bytes() if out.exists() else b''
 if stdout_raw:
  counted_raw=stdout_raw; frame_source='private_stdout'
 else:
  counted_raw=log.read_bytes() if log.exists() else b''; frame_source='private_log_fallback'
 count=frames(counted_raw); live=alive()
 all_raw=b''.join(x.read_bytes() for x in (log,out,err) if x.exists())
 return {'schema':'grok130-cdb-stack-capture-v2','pid':pid,'exit_code':code,'timed_out':timeout,'elapsed_seconds':time.monotonic()-started,'frame_count':count,'frame_count_source':frame_source,'module_labels':modules(all_raw),'child_alive_after_detach':live,'success_established':not timeout and code==0 and count>0 and live,'brief_suspension_possible':True,'remote_symbol_path_configured':False,'raw_private_files':{x.name:{'bytes':x.stat().st_size if x.exists() else None,'sha256':sha(x) if x.exists() else None} for x in (log,out,err)}}
