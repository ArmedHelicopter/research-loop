"""Retain already joined, independently source-frozen engineering checks.

Usage: python archive_frozen_module_checks_r1.py custody|grok130
Never reruns tests or reads live trees to reconstruct earlier source generations.
"""
from __future__ import annotations
import hashlib, importlib.util, json, shutil, sys, zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
WORK = BASE / 'work'
ROOT = BASE / 'artifact-evidence-provenance'
RETENTION_HELPER = WORK / 'prepare_headless_lineage_full4_archive_r1.py'
SUFFIXES = ('-before.json', '-closed.json', '-native-start.json', '-native-join.json',
            '-source-members.json', '-sources.zip', '.xml', '.log')
JUNIT_FIELDS = ('tests', 'failures', 'errors', 'skipped')
CONFIGS = {
 'custody': {
  'name': 'custody-transition-retention-r1',
  'runs': [
   ('r3', 'custody-transition-retention-frozen-r3', 'bbee0ef315c90a14fd63e7f24d59ebb59b38f0df', 74296, 20),
   ('r4', 'custody-transition-retention-frozen-r4', '41f0c892c244a9d9c88ebd1afcf4cf2fd52cb8cb', 48001, 10),
   ('root', 'custody-transition-root-integration-r1', 'dac25750dad42d42e510f9a4eaad767a831f31ee', 93865, 17)],
  'attempts': [('historical-r1', 'custody-transition-retention-r1-pytest-r1'),
               ('historical-r2', 'custody-transition-retention-r1-pytest-r2')],
  'description': '''# P0 custody transition retention checks

The opt-in custody writer retains exact private snapshots after durable operations and signed receipt creation.
Capture failure is reported separately and does not falsify an already completed custody operation.
Independent replay checks state and receipt bindings, ordering, source bytes and caller-held tail anchors.

Three separate frozen generations are preserved: r3 has 20 passing tests; r4 has 10 after the
global-order and mutator-source repairs; ROOT has 17 including label isolation. r3 is not credited with r4 repairs.
The r1/r2 historical attempts have raw files and their original reports, but no original native start/join;
their process completion and in-flight source identity are not inferred from the later runs.

Private snapshots and test-run originals remain outside public packet and optimizer roots. Only source,
test reports and retention metadata are published here. This is synthetic engineering evidence, not
complete custody history, external authority authentication, operating-system isolation, or scientific validation.
'''
 },
 'grok130': {
  'name': 'grok130-normal-runtime-checks-r1',
  'runs': [('isolated', 'grok130-normal-runtime-frozen-r1', '29107a013ab2a102edecb4792fb3cf8564fbb78b', 34788, 51)],
  'attempts': [],
  'description': '''# Pinned Grok 1.0.30 normal TRAIN interface checks

The opt-in normal streaming-JSON deployment binds the exact executable, model, account client header,
source and configuration to the TRAIN producer and its persisted replay. The legacy interface is retained.
The isolated frozen generation passed 51 synthetic checks, including actual synthetic HTTP request headers,
successful producer/replay and rejection of a coherently rehashed incorrect header.

These checks do not log in, call a real model or paid API, read real VAL data, or establish actual model
availability or scientific effect. They do not cover the separately implemented evaluator factory.
'''
 }
}

def require(value, message):
    if not value: raise RuntimeError(message)

def sha(raw): return hashlib.sha256(raw).hexdigest()
def load(path): return json.loads(path.read_bytes())
def stamp(path):
    raw = path.read_bytes()
    return {'sha256': sha(raw), 'bytes': len(raw), 'mtime_ns': path.stat().st_mtime_ns}
def write(path, body):
    with path.open('xb') as out: out.write((json.dumps(body, ensure_ascii=False, indent=2)+'\n').encode())

def validate_run(row):
    tag, prefix, commit, sid, count = row
    paths = {s: WORK/(prefix+s) for s in SUFFIXES}
    before, closed, started, joined, sources = [load(paths[s]) for s in SUFFIXES[:5]]
    require(before.get('commit') == closed.get('commit') == sources.get('commit') == joined.get('source_commit') == commit, tag+' commit')
    require(started.get('result', started).get('session_id') == joined.get('native_session_id') == sid, tag+' session')
    require(joined.get('result', {}).get('exit_code') == closed.get('exit_code') == 0, tag+' exit')
    source_map = {r['path']: r['sha256'] for r in sources['members']}
    require(len(source_map) == len(sources['members']) == closed.get('source_count'), tag+' source count')
    require(before.get('source_before') == closed.get('source_after') == source_map and closed.get('source_unchanged') is True, tag+' source equality')
    require(closed.get('new_paid_calls') == 0, tag+' paid calls')
    xml = paths['.xml'].read_bytes()
    require(sha(xml) == closed.get('report_sha256'), tag+' XML hash')
    suites = list(ET.fromstring(xml).iter('testsuite'))
    actual = {k: sum(int(s.get(k, 0)) for s in suites) for k in JUNIT_FIELDS}
    require(actual == closed.get('junit') == dict(zip(JUNIT_FIELDS, (count, 0, 0, 0))), tag+' JUnit')
    require(sha(paths['-sources.zip'].read_bytes()) == sources.get('archive_sha256'), tag+' source ZIP hash')
    with zipfile.ZipFile(paths['-sources.zip']) as archive:
        require(archive.testzip() is None and archive.namelist() == [r['path'] for r in sources['members']], tag+' ZIP inventory')
        for member in sources['members']:
            raw = archive.read(member['path'])
            require(len(raw) == member['bytes'] and sha(raw) == member['sha256'], tag+' ZIP member')
    return paths, {'tag': tag, 'prefix': prefix, 'commit': commit, 'native_session_id': sid,
                   'junit': actual, 'wall_seconds': closed['wall_seconds'], 'source_count': len(source_map)}

