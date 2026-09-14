"""Allowlisted public metadata and exact reviewed source; omit native login/logs."""
from collections import Counter
import hashlib,json,shutil
from pathlib import Path
ROOT=Path('E:/_ryanDev/AI/research-loop-modular/work/init-wct-driver-r1')
OUT=ROOT.parent/'grok-initialize-wct-archive-r1'
OUT.mkdir(exist_ok=False)
sha=lambda raw:hashlib.sha256(raw).hexdigest()
def write(name,body):(OUT/name).write_text(json.dumps(body,indent=2)+'\n',encoding='utf-8')
envelope=json.loads((ROOT/'frozen-envelope.json').read_bytes())
assert len(envelope['frozen_files'])==7
assert all(sha(Path(p).read_bytes())==v for p,v in envelope['frozen_files'].items())
for name in ('driver.py','wct_metadata.py','check_cleanup.py','cleanup-checks.json','observer-self-check.json',
             'frozen-envelope.json','launch-reserved.json','public-closure.json','os-metadata.jsonl'):
    shutil.copyfile(ROOT/name,OUT/name)
source_names={}
for i,(name,expected) in enumerate(envelope['frozen_files'].items()):
    path=Path(name)
    if path.suffix=='.exe':continue
    target='frozen-'+str(i)+'-'+path.name
    shutil.copyfile(path,OUT/target);source_names[target]={'source_path':name,'sha256':expected}
write('frozen-source-map.json',source_names)
frames=[]
for i,line in enumerate((ROOT/'private-receipt/stdout.private.bin').read_bytes().splitlines()):
    row=json.loads(line);params=row.get('params',{})
    frames.append({'index':i,'sha256':sha(line),'keys':sorted(row),'id':row.get('id'),
                   'method':row.get('method'),'parameter_keys':sorted(params) if isinstance(params,dict) else None})
write('public-frame-index.json',frames)
closure=json.loads((ROOT/'public-closure.json').read_bytes())
assert closure['process_tree_closed'] and closure['observer_status']=={'started':True,'closed':True,'fault':None}
assert closure['outbound_method_counts']['initialize']==1
assert all(v==0 for k,v in closure['outbound_method_counts'].items() if k!='initialize')
samples=[json.loads(line) for line in (ROOT/'os-metadata.jsonl').read_text().splitlines()]
assert len(samples)==1
write('public-verification.json',{'frozen_files_match':True,'source_snapshot_files':len(source_names),
    'initialize_response_observed':closure['response'] is not None,
    'strict_diagnostic_accepted_initialize':closure['accepted_initialize'],
    'native_and_observer_closed':True,'notification_counts':dict(Counter(f['method'] for f in frames if f['method'])),
    'os_sample_count':len(samples),'model_session_prompt_calls':0,'private_auth_content_or_hash_inspected':False,
    'raw_native_frames_archived':False,'model_tools_billing_readiness_established':False})
(OUT/'FINDING.md').write_text('''# Bounded Grok initialization observation, 2026-09-14

The isolated official-download Grok1.0.30 executable returned an ACP protocol1
initialize response after29.844 seconds; shutdown completed at30.0 seconds.
There was exactly one initialize and no session, authenticate, billing, top-up
or prompt RPC. The native process68668 exited and the numeric observer closed.
Global login-file metadata stayed unchanged; the isolated opaque copy refreshed.
Neither credential contents nor credential hashes were inspected or archived.

The immutable initialize-only engine rejected subsequent notifications, so its
original accepted_initialize=false and unexpected_notification/extra_captured_frame
faults remain unchanged. Four model updates, two settings updates and two
announcement updates followed the response. Scoped read-back showed current
model grok-4.6, allow_access=true, consent_gate=null and no gate label/message.
These facts establish a returned initialization response in this attempt. They
do not establish working generation, tool isolation, billing settlement or a
scientific result. Earlier timeouts remain valid observations; changing time,
paths/account/cache state means no startup cause or corrective effect is proved.

One numeric Windows wait-chain snapshot was captured at10 seconds (the native
process closed before the scheduled30/50 second snapshots). No memory, lock
names, native log bodies or credential files were collected. Single-node wait
chains do not exclude unsupported synchronization waits. Windows documents the
API and its limitations at https://learn.microsoft.com/en-us/windows/win32/api/wct/nf-wct-getthreadwaitchain
and https://learn.microsoft.com/en-us/windows/win32/api/wct/ns-wct-waitchain_node_info .

Independent reviewer grok_provider_independent_review found two observer cleanup
defects before launch: startup could lose ownership, and shutdown used an error
type the unchanged engine did not catch. Both were repaired; two injected cleanup
checks passed without a native launch. Re-review approved exactly one60s launch,
with at most three observations each bounded by4s. The envelope pins both new
files, cleanup test, unchanged engine and transport, config and executable.

The archive preserves original public closure, exact reviewed source snapshots,
numeric OS metadata and frame hashes/structure. Native stdout remains private
at the original path and is not copied here. No old protocol was relaxed and no
additional probe is authorized by this receipt. Normal transport handling and
the versioned native deployment/readiness path remain the next integration work.
''',encoding='utf-8')
(OUT/'.gitattributes').write_text('* -text\n',encoding='utf-8')
shutil.copyfile(__file__,OUT/'archive_builder.py')
write('archive-integrity.json',{p.name:{'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size}
    for p in OUT.iterdir() if p.is_file()})
print(json.dumps({'stage':str(OUT),'files':len(list(OUT.iterdir())),'native_launches':1,
                  'model_calls':0,'initialize_response_observed':True,'diagnostic_accepted':False}))
