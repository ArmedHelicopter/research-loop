"""Preserve reviewed public evidence and exact source snapshots, not private payloads."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile

work = Path(__file__).parent
repo = work.parent / 'artifact-evidence-provenance'
destination = repo / 'results/modular-engineering-20260915/native-authoring-observations-r1'
destination.mkdir(parents=True, exist_ok=False)
rows = []

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def copy(source, name):
    source = Path(source)
    target = destination / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    assert target.read_bytes() == source.read_bytes()
    rows.append({'file': name, 'source': str(source), 'source_mtime_ns': source.stat().st_mtime_ns,
                 'bytes': target.stat().st_size, 'sha256': sha(target)})

def derived(name, body):
    target = destination / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((json.dumps(body, indent=2, ensure_ascii=False)+'\n').encode())
    rows.append({'file': name, 'source': 'derived from pinned originals', 'bytes': target.stat().st_size,
                 'sha256': sha(target)})

event_names = {'startup complete', 'shell.turn.inference_start', 'shell.turn.inference_done',
               'shell.handle_prompt.done', 'session_end.worker_join'}
context_keys = {'total_ms', 'outcome', 'session_spawn_ms', 'loop_index', 'elapsed_since_turn_start_ms',
                'transient_retry_attempts', 'model_elapsed_ms', 'ttft_ms', 'itl_p50_ms', 'attempts',
                'prompt_tokens', 'cached_prompt_tokens', 'completion_tokens', 'reasoning_tokens',
                'total_elapsed_ms', 'turn_elapsed_ms', 'pre_turn_ms', 'ok', 'elapsed_ms', 'notice_shown'}
observations = {}
private_pointers = []
for label, directory, script in (
    ('r2', 'headless-instrumented-request-r2', 'run_headless_instrumented_request_r2.py'),
    ('low-effort-r1', 'headless-low-effort-request-r1', 'run_headless_low_effort_request_r1.py')):
    root = work / directory
    observation = json.loads((root/'public-observation.json').read_bytes())
    observations[label] = observation
    assert observation['source_unchanged'] and not observation['validation_access']
    assert not observation['material_admitted'] and not observation['production_receipt']
    for filename in ('public-observation.json', 'envelope.json', 'reservation.json'):
        copy(root/filename, label+'/'+filename)
    copy(work/script, label+'/observer.py')
    copy(root/'home/config.toml', label+'/config.toml')
    # Only fixed event names and scalar performance fields enter the public timeline.
    log = root/'home/logs/unified.jsonl'
    events = []
    for line in log.read_text(encoding='utf-8').splitlines():
        record = json.loads(line)
        if record.get('msg') in event_names:
            events.append({'ts': record['ts'], 'event': record['msg'], 'metrics': {
                key: value for key, value in record.get('ctx', {}).items() if key in context_keys}})
    debug = root/'native/debug.private.log'
    fields = []
    for number, line in enumerate(debug.read_text(encoding='utf-8').splitlines(), 1):
        caps = re.findall(r'"max_completion_tokens"\s*:\s*(\d+)', line)
        efforts = re.findall(r'"reasoning_effort"\s*:\s*"(low|medium|high|xhigh)"', line)
        if caps or efforts:
            fields.append({'line': number, 'line_sha256': hashlib.sha256(line.encode()).hexdigest(),
                           'completion_caps': [int(x) for x in caps], 'reasoning_efforts': efforts})
    derived(label+'/timeline.json', {'schema': 'safe-native-timeline-v1', 'log_sha256': sha(log),
        'debug_sha256': sha(debug), 'events': events, 'debug_field_occurrences': fields,
        'provider_wire_enforcement_proven': False})
    for filename in ('request.private.json', 'native/stdout.private.jsonl', 'native/stderr.private.txt',
                     'native/debug.private.log', 'home/logs/unified.jsonl'):
        path = root/filename
        private_pointers.append({'run': label, 'path': str(path), 'sha256': sha(path),
                                 'bytes': path.stat().st_size, 'archived_content': False})
    if (root/'native/response.private.json').exists():
        path = root/'native/response.private.json'
        private_pointers.append({'run': label, 'path': str(path), 'sha256': sha(path),
                                 'bytes': path.stat().st_size, 'archived_content': False})

assert observations['r2']['status']=='rejected'
assert observations['low-effort-r1']['status']=='provisional_response_observed'
for filename in ('postfailure-material-lint.json', 'postfailure-lint-detail.json', 'counterfactual-format-check.json'):
    copy(work/'headless-instrumented-request-r2'/filename, 'r2/'+filename)
for prefix, label, count in (('headless-instrumented-prerequisite-r1', 'transport-check', 59),
                              ('headless-authoring-prompt-contract-r1', 'prompt-check', 40)):
    closed = json.loads((work/(prefix+'-closed.json')).read_bytes())
    assert closed['exit_code']==0 and closed['source_unchanged'] and closed['junit']=={
        'tests':count,'failures':0,'errors':0,'skipped':0}
    members = json.loads((work/(prefix+'-source-members.json')).read_bytes())
    assert {r['path']:r['sha256'] for r in members['members']}==closed['source_after']
    with zipfile.ZipFile(work/(prefix+'-sources.zip')) as archive:
        assert set(archive.namelist())==set(closed['source_after'])
        for name, pin in closed['source_after'].items():
            assert hashlib.sha256(archive.read(name)).hexdigest()==pin
    for suffix, name in (('-closed.json','closed.json'), ('-before.json','before.json'),
                         ('-source-members.json','source-members.json'), ('-sources.zip','sources.zip'), ('.xml','junit.xml')):
        copy(work/(prefix+suffix), label+'/'+name)
copy(work/'headless-instrumented-source-byte-sync-r1.json', 'preparation/source-byte-sync-r1.json')
unlaunched = work/'headless-instrumented-request-r1'
assert not (unlaunched/'reservation.json').exists()
derived('preparation/unlaunched-r1.json', {'schema':'unlaunched-instrumented-preparation-v1',
    'envelope_path':str(unlaunched/'envelope.json'),'envelope_sha256':sha(unlaunched/'envelope.json'),
    'reservation_exists':False,'native_model_calls':0,
    'reason_for_new_preparation':'frozen authorized account binding added before r2 launch'})
for name in ('grok-native-sampling-source-r1.md','grok-native-sampling-source-r1.metadata.json'):
    copy(work/name,'sampling-source/'+name)

r2 = json.loads((work/'headless-instrumented-request-r2/request.private.json').read_bytes())
low = json.loads((work/'headless-low-effort-request-r1/request.private.json').read_bytes())
a,b = json.loads(r2['prompt']),json.loads(low['prompt'])
assert {k:v for k,v in a.items() if k!='instruction'} == {k:v for k,v in b.items() if k!='instruction'}
assert r2['output_schema']==low['output_schema']
derived('comparison.json', {'schema':'same-train-authoring-observation-comparison-v1',
    'same_task_references_categories_schema':True,'validation_access':False,'formal_calibration':False,
    'new_main_calls':2,'extra_paid_api_budget':0,'settled_additional_charge_usd':None,
    'changes':['blank-control instruction clarification','explicit low reasoning effort'],
    'individual_causal_effect_identifiable':False,'wire_output_cap_proven':False,
    'rejected_run_preserved':True,'provisional_materials_admitted':False,
    'original_raw_artifacts':private_pointers})
(destination/'.gitattributes').write_text('* -text\n',encoding='utf-8')
manifest = {'schema':'native-authoring-observations-archive-v1','files':rows,
    'new_native_model_calls':2,'validation_access':False,'materials_admitted':0,
    'private_payloads_remain_at_original_paths':True,'extra_paid_api_budget':0}
(destination/'manifest.json').write_bytes((json.dumps(manifest,indent=2)+'\n').encode())
for row in rows:
    assert sha(destination/row['file'])==row['sha256']
print(json.dumps({'archive':str(destination),'verified_files':len(rows),
                  'new_main_calls':2,'materials_admitted':0,'validation_access':False}))
