import hashlib,json,shutil,subprocess,zipfile,xml.etree.ElementTree as ET
from pathlib import Path
repo=Path('E:/_ryanDev/AI/research-loop-modular/provider-core');work=repo.parent/'work'
archive=repo/'results/train-provider-core-repair-20260914'
sha=lambda b:hashlib.sha256(b).hexdigest()
git=lambda *args:subprocess.check_output(['git','-C',str(repo),*args])
source=git('rev-parse','HEAD').decode().strip();assert not git('status','--porcelain').strip()
run=work/'provider-core-r4';check=json.loads((run/'check.json').read_bytes())
assert check['source_commit']==source and check['exit_code']==0 and check['source_unchanged']
shutil.copyfile(work/'provider-core-repair-check.py',run/'check-runner.py')
archive.mkdir(exist_ok=False);(archive/'.gitattributes').write_bytes(b'** -text\n')
checkpoint=repo/'results/train-provider-core-20260914.zip'
assert sha(checkpoint.read_bytes())=='a9f68c503df696448e3d3a3690a21512563ae4e77d1d8a82b0acf1d0080b2377'
shutil.copyfile(checkpoint,archive/'checkpoint-52.zip')
raw_files=[];excluded=0
for p in sorted(run.rglob('*')):
    if not p.is_file() or p.is_symlink():continue
    if p.name.lower() in ('auth.json','login-backup.json') or p.suffix.lower() in ('.pyc','.key'):
        excluded+=1;continue
    raw_files.append(p)
raw_manifest={p.relative_to(run).as_posix():sha(p.read_bytes()) for p in raw_files}
with zipfile.ZipFile(archive/'repair-run-raw.zip','x',compression=zipfile.ZIP_DEFLATED) as z:
    for p in raw_files:z.write(p,p.relative_to(run).as_posix())
with zipfile.ZipFile(archive/'repair-run-raw.zip') as z:
    assert set(z.namelist())==set(raw_manifest)
    assert all(z.read(p.relative_to(run).as_posix())==p.read_bytes() for p in raw_files)
(archive/'repair-run-MANIFEST.json').write_text(json.dumps(raw_manifest,indent=2),encoding='utf-8')
copy_map=[{'original':str(p),'container':'repair-run-raw.zip','member':p.relative_to(run).as_posix(),'sha256':raw_manifest[p.relative_to(run).as_posix()]} for p in raw_files]
(archive/'original-copy-map.json').write_text(json.dumps(copy_map,indent=2),encoding='utf-8')
for rel in ('research_loop/modular/train_provider.py','research_loop/modular/grok_train_solver.py','research_loop/modular/grok_acp_transport.py','research_loop/modular/model_port.py','research_loop/modular/contracts.py','research_loop/ontology.py','tests/test_train_provider.py','tests/test_grok_train_solver.py','tests/test_modular_train_controller.py','tests/test_label_isolation.py','tests/fixtures/grok_acp_peer.py','docs/TRAIN_PROVIDER_CORE_V1.md'):
    dst=archive/'tested-source'/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(repo/rel,dst)
xml=ET.parse(run/'pytest.xml').getroot();suites=list(xml.iter('testsuite'))
counts={k:sum(int(s.get(k,0)) for s in suites) for k in ('tests','failures','errors','skipped')}
wires=list((run/'pytest').rglob('requests.private.jsonl'))
native_requests=sum(sum(json.loads(line).get('method')=='session/prompt' for line in p.read_bytes().splitlines()) for p in wires)
summary={'schema':'train-provider-core-repair-evidence-v1',**check,**counts,'synthetic_native_main_requests':native_requests,
    'raw_files':len(raw_files),'opaque_login_files_excluded_without_reading':excluded,
    'checkpoint_zip_sha256':sha(checkpoint.read_bytes()),'scientific_validation_performed':False,
    'legacy_controller_or_port_source_changed':False,'checkpoint_known_gaps':'malformed-sibling scalar recovery and per-cell identical-call span selection repaired here'}
(archive/'check-summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
shutil.copyfile(work/'provider-core-final-archive.py',archive/'archive-builder.py')
(archive/'README.md').write_text(f'''# TRAIN provider core repaired synthetic evidence

Final source `{source}` passed {counts['tests']} frozen checks with zero failures/errors, {check['source_hash_count']} source files unchanged, and zero real model/API calls. Native synthetic streams contain {native_requests} MAIN requests. No native Grok executable was launched, and no scientific scoring or validation occurred.

This repairs two reviewed gaps after the preserved 52-test checkpoint: usage extraction now checks malformed sibling branches independently and conservatively recovers only unambiguous failed-frame scalars; declared immutable per-cell call-ID tuples bind identical repeated requests to their actual spans with strict ordering, exact coverage and explicit boolean eligibility mode. Failed frames remain incomplete and ineligible. The old legacy token ledger remains separate from recovered known usage. No global cross-invocation non-reuse claim is made: downstream controllers must freeze spans and enforce required disjointness.

repair-run-raw.zip contains every retained raw r4 test output, XML, source hash manifest, native original request/response/reservation/config/observer stream, Codex reviewed-context evidence, ledger and seal, except opaque fixture login files. repair-run-MANIFEST.json hashes each raw member; original-copy-map.json maps the original synthetic E-drive paths to these exact bytes. The ZIP was checked member-by-member against the original disk files.

checkpoint-52.zip is byte-identical to the immutable earlier checkpoint (SHA-256 {sha(checkpoint.read_bytes())}). It preserves the initial 12 fixture failures/8 passes, the 20-pass checkpoint, and the 52-pass checkpoint with all raw evidence and their distinct frozen source identities. Those checkpoints do not imply the two later-found gaps were already repaired.

The tested-source directory contains exact current disk bytes. This archive's .gitattributes disables text conversion before staging. MANIFEST.json hashes every other outer member. The adjacent outer ZIP must match these outer member bytes, and committed Git blobs must match them too. The inner raw ZIP is independently checked against its per-member manifest; thus outer byte equality does not substitute for original-member checks.

Only new train_provider.py, its focused tests/docs, and evidence archives changed. Existing controller admission, _safe_call, FrozenProviderLedger, and legacy schemas remain untouched. This is provider-core engineering; remaining controller integration and C5 selection/calibration/validation remain open.
''',encoding='utf-8')
manifest={p.relative_to(archive).as_posix():sha(p.read_bytes()) for p in sorted(archive.rglob('*')) if p.is_file()}
(archive/'MANIFEST.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
outer=archive.with_suffix('.zip')
with zipfile.ZipFile(outer,'x',compression=zipfile.ZIP_DEFLATED) as z:
    for p in sorted(archive.rglob('*')):
        if p.is_file():z.write(p,p.relative_to(archive).as_posix())
with zipfile.ZipFile(outer) as z:
    assert set(z.namelist())==set(manifest)|{'MANIFEST.json'}
    assert all(z.read(p.relative_to(archive).as_posix())==p.read_bytes() for p in archive.rglob('*') if p.is_file())
    assert all(sha(z.read(k))==v for k,v in manifest.items())
proof={'archive':str(archive),'source_commit':source,'outer_payload_files':len(manifest)+1,'raw_member_files':len(raw_files),'zip_sha256':sha(outer.read_bytes()),'disk_inner_zip_manifest_equal':True,'disk_outer_zip_manifest_equal':True,**counts,'synthetic_native_main_requests':native_requests}
(work/'provider-core-final-byte-proof.json').write_text(json.dumps(proof,indent=2));print(json.dumps(proof))
