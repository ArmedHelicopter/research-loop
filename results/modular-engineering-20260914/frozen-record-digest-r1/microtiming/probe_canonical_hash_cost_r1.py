"""Read-only timing of equivalent hashes on original frozen C5 public records."""
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time

work=Path(__file__).resolve().parent
tree=work.parent/'integration'
sys.path.insert(0,str(tree))
from research_loop.modular.contracts import FrozenRecord

root=work/'c5-common-complete-r3/test_complete_common_train_con0/common-run'
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=tree,text=True).strip()
assert head=='98eae2811b929d2d2f0eaf2863711280cf753ce5'
rows=[]
for name in ('plan.json','protocol.json'):
    path=root/name; original=path.read_bytes()
    record=FrozenRecord(original.decode('utf-8').removesuffix('\n'))
    reference=record.content_hash
    def encoded_hash(): return hashlib.sha256(record.encoded.encode('utf-8')).hexdigest()
    assert encoded_hash()==reference
    times={'current':[],'canonical_bytes':[]}
    started=time.monotonic()
    for order in (('current','canonical_bytes'),('canonical_bytes','current'))*2:
        for method in order:
            begin=time.perf_counter()
            for _ in range(40):
                value=record.content_hash if method=='current' else encoded_hash()
                assert value==reference
            times[method].append((time.perf_counter()-begin)/40)
            assert time.monotonic()-started < 45
    assert path.read_bytes()==original
    rows.append({'file':str(path),'bytes':len(original),'sha256':hashlib.sha256(original).hexdigest(),
        'iterations_per_block':40,'seconds_per_call':times,
        'median_ratio_current_over_canonical_bytes':statistics.median(times['current'])/statistics.median(times['canonical_bytes']),
        'digests_identical':True,'original_unchanged':True})
body={'schema':'canonical-hash-cost-observation-v1','source':head,
    'contracts_sha256':hashlib.sha256((tree/'research_loop/modular/contracts.py').read_bytes()).hexdigest(),
    'rows':rows,'scope':'Micro-timing on two real frozen public engineering records. No running process altered, no production optimization applied, no extrapolation to total C5 speedup.',
    'new_paid_calls':0,'scientific_effectiveness_proven':False}
with (work/'canonical-hash-cost-observation-r1.json').open('x',encoding='utf-8',newline='\n') as stream:
    stream.write(json.dumps(body,indent=2)+'\n')
print(json.dumps({'source':head,'measurements':[{'file':Path(r['file']).name,'bytes':r['bytes'],
    'ratio':r['median_ratio_current_over_canonical_bytes']} for r in rows]}))
