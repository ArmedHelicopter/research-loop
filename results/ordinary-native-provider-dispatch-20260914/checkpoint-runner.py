import hashlib,json,os,subprocess,sys,time,zipfile
from pathlib import Path
repo=Path(sys.argv[1]);out=Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=False)
env=dict(os.environ);env['TEMP']=env['TMP']=str(out/'temp');Path(env['TEMP']).mkdir()
env['PYTHONDONTWRITEBYTECODE']='1'
def git(*args):return subprocess.check_output(['git','-C',str(repo),*args]).decode().strip()
assert not git('status','--porcelain'), 'source not clean'
files=[p for p in git('ls-files').splitlines() if not p.startswith(('results/','data/'))]
def hashes():return {p:hashlib.sha256((repo/p).read_bytes()).hexdigest() for p in files if (repo/p).is_file()}
before=hashes();(out/'source-before.json').write_text(json.dumps(before,indent=2))
with zipfile.ZipFile(out/'exact-tested-source.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for path,expected in before.items():
        raw=(repo/path).read_bytes();assert hashlib.sha256(raw).hexdigest()==expected
        archive.writestr(path,raw)
cmd=[sys.executable,'-m','pytest','-q',*sys.argv[3:],'--basetemp',str(out/'pytest'),'-o','cache_dir='+str(out/'cache'),'--junitxml',str(out/'pytest.xml')]
start=time.time()
with (out/'pytest.stdout.txt').open('wb') as log:result=subprocess.run(cmd,cwd=repo,env=env,stdout=log,stderr=subprocess.STDOUT)
after=hashes();(out/'source-after.json').write_text(json.dumps(after,indent=2))
report={'source_commit':git('rev-parse','HEAD'),'command':cmd,'exit_code':result.returncode,'seconds':time.time()-start,'source_hash_count':len(before),'source_unchanged':before==after,'clean_status':git('status','--porcelain'),'real_model_or_api_calls':0,'scope':'synthetic ordinary TRAIN provider engineering; no scientific validation'}
(out/'check.json').write_text(json.dumps(report,indent=2));print(json.dumps(report));sys.exit(result.returncode)
