"""Synthetic one-request peer; no credentials/network or native CLI."""
import json
from pathlib import Path
import subprocess
import sys
import time
mode, directory = sys.argv[1:]; root = Path(directory)
line = sys.stdin.buffer.readline()
(root / 'received.private.jsonl').write_bytes(line)
if mode == 'success':
    print(json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': {'protocolVersion': 1}}), flush=True)
elif mode == 'malformed':
    print('{invalid', flush=True)
elif mode == 'server_request':
    print(json.dumps({'jsonrpc': '2.0', 'id': 99, 'method': 'session/request_permission', 'params': {}}), flush=True)
elif mode == 'timeout':
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    (root / 'child.pid').write_text(str(child.pid))
else:
    raise AssertionError(mode)
# Keep reading to prove the driver never sends any follow-up or response frame.
for line in sys.stdin.buffer:
    with (root / 'received.private.jsonl').open('ab') as out: out.write(line)
