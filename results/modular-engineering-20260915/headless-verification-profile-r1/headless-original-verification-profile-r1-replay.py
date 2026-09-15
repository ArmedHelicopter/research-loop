from __future__ import annotations
import cProfile, hashlib, json, pstats, time
from pathlib import Path
from types import SimpleNamespace
SOURCE=Path(r"E:\_ryanDev\AI\research-loop-modular\headless-lineage-complete-r5")
ORIGINAL=Path(r"E:\_ryanDev\AI\research-loop-modular\work\headless-lineage-controller-full5\test_native_v4_headless_lineag0")
OUT=Path(r"E:\_ryanDev\AI\research-loop-modular\work\headless-original-verification-profile-r1-replay")
for suffix in ('.input-before.json','.input-after.json','.summary.json','.pstats'):
    if Path(str(OUT)+suffix).exists(): raise SystemExit('refusing to overwrite profile output')
def sha(raw): return hashlib.sha256(raw).hexdigest()
def snap(root):
 rows=[]
 for path in sorted(p for p in root.rglob('*') if p.is_file()):
  st=path.stat();rows.append({'path':str(path.relative_to(root)).replace('\\','/'),'bytes':st.st_size,'mtime_ns':st.st_mtime_ns,'sha256':sha(path.read_bytes())})
 return {'schema':'headless-original-verification-input-v1','root':str(root),'file_count':len(rows),'total_bytes':sum(r['bytes'] for r in rows),'files':rows}
def write(path,value):
 raw=json.dumps(value,sort_keys=True,separators=(',',':')).encode()
 with path.open('xb') as out:out.write(raw)
def main():
 before=snap(ORIGINAL);write(Path(str(OUT)+'.input-before.json'),before)
 import sys
 sys.path.insert(0,str(SOURCE))
 from research_loop.modular.contracts import FrozenRecord
 from research_loop.modular.grok_headless_train_solver import replay_headless_train_ledger
 import research_loop.modular.grok_headless_transport as transport
 lp=ORIGINAL/'solver'/'ledger'/'ledger.json'; ledger=json.loads(lp.read_bytes()); cfg=ledger['config']
 # Exact test-fixture deployment pin, applied only to this verifier process; no transport is called.
 transport.EXECUTABLE_SHA256=sha(Path(cfg['executable']).read_bytes())
 port=SimpleNamespace(executable=cfg['executable'],root=lp.parent,private_home=Path(cfg['private_home']),private_profile=Path(cfg['private_profile_root']),public_cwd=Path(cfg['public_cwd_root']),frozen_files=cfg['frozen_files'],max_calls=cfg['max_calls'],schemas=cfg['schemas'],slot_output_caps=cfg['slot_output_caps'],slot_input_byte_caps=cfg['slot_input_byte_caps'],observed_main_token_cap=cfg['observed_main_token_cap'],account_read_recovery=cfg['account_read_recovery'],model=cfg['model'],effort=cfg['reasoning_effort'],provider_kind=cfg['provider_kind'],calls_root=lp.parent/'calls',ledger_path=lp,ledger=ledger,_config_record=FrozenRecord.from_dict(cfg))
 prof=cProfile.Profile();started=time.perf_counter();prof.enable();replay_headless_train_ledger(port,preserve_failure=True);prof.disable();elapsed=time.perf_counter()-started;prof.dump_stats(str(Path(str(OUT)+'.pstats')))
 after=snap(ORIGINAL);write(Path(str(OUT)+'.input-after.json'),after)
 if before!=after:raise SystemExit('original inputs changed during read-only replay')
 stats=pstats.Stats(prof).strip_dirs(); rows=[]
 for fn,stat in stats.stats.items():
  cc,nc,tt,ct,_=stat;file,line,name=fn
  if 'research_loop' in file or name in {'_verify_headless_request_binding','_reread_process','_reread_recovered_account','_reread_account','_verify_row','_replay_headless_native_call','_sources'}:rows.append({'function':f'{file}:{line}:{name}','primitive_calls':cc,'total_calls':nc,'self_seconds':tt,'cumulative_seconds':ct})
 rows.sort(key=lambda v:v['cumulative_seconds'],reverse=True)
 write(Path(str(OUT)+'.summary.json'),{'schema':'headless-original-verification-profile-r1','status':'completed','source_commit':'0a9ca90abfb16ded9a6d5f312739a56cf18e7bb9','entrypoint':'replay_headless_train_ledger(preserve_failure=True)','adapter':'SimpleNamespace from persisted ledger config; no provider/allocator constructor','fixture_executable_pin':'in-process test-fixture constant only','transport_dispatched':False,'elapsed_seconds':elapsed,'replayed_calls':len(ledger['calls']),'originals_unchanged':True,'input_before_sha256':sha(Path(str(OUT)+'.input-before.json').read_bytes()),'input_after_sha256':sha(Path(str(OUT)+'.input-after.json').read_bytes()),'top_own_functions':rows[:40],'note':'Every replay rereads persisted originals and frozen sources. It is not a C5 duration estimate.'})
if __name__=='__main__':main()
