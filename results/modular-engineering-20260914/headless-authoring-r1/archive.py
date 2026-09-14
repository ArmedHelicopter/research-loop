"""Archive frozen engineering evidence and public actual-run receipts; keep real bodies private."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

BASE=Path('E:/_ryanDev/AI/research-loop-modular'); WORK=BASE/'work'; TREE=BASE/'artifact-evidence-provenance'
sys.path.insert(0,str(TREE))
from evaluation.modular.diagnostic_subscription import sha
from evaluation.modular.calibration_pilot_process import load_record
from research_loop.modular.grok_headless_transport import HeadlessResult, verify_headless_request_binding
from research_loop.modular.contracts import FrozenRecord

OUT=TREE/'results/modular-engineering-20260914/headless-authoring-r1'
OUT.mkdir(parents=True,exist_ok=False)
records=[]
def copy(name,path):
    raw=Path(path).read_bytes(); dest=OUT/name; dest.parent.mkdir(parents=True,exist_ok=True); dest.write_bytes(raw)
    records.append({'path':name,'source_path':str(path),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})

prefix=WORK/'headless-authoring-frozen-r2'
before=json.loads(Path(str(prefix)+'-before.json').read_bytes())
closed=json.loads(Path(str(prefix)+'-closed.json').read_bytes())
assert closed['source_unchanged'] and closed['source_after']==before['source_before']
members=json.loads(Path(str(prefix)+'-source-members.json').read_bytes())
assert members['archive_sha256']==sha(Path(str(prefix)+'-sources.zip'))
with zipfile.ZipFile(Path(str(prefix)+'-sources.zip')) as z:
    assert {name:hashlib.sha256(z.read(name)).hexdigest() for name in z.namelist()}==before['source_before']
for suffix in ('-before.json','-closed.json','-source-members.json','-sources.zip','.xml'):
    copy('frozen'+suffix,Path(str(prefix)+suffix))
runtime=OUT/'synthetic-runtime.zip'
with zipfile.ZipFile(runtime,'x',zipfile.ZIP_DEFLATED) as z:
    for path in sorted(prefix.rglob('*')):
        if path.is_file(): z.write(path,path.relative_to(prefix).as_posix())
records.append({'path':'synthetic-runtime.zip','source_path':str(prefix),'bytes':runtime.stat().st_size,
    'sha256':sha(runtime),'scope':'synthetic test outputs only; contains synthetic authority keys'})
# Preserve the original 86-pass/2-fail frozen report and runtime without rewriting it.
old=WORK/'headless-authoring-frozen-r1'
for suffix in ('-before.json','-closed.json','-source-members.json','-sources.zip','.xml'):
    copy('original-r1'+suffix,Path(str(old)+suffix))
old_zip=OUT/'original-r1-synthetic-runtime.zip'
with zipfile.ZipFile(old_zip,'x',zipfile.ZIP_DEFLATED) as z:
    for path in sorted(old.rglob('*')):
        if path.is_file(): z.write(path,path.relative_to(old).as_posix())
records.append({'path':old_zip.name,'source_path':str(old),'bytes':old_zip.stat().st_size,
    'sha256':sha(old_zip),'scope':'original synthetic failing run, unchanged'})
# Retain the actual first exploratory rejection. It had no frozen source archive.
early=WORK/'headless-authoring-actual-seam-r1/test_actual_headless_authoring0/out/public-outcome.json'
if early.exists(): copy('exploratory-crlf-rejection.json',early)
replayed=[]; rejected_replayed=[]
actual=WORK/'headless-authoring-actual-run-r1'
if (actual/'public-parent-closure.json').exists():
    copy('actual/public-parent-closure.json',actual/'public-parent-closure.json')
    copy('actual/parent-reservation.json',actual/'parent-reservation.json')
    prepared=WORK/'headless-authoring-actual-preparation-r1'
    copy('actual/public-preparation.json',prepared/'public-preparation.json')
    copy('actual/public-freeze-metadata.json',prepared/'freeze/public-freeze-metadata.json')
    envelope=json.loads((prepared/'freeze/authoring-envelope.json').read_bytes())
    envelope_desc={'path':str(prepared/'freeze/authoring-envelope.json'),'sha256':sha(prepared/'freeze/authoring-envelope.json')}
    files=envelope['frozen_files']|{envelope_desc['path']:envelope_desc['sha256']}
    outcome_path=actual/'private-output/public-outcome.json'
    if outcome_path.exists():
        copy('actual/public-outcome.json',outcome_path)
        outcome=json.loads(outcome_path.read_bytes())
        entries={e['opportunity_id']:e for e in envelope['entries']}
        for state in outcome['authoring_outcomes']:
            oid=state['opportunity_id']; directory=actual/'private-output'/oid
            if not (directory/'native/observer-receipt.json').exists(): continue
            raw=json.loads((directory/'native/observer-receipt.json').read_bytes())
            response_path=directory/'native/response.private.json'
            response=FrozenRecord.from_dict(json.loads(response_path.read_bytes())) if raw['accepted'] else None
            native=HeadlessResult(FrozenRecord.from_dict(raw),response)
            copy(f'actual/{oid}/observer-receipt.json',directory/'native/observer-receipt.json')
            for phase in ('billing-before','billing-after'):
                folder=directory/'native'/phase
                for name in ('requests.json','observation.json'):
                    if (folder/name).exists(): copy(f'actual/{oid}/{phase}/{name}',folder/name)
            for name in ('command.json','process.json','stdout.private.jsonl','stderr.private.txt'):
                if (directory/'native'/name).exists(): copy(f'actual/{oid}/{name}',directory/'native'/name)
            if state.get('headless_request_binding_digest'):
                context=envelope['native_deployment']['slots'][oid]|{'executable':envelope['native_deployment']['executable']}
                verified=verify_headless_request_binding(native,entries[oid],directory,
                    envelope['limits']|{'native_context':context},files)
                saved=json.loads((directory/'headless-request-binding.json').read_bytes())
                assert verified.data()==saved and verified.content_hash==state['headless_request_binding_digest']
                copy(f'actual/{oid}/request-binding.json',directory/'headless-request-binding.json')
                (replayed if verified.data()['accepted'] else rejected_replayed).append(oid)
    for script in ('prepare_headless_authoring_r1.py','run_headless_authoring_actual_r1.py'):
        copy(script,WORK/script)
copy('archive.py',Path(__file__))
(OUT/'manifest.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
(OUT/'verification.json').write_text(json.dumps({'source_commit':before['commit'],
    'source_zip_and_frozen_checks_verified':True,'junit':closed['junit'],'original_files':len(records),
    'accepted_real_authoring_bindings_replayed':replayed,'rejected_real_authoring_bindings_replayed':rejected_replayed,'real_candidate_and_reference_bodies_published':False,
    'real_auth_or_private_authority_keys_published':False,'scientific_effectiveness_proven':False},indent=2),encoding='utf-8')
(OUT/'.gitattributes').write_bytes(b'* -text\n')
for row in records: assert sha(OUT/row['path'])==row['sha256']
print(json.dumps({'archive':str(OUT),'original_files':len(records),'accepted_real_bindings_replayed':len(replayed),'rejected_real_bindings_replayed':len(rejected_replayed)}))
