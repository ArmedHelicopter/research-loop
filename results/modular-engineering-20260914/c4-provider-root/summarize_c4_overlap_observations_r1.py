"""Retain measured phase timing, without interpreting it as throughput benefit."""
import hashlib,json
from pathlib import Path
work=Path('E:/_ryanDev/AI/research-loop-modular/work')
out=work/'c4-root-overlap-observations-r1.json'
assert not out.exists()
rows=[]
for run in ('c4-integrated-root-r1','c4-integrated-root-r2'):
    phases=[]
    for path in sorted((work/run/'full-loo0/run/targets').glob('*/phase/receipt.json')):
        raw=path.read_bytes();b=json.loads(raw)
        a=json.loads((path.parent/'allocation.json').read_bytes());cell=a['cell']
        events=(path.parent/'events.jsonl').read_bytes()
        phases.append({'arm_id':cell['arm_id'],'benchmark':cell['identity']['benchmark'],
            'm8_enabled':'M8' in cell['runtime_arm']['enabled'],
            'overlap_ns':b['overlap_ns'],'wall_ns':b['wall_ns'],
            'peak_leases':b['peak_leases'],'docker_attempts':b['actual_docker_attempts'],
            'phase_path':str(path),'phase_sha256':hashlib.sha256(raw).hexdigest(),
            'events_sha256':hashlib.sha256(events).hexdigest()})
    scheduled=[r for r in phases if r['m8_enabled']]
    rows.append({'run':run,'target_phases':len(phases),'scheduled_phases':len(scheduled),
        'zero_overlap_scheduled_phases':sum(r['overlap_ns']==0 for r in scheduled),'phases':phases})
body={'schema':'c4-root-scheduler-observations-v1','runs':rows,
    'source_change':'Persist ready lease batch before submitting workers',
    'controlled_host_comparison':False,'benchmark_throughput_gain_established':False,
    'scientific_effectiveness_proven':False,'interpretation':'Retain actual intervals; host load and scheduling differ across runs.'}
out.write_bytes((json.dumps(body,indent=2)+'\n').encode())
print(json.dumps([{k:v for k,v in r.items() if k!='phases'} for r in rows]))
