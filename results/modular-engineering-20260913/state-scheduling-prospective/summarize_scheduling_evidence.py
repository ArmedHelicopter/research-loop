from pathlib import Path
import hashlib,json,sys
work=Path('E:/_ryanDev/AI/research-loop-modular/work')
result={}
for prefix in sys.argv[1:]:
    closure=json.loads((work/(prefix+'-closed.json')).read_bytes())
    assert closure['source_unchanged'] and closure['exit_code']==0
    base=work/prefix;cells=[];variants=[]
    for path in sorted((base/'state-scheduling-controller0').glob('run/cells/*/phase/receipt.json')):
        phase=json.loads(path.read_bytes());allocation=json.loads((path.parent/'allocation.json').read_bytes());cell=allocation['cell']
        cells.append({'pair':cell['coverage_id'],'benchmark':cell['identity']['benchmark'],'arm_id':cell['arm_id'],
            'enabled':cell['runtime_arm']['enabled'],'selected_jobs':phase['selection']['selected'],'permit':phase['selection']['permit'],
            'docker_attempts':phase['actual_docker_attempts'],'peak_leases':phase['peak_leases'],'overlapping_docker_call_intervals':phase['overlap_ns']>0,
            'remaining_leases':phase['remaining_leases'],'residual_containers':phase['residual_containers']})
    for path in sorted(base.glob('test_bound_driver_scheduler_va*/variant/phase/receipt.json')):
        if any(p.is_symlink() for p in path.parents):continue
        phase=json.loads(path.read_bytes());values=[]
        for observation in phase['public']['observations']:
            try:values.append(json.loads(observation['stdout']))
            except ValueError:pass
        inside=all('started_ns' in v and 'finished_ns' in v for v in values) and len(values)==2
        score=path.parent.parent.parent/'variant-score.json'
        variants.append({'case':path.parent.parent.parent.name,'status':phase['status'],'docker_attempts':phase['actual_docker_attempts'],
            'selected_jobs':phase['selection']['selected'],'peak_leases':phase['peak_leases'],'completion_order':phase['completion_order'],
            'fifo_order':phase['fifo_order'],'overlapping_docker_call_intervals':phase['overlap_ns']>0,
            'inside_container_intervals':[{k:v[k] for k in ('started_ns','finished_ns')} for v in values] if inside else None,
            'inside_container_overlap': min(v['finished_ns'] for v in values)>max(v['started_ns'] for v in values) if inside else None,
            'remaining_leases':phase['remaining_leases'],'residual_containers':phase['residual_containers'],
            'independent_scorer_receipt_sha256':hashlib.sha256(score.read_bytes()).hexdigest() if score.exists() else None})
    assert len(cells)==24 and all(c['permit'] is None for c in cells)
    assert len({tuple(c['selected_jobs']) for c in cells})==1
    assert sum('M8' in c['enabled'] and c['peak_leases']==2 and c['overlapping_docker_call_intervals'] for c in cells)==12
    assert sum('M8' not in c['enabled'] and c['peak_leases']==0 and not c['overlapping_docker_call_intervals'] for c in cells)==12
    result[prefix]={'source_commit':closure['commit'],'grid':cells,'variants':variants,'throughput_claim':False,'scientific_effect_measured':False}
last=result[sys.argv[-1]]
assert any(v['inside_container_overlap'] is True and v['independent_scorer_receipt_sha256'] for v in last['variants'])
out=Path.cwd()/'results/modular-engineering-20260913/state-scheduling-prospective/scheduling-evidence.json'
out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'grid_phases':sum(len(r['grid']) for r in result.values()),'variants':sum(len(r['variants']) for r in result.values()),'final_inside_container_overlap_verified':True}))
