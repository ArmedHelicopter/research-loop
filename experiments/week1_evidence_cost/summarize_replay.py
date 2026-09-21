
"""Summarize native replay without promoting diagnostic warm probes into real reuse."""
from pathlib import Path
import json,sys,statistics,hashlib
P=Path(__file__).resolve().parent
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def run(name):
 out=P/name;m=read(out/'manifest.json');rows=[json.loads(x) for x in (out/'measurement/raw.jsonl').read_text(encoding='utf-8').splitlines()]
 summary=read(out/'measurement/summary.json');result=read(out/'measurement/result.json')
 assert len(rows)==len(m['cases'])*len(m['schemes'])*m['repeats']==result['child_runs']
 assert len({(x['opportunity'],x['scheme'],x['repeat']) for x in rows})==len(rows)
 def total(row,names):return sum(x['ns'] for x in row['measurements'] if x['operation'] in names)
 aggregate=[];checks_by_task={}
 for x in rows:
  reference=checks_by_task.setdefault(x['opportunity'],x['checks']);assert x['checks']==reference
 for r in summary:
  own=[x for x in rows if x['opportunity']==r['opportunity'] and x['scheme']==r['scheme']]
  assert len(own)==m['repeats']
  cost=[total(x,{'cold_session_and_index_bind','update_with_journal_and_index','actual_query_with_refresh','actual_full_expand_serialize'})/1e6 for x in own]
  q=statistics.quantiles(cost,n=4,method='inclusive')
  aggregate.append({'scheme':r['scheme'],'opportunity':r['opportunity'],'component_sum_median_ms':statistics.median(cost),'component_sum_q25_ms':q[0],'component_sum_q75_ms':q[2],'definition':'per-child sum: cold native ledgers/cache binding + persistent public updates + actual query/refresh + actual full expansion; excludes schedule read, correctness checks, imports and warm probes'})
  if r['scheme']=='S':
   assert all(x['actual_cache_stats']['hits']==0 for x in own)
 lines=['# Native R/B/S replay: '+name,'',
 'This is CPU replay of an already recorded TRAIN workflow. No new model invocation, scientific task, scoring or VAL access occurred. All '+str(result['child_runs'])+' shuffled fresh children completed and '+str(result['exact_context_and_state_comparisons'])+' exact context/state comparisons matched. The source is one previously counted NLS SES task, not a new independent task.',
 '',
 '| Scheme | Cold bind us | Native updates + journal us | Three actual queries us | Evidence expansion us | Extra warm query us | Max child peak bytes |',
 '|---|---:|---:|---:|---:|---:|---:|']
 for r in summary:
  lines.append('| '+' | '.join(str(r[k]) for k in ['scheme','median_cold_bind_us','median_updates_with_journal_us','median_three_actual_queries_us','median_full_expand_us','median_separate_warm_query_us','max_whole_child_peak_working_set_bytes'])+' |')
 lines+=['','| Scheme | Median component sum ms | Q25 ms | Q75 ms |','|---|---:|---:|---:|']
 for r in aggregate:lines.append('| '+' | '.join(str(r[k]) for k in ['scheme','component_sum_median_ms','component_sum_q25_ms','component_sum_q75_ms'])+' |')
 lines+=['',
 'The second table sums measured nonoverlapping components within each child before aggregation; it is not a sum of separate medians. Quartiles describe timing variation, not cross-task inference or confidence intervals.',
 '',
 'S has zero hits in every actual sequence. The ten extra identical-query warm probes are separate; they cannot establish a realized domain-workflow cache benefit. Persistent native journal costs dominate this replay, and their variation is visible. Native replay excludes the full RunSession artifact-catalogue persistence, so it cannot explain away the original registration cost.',
 '',
 'Tracemalloc was enabled during timed operations. Actual-sequence wall time includes correctness checks; whole-child wall includes import/validation and warm probes. Raw results separately record actual_sequence_peak_working_set_bytes before warm probes and whole_child_peak_working_set_bytes afterward. Do not compare these instrumented query times directly with the original uninstrumented live timings.',
 '',
 'All native semantics remain unchanged. AND grouping is unsupported by the native reference, not a passed capability or an S improvement. No candidate C, end-to-end optimized rerun, token savings or capability gain is demonstrated. Source/operation hashes and fixed resource/timeout bounds are in manifest.json.',
 '',
 'Prior attempt RBS-rich-r1 remains incomplete at 46/60 under its 180-second parent cap. RBS-rich-r1b is a fresh complete comparison with a 600-second cap and unchanged scheme semantics/operations/repeats. This report never substitutes partial rows for missing runs.']
 if name=='RBS-rich-r1b':lines+=['','Source workflow limitation: domain-rich-r1 recorded eight primary statistics but its qualification produced no facts due to the retained mounted-file mistake. This complete CPU replay does not turn that failure into a successful scientific check.']
 with (out/'measurement/component-totals.json').open('x',encoding='utf-8') as f:json.dump(aggregate,f,indent=2)
 (out/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
 print(json.dumps({'run':name,'rows':len(rows),'component_totals':aggregate}))
if __name__=='__main__':run(sys.argv[1])

