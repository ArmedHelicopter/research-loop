"""Archive only fixed metadata from this task's synthetic tests."""
import hashlib
import json
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from collections import Counter

ROOT = Path('E:/_ryanDev/AI/research-loop-modular/cal-pilot')
OUT = Path('E:/_ryanDev/AI/research-loop-modular/work/cal-pilot-checks')
TEMP = OUT / 'final2-tmp'
def sha(raw): return hashlib.sha256(raw).hexdigest()
def canonical(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
def write(name, value):
    path = OUT / name
    with path.open('x', encoding='utf-8') as stream: json.dump(value, stream, indent=2, ensure_ascii=True); stream.write('\n')
    return {'path':str(path),'sha256':sha(path.read_bytes()),'size_bytes':path.stat().st_size}
def main():
    before = json.loads((OUT/'source-before-final-r2.json').read_text())
    after = [{'path':row['path'],'sha256':sha((ROOT/row['path']).read_bytes())} for row in before['files']]
    changed = [a['path'] for a,b in zip(after,before['files']) if a!=b]
    if changed: raise RuntimeError('source_changed')
    source_after = write('source-after-final-r2.json',{'schema':'calibration-pilot-source-verification-v1',
        'commit':before['commit'],'files':after,'file_count':len(after),'changed_files':changed})
    attempts = []
    for name in ('red-r1.xml','green-r1.xml','boundary-r2.xml','final-r1.xml',
                 'red-boundary-r1.xml','green-boundary-r3.xml','final-r2.xml'):
        path=OUT/name; suite=ET.parse(path).getroot().find('testsuite')
        attempts.append({'path':str(path),'sha256':sha(path.read_bytes()),'tests':int(suite.attrib['tests']),
            'failures':int(suite.attrib['failures']),'errors':int(suite.attrib['errors']),
            'skipped':int(suite.attrib['skipped']),'seconds':float(suite.attrib['time'])})
    journals=[]; main_receipts=[]
    for dirname, dirs, files in os.walk(TEMP, followlinks=False):
        dirs[:]=[d for d in dirs if not d.endswith('current') and not ((Path(dirname)/d).lstat().st_file_attributes & 0x400)]
        for name in files:
            path=Path(dirname)/name
            if name=='diagnostic-result.json': main_receipts.append(path)
            if name not in ('pilot.jsonl','budget.jsonl','private-journal.jsonl','parent.jsonl','timeout-parent.jsonl'): continue
            rows=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
            if not rows or set(rows[0])!={'sequence','previous','event','data','digest'}: continue
            if rows[0]['event'] not in ('pilot_reserved','port_reserved','capacity_rejected','source_guard_rejected','process_reserved'): continue
            previous='0'*64
            for index,row in enumerate(rows):
                payload={k:v for k,v in row.items() if k!='digest'}
                if row['sequence']!=index or row['previous']!=previous or row['digest']!=sha(canonical(payload).encode()):
                    raise RuntimeError('journal_chain_invalid')
                previous=row['digest']
            events=Counter(row['event'] for row in rows)
            reservations=Counter(row['data']['role'] for row in rows if row['event']=='port_reserved')
            raw=Counter(row['data']['role'] for row in rows if row['event']=='port_raw')
            cost_statuses=Counter(row['data']['cost_status'] for row in rows if row['event']=='port_closed')
            journals.append({'path':str(path),'sha256':sha(path.read_bytes()),'events':dict(events),
                'reserved_port_attempts':dict(reservations),'retained_raw_responses':dict(raw),
                'cost_statuses':dict(cost_statuses),'last_chain_digest':previous})
    if len(main_receipts)!=1: raise RuntimeError('main_grid_receipt_not_unique')
    raw=main_receipts[0].read_bytes()
    with (OUT/'synthetic-main-grid-receipt-r2.json').open('xb') as stream: stream.write(raw)
    main_payload=json.loads(raw)['body']['payload']
    if main_payload['validation_eligible'] is not False or len(main_payload['observations'])!=72:
        raise RuntimeError('main_grid_scope_invalid')
    sums=Counter(); statuses=Counter()
    for row in journals:
        sums.update(row['reserved_port_attempts']); statuses.update(row['cost_statuses'])
    denom=write('synthetic-denominators-r2.json',{'schema':'calibration-pilot-synthetic-denominators-v1',
        'journals':journals,'journal_count':len(journals),'reserved_port_attempts':dict(sums),
        'cost_statuses':dict(statuses),'main_grid':{'source_tasks':main_payload['source_task_count'],
            'slots':main_payload['slot_count'],'evaluator_opportunities':main_payload['evaluator_opportunity_count'],
            'budget':main_payload['budget'],'per_benchmark':main_payload['per_benchmark']},
        'actual_paid_model_calls':0,'actual_reference_payload_reads':0,'validation_calls':0,
        'denominator_scope':'Synthetic private journals in final2-tmp only; counts are port-dispatch attempts, including rejected/cached/partial counterexamples, not paid model calls. Hand-authored fixture preparation is not a model call.'})
    summary={'schema':'four-train-calibration-pilot-verification-v1','source_commit':before['commit'],
        'source_files':len(after),'source_changes_during_final_run':0,'tests':attempts,
        'final_acceptance':attempts[-1]['failures']==attempts[-1]['errors']==attempts[-1]['skipped']==0,
        'source_after':source_after,'synthetic_denominators':denom,
        'retained_red_branch_commit':'4187412','red_branch_must_not_be_integrated':True,
        'prior_fixture_failure':'final-r1 retained an empty-candidate-shape fixture failure; 111 other tests passed; source unchanged',
        'scope':{'actual_four_train_reference_read':False,'actual_model_calls':0,'docker_calls':0,
                 'validation_leases':0,'legacy_split_or_hold_mutations':0,'official_metric_equivalence':False,'scientific_calibration':False},
        'remaining':['Deploy independent reviewers with standard resolver and private references',
            'Provide and independently review exact full-context/tokenizer/output-limit and pricing bounds',
            'Freeze actual four-train material and expected-target receipts using existing allowlist',
            'Four tasks cannot establish population calibration or validation eligibility']}
    result=write('delivery-verification-r2.json',summary)
    names=['source-before-final-r1.json','final-r1-closure.json','source-before-final-r2.json','source-after-final-r2.json',
        'synthetic-main-grid-receipt-r2.json','synthetic-denominators-r2.json','delivery-verification-r2.json','archive_delivery.py']+[Path(r['path']).name for r in attempts]
    manifest=write('delivery-manifest-r2.json',{'schema':'calibration-pilot-delivery-v1','source_commit':before['commit'],
        'files':[{'path':str(OUT/name),'sha256':sha((OUT/name).read_bytes()),'size_bytes':(OUT/name).stat().st_size} for name in names]})
    print(json.dumps({'manifest':manifest,'verification':result,'tests':attempts[-1],
        'source_changes':0,'synthetic_journals':len(journals),'synthetic_dispatch_attempts':dict(sums)}))
if __name__=='__main__':
    try: main()
    except Exception as exc:
        print(json.dumps({'status':'archive_failed','error_class':type(exc).__name__}))
        raise SystemExit(1)
