"""Aggregate only original live opportunities; fixtures are excluded by explicit list."""
import json,sys,hashlib
from pathlib import Path
HERE=Path(__file__).resolve().parent
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
cases=[('domain-pilot-r1','week1-domain-1-r1',None),
       ('domain-pilot-r2','week1-domain-2-r2','measurement-task2'),
       ('domain-pilot-r2','week1-domain-3-r2','measurement-task3'),
       ('domain-pilot-r3','week1-domain-1-r3','measurement-task1')]
rows=[]
for series,op,measurement in cases:
 p=HERE/series/op
 if not p.exists():continue
 complete=(p/'completion.json').exists()
 timing=read(p/'timing.json') if (p/'timing.json').exists() else []
 def total(prefix):return sum(r['ns'] for r in timing if r['operation'].startswith(prefix))/1e9
 context=total('B_context_get_or_build')+total('dependency_refresh')
 external=total('official_client_')+total('tool_')
 invoke_overhead=total('invoke_total_')-total('model_port_total_') if complete else None
 checks=read(HERE/series/measurement/'checks.json') if measurement and (HERE/series/measurement/'checks.json').exists() else []
 summary=read(HERE/series/measurement/'summary.json') if checks else []
 row={'series':series,'opportunity':op,'status':'complete' if complete else 'failed' if (p/'failure.json').exists() else 'incomplete',
 'manifest_sha256':sha(HERE/series/'manifest.json'),'context_and_refresh_ms':context*1000,
 'official_client_seconds':total('official_client_'),'tool_seconds':total('tool_'),'client_plus_tool_seconds':external,
 'target_elimination_share_percent':context/external*100 if external else None,
 'session_startup_ms':total('session_startup')*1000,'evidence_claim_append_ms':total('evidence_and_claim_append_')*1000,
 'runtime_invoke_overhead_ms':invoke_overhead*1000 if invoke_overhead is not None else None,
 'wall_including_quota_seconds':total('trajectory_wall_'),
 'exact_request_checks':len(checks),'B_cache_hit_medians_us':[v['median_us'] for v in summary if v['operation']=='B_cache_hit'],
 'replay_timing_batches':sum(v['batch_count'] for v in summary),
 'analysis_execution_status':read(p/'completion.json')['analysis_execution_status'] if complete else 'not_completed',
 'scientific_validated':False,'client_slots_completed':len(list(p.glob('*/client-check.json')))}
 if checks:row.update(context_bytes=[v['context_bytes'] for v in checks],evidence_roots=[v['evidence_roots'] for v in checks],claims=[v['claims'] for v in checks])
 rows.append(row)
out=HERE/'decision-summary.json'
assert not out.exists(),'do not overwrite a decision snapshot'
body={'schema':'week1-cost-decision-v1','source_sha256':sha(Path(__file__)),'resource_rule_sha256':sha(HERE/'domain-decision-rule.json'),
 'opportunities':rows,'observed_complete':sum(x['status']=='complete' for x in rows),
 'failed':sum(x['status']=='failed' for x in rows),'raw_original_opportunities':len(rows),
 'scientific_task_success':'unscored; no VAL/scorer used','paid_api_calls':0,
 'candidate_development':'stop under predeclared <1% observed target-cost elimination rule' if len([r for r in rows if r['status']=='complete'])>=3 and all(r['target_elimination_share_percent']<1 for r in rows if r['status']=='complete') else 'insufficient complete trajectories for final decision',
 'scope':'bounded official-client two-stage observational analyses; 1 then 2 evidence roots and execution-status claims; no rich dependency workload'}
out.write_text(json.dumps(body,indent=2),encoding='utf-8')
print(json.dumps(body))

