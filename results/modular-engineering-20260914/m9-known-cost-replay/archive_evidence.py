"""Preserve original M9 replay failures and the separately frozen repair run."""
import hashlib, json, shutil, subprocess, zipfile
from pathlib import Path

TREE = Path('E:/_ryanDev/AI/research-loop-modular/m9-replay')
WORK = TREE.parent / 'work'
OUT = TREE / 'results/modular-engineering-20260914/m9-known-cost-replay'
HEAD = '5f4d12ad771eca23d3a5316eeb9ede51c9c7c5aa'
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=TREE,text=True).strip() == HEAD
assert not subprocess.check_output(['git','status','--porcelain'],cwd=TREE).strip()
sha = lambda raw: hashlib.sha256(raw).hexdigest()
def write(path, value):
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')
def permitted(path, base):
    parts = path.relative_to(base).parts
    if not path.is_file() or any(p.is_symlink() or p.is_junction() for p in (path,*path.parents) if p.is_relative_to(base)):
        return False
    if 'private-scorer-store' in parts or '.codex' in parts or path.suffix == '.key' or path.name.startswith('server-'):
        return False
    if path.suffix not in {'.json','.jsonl','.py','.csv','.txt'}:
        return False
    if path.name in {'plan.json','candidate-barrier.json','build-provider-ledger.json','target-provider-ledger.json',
                    'frozen-config.json','controller-attempt.json','controller-receipt.json','public.csv','source-verification.json',
                    'counterexample.json','original-source.json','original-trace.jsonl','forged-source.json','forged-trace.jsonl',
                    'original-build-receipt.json','forged-build-receipt.json'}:
        return True
    if path.name.startswith(('worker-','client-','replay-')) and path.suffix in {'.json','.jsonl'}:
        return True
    if set(parts) & {'export','prepared','runtime','history','model','builds','targets','context-audit'}:
        return True
    if 'run' in parts and path.name == 'controller.jsonl':
        return True
    if path.name == 'reviewed-policy.json' or 'export-audit' in parts and path.name == 'exports.jsonl':
        return True
    return False

closures = {}
for phase, tests, failures in [('red',9,9),('green',22,0)]:
    prefix = f'm9-known-cost-{phase}-r1'
    closed = json.loads((WORK / (prefix+'-closed.json')).read_bytes())
    assert closed['source_unchanged'] and closed['new_paid_calls'] == 0
    assert closed['junit'] == {'tests':tests,'failures':failures,'errors':0,'skipped':0}
    if phase == 'green': assert closed['commit'] == HEAD and closed['exit_code'] == 0
    closures[prefix] = {k:v for k,v in closed.items() if k != 'source_after'}
OUT.mkdir(parents=True,exist_ok=False)
members, proofs, denominators, excluded = {}, {}, {}, {}
for prefix in closures:
    for suffix in ('-before.json','-closed.json','.xml'):
        shutil.copyfile(WORK/(prefix+suffix), OUT/(prefix+suffix))
    base = WORK / prefix
    rows, proof_rows, excluded_rows = [], [], []
    with zipfile.ZipFile(OUT/(prefix+'.zip'),'x',zipfile.ZIP_DEFLATED) as z:
        for path in sorted(base.rglob('*')):
            if not path.is_file(): continue
            relative = path.relative_to(base).as_posix()
            if not permitted(path,base):
                excluded_rows.append(relative)
                continue
            raw = path.read_bytes()
            assert all(marker not in raw for marker in (b'PRIVATE-REFERENCE-SENTINEL',b'PRIVATE_TASK_ANSWER_DYNAMIC_KEY_MUST_NOT_ESCAPE')), relative
            z.writestr(relative,raw)
            rows.append({'path':relative,'bytes':len(raw),'sha256':sha(raw)})
            if path.name == 'counterexample.json':
                proof = json.loads(raw)
                assert proof['original_verified'] and proof['generic_verified']
                assert proof['family_rejected'] == ('green' in prefix)
                assert all(proof[k] == 0 for k in ['new_model_calls_during_replay','new_source_calls_during_replay','new_docker_calls_during_replay'])
                proof_rows.append({'path':relative,**proof})
            if path.name == 'controller-receipt.json':
                body = json.loads(raw)
                denominators[prefix+'/'+relative] = {k:v for k,v in body.items() if k not in {'contrasts','arm_recipe_bindings'}}
    assert len(proof_rows) == 9
    with zipfile.ZipFile(OUT/(prefix+'.zip')) as z:
        assert len(z.namelist()) == len(rows)
        assert all(sha(z.read(row['path'])) == row['sha256'] for row in rows)
    members[prefix], proofs[prefix], excluded[prefix] = rows, proof_rows, excluded_rows
write(OUT/'checks.json',closures)
write(OUT/'archive-members.json',members)
write(OUT/'replay-proofs.json',proofs)
write(OUT/'denominators.json',denominators)
write(OUT/'excluded-paths.json',excluded)
shutil.copyfile(__file__,OUT/'archive_evidence.py')
(OUT/'README.md').write_text('''# M9 known source cost replay

The original frozen source reproduced nine failures: seven target score inputs
were accepted and two canonical builds replayed successfully after their source
cost became unknown. Original generic replay still passed. The separate repair
checkpoint passed all 22 selected tests without source drift.

Each checkpoint's normal state and mechanism fixtures used 17 canonical builds,
133 scripted model calls, 142 source qualifications, 24 retrieval operations,
46 target Docker executions and 46 independent process scores. Two prior-history
fixtures each add two model calls and one Docker execution; GREEN also retains
the selected original stop-case fixtures separately in denominators.json.
The nine replay cases themselves issued no new model, source or Docker calls.

Original and modified source/trace/build receipts, exact JUnit failures,
source manifests and separate GREEN closure are preserved. Unknown source cost
is rejected by the canonical builder and the state/mechanism family verifiers,
including M6 corpus qualification. The generic provenance contract is unchanged.

These are synthetic engineering checks, not demonstrated benchmark gains,
known real API settlement, scientific effectiveness or validation acceptance.
''',encoding='utf-8')
write(OUT/'archive-integrity.json',{p.relative_to(OUT).as_posix():{'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for p in OUT.rglob('*') if p.is_file()})
print(json.dumps({'files':len(list(OUT.iterdir())),'zip_members':sum(map(len,members.values())),'proofs':sum(map(len,proofs.values())),'closures':closures}))
