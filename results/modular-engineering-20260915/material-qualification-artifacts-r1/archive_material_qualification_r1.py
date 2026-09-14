"""Read and retain actual qualification specimens; never rerun producers."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
ROOT = BASE/'artifact-evidence-provenance'
PREFIX = Path(sys.argv[1])
OUT = ROOT/'results/modular-engineering-20260915/material-qualification-artifacts-r1'
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from research_loop.modular.material_qualification_artifacts import MaterialQualificationArtifacts as Artifacts
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.lineage_combination_material import FrozenLineageMaterial
from research_loop.modular.admission_combination import FrozenAdmissionMaterial
from research_loop.modular.state_retrieval_combination_driver import FrozenStateRetrievalMaterial
from research_loop.ontology import ContractError
from test_lineage_combination_controller import _sources
from test_admission_combination import sources
from test_execution_improvement_train_controller import provenance

R = FrozenRecord.from_dict
def sha(raw): return hashlib.sha256(raw).hexdigest()
def tree(root):
    found = {}
    for path in root.rglob('*'):
        assert not path.is_symlink() and not path.is_junction(), path
        if path.is_file(): found[path.relative_to(root).as_posix()] = path.read_bytes()
    return found
def write(path, value):
    with path.open('xb') as stream:
        stream.write((json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode())

closed = json.loads(Path(str(PREFIX)+'-closed.json').read_bytes())
assert closed['exit_code'] == 0 and closed['source_unchanged']
assert all(closed['junit'][key] == 0 for key in ('failures', 'errors', 'skipped'))
assert closed['junit']['tests'] >= 27
source = json.loads(Path(str(PREFIX)+'-source-members.json').read_bytes())
source_zip = Path(str(PREFIX)+'-sources.zip')
assert sha(source_zip.read_bytes()) == source['archive_sha256']
with zipfile.ZipFile(source_zip) as archive:
    assert archive.testzip() is None
    for member in source['members']:
        raw = archive.read(member['path'])
        assert len(raw) == member['bytes'] and sha(raw) == member['sha256']

OUT.mkdir(parents=True, exist_ok=False)
(OUT/'.gitattributes').write_bytes(b'* -text\n')
originals = []
def original(path, name=None):
    name = name or path.name
    shutil.copyfile(path, OUT/name)
    raw = path.read_bytes()
    originals.append({'file': name, 'bytes': len(raw), 'sha256': sha(raw)})
for suffix in ('-before.json', '-closed.json', '.xml', '-sources.zip', '-source-members.json'):
    original(Path(str(PREFIX)+suffix))
original(Path(__file__))
for name in ('material-consumer-review-r1.md', 'grok-headless-root-cause-readonly-r1.md'):
    original(BASE/'work'/name)
for name in ('material-own-r2.xml', 'material-own-r2-output.txt'):
    original(BASE/'work'/name)
original(BASE/'material-qualification-artifacts/work/material-qualification-artifacts-20260915.md',
    'initial-provisional-implementation.md')
original(BASE/'work/material-consumer-probe-r1/outcome.json', 'initial-consumer-probe.json')

records = []
def specimen(receipt, expected, *, name, attack=False):
    companion = receipt.with_name(receipt.name+'.artifacts')
    before = tree(companion)
    actual_receipt = receipt.read_bytes() if receipt.is_file() else None
    temporary = receipt.with_suffix(receipt.suffix+'.tmp')
    actual_temporary = temporary.read_bytes() if temporary.is_file() else None
    calls = []
    candidates = [sources(calls), _sources(calls), provenance(calls, corpus=True)]
    verifier = next(value for value in candidates if value.binding().data() == expected['binding'])
    classes = {'lineage-combination-material-v1': FrozenLineageMaterial,
        'admission-combination-material-v1': FrozenAdmissionMaterial,
        'state-retrieval-material-v1': FrozenStateRetrievalMaterial}
    # The class spelling is frozen by the independently retained host input;
    # fallback only uses the explicit supported class's known schema.
    by_name = {c.__name__: c for c in classes.values()}
    cls = by_name[expected['material_type']] if 'material_type' in expected else classes[expected['material']['schema']]
    material = cls(R(expected['material']))
    cell = R(expected['cell_binding'])
    assert verifier.request(material, cell).data() == expected['request']
    try:
        _, rows, seal, _ = Artifacts.inspect(receipt)
    except ContractError:
        status = 'incomplete'; rows = []
    else:
        status = 'failed_storage_only' if seal is None else (
            'rejected' if rows[-1]['data']['outcome'] == 'rejected' else 'accepted')
    try:
        digest = verifier.replay(material, receipt, cell_binding=cell)
    except ContractError:
        assert attack or status != 'accepted'
    else:
        assert not attack and status == 'accepted' and digest == sha(actual_receipt)
    assert calls == [] and tree(companion) == before
    assert (receipt.read_bytes() if receipt.is_file() else None) == actual_receipt
    assert (temporary.read_bytes() if temporary.is_file() else None) == actual_temporary
    archive_path = OUT/(name+'.zip')
    with zipfile.ZipFile(archive_path, 'x', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('independent-input.json', R(expected).encoded.encode())
        if actual_receipt is not None: archive.writestr(receipt.name, actual_receipt)
        if actual_temporary is not None: archive.writestr(temporary.name, actual_temporary)
        for relative, raw in sorted(before.items()): archive.writestr(companion.name+'/'+relative, raw)
    raw = archive_path.read_bytes()
    item = {'file': archive_path.name, 'bytes': len(raw), 'sha256': sha(raw)}
    originals.append(item)
    records.append({**item, 'original_receipt': str(receipt), 'status': 'attack_rejected' if attack else status,
        'storage_status': status, 'events': len(rows), 'independent_input_sha256': sha(R(expected).encoded.encode()),
        'files': {key: sha(value) for key, value in before.items()}, 'read_only': True,
        'callbacks_on_read': 0, 'qualification_accepted': not attack and status == 'accepted'})

unit_prefixes = ('test_partial_sidecar_failure_', 'test_secondary_failure_does_',
    'test_partial_terminal_seal_', 'test_post_return_custody_', 'test_admission_rejection_is_')
unit_count = host_count = 0
for case in sorted(PREFIX.iterdir()):
    if not case.is_dir() or case.is_symlink() or case.is_junction(): continue
    if case.name.startswith(unit_prefixes):
        expected = json.loads((case/'independent-qualification-inputs.json').read_bytes())
        specimen(case/'attempt/source.json', expected, name=case.name)
        unit_count += 1
    if (case/'qualification-expected').is_dir():
        host_count += 1
        expected_entries = [json.loads(p.read_bytes()) for p in (case/'qualification-expected').glob('*.json')]
        for expected in expected_entries:
            receipt = case/expected['receipt']
            specimen(receipt, expected, name=case.name+'-'+receipt.parent.parent.name[:12]+'-'+receipt.parent.name)
        for replica in sorted((case/'attack-replicas').glob('*')) if (case/'attack-replicas').exists() else []:
            attack = json.loads((replica/'attack.json').read_bytes())
            expected = next(e for e in expected_entries if e['cell_binding'] == attack['cell_binding']
                and Path(e['receipt']).parent.name == attack['role'])
            specimen(replica/'source.json', expected, name='attack-'+replica.name, attack=True)
        native = tree(case/'common-run')
        path = OUT/(case.name+'-host.zip')
        with zipfile.ZipFile(path, 'x', zipfile.ZIP_DEFLATED) as archive:
            for relative, raw in sorted(native.items()): archive.writestr('common-run/'+relative, raw)
            archive.writestr('qualification-host-inputs.json', (case/'qualification-host-inputs.json').read_bytes())
            for p in (case/'qualification-expected').glob('*.json'):
                archive.writestr('qualification-expected/'+p.name, p.read_bytes())
        raw = path.read_bytes()
        originals.append({'file': path.name, 'bytes': len(raw), 'sha256': sha(raw)})
assert unit_count == 13 and host_count == 3, (unit_count, host_count)
counts = {status: sum(row['status'] == status for row in records)
    for status in ('accepted', 'rejected', 'failed_storage_only', 'incomplete', 'attack_rejected')}
assert counts == {'accepted':5, 'rejected':5, 'failed_storage_only':7, 'incomplete':3, 'attack_rejected':4}, counts
for item in originals:
    raw = (OUT/item['file']).read_bytes()
    assert len(raw) == item['bytes'] and sha(raw) == item['sha256']
    if item['file'].endswith('.zip'):
        with zipfile.ZipFile(OUT/item['file']) as archive: assert archive.testzip() is None
write(OUT/'manifest.json', {'schema':'material-qualification-artifact-archive-v1', 'source_commit':closed['commit'],
    'originals': originals, 'specimens': records, 'counts': counts, 'source_archive_members_verified':len(source['members']),
    'input_origin':'actual caller inputs retained before each producer; not derived from qualification receipts',
    'new_paid_api_calls':0, 'real_validation_access':False, 'scientific_effect':'not_measured'})
write(OUT/'verification.json', {'status':'verified', 'original_files':len(originals), 'specimens':len(records),
    'counts':counts, 'read_only':True, 'producers_rerun':False, 'callbacks_on_read':0})
print(json.dumps({'archive':str(OUT), 'original_files':len(originals), 'specimens':len(records), 'counts':counts}))
