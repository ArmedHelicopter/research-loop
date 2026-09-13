"""Archive public engineering evidence only after the frozen run closes."""
import hashlib,json,shutil,zipfile
from pathlib import Path

WORK=Path('E:/_ryanDev/AI/research-loop-modular/work')
ROOT=Path('E:/_ryanDev/AI/research-loop-modular/triple-369')
OUT=ROOT/'results/modular-engineering-20260913/lineage-retrieval-improvement-triple'
import sys
PREFIXES=sys.argv[1:]
assert PREFIXES


def digest(raw):return hashlib.sha256(raw).hexdigest()
def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2,ensure_ascii=True)+'\n',encoding='utf-8')
def permitted(path,base):
    rel=path.relative_to(base);parts=rel.parts
    if not path.is_file() or any(p.is_symlink() or p.is_junction() for p in (path,*path.parents) if p.is_relative_to(base)):return False
    if 'private-scorer-store' in parts or '.codex' in parts or path.suffix=='.key' or path.name.startswith('server-'):return False
    if path.suffix not in {'.json','.jsonl','.py','.csv','.txt'}:return False
    if path.name in {'plan.json','candidate-barrier.json','build-provider-ledger.json','target-provider-ledger.json',
            'frozen-config.json','controller-attempt.json','controller-receipt.json','public.csv','source-verification.json'}:return True
    if path.name.startswith(('worker-','client-','replay-')) and path.suffix in {'.json','.jsonl'}:return True
    if set(parts)&{'export','prepared','runtime','history','model','builds','targets','context-audit'}:return True
    if 'run' in parts and path.name=='controller.jsonl':return True
    if path.name.startswith('cost-') and path.suffix in {'.json','.jsonl'}:return True
    if path.name=='reviewed-policy.json':return True
    if 'export-audit' in parts and path.name=='exports.jsonl':return True
    return False

OUT.mkdir(parents=True,exist_ok=False)
checks={};members={};summary={};inventory={}
for name in PREFIXES:
    closure=WORK/(name+'-closed.json')
    closed=json.loads(closure.read_bytes())
    assert closed['source_unchanged'] is True
    checks[name]={k:v for k,v in closed.items() if k!='source_after'}
    for suffix in ['-before.json','-closed.json','.xml']:
        src=WORK/(name+suffix);dst=OUT/'checks'/src.name;dst.parent.mkdir(exist_ok=True)
        shutil.copyfile(src,dst)
    base=WORK/name;zip_path=OUT/(name+'.zip');rows=[]
    with zipfile.ZipFile(zip_path,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for path in sorted(base.rglob('*')):
            if not permitted(path,base):continue
            raw=path.read_bytes();assert all(marker not in raw for marker in (b'PRIVATE-REFERENCE-SENTINEL',b'PRIVATE_TASK_ANSWER_DYNAMIC_KEY_MUST_NOT_ESCAPE')),path
            rel=path.relative_to(base).as_posix();z.writestr(rel,raw)
            rows.append({'path':rel,'bytes':len(raw),'sha256':digest(raw)})
            if path.name=='controller-receipt.json':
                b=json.loads(raw);summary[name+'/'+str(path.parent.parent.name)]={k:v for k,v in b.items() if k not in {'contrasts','arm_recipe_bindings'}}
                summary[name+'/'+str(path.parent.parent.name)]['contrasts']=[{'status':c['status'],'reason':c.get('reason')} for c in b['contrasts']]
    with zipfile.ZipFile(zip_path) as z:
        assert len(z.infolist())==len(rows)
        for row in rows:assert digest(z.read(row['path']))==row['sha256']
    members[name]=rows
write(OUT/'checks.json',checks);write(OUT/'denominators.json',summary);write(OUT/'archive-members.json',members)
shutil.copyfile(__file__,OUT/'archive_evidence.py')
for path in OUT.rglob('*'):
    if path.is_file():inventory[path.relative_to(OUT).as_posix()]={'sha256':digest(path.read_bytes()),'bytes':path.stat().st_size}
write(OUT/'archive-integrity.json',inventory)
print(json.dumps({'archive':str(OUT),'checks':checks,'denominators':summary},indent=2))
