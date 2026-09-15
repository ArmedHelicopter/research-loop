import ast
import hashlib
import json
import re
from pathlib import Path
ROOT=Path(__file__).resolve().parent
SOURCE=ROOT.parent/'grok-startup-source-study-r3/acp_agent.rs'
raw=SOURCE.read_bytes()
# Only constant text taken from public source can appear in this output.
messages=set()
for literal in re.findall(r'"(?:[^"\\]|\\.)*"',raw.decode('utf-8')):
    try: text=ast.literal_eval(literal)
    except (ValueError,SyntaxError): continue
    if 10 <= len(text) <= 150 and len(text.split()) >= 2 and '\n' not in text:
        messages.add(text)
files=[]
for p in (ROOT/'native-startup.private.log',ROOT/'home/logs/unified.jsonl'):
    lines=p.read_text(encoding='utf-8',errors='replace').splitlines(); events=[]
    for i,line in enumerate(lines,1):
        for msg in sorted(messages):
            if msg in line:
                ts=re.search(r'\d{4}-\d\d-\d\dT[\d:.]+Z',line)
                events.append({'line':i,'source_constant':msg,'timestamp':ts.group(0) if ts else None})
    files.append({'path':str(p),'matched_events':events,'line_count':len(lines)})
body={'schema':'public-source-constant-phase-match-v1','source':str(SOURCE),
      'source_sha256':hashlib.sha256(raw).hexdigest(),'files':files,
      'binary_source_equivalence_verified':False,'raw_log_values_exposed':False}
(ROOT/'source-bound-phase-summary.json').write_text(json.dumps(body,indent=2)+'\n',encoding='utf-8')
print(json.dumps(body))
