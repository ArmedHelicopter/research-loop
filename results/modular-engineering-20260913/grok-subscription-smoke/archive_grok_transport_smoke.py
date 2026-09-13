"""Copy only the fixed public evidence allowlist; never traverse private homes."""
import hashlib,json,shutil
from pathlib import Path

TREE=Path('E:/_ryanDev/AI/research-loop-modular/integration')
WORK=TREE.parent/'work'; SRC=WORK/'grok-subscription-smoke-r5'
OUT=TREE/'results/modular-engineering-20260913/grok-subscription-smoke'
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path): return json.loads(path.read_bytes())
receipt=read(SRC/'receipt.json'); verification=read(SRC/'postrun-verification.json')
reservation=WORK/'grok-subscription-smoke-single-call-reservation.json'
assert verification['receipt_sha256']==sha(SRC/'receipt.json')
assert receipt['reservation_sha256']==sha(reservation)
assert receipt['envelope_sha256']==sha(SRC/'frozen-envelope.json')
assert receipt['generation_process_attempts']==1 and receipt['retries']==0
assert receipt['process_exit_code']==0 and receipt['constant_response_valid']
assert verification['runtime_toolset_empty'] is False and verification['raw_tool_call_count']==0
assert verification['server_reported_usd']==0.00644164
allowed=('receipt.json','postrun-verification.json','frozen-envelope.json','inspect-metadata.json','prompt.txt')
assert tuple(verification['safe_evidence_files'])==allowed
OUT.mkdir(parents=True,exist_ok=False)
for name in allowed: shutil.copyfile(SRC/name,OUT/name)
shutil.copyfile(reservation,OUT/reservation.name)
shutil.copyfile(__file__,OUT/Path(__file__).name)
(OUT/'README.md').write_text('''# Grok CLI subscription transport smoke

The user authorized Grok CLI `grok-4.6` after declining additional API fees.
One synthetic constant request ran through the existing grok.com login, with
no API key route, no benchmark input, and no retry. The process returned
`{"ok":true}` in 10.938 seconds. The receipt reports one main model call under
`grok-4.6-build`, 9,335 input tokens and 46 output tokens (including 37 reasoning
tokens), for 9,381 total tokens. It reports $0.00644164 in server accounting;
this does not establish settlement or prove no additional charge.

The external inventory was empty: no skills, hooks, plugins, MCP or project
instructions. Runtime events nevertheless advertised 21 built-in tools; zero
tool calls occurred. Thus this smoke passes basic transport only, and does
not certify a tool-free request. The original reservation's no-tools invariant
was not established. `receipt.additional_api_fee_route_used=false` means only
that no API-key route was configured. The accompanying postrun verification
preserves both corrections without rewriting the original receipt.

The 128 output token request was set under the correctly quoted TOML key
`[model."grok-4.6"]`; no captured wire request proves server enforcement.
Earlier read-only preparations r1–r4 made no generations. They exposed native
profile discovery and an unquoted dotted TOML key, repaired before this run.
Further experiments require a separately frozen transport contract, explicit
tool exclusion, and a verified spending policy compatible with the user.

Only five explicitly allowlisted evidence files and the one-call reservation
are copied here. Credential homes, private profile directories and raw private
streams are excluded. Their hashes remain in the receipt for custody checks.
No scientific effectiveness or validation acceptance is claimed.
''',encoding='utf-8',newline='\n')
(OUT/'SHA256.json').write_text(json.dumps({p.name:sha(p) for p in OUT.iterdir() if p.is_file()},indent=2)+'\n',encoding='utf-8')
print(json.dumps({'archive':str(OUT),'files':len(list(OUT.iterdir())),'actual_model_calls':1,'validation_opened':False}))
