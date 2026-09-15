from __future__ import annotations
import cProfile, hashlib, json, os, pstats, time
from pathlib import Path
from types import SimpleNamespace

SOURCE=Path(r"E:\_ryanDev\AI\research-loop-modular\headless-lineage-complete-r5")
ORIGINAL=Path(r"E:\_ryanDev\AI\research-loop-modular\work\headless-lineage-controller-full5\test_native_v4_headless_lineag0")
OUT=Path(r"E:\_ryanDev\AI\research-loop-modular\work\headless-original-verification-profile-r1")
for suffix in ('.input-before.json','.input-after.json','.summary.json','.pstats'):
    if Path(str(OUT)+suffix).exists(): raise SystemExit('refusing to overwrite profile output')

def digest(raw: bytes) -> str: return hashlib.sha256(raw).hexdigest()
def snap(root: Path):
    rows=[]
    for path in sorted(p for p in root.rglob('*') if p.is_file()):
        stat=path.stat()
        rows.append({'path':str(path.relative_to(root)).replace('\\','/'),'bytes':stat.st_size,
                     'mtime_ns':stat.st_mtime_ns,'sha256':digest(path.read_bytes())})
    return {'schema':'headless-original-verification-input-v1','root':str(root),
            'file_count':len(rows),'total_bytes':sum(r['bytes'] for r in rows),'files':rows}
def write_new(path: Path, value):
    raw=json.dumps(value,sort_keys=True,separators=(',',':')).encode()
    with path.open('xb') as out: out.write(raw)

def main():
    before=snap(ORIGINAL); write_new(Path(str(OUT)+'.input-before.json'),before)
    sys_path_added=False
    import sys
    if str(SOURCE) not in sys.path: sys.path.insert(0,str(SOURCE));sys_path_added=True
    from research_loop.modular.contracts import FrozenRecord
    from research_loop.modular.grok_headless_train_solver import replay_headless_train_ledger
    ledger_path=ORIGINAL/'solver'/'ledger'/'ledger.json'
    ledger=json.loads(ledger_path.read_bytes()); config=ledger['config']
    port=SimpleNamespace(executable=config['executable'],root=ledger_path.parent,private_home=Path(config['private_home']),
        private_profile=Path(config['private_profile_root']),public_cwd=Path(config['public_cwd_root']),
        frozen_files=config['frozen_files'],max_calls=config['max_calls'],schemas=config['schemas'],
        slot_output_caps=config['slot_output_caps'],slot_input_byte_caps=config['slot_input_byte_caps'],
        observed_main_token_cap=config['observed_main_token_cap'],account_read_recovery=config['account_read_recovery'],
        model=config['model'],effort=config['reasoning_effort'],provider_kind=config['provider_kind'],
        calls_root=ledger_path.parent/'calls',ledger_path=ledger_path,ledger=ledger,
        _config_record=FrozenRecord.from_dict(config))
    started=time.perf_counter(); profile=cProfile.Profile(); profile.enable()
    replay_headless_train_ledger(port,preserve_failure=True)
    profile.disable(); elapsed=time.perf_counter()-started
    pstats_path=Path(str(OUT)+'.pstats'); profile.dump_stats(str(pstats_path))
    stats=pstats.Stats(profile).strip_dirs().sort_stats('cumulative')
    top=[]
    for func,stat in list(stats.stats.items()):
        cc,nc,tt,ct,callers=stat
        filename,line,name=func
        if 'research_loop' in filename or name in {'_verify_headless_request_binding','_reread_process','_reread_recovered_account','_reread_account','_verify_row','_replay_headless_native_call','_sources'}:
            top.append({'function':f'{filename}:{line}:{name}','primitive_calls':cc,'total_calls':nc,'self_seconds':tt,'cumulative_seconds':ct})
    top.sort(key=lambda x:x['cumulative_seconds'],reverse=True)
    after=snap(ORIGINAL); write_new(Path(str(OUT)+'.input-after.json'),after)
    if before!=after: raise SystemExit('original inputs changed during read-only replay')
    write_new(Path(str(OUT)+'.summary.json'),{'schema':'headless-original-verification-profile-r1','status':'completed',
        'source_commit':'0a9ca90abfb16ded9a6d5f312739a56cf18e7bb9','entrypoint':'replay_headless_train_ledger(preserve_failure=True)',
        'adapter':'SimpleNamespace populated from immutable ledger config; no provider/allocator constructor',
        'transport_dispatched':False,'elapsed_seconds':elapsed,'replayed_calls':len(ledger['calls']),
        'originals_unchanged':True,'input_before_sha256':digest(Path(str(OUT)+'.input-before.json').read_bytes()),
        'input_after_sha256':digest(Path(str(OUT)+'.input-after.json').read_bytes()),'top_own_functions':top[:40],
        'note':'Each replay rerereads persisted original files and frozen sources. This profile is not a C5 runtime duration estimate.'})
if __name__=='__main__': main()
