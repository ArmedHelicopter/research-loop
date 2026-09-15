"""Regression from a closed synthetic native postflight failure; read originals only."""
import hashlib
import importlib.util
import json
from pathlib import Path

base=Path('E:/_ryanDev/AI/research-loop-modular/WORK')
helper=base/'audit_headless_review_r2.py'
spec=importlib.util.spec_from_file_location('r2_reader',helper)
reader=importlib.util.module_from_spec(spec);spec.loader.exec_module(reader)
native=base/'headless-train-integration-preliminary-r1/test_postflight_rejection_is_r0/ledger/calls/0001-m4_plan/native'
receipt=json.loads((native/'observer-receipt.json').read_bytes())
response=native/'response.private.json'
before={str(p):(hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns)
    for p in native.rglob('*') if p.is_file()}
assert receipt['accepted'] is False and response.is_file()
checked=reader.retained_rejected_response(response,receipt)
assert checked['present'] is True and checked['consumed'] is False
for path,record in ((response,dict(receipt,response_sha256='0'*64)),
    (native/'absent-response.json',receipt)):
    try:reader.retained_rejected_response(path,record)
    except ValueError:pass
    else:raise AssertionError('reader admitted missing or substituted response')
assert reader.retained_rejected_response(native/'absent-response.json',{'response_sha256':None})=={
    'present':False,'sha256':None,'consumed':False}
after={str(p):(hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns)
    for p in native.rglob('*') if p.is_file()}
assert before==after
out=base/'r2-rejected-response-reader-regression-r1.json'
with out.open('x',encoding='utf-8') as stream:
    json.dump({'schema':'r2-rejected-response-reader-regression-v1','passed':4,
        'source':'closed synthetic native producer postflight failure',
        'helper_sha256':hashlib.sha256(helper.read_bytes()).hexdigest(),
        'source_native':str(native),'original_files_unchanged':len(before),
        'retained_unbound_response':checked,'model_calls':0,'validation_access':False},stream,indent=2)
print(out)
