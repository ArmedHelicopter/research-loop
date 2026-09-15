"""Finalize metadata for the already-consumed diagnostic; never launches a process."""
from __future__ import annotations
import datetime, hashlib, json, pathlib

ROOT = pathlib.Path(__file__).resolve().parent
SOURCE = pathlib.Path(r"E:\_ryanDev\AI\research-loop-modular\work\actual-m4m5-headless-run-r1\solver-model\calls\0001-m4_plan\native-home")
INPUT = ROOT / "private-input-home-opaque"
RUNTIME = ROOT / "private-runtime-home"

def h(p):
    x=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''): x.update(b)
    return x.hexdigest()

def noncred(root):
    out=[]; excluded=[]
    for p in sorted(root.rglob('*'), key=lambda q:q.as_posix()):
        if p.is_symlink(): raise RuntimeError('unexpected symlink '+str(p))
        if not p.is_file(): continue
        s=p.stat(); e={'path':p.relative_to(root).as_posix(),'bytes':s.st_size,'mtime_ns':s.st_mtime_ns}
        if p.name.lower()=='auth.json' or p.suffix.lower()=='.key': excluded.append(e)
        else: e['sha256']=h(p); out.append(e)
    return out,excluded

def main():
    freeze=json.loads((ROOT/'frozen-prelaunch.json').read_text(encoding='utf8'))
    source_files,source_excluded=noncred(SOURCE)
    input_files,input_excluded=noncred(INPUT)
    log=RUNTIME/'logs'/'unified.jsonl'
    events=[]
    cutoff=datetime.datetime.fromtimestamp(freeze['created_at_epoch'], tz=datetime.timezone.utc)
    if log.exists():
        for line in log.read_text(encoding='utf8', errors='replace').splitlines():
            try: x=json.loads(line)
            except json.JSONDecodeError: continue
            # Safe public projection: no context values, raw log remains private.
            ts=x.get('ts')
            try: include=datetime.datetime.fromisoformat(ts.replace('Z','+00:00')) >= cutoff
            except Exception: include=False
            if include: events.append({'ts':ts,'msg':x.get('msg')})
    (ROOT/'private-runtime-log-hashes.json').write_text(json.dumps({
        'unified_jsonl': {'exists':log.exists(),'bytes':log.stat().st_size if log.exists() else None,'sha256':h(log) if log.exists() else None}
    },indent=2,sort_keys=True),encoding='utf8')
    (ROOT/'log-event-timeline.safe.json').write_text(json.dumps(events,indent=2,sort_keys=True),encoding='utf8')
    receipt={
      'kind':'acp_initialize_only',
      'launch_count':1,
      'launch_receipt_completeness':'incomplete_wrapper_timeout',
      'documented_entrypoint':freeze['documented_entrypoint'],
      'deadline_seconds':freeze['deadline_seconds'],
      'sent_methods':['initialize'],
      'request_count':1,
      'session_new_sent':False,'prompt_sent':False,'model_selected':False,'evaluator_called':False,
      'process_exit_code':'unknown','process_pid':'unrecorded','timed_out':'not conclusively recorded',
      'owned_tree_status':'no grok process observed after wrapper return',
      'usage':'unknown','settlement':'unknown',
      'stdio_raw_capture':'unavailable because the outer wrapper ended before helper receipt finalization',
      'source_noncredential_bytes_and_mtimes_unchanged_vs_frozen_input':source_files==input_files,
      'credential_values_parsed_or_emitted':False,
      'credential_named_exclusion_count':len(source_excluded),
      'runtime_log_hash_file':'private-runtime-log-hashes.json',
    }
    (ROOT/'receipt.incomplete.json').write_text(json.dumps(receipt,indent=2,sort_keys=True),encoding='utf8')
    (ROOT/'source-home-before-after.json').write_text(json.dumps({
      'source_noncredential_files_now':source_files,
      'opaque_input_noncredential_files_now':input_files,
      'source_equals_opaque_input_noncredential':source_files==input_files,
      'source_credential_named_exclusions':source_excluded,
      'opaque_input_credential_named_exclusions':input_excluded,
    },indent=2,sort_keys=True),encoding='utf8')

if __name__=='__main__': main()
