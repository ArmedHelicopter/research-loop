"""Archive public engineering evidence only after the frozen run closes."""
import hashlib,json,shutil,zipfile
from pathlib import Path

WORK=Path('E:/_ryanDev/AI/research-loop-modular/work')
ROOT=Path('E:/_ryanDev/AI/research-loop-modular/state-retrieval-combos')
OUT=ROOT/'results/modular-engineering-20260913/state-retrieval-prospective'
PREFIXES=['state-retrieval-driver-2603c46-a','state-retrieval-driver-4a1db59-b',
    'state-retrieval-driver-e147c96-c','state-retrieval-driver-6357c8e-d',
    'state-retrieval-controller-607bfde-a']

def digest(raw):return hashlib.sha256(raw).hexdigest()
def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2,ensure_ascii=True)+'\n',encoding='utf-8')
def permitted(path,base):
    rel=path.relative_to(base);parts=rel.parts
    if path.is_symlink() or not path.is_file():return False
    if 'private-scorer-store' in parts or path.suffix=='.key' or path.name.startswith('server-'):return False
    if path.name in {'frozen-config.json','controller-attempt.json','controller-receipt.json','public.csv'}:return True
    if path.name.startswith(('worker-','client-','replay-')) and path.suffix in {'.json','.jsonl'}:return True
    if path.name=='ledger.json' and 'model' in parts:return True
    if 'export' in parts or 'runtime' in parts:return True
    if path.name=='source-verification.json':return True
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
            raw=path.read_bytes();assert b'PRIVATE-REFERENCE-SENTINEL' not in raw,path
            rel=path.relative_to(base).as_posix();z.writestr(rel,raw)
            rows.append({'path':rel,'bytes':len(raw),'sha256':digest(raw)})
            if path.name=='controller-receipt.json':
                b=json.loads(raw);summary[name+'/'+str(path.parent.parent.name)]={k:b[k] for k in (
                    'status','expected_cells','observed_cells','scored_cells','failed_cells','blocked_cells','actual_model_usage',
                    'actual_docker_attempts','actual_scorer_calls','source_calls','retrieval_calls','unused_model_opportunities',
                    'unused_docker_opportunities','unused_scorer_opportunities','unused_retrieval_opportunities','pruned_cells',
                    'scientific_effectiveness_proven','validation_opened')}
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
