"""Run a clean, hash-frozen engineering checkpoint and preserve its closure."""
import hashlib, json, subprocess, sys, time
from pathlib import Path
import xml.etree.ElementTree as ET

root=Path(sys.argv[1]).resolve(); prefix=Path(sys.argv[2]).resolve()
args=sys.argv[3:]
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def state():
    files=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
    return {name:sha(root/name) for name in files if name and Path(name).suffix in ('.py','.md') and not name.startswith('results/')}
def write(path,body): path.write_text(json.dumps(body,ensure_ascii=True,indent=2)+'\n',encoding='utf-8')
assert not subprocess.check_output(['git','status','--porcelain'],cwd=root).strip()
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
before=state(); report=Path(str(prefix)+'.xml'); manifest=Path(str(prefix)+'-before.json')
assert not manifest.exists() and not report.exists() and not prefix.exists()
write(manifest,{'commit':head,'source_before':before,'pytest_args':args,'scope':'synthetic_engineering_only','paid_calls':0})
started=time.monotonic()
run=subprocess.run([sys.executable,'-m','pytest',*args,'--basetemp',str(prefix),'--junitxml',str(report),'-q'],cwd=root)
after=state(); suites=list(ET.parse(report).getroot().iter('testsuite')) if report.exists() else []
body={'commit':head,'source_after':after,'source_unchanged':before==after,'source_count':len(before),
      'exit_code':run.returncode,'wall_seconds':time.monotonic()-started,'new_paid_calls':0,
      'report_sha256':sha(report) if report.exists() else None,
      'junit':{k:sum(int(v.get(k,0)) for v in suites) for k in ('tests','failures','errors','skipped')}}
write(Path(str(prefix)+'-closed.json'),body)
print(json.dumps({k:v for k,v in body.items() if k!='source_after'}))
sys.exit(run.returncode if before==after else 99)
