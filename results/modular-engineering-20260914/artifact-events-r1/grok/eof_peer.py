import sys,json
for line in sys.stdin:
    json.loads(line)
for _ in sys.stdin: pass
print(json.dumps({'jsonrpc':'2.0','id':1,'result':{'protocolVersion':1}}),flush=True)
