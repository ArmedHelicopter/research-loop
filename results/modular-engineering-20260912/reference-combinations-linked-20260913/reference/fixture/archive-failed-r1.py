import hashlib, json, subprocess, xml.etree.ElementTree as ET
from pathlib import Path
BASE=Path('E:/_ryanDev/AI/research-loop-modular')
TREE=BASE/'pr-ref'
WORK=BASE/'work/primary-reference-checks'
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_bytes())
result=read(WORK/'frozen-result-r1.json')
freeze=read(WORK/'source-freeze-r1.json')
assert result['exit_code']==0 and result['all_source_bytes_unchanged'] and result['worktree_clean']
assert result['source_commit_before']==result['source_commit_after']==freeze['source_commit']
assert all(sha(TREE/path)==value for path,value in freeze['files'].items())
junit=[]
for name in ('red-r1','green-r2','boundary-r3','integration-r4','frozen-r1'):
    path=WORK/(name+'.xml')
    suites=ET.parse(path).getroot().findall('testsuite')
    row={'path':str(path),'sha256':sha(path),'verification_scope':'invalid_source_changed_during_run' if name=='boundary-r3' else 'development' if name!='frozen-r1' else 'frozen_acceptance'}
    for field in ('tests','failures','errors','skipped'):row[field]=sum(int(s.attrib.get(field,0)) for s in suites)
    row['time_seconds']=sum(float(s.attrib['time']) for s in suites)
    junit.append(row)
assert junit[-1]['failures']==junit[-1]['errors']==junit[-1]['skipped']==0
calls=[]
for name in ('integration-r4','frozen-r1'):
    files=list((WORK/name).glob('test_actual_scorer_subproce*/fixture-call-counts.json'))
    assert len(files)==1
    data=read(files[0])
    calls.append({'run':name,'path':str(files[0]),'sha256':sha(files[0]),'counts':data})
reference_attempts=[]
for name in ('green-r2','boundary-r3','integration-r4','frozen-r1'):
    totals={'attempt_reserved':0,'completed':0,'failed':0,'reference_read_reserved':0,'publication_reserved':0}
    files=[]; corrupt=0
    for path in (WORK/name).glob('test_*/reference-audit/references.jsonl'):
        files.append({'path':str(path),'sha256':sha(path)})
        try:rows=[json.loads(line) for line in path.read_bytes().splitlines()]
        except ValueError:
            corrupt+=1;continue
        for row in rows:
            if row['event'] in totals:totals[row['event']]+=1
    reference_attempts.append({'run':name,'journal_count':len(files),'intentionally_corrupt_journals':corrupt,'events':totals,'journals':files})
paths=[WORK/name for name in ('source-freeze-r1.json','frozen-result-r1.json','frozen-command-r1.json','frozen-r1.log',
    'boundary-r3-source-change.json','boundary-r3-source-reconstructed-before.py','boundary-r3-source-after.py',
    'actual-four-train-reference-plan-r1.json','actual-four-train-reference-descriptor-r2.json','verify_descriptor_metadata.py',
    'run_frozen.py','preserve_development_scope.py','archive_frozen.py')]
body={'schema':'primary-reference-bridge-delivery-verification-v1','source_commit':freeze['source_commit'],
    'base_commit':freeze['base_commit'],'source_files_verified':len(freeze['files']),'source_before_after_unchanged':True,
    'junit':junit,'new_bridge_scorer_process_fixture_calls':calls,'reference_attempt_denominators':reference_attempts,
    'worktree_setup_failure':{'attempts':2,'failed_attempts':1,'failure_category':'windows_filename_too_long',
        'failed_path':str(BASE/'primary-prospective-reference-bridge'),'successful_path':str(TREE),
        'git_config_override':'one_command_core.longpaths_true','global_git_config_modified':False},
    'artifact_pins':[{'path':str(path),'sha256':sha(path)} for path in paths],
    'actual_reference_payload_reads':0,'actual_validation_exports':0,'actual_validation_leases':0,
    'paid_model_calls':0,'network_calls':0,'scientific_validity':'not_measured','calibration':'not_measured',
    'actual_public_four_export_unchanged':True}
with (WORK/'delivery-verification-r1.json').open('x') as f:json.dump(body,f,indent=2)
(TREE/'docs/primary-reference-bridge-verification.json').write_text(json.dumps(body,indent=2)+'\n')
print(json.dumps({'status':'verified','source_commit':freeze['source_commit'],'junit':junit[-1],
    'new_bridge_frozen_fixture_counts':calls[-1]['counts'],'source_files_verified':len(freeze['files']),
    'delivery_verification_sha256':sha(WORK/'delivery-verification-r1.json')}))
