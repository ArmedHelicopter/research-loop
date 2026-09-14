"""Use the real historical reader against already committed runtime witnesses."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

WORK = Path(__file__).resolve().parent
TREE = WORK.parent / 'artifact-evidence-provenance'
ROOT = WORK / 'artifact-events-archive-staging-r1'
sys.path.insert(0, str(TREE))
from research_loop.modular.artifact_catalogue import ArtifactCatalogue
from research_loop.modular.artifact_source_archive import ArchivedSourceResolver
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.ontology import ContractError

scope_raw = (ROOT/'SCOPE.json').read_bytes()
assert scope_raw == subprocess.check_output(['git', 'show',
    '458dfee2d9e9df206251506a02a579d2c920e268:results/modular-engineering-20260914/artifact-events-r1/SCOPE.json'], cwd=TREE)
scope = json.loads(scope_raw)
for item in scope['items']:
    raw = (ROOT/item['path']).read_bytes()
    assert len(raw) == item['bytes'] and hashlib.sha256(raw).hexdigest() == item['sha256']
checks = {row['prefix']: row for row in scope['checks']}
rows = []
for witness in scope['runtime_witnesses']:
    directory = ROOT/'runtime'/witness['prefix']/witness['case']/witness['stage']/'runtime'
    first = json.loads((directory/'artifacts.jsonl').read_bytes().splitlines()[0])['descriptor']
    seal = FrozenRecord.from_dict(json.loads((directory/'artifacts.jsonl.seal.json').read_bytes()))
    kwargs = dict(identity=DataIdentity(**first['identity']), **first['binding'], producer_source=first['producer_source'])
    try:
        ArtifactCatalogue(directory/'artifacts.jsonl', **kwargs)
    except ContractError as exc:
        live_failure = str(exc)
    else:
        raise AssertionError('The original producer code was expected to have changed')
    archive = ROOT/'checks'/(witness['prefix']+'-sources.zip')
    digest = checks[witness['prefix']]['source_archive_sha256']
    resolver = ArchivedSourceResolver(archive, digest, TREE)
    reader = ArtifactCatalogue(directory/'artifacts.jsonl', **kwargs, source_resolver=resolver)
    reader.verify(seal)
    records = reader.records()
    assert len(records) == witness['descriptors']
    before = hashlib.sha256((directory/'artifacts.jsonl').read_bytes()).hexdigest()
    reader.verify(seal)
    assert before == hashlib.sha256((directory/'artifacts.jsonl').read_bytes()).hexdigest()
    rows.append({**witness, 'current_live_source_failure': live_failure,
                 'historical_catalogue_integrity_verified': True, 'semantic_replay_executed': False})
result = {'schema': 'historical-runtime-catalogue-check-v1', 'reader_commit': subprocess.check_output(
    ['git','rev-parse','HEAD'], cwd=TREE, text=True).strip(), 'witnesses': rows,
    'scientific_validated': False, 'original_failure_status_preserved': True,
    'scope': 'Archived producer bytes and catalogue integrity only; no semantic replay or environment reconstruction'}
with (WORK/'historical-catalogues-root-verification-r1.json').open('x', encoding='utf-8', newline='\n') as stream:
    stream.write(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
