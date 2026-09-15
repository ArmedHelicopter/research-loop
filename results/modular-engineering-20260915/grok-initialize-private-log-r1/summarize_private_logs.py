"""Never emit raw log text: count fixed messages and safe Rust subsystem labels."""
import collections
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ALLOWED = ('agent initialized','auth update enrichment done','model catalog: fetch succeeded',
    'model catalog: retry succeeded','model catalog: notifying clients',
    'auth: initialize() refreshed auth state from disk',
    'auth: initialize() built auth_methods for ACP response',
    'session created','slash.advertise','acp_initialize','auth method selection',
    'auto worktree gc and session search deferred until remote_settings arrive',
    'chat_modes','model_state','remote_settings','initialize response',
    'startup complete','initialize completed')
out = {'schema':'private-startup-log-allowlist-v1','files':[],'raw_text_published':False}
for path in [ROOT/'native-startup.private.log',ROOT/'home/logs/unified.jsonl']:
    if not path.exists(): continue
    raw = path.read_bytes(); lines = raw.decode('utf-8',errors='replace').splitlines()
    phases=[]; subsystems=collections.Counter(); json_keys=collections.Counter()
    for number,line in enumerate(lines,1):
        ts=re.search(r'\d{4}-\d\d-\d\dT[\d:.]+Z',line)
        timestamp=ts.group(0) if ts else None
        for message in ALLOWED:
            if message in line: phases.append({'line':number,'timestamp':timestamp,'message':message})
        # Rust targets only; arbitrary text/account values are excluded.
        for target in re.findall(r'\b(?:xai_grok|grok|agent_client_protocol)(?:::[a-z_][a-z0-9_]*)+\b',line):
            subsystems[target]+=1
        try:
            item=json.loads(line)
            if isinstance(item,dict):
                for key in item:
                    if key in ('msg','src','ts','lvl','ver','message','timestamp','level','target','fields'):
                        json_keys[key]+=1
        except ValueError: pass
    out['files'].append({'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),
        'bytes':len(raw),'mtime_ns':path.stat().st_mtime_ns,'lines':len(lines),
        'phases':phases,'rust_subsystem_counts':dict(subsystems),'recognized_json_field_counts':dict(json_keys)})
(ROOT/'allowlisted-log-summary.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8')
print(json.dumps(out))
