"""Archive a closed parser repair and metadata-only original-stream replay."""
import hashlib,json,shutil,subprocess
from pathlib import Path
TREE=Path('E:/_ryanDev/AI/research-loop-modular/integration');WORK=TREE.parent/'work'
OUT=TREE/'results/modular-engineering-20260913/grok-const-repair'
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_bytes())
def write(path,value):path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=TREE,text=True).strip()
closed=read(WORK/'grok-protocol-r3-closed.json')
assert head==closed['commit'] and closed['source_unchanged'] and closed['exit_code']==0
assert closed['junit']=={'tests':46,'failures':0,'errors':0,'skipped':0}
first=read(WORK/'grok-r5-original-stream-inspection-r1.json');second=read(WORK/'grok-r5-original-stream-inspection-r2.json')
assert first['inspection']['faults']==['runtime_tools_available','invalid_or_mismatched_response']
assert second['inspection']['faults']==['runtime_tools_available']
assert first['inspection']['events_sha256']==second['inspection']['events_sha256']
OUT.mkdir(parents=True,exist_ok=False)
for name in ('grok-r5-original-stream-inspection-r1.json','grok-r5-original-stream-inspection-r2.json',
    'grok-protocol-r3-before.json','grok-protocol-r3-closed.json','grok-protocol-r3.xml',
    'inspect_grok_r5_closed_stream.py'):
    shutil.copyfile(WORK/name,OUT/name)
shutil.copyfile(__file__,OUT/Path(__file__).name)
write(OUT/'FINAL-VERIFICATION.json',{'source_commit':head,'junit':closed['junit'],'source_files':closed['source_count'],
    'source_unchanged':True,'junit_sha256':closed['report_sha256'],'new_generation_calls':0,
    'repair':'Grok-specific primitive const schema support; legacy Codex schema behavior unchanged',
    'first_original_stream_inspection':'tools and unsupported const response contract rejected',
    'repaired_original_stream_inspection':'same original raw bytes; only runtime tools remain rejected',
    'original_reported_tokens':9381,'original_server_accounting_usd':.00644164,
    'private_raw_stream_copied':False,'validation_opened':False,'scientific_effectiveness_proven':False})
write(OUT/'SHA256.json',{p.name:sha(p) for p in OUT.iterdir() if p.is_file()})
print(json.dumps({'files':len(list(OUT.iterdir())),'new_generation_calls':0,'original_stream_accepted':False}))
