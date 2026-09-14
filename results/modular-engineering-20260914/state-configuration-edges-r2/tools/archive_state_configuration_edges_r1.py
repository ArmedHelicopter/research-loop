"""Preserve the exact graph check and selected actual source/target directories."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile

work = Path(__file__).resolve().parent
tree = work.parent/'artifact-evidence-provenance'
prefix = sys.argv[1]
expected_exit, expected_junit = {
    'state-configuration-edges-r1': (1, {'tests':32,'failures':1,'errors':0,'skipped':0}),
    'state-configuration-edges-r2': (0, {'tests':38,'failures':0,'errors':0,'skipped':0}),
}[prefix]
root = work/prefix/'state-improvement0/run'
stage = work/(prefix+'-staging-r1')
dest = tree/'results/modular-engineering-20260914'/prefix
assert not stage.exists() and not dest.exists()
sys.path.insert(0, str(tree))
from research_loop.modular.artifact_catalogue import ArtifactCatalogue
from research_loop.modular.artifact_source_archive import ArchivedSourceResolver
from research_loop.modular.contracts import DataIdentity, FrozenRecord

R = FrozenRecord.from_dict
sha = lambda raw: hashlib.sha256(raw).hexdigest()
read = lambda path: json.loads(path.read_bytes())
at = lambda suffix: work/(prefix+suffix)
before, closed, manifest = [read(at(s)) for s in ('-before.json','-closed.json','-source-members.json')]
assert before['commit'] == closed['commit'] == manifest['commit']
assert before['source_before'] == closed['source_after'] and closed['source_unchanged'] and closed['exit_code'] == expected_exit
assert sha(at('.xml').read_bytes()) == closed['report_sha256']
suites = list(ET.parse(at('.xml')).getroot().iter('testsuite'))
junit = {key:sum(int(s.get(key,0)) for s in suites) for key in ('tests','failures','errors','skipped')}
assert junit == closed['junit'] == expected_junit
assert sha(at('-sources.zip').read_bytes()) == manifest['archive_sha256']
with zipfile.ZipFile(at('-sources.zip')) as archive:
    members = {row['path']:row for row in manifest['members']}
    assert len(archive.namelist()) == len(set(archive.namelist())) == len(members)
    assert set(archive.namelist()) == set(members) == set(before['source_before'])
    for name, row in members.items():
        raw = archive.read(name)
        assert len(raw) == row['bytes'] and sha(raw) == row['sha256'] == before['source_before'][name]

receipt = read(root/'controller-receipt.json')
assert receipt['status'] == 'complete_train_engineering'
assert receipt['actual_builder_executions'] == 11 and receipt['actual_docker_attempts'] == receipt['actual_scorer_calls'] == 22
assert receipt['pruned_cells'] == [] and len(receipt['structural_exclusions']) == 2
assert receipt['scientific_effectiveness_proven'] is receipt['validation_opened'] is False
stage.mkdir(); items = []; catalogues = []; links = []

def copy(path, relative):
    raw = path.read_bytes(); target = stage/relative; target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream: stream.write(raw)
    items.append({'path':relative,'bytes':len(raw),'sha256':sha(raw),'original':str(path)})

for suffix in ('-before.json','-closed.json','-source-members.json','-sources.zip','.xml','-watchdog-config.json','-watchdog.json'):
    if at(suffix).is_file(): copy(at(suffix), 'checks/'+prefix+suffix)

builds = sorted((root/'builds').iterdir()); targets = sorted((root/'targets').iterdir())
assert len(builds) == 11 and len(targets) == 22
resolver = ArchivedSourceResolver(at('-sources.zip'), manifest['archive_sha256'], tree)
source_map = {}
for directory in [*builds, *targets]:
    is_build = directory.parent.name == 'builds'
    path = directory/('proposal' if is_build else 'runtime')/'artifacts.jsonl'
    first = json.loads(path.read_bytes().splitlines()[0])['descriptor']
    catalogue = ArtifactCatalogue(path, identity=DataIdentity(**first['identity']), **first['binding'],
        producer_source=first['producer_source'], source_resolver=resolver)
    records = catalogue.records()
    catalogue.verify(R(read(catalogue.seal_path)))
    if is_build:
        source_map[str(path.absolute())] = directory
        binding = read(directory/'build-receipt.json')
        assert binding['status'] == 'succeeded'
        actual = {p.relative_to(directory).as_posix():sha(p.read_bytes()) for p in directory.rglob('*')
            if p.is_file() and p.name != 'build-receipt.json'}
        assert actual == binding['files']
    else:
        trace = [json.loads(line) for line in (directory/'runtime/trace.jsonl').read_bytes().splitlines()]
        assert [r.data()['payload']['canonical'] for r in records if r.data()['kind'] == 'trace_event'] == trace
        record = records[1]; edge = record.data()['payload']['canonical']; source = edge['source']
        assert edge['relation'] == 'configured_by' and edge['task_evidence_support'] is False
        original = source_map[source['path']]
        source_path = original/'proposal/artifacts.jsonl'; source_raw = source_path.read_bytes()
        source_records = [FrozenRecord.from_dict(json.loads(line)['descriptor']) for line in source_raw.splitlines()]
        selected = next(r for r in source_records if r.content_hash == source['descriptor_digest'])
        assert sha(source_raw) == source['journal_sha256'] and len(source_raw) == source['journal_bytes']
        assert read(source_path.with_name(source_path.name+'.seal.json')) == source['seal']
        assert R(source['seal']).content_hash == source['seal_digest']
        assert selected.data()['kind'] == 'm9_candidate'
        assert selected.data()['payload']['canonical']['canonical'] == source['candidate'] == read(original/'candidate.json')
        assert R(source['candidate']).content_hash == source['candidate_digest']
        assert trace[1]['stage'] == 'state_train_configuration_bound'
        assert trace[1]['data'] == {'descriptor_digest':record.content_hash,'edge_digest':R(edge).content_hash}
        links.append({'target_catalogue':'runtime/'+path.relative_to(root).as_posix(),
            'target_descriptor':record.content_hash,'source_catalogue':'runtime/'+source_path.relative_to(root).as_posix(),
            'source_descriptor':source['descriptor_digest'],'candidate_digest':source['candidate_digest'],
            'source_identity':source['identity'],'target_identity':edge['target']['cell']['identity'],
            'recipe':source['recipe'],'relation':edge['relation'],'module_status':record.data()['status']})
    files = sorted(p for p in directory.rglob('*') if p.is_file())
    for path in files:
        name = path.relative_to(directory).as_posix()
        assert not path.is_symlink()
        pattern = (r'(build-receipt\.json|builder-receipt\.json|builder\.json|candidate\.json|m9-build-terminal\.json|'
            r'm9-builder-return\.json|phase\.jsonl|(?:proposal|runtime)/(?:artifacts\.jsonl(?:\.seal\.json)?|'
            r'claims\.jsonl|evidence\.jsonl|predictions\.jsonl|reviews\.jsonl|trace\.jsonl|analysis-1\.py)|'
            r'(?:source/)?source-verification\.json)')
        assert re.fullmatch(pattern,name),name
        copy(path,'runtime/'+path.relative_to(root).as_posix())
    catalogues.append({'path':'runtime/'+catalogue.path.relative_to(root).as_posix(),
        'descriptors':len(records),'files':len(files),'historical_semantic_replay_executed':False})

assert len(links) == 22 and len({row['source_catalogue'] for row in links}) == 11
assert sum(row['module_status'] == 'not_applied' for row in links) == 12
for name in ('plan.json','candidate-barrier.json','controller.jsonl','controller-receipt.json'):
    copy(root/name, 'controller/'+name)
copy(Path(__file__), 'tools/'+Path(__file__).name)
(stage/'REVERSE-LINKS.json').write_bytes((json.dumps({'schema':'state-configuration-reverse-links-v1',
    'links':links,'scientific_validated':False},indent=2)+'\n').encode('utf-8'))
scope = {'schema':'state-configuration-public-archive-v1','check':{k:v for k,v in closed.items() if k!='source_after'},
    'source_archive_sha256':manifest['archive_sha256'],'catalogues':catalogues,'items':items,
    'configuration_edges':len(links),'new_paid_calls':0,'scientific_effectiveness_proven':False,
    'validation_acceptance':False,'all_module_output_coverage_complete':False,
    'scope':'Complete selected state build and target directories plus controller provenance. Synthetic peers and actual Docker. Provider streams, authority key files and source export roots excluded. Archive readback verifies original bytes and graph references, not complete historical semantic replay.'}
(stage/'SCOPE.json').write_bytes((json.dumps(scope,indent=2)+'\n').encode('utf-8'))
(stage/'.gitattributes').write_bytes(b'* -text\n')
shutil.copytree(stage,dest)
assert all(p.read_bytes() == (dest/p.relative_to(stage)).read_bytes() for p in stage.rglob('*') if p.is_file())
print(json.dumps({'archive':str(dest),'files':len(items)+3,'catalogues':len(catalogues),
    'configuration_edges':len(links),'descriptors':sum(row['descriptors'] for row in catalogues)}))
