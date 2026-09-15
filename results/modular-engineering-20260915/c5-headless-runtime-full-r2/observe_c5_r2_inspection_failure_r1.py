from pathlib import Path
from datetime import datetime, timezone
import hashlib, json

work = Path('E:/_ryanDev/AI/research-loop-modular/work')
root = work/'c5-headless-runtime-full-r2/test_full_headless_c5_controll0'
call = root/'headless-solver/ledger/calls/0187-review_first'
paths = {'observer': call/'observer-receipt.private.json',
    'inspect_process': call/'native/inspect/process.json',
    'inspect_stdout': call/'native/inspect/stdout.private.jsonl',
    'inspect_stderr': call/'native/inspect/stderr.private.txt',
    'stage': root/'headless-common-run/stages/3762079dfc9b827e2a20b84022bdfd66c3be5b06441f461aff07ea781e678363/receipt.json'}
originals = {key: path.read_bytes() for key,path in paths.items()}
observer = json.loads(originals['observer'])
process = json.loads(originals['inspect_process'])
stage = json.loads(originals['stage'])
body = {'schema':'c5-synthetic-inspection-failure-observation-v1',
    'observed_at':datetime.now(timezone.utc).isoformat(), 'original_native_session':4370,
    'native_status':'last rejoin confirmed live; observation is not a terminal completion',
    'source_commit':'83aefb74f15a72d421dd5e34002e36483b6ce6d0',
    'build_id':'3762079dfc9b827e2a20b84022bdfd66c3be5b06441f461aff07ea781e678363',
    'stage_status':stage['status'], 'stage_reason':stage['reason'],
    'call_id':187, 'slot':'review_first', 'faults':observer['faults'],
    'prompt_process_launched':observer['prompt_process_launched'],
    'inspect_process':{key:process[key] for key in ['launched','pid','started_at','finished_at','process_exit_code','timed_out','timeout_seconds','owned_tree_closed','failure']},
    'originals':{key:{'path':str(path),'sha256':hashlib.sha256(originals[key]).hexdigest(),'bytes':len(originals[key])} for key,path in paths.items()},
    'interpretation':'Synthetic context inspection timed out before MAIN dispatch. The original failed shutdown/unknown exit remain unmodified. This does not establish why the OS peer failed or any module-effect result.',
    'actual_model_calls':0, 'validation_opened':False, 'pruned_combinations':[]}
assert observer['prompt_process_launched'] is False
assert process['timed_out'] is True and process['timeout_seconds']==10
assert all(path.read_bytes()==originals[key] for key,path in paths.items())
dest=work/'c5-headless-runtime-full-r2-inspection-failure-observation-r1.json'
with dest.open('xb') as stream:
    stream.write((json.dumps(body,ensure_ascii=True,indent=2)+'\n').encode())
print(json.dumps({'path':str(dest),'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'main_dispatched':False}))
