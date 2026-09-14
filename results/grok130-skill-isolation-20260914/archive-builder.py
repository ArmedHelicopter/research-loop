"""Compact closed-checkpoint archive; no opaque auth/key or link-target reads."""
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
import zipfile

base = Path('E:/_ryanDev/AI/research-loop-modular')
repo = base/'grok130-skill-isolation'
name = 'grok130-skill-isolation-20260914'
dest = repo/'results'/name
runs = [base/'work'/f'grok130-skill-isolation-r{i}' for i in (1, 2, 3)]
sha = lambda b: hashlib.sha256(b).hexdigest()
checks = []
for run in runs:
    check = json.loads((run/'check.json').read_bytes())
    before = json.loads((run/'source-before.json').read_bytes())
    assert check['source_unchanged'] and not check['clean_status']
    assert before == json.loads((run/'source-after.json').read_bytes())
    with zipfile.ZipFile(run/'exact-tested-source.zip') as source:
        assert set(source.namelist()) == set(before)
        assert all(sha(source.read(p)) == h for p, h in before.items())
    suite = ET.parse(run/'pytest.xml').getroot().find('testsuite')
    checks.append({'run': run.name, 'check': check,
        'pytest_counts': {k: suite.attrib[k] for k in ('tests','failures','errors','skipped')},
        'exact_tested_source_zip_sha256': sha((run/'exact-tested-source.zip').read_bytes())})
dest.mkdir(parents=True, exist_ok=False)
def write(name, value):
    (dest/name).write_bytes(value if isinstance(value, bytes) else json.dumps(value, indent=2).encode())
write('.gitattributes', b'** -text\n')
members = {}; excluded = []; links = []
inputs = [(run.name, run, None) for run in runs]
inputs += [('public-chain-source', base/'work/grok130-reload-source-r1', {'.rs','.json','.md'}),
           ('public-isolation-source', base/'work/grok130-skill-isolation-source', {'.rs','.json'})]
with zipfile.ZipFile(dest/'raw-evidence.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
    for prefix, root, suffixes in inputs:
        for path in sorted(root.rglob('*')):
            rel = path.relative_to(root)
            if path.name == 'public-tree.json': continue
            if any(p in {'cache','__pycache__'} for p in rel.parts): continue
            member = prefix + '/' + rel.as_posix()
            if path.name in {'auth.json','login-backup.json','synthetic-login','synthetic-auth'} or path.suffix == '.key':
                excluded.append(member); continue
            if path.is_symlink():
                links.append({'member': member, 'link_target': str(path.readlink()),
                              'target_body_not_opened_through_link': True}); continue
            if not path.is_file() or (suffixes is not None and path.suffix not in suffixes): continue
            raw = path.read_bytes()
            assert member not in members
            archive.writestr(member, raw)
            members[member] = {'sha256': sha(raw), 'bytes': len(raw), 'original_path': str(path)}
with zipfile.ZipFile(dest/'raw-evidence.zip') as archive:
    assert set(archive.namelist()) == set(members)
    for member, row in members.items():
        raw = archive.read(member)
        assert sha(raw) == row['sha256'] and raw == Path(row['original_path']).read_bytes()
write('RAW-MANIFEST.json', members)
write('EXCLUSIONS.json', {'opaque_auth_or_key_bodies_never_opened': excluded,
    'symlink_metadata_without_target_reads': links, 'cache_and_large_public_tree_omitted': True})
write('CHECKPOINTS.json', checks)
write('SUMMARY.json', {'schema': 'grok130-skill-isolation-evidence-v1',
    'base': 'ddbc09c',
    'source_chain': ['5407b5bd77d9d53d1cba4e792d62002d6d3e05a7',
        'cad553b1b4bda06def42967a2e3e2b89611c34be', 'b3b62c18e6cad0bc3b805f2d3d27bc5cc93abf06'],
    'scope': 'Explicit Windows 1.0.30 readiness deployment v2 only; native_launch and ACP stream synthetic integration.',
    'runner_scope_correction': 'Historical runner scope string ordinary TRAIN is not this checkpoint scope. Suite args and this summary apply.',
    'checkpoints': {'r1': '105/105 initial integration and legacy regression',
        'r2': '2/2 regression failures retained: config-link target read and MAIN request written after expired deadline',
        'r3': '63/63 final source; all 24 isolated-v2 cases, old 1.0.30 entry/material/diagnostic compatibility and label isolation'},
    'raw_members': len(members), 'all_original_zip_manifest_bytes_equal': True,
    'exact_source_zips_match_all_692_frozen_disk_hashes_per_run': True,
    'original_real_r2': 'Untouched; MAIN and TITLE remain unknown. Its private capture is not copied into this synthetic archive.',
    'real_model_or_api_calls': 0, 'validation_calls': 0,
    'synthetic_child_models_public_prefix_filter_only': True,
    'binary_public_source_equivalence_verified': False,
    'real_effective_model_context_inspected': False,
    'legacy_1013_and_default_contract_unchanged': True,
    'material_and_diagnostic_v2_readiness_admission': 'explicitly rejected; unsupported reader schema is not disguised',
    'remaining': ['Root independent review', 'Separately authorized frozen actual readiness probe, if root elects to proceed',
        'Diagnostic/material portability of this new isolated context contract is outside this delivery']})
write('archive-builder.py', Path(__file__).read_bytes())
write('checkpoint-runner.py', (base/'work/ordinary-provider-check.py').read_bytes())
manifest = {p.name: {'sha256': sha(p.read_bytes()), 'bytes': p.stat().st_size}
            for p in dest.iterdir() if p.is_file()}
write('MANIFEST.json', manifest)
outer = dest.with_suffix('.zip')
with zipfile.ZipFile(outer, 'w', zipfile.ZIP_STORED) as archive:
    for path in sorted(dest.iterdir()): archive.writestr(path.name, path.read_bytes())
with zipfile.ZipFile(outer) as archive:
    assert set(archive.namelist()) == {p.name for p in dest.iterdir()}
    for member in archive.namelist(): assert archive.read(member) == (dest/member).read_bytes()
proof = {'archive': str(dest), 'outer_zip_sha256': sha(outer.read_bytes()),
    'raw_zip_sha256': sha((dest/'raw-evidence.zip').read_bytes()), 'raw_members': len(members),
    'payload_files': len(manifest)+1, 'all_original_zip_manifest_bytes_equal': True}
(base/'work'/f'{name}-byte-proof.json').write_text(json.dumps(proof, indent=2))
print(json.dumps(proof))
