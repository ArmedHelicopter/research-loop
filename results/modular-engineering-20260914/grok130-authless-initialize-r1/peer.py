"""Synthetic only: one fixed request, delayed response or a typed notification."""
import json
import os
from pathlib import Path
import sys
import time

request = json.loads(sys.stdin.readline())
assert request['method'] == 'initialize'
if sys.argv[1] == 'delay':
    time.sleep(10)
if sys.argv[1] == 'auth-path':
    (Path(os.environ['GROK_HOME'])/'auth.json').write_text('synthetic only')
    time.sleep(10)
print(json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': {'protocolVersion': 1}}), flush=True)
if sys.argv[1] == 'notification':
    print(json.dumps({'jsonrpc': '2.0', 'method': '_x.ai/models/update', 'params': {}}), flush=True)
time.sleep(10)
