"""Preserve merged C2/C3 wiring checks and the failed initial test selection."""
import hashlib,json,shutil,subprocess,zipfile
from pathlib import Path
TREE=Path('E:/_ryanDev/AI/research-loop-modular/integration')
WORK=TREE.parent/'work'
OUT=TREE/'results/modular-engineering-20260914/remaining-combinations-root'
sha=lambda raw:hashlib.sha256(raw).hexdigest()
def write(path,value):
    path.write_bytes((json.dumps(value,indent=2)+'\n').encode())
def permitted(path,base):
    parts=path.relative_to(base).parts
    if not path.is_file() or any(p.is_symlink() or p.is_junction() for p in (path,*path.parents) if p.is_relative_to(base)): return False
    if 'private-scorer-store' in parts or '.codex' in parts or path.suffix=='.key' or path.name.startswith('server-'): return False
    if path.suffix not in {'.json','.jsonl','.py','.csv','.txt'}: return False
    if path.name in {'plan.json','candidate-barrier.json','build-provider-ledger.json','target-provider-ledger.json',
                    'frozen-config.json','controller-attempt.json','controller-receipt.json','public.csv','source-verification.json',
                    'counterexample.json','original-source.json','original-trace.jsonl','forged-source.json','forged-trace.jsonl',
                    'original-build-receipt.json','forged-build-receipt.json'}: return True
    if path.name.startswith(('worker-','client-','replay-','cost-')) and path.suffix in {'.json','.jsonl'}: return True
    if set(parts)&{'export','prepared','runtime','history','model','builds','targets','context-audit'}: return True
    return ('run' in parts and path.name=='controller.jsonl' or path.name=='reviewed-policy.json'
            or 'export-audit' in parts and path.name=='exports.jsonl')

head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=TREE,text=True).strip()
assert not subprocess.check_output(['git','status','--porcelain'],cwd=TREE).strip()
checks={}
for i in (1,2):
    prefix=f'remaining-combinations-integrated-r{i}'
    closed=json.loads((WORK/(prefix+'-closed.json')).read_bytes())
    assert closed['source_unchanged'] and closed['new_paid_calls']==0 and closed['commit']==head
    if i==1: assert closed['exit_code']==4 and closed['junit']['tests']==0
    else: assert closed['exit_code']==0 and closed['junit']['tests']>0 and all(closed['junit'][k]==0 for k in ('failures','errors','skipped'))
    checks[prefix]={k:v for k,v in closed.items() if k!='source_after'}
OUT.mkdir(parents=True,exist_ok=False)
(OUT/'.gitattributes').write_bytes(b'* -text\n')
for prefix in checks:
    for suffix in ('-before.json','-closed.json','.xml'):
        shutil.copyfile(WORK/(prefix+suffix),OUT/(prefix+suffix))
for name in ('execution-improvement-integrated-archive-root-r1.json','triple369-integrated-archive-root-r1.json','m9-known-cost-committed-archive-r2.json'):
    shutil.copyfile(WORK/name,OUT/name)
base=WORK/'remaining-combinations-integrated-r2'
rows=[];denominators={};excluded=[]
with zipfile.ZipFile(OUT/'original-synthetic-evidence.zip','x',zipfile.ZIP_DEFLATED) as z:
    for path in sorted(base.rglob('*')):
        if not path.is_file():continue
        relative=path.relative_to(base).as_posix()
        if not permitted(path,base):excluded.append(relative);continue
        raw=path.read_bytes()
        assert all(marker not in raw for marker in (b'PRIVATE-REFERENCE-SENTINEL',b'PRIVATE_TASK_ANSWER_DYNAMIC_KEY_MUST_NOT_ESCAPE')),relative
        z.writestr(relative,raw);rows.append({'path':relative,'sha256':sha(raw),'bytes':len(raw)})
        if path.name=='controller-receipt.json':
            body=json.loads(raw)
            denominators[relative]={k:v for k,v in body.items() if k not in {'contrasts','arm_recipe_bindings'}}
with zipfile.ZipFile(OUT/'original-synthetic-evidence.zip') as z:
    assert len(z.namelist())==len(rows) and all(sha(z.read(r['path']))==r['sha256'] for r in rows)
write(OUT/'checks.json',checks)
write(OUT/'archive-members.json',{'original-synthetic-evidence':rows})
write(OUT/'denominators.json',denominators)
write(OUT/'excluded-paths.json',excluded)
shutil.copyfile(__file__,OUT/'archive_evidence.py')
(OUT/'README.md').write_bytes(('''# Remaining pair and triple integration

The merged source runs the complete M3/M6/M9 sixteen-cell grid and the M7/M9,
M8/M9 and M7/M8/M9 thirty-two-cell grid through restricted Docker and independent
scorer processes. Older state/mechanism M9 grids, original known-cost replay
regressions and label isolation also run at the same source pin. The exact
test count, source hash freeze and runtime denominators are in the indexed
closures and original evidence.

The initial selection failed before collecting tests because it named a missing
label test file. Its zero-test closure is retained; the corrected selection ran
at the identical source commit. No acceptance thresholds or production rules
were changed to address that selection error.

Scorer families keep distinct explicit schemas, panel types and candidate
provenance. The integrated check exercises cross-family rejection in both
serialization and parsing, frozen factorial components, history-only candidate
sharing and the known-source-cost stop rule at build and target replay.

All 36 requested pair controllers and five required triple controllers now have
source and root engineering coverage, accumulated over their recorded
checkpoints. This is not one fresh run of every historical case. The controllers
retain dependency-constrained and structurally unavailable arms; controller
coverage does not imply every factorial effect is identifiable. These checks
establish implementation wiring, not real benchmark effect, calibration,
scientific validity, full/LOO completion or independent validation acceptance.
No actual model generation or validation access occurred in this checkpoint.
''').encode())
write(OUT/'archive-integrity.json',{p.relative_to(OUT).as_posix():{'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for p in OUT.rglob('*') if p.is_file()})
print(json.dumps({'source':head,'files':len(list(OUT.iterdir())),'zip_members':len(rows),'checks':checks}))
