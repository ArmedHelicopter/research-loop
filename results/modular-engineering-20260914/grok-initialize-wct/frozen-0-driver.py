"""One unchanged initialize request with bounded numeric OS observations.

No sessions, prompts, account RPC, permissive profile or configuration workaround.
This adds process observations to the existing initialize-only protocol engine.
"""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

HERE=Path(__file__).resolve().parent
WORK=HERE.parent
REPO=WORK.parent/'grok-materials'
ENGINE=WORK/'init-only-driver-r1/driver.py'
EXE=WORK/'grok-cli-1.0.30/grok.exe'
EXE_SHA='ca24ea63272ba7881261f4a52498d1f5bd884b01da25845990422a10dd315266'
sys.path.insert(0,str(REPO))
spec=importlib.util.spec_from_file_location('initialize_engine',ENGINE)
engine=importlib.util.module_from_spec(spec);spec.loader.exec_module(engine)
OriginalTree=engine.ProcessTree
OBSERVER_STATUS={'started':False,'closed':False,'fault':None}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def metadata(path):
    stat=Path(path).stat();return {'bytes':stat.st_size,'mtime_ns':stat.st_mtime_ns}


class ObservedTree(OriginalTree):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        try:
            self.observer_stop=threading.Event()
            self.observer=threading.Thread(target=self.observe,daemon=True)
            self.observer.start()
            OBSERVER_STATUS['started']=True
        except Exception:
            OBSERVER_STATUS['fault']='observer_start_failure'
            try:super().close()
            finally:raise OSError('observer_start_failure')

    def observe(self):
        started=time.monotonic()
        for second in (10,30,50):
            if self.observer_stop.wait(max(0,second-(time.monotonic()-started))):break
            if self.process.poll() is not None:break
            row={'elapsed_seconds':time.monotonic()-started,'native_pid':self.process.pid}
            try:
                child=subprocess.run([sys.executable,str(HERE/'wct_metadata.py'),str(self.process.pid)],
                    stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                    timeout=4,creationflags=subprocess.CREATE_NO_WINDOW,cwd=HERE)
                row['exit_code']=child.returncode
                if child.returncode==0:row['metadata']=json.loads(child.stdout)
                else:row['metadata_error']='observer_nonzero_exit'
            except subprocess.TimeoutExpired:row['metadata_error']='observer_four_second_timeout'
            except (OSError,ValueError):row['metadata_error']='observer_local_error'
            with (HERE/'os-metadata.jsonl').open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(row)+'\n')

    def close(self):
        observer_failed=False
        try:
            self.observer_stop.set()
            self.observer.join(timeout=5)
            observer_failed=self.observer.is_alive()
        except Exception:observer_failed=True
        finally:
            super().close()
        OBSERVER_STATUS['closed']=not observer_failed
        if observer_failed:
            OBSERVER_STATUS['fault']='observer_did_not_close'
            raise OSError('observer_did_not_close')


def run():
    envelope=json.loads((HERE/'frozen-envelope.json').read_bytes())
    expected={'launches_max':1,'timeout_seconds':60,'initialize_writes_max':1,
              'session_new_writes_max':0,'prompt_writes_max':0,'retry':False,
              'os_samples_max':3,'os_sample_timeout_seconds':4}
    if any(envelope.get(k)!=v for k,v in expected.items()):raise RuntimeError('envelope_contract')
    for path,value in envelope['frozen_files'].items():
        if sha(path)!=value:raise RuntimeError('source_or_input_drift')
    if sha(EXE)!=EXE_SHA:raise RuntimeError('native_executable_drift')
    home,profile,cwd=HERE/'home',HERE/'profile',HERE/'cwd'
    if set(p.name for p in home.iterdir())!={'auth.json','config.toml'}:raise RuntimeError('native_home_not_fresh')
    if any(profile.iterdir()) or any(cwd.iterdir()):raise RuntimeError('native_context_not_empty')
    # Reserve one attempt before any native process launch, independently of result.
    with (HERE/'launch-reserved.json').open('x',encoding='utf-8') as stream:
        json.dump({'created_utc':datetime.now(timezone.utc).isoformat(),'envelope_sha256':sha(HERE/'frozen-envelope.json')},stream)
    original_auth=Path('C:/Users/Administrator/.grok/auth.json')
    before={'global':metadata(original_auth),'private':metadata(home/'auth.json')}
    env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','SYSTEMDRIVE',
        'COMSPEC','PATHEXT','PATH','NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE','OS'}}
    env.update({'GROK_HOME':str(home),'USERPROFILE':str(profile),'HOME':str(profile),
        'HOMEDRIVE':profile.drive,'HOMEPATH':str(profile)[len(profile.drive):],
        'APPDATA':str(profile/'AppData/Roaming'),'LOCALAPPDATA':str(profile/'AppData/Local'),
        'TEMP':str(profile/'temp'),'TMP':str(profile/'temp'),'GROK_DISABLE_AUTOUPDATER':'1',
        'GROK_TITLE_REFRESH':'false','GROK_TURN_SUMMARY':'false','GROK_MEMORY':'false',
        'GROK_WORKFLOWS':'false','GROK_SUBAGENTS':'false'})
    for k in ('APPDATA','LOCALAPPDATA','TEMP'):Path(env[k]).mkdir(parents=True,exist_ok=True)
    engine.ProcessTree=ObservedTree
    result=engine.run_once([str(EXE),'--cwd',str(cwd),'agent','stdio'],cwd=cwd,env=env,
        directory=HERE/'private-receipt',frozen_files=envelope['frozen_files'],timeout=60)
    result.update(global_auth_metadata_unchanged=before['global']==metadata(original_auth),
        private_auth_metadata_changed=before['private']!=metadata(home/'auth.json'),
        auth_contents_read_or_hashed=False,observer_max_samples=3,
        observer_status=dict(OBSERVER_STATUS),
        settled_additional_charge_usd=None,model_readiness_verified=False)
    (HERE/'public-closure.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    if sys.argv[1:]!=['--run']:raise SystemExit('explicit once-only run required')
    print(json.dumps(run()))
