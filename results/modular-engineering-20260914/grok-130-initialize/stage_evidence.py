"""Archive explicit non-secret initialization evidence; never walk auth homes."""
import hashlib, json, shutil, zipfile
from pathlib import Path

work=Path('E:/_ryanDev/AI/research-loop-modular/work')
stage=work/'grok-130-initialize-safe-archive-r1'
follow=work/'grok-cli-launch-audit-r1/init-1.0.30-r2-followup'
sha=lambda raw:hashlib.sha256(raw).hexdigest()
def write(path,body):path.write_bytes((json.dumps(body,indent=2)+'\n').encode())
selected={}
index=json.loads((follow/'safe-archive-index.json').read_bytes())
for name,row in index['safe_artifacts'].items():
    path=(follow/row['path']).resolve();raw=path.read_bytes()
    assert sha(raw)==row['sha256'],name
    selected['recorded-safe-index/'+name+path.suffix]=(path,raw)
for name in ('safe-archive-index.json','READONLY-FINDING.md','PASSIVE-DIAGNOSTIC-PROPOSAL.md',
             'PASSIVE-CORRELATION-FINDING.md','passive-correlation-result.json',
             'extract_sanitized_metadata.py','passive_correlation.py'):
    path=follow/name;selected['followup/'+name]=(path,path.read_bytes())
for run in ('init-only-1.0.30-r2','init-only-1.0.30-cap128-r1'):
    for name in ('frozen-envelope.json','public-verification.json','driver.py','home/config.toml',
                 'private-receipt/public-closure.json'):
        path=work/run/name;selected[run+'/'+name]=(path,path.read_bytes())
for name in ('prepare_initialize_cap_comparison_r1.py','verify_initialize_cap_comparison_r1.py',
             'init-only-driver-r1/driver.py','grok-cli-1.0.30/PINNED-BINARY-RECEIPT.md'):
    path=work/name;selected['support/'+name]=(path,path.read_bytes())
assert not stage.exists();stage.mkdir()
(stage/'.gitattributes').write_bytes(b'* -text\n')
rows=[]
with zipfile.ZipFile(stage/'original-safe-evidence.zip','x',zipfile.ZIP_DEFLATED) as archive:
    for name,(path,raw) in sorted(selected.items()):
        assert not any(part in ('auth.json','memtrace') for part in path.parts)
        archive.writestr(name,raw)
        rows.append({'path':name,'original_path':str(path),'sha256':sha(raw),'bytes':len(raw)})
with zipfile.ZipFile(stage/'original-safe-evidence.zip') as archive:
    assert archive.namelist()==[r['path'] for r in rows]
    for row in rows:
        raw=archive.read(row['path']);assert sha(raw)==row['sha256'] and len(raw)==row['bytes']
write(stage/'archive-members.json',rows)
closures={name:json.loads((work/name/'private-receipt/public-closure.json').read_bytes())
          for name in ('init-only-1.0.30-r2','init-only-1.0.30-cap128-r1')}
write(stage/'checks.json',{'schema':'grok-130-initialize-safe-archive-v1','safe_members':len(rows),
    'all_original_bytes_verified':True,'runs':closures,'real_model_prompts':0,
    'settled_additional_charge_usd':None,'native_model_readiness_established':False})
(stage/'README.md').write_bytes(b'''# Grok 1.0.30 initialization evidence

Both one-shot, 60-second initialize-only runs timed out with zero received
frames. Each wrote one initialize request and no session, authentication,
account or model-prompt request. Original public closures and post-run pin
verification are retained. Cleanup completed and the global executable stayed
unchanged. No model readiness, successful research run or settled zero-charge
claim follows from these observations.

The second run changed both recorded completion caps from 8192 to 128 while
retaining the reviewed protocol engine and executable. Initialization still
timed out. Time, paths, network and account/cache state were not controlled;
this observation does not establish causal independence from the cap. The
private auth copy's metadata changed during that run; global auth metadata did
not. Neither auth bodies nor auth hashes were inspected or archived.

Passive diagnostics and original source/config pins are included by explicit
allowlist. Auth files, memtrace contents, raw runtime logs, credentials and the
150 MB executable are excluded. Its locally measured hash identifies the
download; it is not an official release checksum. The installed global CLI
was not upgraded.

The original safe index contains a legacy field named
historical_success_command_envelope pointing to a HEADLESS subscription smoke.
That original field is retained as provenance, not ACP readiness evidence.
The earlier successful ACP run is the separately preserved
grok-acp-two-opportunity-smoke-r3. The passive correlation finding identifies
the ACP run it actually compares. No new startup cause is established.
''')
shutil.copyfile(__file__,stage/'stage_evidence.py')
write(stage/'archive-integrity.json',{p.name:{'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size}
                                    for p in stage.iterdir() if p.is_file()})
print(json.dumps({'stage':str(stage),'files':len(list(stage.iterdir())),'zip_members':len(rows),
                 'zip_sha256':sha((stage/'original-safe-evidence.zip').read_bytes())}))
