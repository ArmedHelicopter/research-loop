"""Preserve selected public synthetic primary outputs with an independent fixture oracle.

Run only after the final root frozen check has completed. No producer is rerun.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import zipfile

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
ROOT = BASE/'artifact-evidence-provenance'
parser = argparse.ArgumentParser()
parser.add_argument('--prefix', required=True)
parser.add_argument('--tests', required=True, type=int)
parser.add_argument('--attempts', required=True)
args = parser.parse_args()
PREFIX = BASE/'work'/args.prefix
OUT = ROOT/'results/modular-engineering-20260915/legacy-primary-artifacts-r1'
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from evaluation.modular import legacy_primary_packet_artifacts as artifacts
from evaluation.modular.train_io import read_primary_train_sources
from research_loop.modular.artifact_source_archive import ArchivedSourceResolver
from research_loop.modular.contracts import DataIdentity
from research_loop.ontology import ContractError, digest
from test_modular_train_io import Custody


def sha(raw): return hashlib.sha256(raw).hexdigest()
def write(path, body):
    with path.open('xb') as stream:
        stream.write((json.dumps(body, indent=2, ensure_ascii=False)+'\n').encode())


def oracle(case):
    """Reconstruct the frozen synthetic fixture from known constants and original buffers."""
    snapshot = case/'snapshot'
    disc = snapshot/'discovery/upstream/discoverybench/synth/train/family_1_1'
    blade = snapshot/'scienceagent/work/BLADE/blade_bench/datasets/fish'
    expected = {
        disc/'metadata_1.json':json.dumps({'queries':[{'question':'public q','difficulty':1}],
            'datasets':[{'name':'data.csv','description':'d','columns':[{'name':'x','description':'x'}]}]}).encode(),
        disc/'data.csv':('x'+os.linesep+'1'+os.linesep).encode(),
        blade/'info.json':json.dumps({'research_questions':['public blade q'],
            'data_desc':{'dataset_description':'public instructions','fields':['x','y']}}).encode(),
        blade/'data.csv':('x,y'+os.linesep+'1,2'+os.linesep).encode(),
    }
    for path, raw in expected.items(): assert path.read_bytes() == raw, path
    rows = []
    for benchmark, task_id, group, official, relative, files in [
        ('discoverybench','synth:train:family_1_1','disc-group','synth/train','synth/train/family_1_1',[disc/'metadata_1.json',disc/'data.csv']),
        ('blade','fish','blade-group','unsplit','fish',[blade/'info.json',blade/'data.csv']),
    ]:
        rows.append({'benchmark':benchmark,'task_id':task_id,'source_group':group,'official_split':official,
            'relative_path':relative,'content_hashes':[sha(expected[path]) for path in files],'exposure':'exposed'})
    inventory_digest = digest(sorted(rows,key=lambda row:(row['benchmark'],row['task_id'])))
    split_rows = [{'item':row['benchmark']+':'+row['task_id'],'group':row['source_group'],
                   'domain':'train','official_split':row['official_split']} for row in rows]
    split = {'digest':digest(split_rows),'rows':split_rows}
    identities = [DataIdentity(row['benchmark'],row['task_id'],row['source_group'],inventory_digest,split['digest'],'train') for row in rows]
    # The final tests retain this controller input before producing any packet.
    # Verify it against the frozen fixture constants, then read it as the oracle.
    retained = json.loads((case/'independent-custody.json').read_bytes())
    state = {'inventory':rows,'inventory_digest':inventory_digest,'split':split}
    assert retained == {'schema':'synthetic-primary-custody-input-v1','state':state,
                        'identities':[identity.data() for identity in identities]}
    custody = Custody([DataIdentity.parse(value) for value in retained['identities']],retained['state'])
    return read_primary_train_sources(custody,snapshot,tuple(row['item'] for row in split_rows))


closed = json.loads(Path(str(PREFIX)+'-closed.json').read_bytes())
assert closed['exit_code'] == 0 and closed['source_unchanged']
assert closed['junit'] == {'tests':args.tests,'failures':0,'errors':0,'skipped':0}
OUT.mkdir(parents=True, exist_ok=False)
(OUT/'.gitattributes').write_bytes(b'* -text\n')
originals = []
def original(source, name=None):
    name = name or source.name
    shutil.copyfile(source,OUT/name)
    raw = source.read_bytes()
    originals.append({'file':name,'bytes':len(raw),'sha256':sha(raw)})
for suffix in ('-before.json','-closed.json','.xml','-sources.zip','-source-members.json'):
    original(Path(str(PREFIX)+suffix))
original(Path(__file__))
original(Path(args.attempts),'agent-verification-attempts.md')
original(Path(args.attempts).with_name('primary-packet-verification.md'),'agent-initial-verification-attempts.md')
source_meta = json.loads(Path(str(PREFIX)+'-source-members.json').read_bytes())
resolver = ArchivedSourceResolver(Path(str(PREFIX)+'-sources.zip'),source_meta['archive_sha256'],ROOT)
records = []
patterns = ('test_actual_exporter_*','test_partial_write_and_*','test_failure_storage_failure*')
cases = sorted({case for pattern in patterns for case in PREFIX.glob(pattern)
    if not case.name.endswith('current') and not case.is_symlink() and not case.is_junction()})
for case in cases:
    sources = oracle(case)
    roots = list((case/'out').glob('*/*')) if (case/'out').exists() else [case/'packet']
    for root in roots:
        source = next((value for value in sources if root.parent.name == value.task.identity.benchmark),sources[0])
        before = {path.name:sha(path.read_bytes()) for path in root.iterdir() if path.is_file()}
        assert all(not path.is_symlink() and not path.is_junction() and path.is_file() for path in root.iterdir())
        if case.name.startswith('test_actual_exporter'):
            status='produced'; report=artifacts.verify(root,source).data()
            assert report['schema']=='legacy-primary-train-packet-v2'
        elif case.name.startswith('test_partial_write'):
            status='failed'; report=artifacts.inspect_failure(root,source).data()
            assert report['storage_integrity_verified'] and not report['operation_validated'] and not report['acceptance_eligible']
            try: artifacts.verify(root,source)
            except ContractError: pass
            else: raise AssertionError('failed packet accepted')
        else:
            status='incomplete'; report={'storage_integrity_verified':False,'reader_rejected_incomplete':True,'operation_validated':False}
            for reader in (artifacts.verify,artifacts.inspect_failure):
                try: reader(root,source)
                except ContractError: pass
                else: raise AssertionError('incomplete packet accepted')
        assert before == {path.name:sha(path.read_bytes()) for path in root.iterdir() if path.is_file()}
        for key, value in artifacts.sources().items():
            if key!='schema': resolver.verify_snapshot(value)
        name=case.name+'-'+root.name+'.zip'
        with zipfile.ZipFile(OUT/name,'x',zipfile.ZIP_DEFLATED) as archive:
            for filename in sorted(before): archive.writestr(filename,(root/filename).read_bytes())
        raw=(OUT/name).read_bytes(); item={'file':name,'bytes':len(raw),'sha256':sha(raw)}
        originals.append(item)
        records.append({**item,'original_root':str(root),'status':status,'report':report,
            'independent_oracle':'original pre-export independent-custody.json, checked against frozen fixture constants and original source buffers',
            'independent_custody_sha256':sha((case/'independent-custody.json').read_bytes()),
            'task_digest':source.task.content_hash,'source_anchor_digest':source.anchor.content_hash,
            'read_only':True,'source_archive_reverified':True,'files':before})
assert [sum(row['status']==status for row in records) for status in ('produced','failed','incomplete')]==[2,6,1]
write(OUT/'manifest.json',{'schema':'legacy-primary-artifact-archive-v1','source_commit':closed['commit'],
    'source_root':str(ROOT),'originals':originals,'specimens':records,'new_paid_api_calls':0,
    'scope':'two successful synthetic packets, six failed write/seal prefixes, one incomplete prefix; no source/private inventory copied',
    'real_validation_access':False,'scientific_effect':'not_measured'})
for item in originals:
    raw=(OUT/item['file']).read_bytes()
    assert sha(raw)==item['sha256'] and len(raw)==item['bytes']
    if item['file'].endswith('.zip'):
        with zipfile.ZipFile(OUT/item['file']) as archive: assert archive.testzip() is None
write(OUT/'verification.json',{'status':'verified','original_files':len(originals),'specimens':len(records),
    'produced':2,'failed_storage_only':6,'incomplete_rejected':1,'all_original_bytes_rechecked':True,
    'source_archive_reverified':True,'private_material_copied':False,'read_only':True})
print(json.dumps({'archive':str(OUT),'original_files':len(originals),'specimens':len(records)}))