def main():
    require(len(sys.argv) == 2 and sys.argv[1] in CONFIGS, 'choose custody or grok130')
    config = CONFIGS[sys.argv[1]]
    dest = ROOT/'results/modular-engineering-20260915'/config['name']
    private = BASE/'retained-private-evidence'/config['name']
    require(not dest.exists() and not private.exists(), 'archive already exists')
    validated = [validate_run(row) for row in config['runs']]
    spec = importlib.util.spec_from_file_location('frozen_retention', RETENTION_HELPER)
    retention = importlib.util.module_from_spec(spec); spec.loader.exec_module(retention)
    roots = [(row[0], WORK/row[1]) for row in config['runs']+config['attempts']]
    original_rows = []
    for tag, run_root in roots:
        require(run_root.is_dir(), 'missing run root '+str(run_root))
        original_rows.extend((tag+'/'+path.relative_to(run_root).as_posix(), path)
                             for path in sorted(retention.regular_files(run_root)))
    metadata = [path for paths, _ in validated for path in paths.values()]
    inputs = sorted({*(path for _, path in original_rows), *metadata, Path(__file__), RETENTION_HELPER})
    input_before = {str(path): stamp(path) for path in inputs}
    private.mkdir(parents=True)
    zip_path = private/'run-originals-without-credentials.zip'
    members = retention.add_zip(zip_path, ((name, path.read_bytes(), str(path)) for name, path in original_rows))
    with zipfile.ZipFile(zip_path) as archive:
        require(archive.testzip() is None and archive.namelist() == [r['path'] for r in members], 'private ZIP inventory')
        for member in members:
            raw = archive.read(member['path']); prior = input_before[member['origin']]
            require(sha(raw) == member['sha256'] == prior['sha256'] and len(raw) == member['byte_count'] == prior['bytes'], 'private member')
    require(input_before == {str(path): stamp(path) for path in inputs}, 'originals changed during retention')
    manifest = {'schema': 'frozen-check-private-retention-v1', 'runs': [row for _, row in validated],
                'historical_attempt_limit': 'No native start/join or continuous source verification is inferred for historical attempts.',
                'archive': {'path': str(zip_path), 'sha256': sha(zip_path.read_bytes()), 'bytes': zip_path.stat().st_size},
                'members': members, 'excluded_credentials': retention.EXCLUSIONS,
                'pruned_reparse_paths': sorted(retention.PRUNED_LINKS), 'inputs_before': input_before, 'inputs_after': input_before}
    write(private/'retention-manifest.json', manifest)
    dest.mkdir(parents=True)
    (dest/'.gitattributes').write_bytes(b'* -text\n')
    public = {'archive-helper.py': Path(__file__), 'retention-helper-source.py': RETENTION_HELPER,
              'private-retention-manifest.json': private/'retention-manifest.json'}
    for paths, summary in validated:
        for suffix, path in paths.items(): public[summary['tag']+suffix] = path
    for name, source in public.items():
        shutil.copyfile(source, dest/name)
        require((dest/name).read_bytes() == source.read_bytes(), 'public copy')
    (dest/'README.md').write_bytes(config['description'].encode())
    published = {'schema': 'frozen-module-check-published-files-v1', 'files': [
        {'path': p.name, 'sha256': sha(p.read_bytes()), 'bytes': p.stat().st_size} for p in sorted(dest.iterdir())]}
    write(dest/'published-manifest.json', published)
    require({p.name for p in dest.iterdir()} == {r['path'] for r in published['files']} | {'published-manifest.json'}, 'public inventory')
    for row in published['files']:
        raw = (dest/row['path']).read_bytes()
        require(sha(raw) == row['sha256'] and len(raw) == row['bytes'], 'public bytes')
    require(input_before == {str(path): stamp(path) for path in inputs}, 'originals changed during public archival')
    print(json.dumps({'archive': str(dest), 'public_files': len(published['files'])+1,
                      'private_originals': len(members), 'manifest_sha256': sha((dest/'published-manifest.json').read_bytes())}))

if __name__ == '__main__': main()
