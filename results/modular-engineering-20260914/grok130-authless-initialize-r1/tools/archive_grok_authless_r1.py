"""Archive only public diagnostic receipts/code and their pinned dependencies."""
import hashlib
import json
from pathlib import Path
import shutil

WORK = Path(__file__).resolve().parent
ORIGIN = WORK/'grok130-authless-initialize-r1'
INTEGRATION = WORK.parent/'integration'
STAGE = WORK/'grok130-authless-public-staging-r1'
DEST = WORK.parent/'artifact-evidence-provenance/results/modular-engineering-20260914/grok130-authless-initialize-r1'
assert not STAGE.exists() and not DEST.exists()
read = lambda path: json.loads(path.read_bytes())
sha = lambda raw: hashlib.sha256(raw).hexdigest()
envelope, closed, checks = [read(ORIGIN/name) for name in ('envelope.json','closure.json','synthetic-checks.json')]
assert closed['envelope_sha256'] == sha((ORIGIN/'envelope.json').read_bytes())
assert envelope['synthetic_checks_sha256'] == sha((ORIGIN/'synthetic-checks.json').read_bytes())
assert closed['native_launches'] == 1 and closed['outbound_method_counts'] == {
    'initialize':1,'session/new':0,'session/prompt':0,'authenticate':0,'_x.ai/billing':0,'_x.ai/auto-topup-rule':0}
assert closed['faults'] == ['timeout'] and not closed['response_received']
assert closed['auth_path_appeared'] is False and closed['post_context_valid'] is True
assert all(closed['owner'][key] for key in ('job_owned','creation_matches_at_close','closed','held_handle_closed'))
assert closed['settled_additional_charge_usd'] is None
assert len(checks['cases']) == 4 and all(row['passed'] and row['owner']['held_handle_closed'] for row in checks['cases'])
STAGE.mkdir()
items = []
def copy(path, relative):
    raw = path.read_bytes(); target = STAGE/relative
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream: stream.write(raw)
    items.append({'path':relative,'bytes':len(raw),'sha256':sha(raw),'original':str(path)})
public_names = {'driver.py','init_engine.py','peer.py','envelope.json','closure.json',
    'native-reservation.json','synthetic-checks.json','FINDING.md'}
for name in sorted(public_names): copy(ORIGIN/name, name)
for name, digest in envelope['frozen_files'].items():
    path = Path(name)
    assert sha(path.read_bytes()) == digest
    if path.is_relative_to(INTEGRATION):
        assert path.suffix == '.py'
        copy(path, 'sources/integration/'+path.relative_to(INTEGRATION).as_posix())
    elif path == ORIGIN/'home/config.toml': copy(path, 'sources/config.toml')
    elif path.parent == ORIGIN: assert path.name in public_names
    else: assert path == WORK/'grok-cli-1.0.30/grok.exe'  # Retained by original binary pin; not duplicated.
copy(Path(__file__), 'tools/'+Path(__file__).name)
manifest = {'schema':'authless-initialize-public-archive-v1','items':items,
    'raw_native_streams_and_credentials_included':False,'native_model_generation_proven':False,
    'scientific_effectiveness_proven':False,'binary_archived':False,
    'pinned_executable_sha256':envelope['frozen_files'][str(WORK/'grok-cli-1.0.30/grok.exe')],
    'settlement_status':'unknown','native_launches':1}
(STAGE/'MANIFEST.json').write_bytes((json.dumps(manifest,indent=2)+'\n').encode())
(STAGE/'.gitattributes').write_bytes(b'* -text\n')
shutil.copytree(STAGE,DEST)
assert all(p.read_bytes()==(DEST/p.relative_to(STAGE)).read_bytes() for p in STAGE.rglob('*') if p.is_file())
print(json.dumps({'archive':str(DEST),'files':len(items)+2,'source_pins_match':True,'raw_private_streams_included':False}))
