"""Audit the already closed synthetic stream; do not invoke or resume Grok."""
import hashlib,json,sys
from pathlib import Path

TREE=Path('E:/_ryanDev/AI/research-loop-modular/integration')
WORK=TREE.parent/'work';ROOT=WORK/'grok-subscription-smoke-r5'
sys.path.insert(0,str(TREE))
from research_loop.modular.grok_cli_protocol import inspect_grok_stream

record=json.loads((ROOT/'receipt.json').read_bytes())
raw_path=ROOT/'generation.stdout.private.jsonl'
raw=raw_path.read_bytes()
assert hashlib.sha256(raw).hexdigest()==record['raw_streams'][str(raw_path)]
schema={'type':'object','properties':{'ok':{'type':'boolean','const':True}},'required':['ok'],'additionalProperties':False}
result=inspect_grok_stream(raw,schema=schema,session_id=record['session_id'],
    max_output_tokens=128,max_total_tokens=20000,process_exit_code=record['process_exit_code'])
body=result.receipt.data()
assert not body['accepted'] and result.response is None
assert body['faults']==['runtime_tools_available'],body['faults']
assert body['usage']['total_tokens']==9381 and body['server_reported_usd']==.00644164
out=WORK/'grok-r5-original-stream-inspection-r2.json'
assert not out.exists()
out.write_text(json.dumps({'scope':'read-only audit of original closed synthetic r5 stream',
    'parser_source_sha256':hashlib.sha256((TREE/'research_loop/modular/grok_cli_protocol.py').read_bytes()).hexdigest(),
    'inspection':body,'new_generation_calls':0,'private_raw_stream_copied':False},indent=2)+'\n',encoding='utf-8')
print(json.dumps({'accepted':body['accepted'],'faults':body['faults'],'tokens':body['usage']['total_tokens'],
                  'server_reported_usd':body['server_reported_usd'],'new_generation_calls':0}))
