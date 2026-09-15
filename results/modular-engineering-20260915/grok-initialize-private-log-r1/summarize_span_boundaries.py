import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parent
rows=[]
for number,line in enumerate((ROOT/'native-startup.private.log').read_text(encoding='utf-8').splitlines(),1):
    line=re.sub(r'\x1b\[[0-9;]*m','',line)
    spans=re.findall(r'\b(?:xai_grok[a-z0-9_]*|grok[a-z0-9_]*)(?:::[a-z_][a-z0-9_]*)+\b',line)
    phases=[p for p in ('model_state','acp_initialize') if p in line]
    if phases or spans:
        end=re.search(r': (new|enter|entered|exit|exited|close|closed)(?:\s.*)?$',line)
        rows.append({'line':number,'phases':phases,'rust_targets':spans,
            'terminal_span_event':end.group(1) if end else None})
body={'schema':'fixed-span-boundary-summary-v1','events':rows,'raw_log_values_exposed':False}
(ROOT/'span-boundary-summary.json').write_text(json.dumps(body,indent=2)+'\n',encoding='utf-8')
print(json.dumps(body))
