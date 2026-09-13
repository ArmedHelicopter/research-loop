"""Retain closed protocol checks and named sanitized metadata, never raw ACP."""
import hashlib,json,shutil,subprocess
from pathlib import Path

TREE=Path('E:/_ryanDev/AI/research-loop-modular/integration');WORK=TREE.parent/'work'
SRC=WORK/'grok-subscription-contract-review-r1'
OUT=TREE/'results/modular-engineering-20260913/grok-contract-root'
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path): return json.loads(path.read_bytes())
def write(path,value):path.write_text(json.dumps(value,indent=2,ensure_ascii=True)+'\n',encoding='utf-8')

head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=TREE,text=True).strip()
closed=read(WORK/'grok-protocol-r2-closed.json')
assert head==closed['commit'] and closed['source_unchanged'] and closed['exit_code']==0
assert closed['junit']=={'tests':45,'failures':0,'errors':0,'skipped':0}
OUT.mkdir(parents=True,exist_ok=False);nested=OUT/SRC.name;nested.mkdir()
allowed=('billing-readonly-receipt.json','billing-requests.json','candidate-agent-profile.json',
         'r5-usage-event-sanitized.json','tool-preflight-receipt.json','tool-preflight-requests.json',
         'transport-no-tools.md','windows-empty-argv-verification.json')
source_index=read(SRC/'public-evidence-sha256.json')
for name in allowed:
    assert sha(SRC/name)==source_index[name]
    shutil.copyfile(SRC/name,nested/name)
shutil.copyfile(SRC/'public-evidence-sha256.json',nested/'public-evidence-sha256.json')
review=WORK/'grok-subscription-contract-review-r1.md'
assert sha(review)=='96a4c934f4cc78c6d7e28d7bd548188a638b831ae27f03d2a14678150f71cee8'
shutil.copyfile(review,OUT/review.name)
for prefix in ('grok-protocol-r1','grok-protocol-r2'):
    for suffix in ('-before.json','-closed.json','.xml'):
        path=WORK/(prefix+suffix);shutil.copyfile(path,OUT/path.name)
shutil.copyfile(__file__,OUT/Path(__file__).name)
write(OUT/'FINAL-VERIFICATION.json',{'source_commit':head,'source_files':closed['source_count'],
    'source_unchanged':True,'junit':closed['junit'],'junit_sha256':closed['report_sha256'],
    'actual_generation_calls':0,'native_billing_and_prompt_free_session_setup':True,
    'observed_empty_acp_runtime_inventories':2,'runtime_transport_implemented_here':False,
    'purpose':'headless receipt inspection and native non-generation transport contract evidence',
    'account_snapshot':'unified SuperGrok, onDemandCap0, onDemandUsed0, prepaidBalance0, successful no-topup-rule response',
    'remaining_allowance_percent':None,'per_request_spending_lock_found':False,
    'limitations':['account snapshot must be refreshed before dispatch','no request-level spending lock found',
                  'headless parser audits after dispatch; same-session ACP gate is a separate implementation',
                  'service-reported model accounting does not prove settlement','no calibration or benchmark efficacy'],
    'validation_opened':False,'scientific_effectiveness_proven':False})
write(OUT/'archive-integrity.json',{p.relative_to(OUT).as_posix():{'bytes':p.stat().st_size,'sha256':sha(p)}
    for p in OUT.rglob('*') if p.is_file()})
print(json.dumps({'files':len([p for p in OUT.rglob('*') if p.is_file()]),'new_generation_calls':0,'junit':closed['junit']}))
