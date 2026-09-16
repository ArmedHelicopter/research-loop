"""Retain the successful one-opportunity TRAIN control without exposing streams."""
import hashlib,importlib.util,json,zipfile
from pathlib import Path
BASE=Path('E:/_ryanDev/AI/research-loop-modular'); WORK=BASE/'work'
PREFIX='grok130-normal-train-control-r3'; SOURCE=WORK/PREFIX
DEST=BASE/'artifact-evidence-provenance/results/modular-engineering-20260916'/PREFIX
PRIVATE=BASE/'retained-private-evidence'/PREFIX
HELPER=WORK/'prepare_headless_lineage_full4_archive_r1.py'
def sha(raw): return hashlib.sha256(raw).hexdigest()
def read(p): return json.loads(p.read_bytes())
def write(p,b):
    with p.open('xb') as out: out.write((json.dumps(b,indent=2)+'\n').encode())
def stamp(p):
    raw=p.read_bytes(); return {'sha256':sha(raw),'bytes':len(raw),'mtime_ns':p.stat().st_mtime_ns}
def main():
    assert not DEST.exists() and not PRIVATE.exists()
    start=WORK/(PREFIX+'-execute-native-start.json'); join=WORK/(PREFIX+'-execute-native-join.json')
    assert read(start)['session_id']==read(join)['native_session_id']==70385
    assert read(join)['result']['exit_code']==0
    assert read(join)['source_commit']=='43ccf107186f730884e64c230d3abe4bfa555d65'
    closure=read(SOURCE/'closure.json'); ledger_path=SOURCE/'control-model/ledger.json'
    assert closure['status']=='succeeded' and closure['source_unchanged'] and closure['global_auth_metadata_unchanged']
    assert closure['ledger_sha256']==sha(ledger_path.read_bytes())
    ledger=read(ledger_path); assert len(ledger['calls'])==1 and ledger['calls'][0]['status']=='succeeded'
    usage=ledger['calls'][0]['known_headless_main_usage']; assert usage['total_tokens']==7931
    call=SOURCE/'control-model/calls/0001-m4_plan'
    observer=read(call/'observer-receipt.private.json')
    assert observer['accepted'] is True and observer['prompt_process_launched'] is True and not observer['faults']
    spec=importlib.util.spec_from_file_location('control_retention_r3',HELPER)
    retention=importlib.util.module_from_spec(spec);spec.loader.exec_module(retention)
    originals=sorted(retention.regular_files(SOURCE))
    public={'control.py':SOURCE/'control.py','closure.json':SOURCE/'closure.json',
            'native-start.json':start,'native-join.json':join,
            'driver.log':WORK/(PREFIX+'-execute.log'),'archive-helper.py':Path(__file__),
            'retention-helper-source.py':HELPER}
    prepare_start=WORK/(PREFIX+'-prepare-native-start.json')
    prepare_join=WORK/(PREFIX+'-prepare-native-join.json')
    assert read(prepare_start)['session_id']==read(prepare_join)['native_session_id']==1920
    assert read(prepare_join)['result']['exit_code']==0
    public.update({'prepare-native-start.json':prepare_start, 'prepare-native-join.json':prepare_join,
                   'prepare.log':WORK/(PREFIX+'-prepare.log')})
    frozen=read(SOURCE/'manifest.json')['frozen_files']
    pinned=[]
    for name,digest in sorted(frozen.items()):
        p=Path(name)
        assert not retention.excluded(p), 'credential-shaped input must not be retained'
        assert sha(p.read_bytes())==digest, 'frozen control source/input changed'
        pinned.append(p)
    inputs=sorted(set(originals+list(public.values())+pinned))
    before={str(p):stamp(p) for p in inputs}
    PRIVATE.mkdir(parents=True); zpath=PRIVATE/'originals-without-credentials.zip'
    members=retention.add_zip(zpath,((p.relative_to(SOURCE).as_posix(),p.read_bytes(),str(p)) for p in originals))
    with zipfile.ZipFile(zpath) as z:
        assert z.testzip() is None and z.namelist()==[r['path'] for r in members]
        for r in members:
            raw=z.read(r['path']); assert sha(raw)==r['sha256']==before[r['origin']]['sha256'] and len(raw)==r['byte_count']
    frozen_zip=PRIVATE/'frozen-source-and-input-pins.zip'
    frozen_members=retention.add_zip(frozen_zip,((f'{i:04d}/{p.name}',p.read_bytes(),str(p)) for i,p in enumerate(pinned)))
    with zipfile.ZipFile(frozen_zip) as z:
        assert z.testzip() is None
        for row in frozen_members:
            assert sha(z.read(row['path']))==row['sha256']==frozen[row['origin']]
    assert before=={str(p):stamp(p) for p in inputs}
    retained={'schema':'grok130-normal-control-retention-v1','archive_path':str(zpath),
        'archive_sha256':sha(zpath.read_bytes()),'members':members,
        'excluded_credentials':retention.EXCLUSIONS,'pruned_reparse_paths':sorted(retention.PRUNED_LINKS),
        'inputs_before':before,'inputs_after':before, 'frozen_pins_archive_path':str(frozen_zip),
        'frozen_pins_archive_sha256':sha(frozen_zip.read_bytes()),'frozen_pin_members':frozen_members}
    write(PRIVATE/'retention-manifest.json',retained)
    DEST.mkdir(parents=True);(DEST/'.gitattributes').write_bytes(b'* -text\n')
    public['private-retention-manifest.json']=PRIVATE/'retention-manifest.json'
    for name,p in public.items():
        (DEST/name).write_bytes(p.read_bytes());assert (DEST/name).read_bytes()==p.read_bytes()
    (DEST/'README.md').write_bytes('''# Successful normal Grok TRAIN control r3

One unchanged, already-exported public TRAIN m4_plan request completed through the explicit
Grok 1.0.30 normal streaming-JSON deployment with model grok-4.6. Native session 70385 joined
with driver exit 0. The accepted model response and persisted ledger passed independent replay
inside the closed driver. Known MAIN usage is 7,931 tokens; title/all-opportunity settlement is unknown.

The original request, exact source/input pins, raw model and account observations, response,
reservation and ledger are retained privately with per-member hashes. Credentials are excluded.
Global auth metadata and frozen source bytes were unchanged. There was no VAL access or model retry.
The earlier expired-login control stays a separate failure; this result does not retroactively change it.

This establishes one real invocation and replayable artifacts. It does not establish module benefit,
complete factorial performance, formal calibration or VAL acceptance. Exact tested runtime source
43ccf107 is bound by the frozen control manifest and retained in the private source-pin archive.
The prompt process completed in 233.385395 seconds against a frozen 240 second cap.
This single completed call does not establish deployment stability or explain all prior timeouts.
'''.encode())
    assert before=={str(p):stamp(p) for p in inputs}
    files=[{'path':p.name,'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for p in sorted(DEST.iterdir())]
    write(DEST/'published-manifest.json',{'schema':'grok130-normal-control-public-v1','files':files})
    print(json.dumps({'archive':str(DEST),'public_files':len(files)+1,'private_originals':len(members),
                      'manifest_sha256':sha((DEST/'published-manifest.json').read_bytes())}))
if __name__=='__main__':main()
