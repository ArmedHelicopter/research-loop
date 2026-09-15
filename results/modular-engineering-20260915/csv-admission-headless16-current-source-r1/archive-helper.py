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
 'csv-headless16': {
  'name': 'csv-admission-headless16-current-source-r1',
  'runs': [('headless16', 'csv-admission-headless-full16-frozen-r1', '43ccf107186f730884e64c230d3abe4bfa555d65', 24184, 1)],
  'attempts': [],
  'description': '# Current CSV actor: full native admission scorer closure\n\nSource 43ccf107 passed its full sixteen-cell native admission controller test\nin 1277.750 seconds. The exact 814-file source generation remained unchanged;\nthe original native session 24184 joined exit 0. The test exercises 48 synthetic\nsolver calls, 16 synthetic evaluator calls, ordered signed final closure,\nall sixteen score-eligible cells and exact 640 known synthetic MAIN tokens.\n\nThis test uses the standard source verifier. The distinct actual CSV verifier\nworkers and raw/spec/source mutation checks are covered by the separately\nretained csv-measurement-repaired-and-root-r1 full-sixteen integration.\nTogether they establish the declared engineering seams at this source revision;\nneither establishes real-model effectiveness or validation acceptance.\nNo real model, paid API or real validation calls were made by this check.\n'
 },
 'csv-repaired-root': {
  'name': 'csv-measurement-repaired-and-root-r1',
  'runs': [
   ('csv-full16', 'csv-measurement-consumer-frozen-r2', '43ccf107186f730884e64c230d3abe4bfa555d65', 19740, 1),
   ('root', 'csv-admission-root-integration-r1', 'e0a91cd89622f772686c57d748bb1446c0e94116', 93806, 21)],
  'attempts': [],
  'description': '''# Repaired CSV consumer and merged ROOT checks

After correcting only the fixture's colliding authority key, source 43ccf107
passed the full sixteen-cell CSV controller/driver integration in 240.422s.
Both synthetic benchmark identities were exercised. All 32 independent worker
callback receipts were retained; actual controller consumption and later replay
rejected altered raw output, specification and pinned temporary worker code.
The production independent-role guard was not loosened. The first failed
forty-check report remains in csv-first-and-c5-successor-checks-r1.

Merged ROOT e0a91cd8 then passed 21 checks in 127.203s: all ten label-isolation
checks and all eleven CSV measurement/replay checks. These include exact typed
original/CSV parent binding, separate reader/DictReader implementation, decimal
aggregation independent of precision context, correct negative measurements,
retained failures and signed-assessment comparison to raw results.

Both original native sessions joined exit 0 and each exact 814-file source
generation remained unchanged. This archive retains both source generations
and their noncredential runtime originals separately. It verifies these
synthetic engineering seams; the separate headless16 scorer closure check,
actual model effect, all other module/combinations and VAL acceptance remain
separate requirements. No real model, paid API or real VAL calls were made.
'''
 },
 'csv-first-c5-successor': {
  'name': 'csv-first-and-c5-successor-checks-r1',
  'runs': [
   ('csv-first', 'csv-measurement-consumer-frozen-r1', '699bb927b5b6b12eaa3d2a6bf4b34ae24727b1c4', 98623, 40, 1),
   ('c5-successor', 'c5-registration-successor-frozen-r1', '73268bb59b18b113f6f20e913900db51375e7377', 15751, 16)],
  'attempts': [],
  'description': '''# CSV first consumer check and C5 successor bounded checks

CSV source 699bb927 passed 39 of 40 checks at 814 unchanged source files.
The eleven focused CSV authority checks passed, including original measurement
binding, exact decimal aggregation, raw stdout replay, wrong-measurement rejection,
forged signed-assessment rejection and retained return-pin failure. The legacy
full sixteen-cell controller and its selected scope/preflight checks also passed.
The new CSV sixteen-cell seam failed before dispatch because its fixture reused
a source authority key for another authority role. The production role-separation
guard rejected it. This is a failed integration check, not a full CSV seam pass.

C5 successor source 73268bb5 passed sixteen bounded checks at 810 unchanged
source files. It combines d672c274 with all three selected-registration retention
commits. The storage-adapter tests still stub upstream authentication; controller
preflight and failed-history terminal checks are included. A separate full C5
successor run is required to cover genuine selected-snapshot authentication.

Both original native sessions joined with their recorded exit codes (CSV1, C5 0).
Each source generation, failure report and noncredential runtime original is
retained separately. These are synthetic engineering checks, with no real model,
paid API or real VAL calls; no scientific effect or combination pruning follows.
'''
 },
 'c5-full-r2': {
  'name': 'c5-headless-runtime-full-r2',
  'runs': [('full', 'c5-headless-runtime-full-r2', '83aefb74f15a72d421dd5e34002e36483b6ce6d0', 4370, 1, 1)],
  'attempts': [],
  'extras': ['c5-headless-runtime-full-r2-inspection-failure-observation-r1.json', 'observe_c5_r2_inspection_failure_r1.py'],
  'description': '''# C5 full synthetic controller r2: failed, with terminal evidence

The original native session 4370 joined exit 1. The one full-controller test
failed after 15,543.109 seconds at unchanged source 83aefb74 (794 files).
The complete declared denominator remains 46 builds and 118 targets:
37 builds succeeded, one failed, eight were blocked; all 118 targets were blocked.
No scores, TRAIN-selected bundle or selected registration were produced.

The first failed build reached synthetic provider reservation 187, review_first.
Context inspection timed out before the prompt process launched. Its original
record retains process_tree_shutdown_failed, null exit and owned_tree_closed=false.
A later diagnostic observed that PID absent; that observation does not rewrite
the original closure evidence. The provider ledger retains 187 reservations,
1,860 known synthetic MAIN tokens and incomplete usage accounting.

This generation produced an actual terminal common-controller receipt, attempts
and checkpoint. The test still failed at its full-build assertion. The retained
earlier diagnostic was taken while the native session was live, and remains a
dated observation; the separate native join establishes later process completion.

This generation predates the repaired owned-file process capture and the pending
selected-registration sidecar. It cannot validate either successor implementation.
This is failed synthetic engineering integration evidence, with no real model,
paid API or real VAL calls. No denominator reduction, checkpoint resume,
scientific effect or successful full-run claim is inferred.
'''
 },
 'capture-timeout-repaired': {
  'name': 'headless-capture-timeout-repaired-checks-r2',
  'runs': [
   ('root', 'headless-capture-scheduler-root-r2', 'd672c274ccb4da45605e2013ec5fcd4b3fcfa9c9', 97982, 21),
   ('scheduler', 'scheduler-headless-stdio-root-r2', 'd672c274ccb4da45605e2013ec5fcd4b3fcfa9c9', 75291, 1)],
  'attempts': [],
  'description': '''# Repaired frozen timeout and complete scheduler checks

Source d672c274 repairs the TRAIN adapter's hardcoded 60-second comparison:
the adapter checks the live integer bound and its equality to the frozen port
configuration. The scheduler test reads the actual configured evaluator ledger.
No previous failed report is rewritten.

All 21 ROOT checks passed, including ten label-isolation checks, actual 240s
solver/evaluator child configuration and replay, the two primary score routes,
M4/M5 preflight drift refusal, stdin EOF, retained-capture overwrite refusal,
ACP stdout compatibility and scheduler descriptor/readback checks.

The separate full scheduler test passed its actual eight-cell stdio/Docker
execution: 16 synthetic solver calls, eight scores, exact ordered signed closure,
eight eligible cells, bound provider/configuration, 80 known MAIN tokens and
explicitly unknown title settlement. Both native sessions joined exit 0 and
each exact 809-file source generation remained unchanged.

These are synthetic engineering checks, not evidence of actual model quality,
scientific effect, or VAL acceptance. They made no real model/paid API calls.
The preceding 128/15/21 first-check reports keep their five original failures
in a separate archive and are not relabeled as passing.
'''
 },
 'capture-timeout-first': {
  'name': 'headless-capture-timeout-first-checks-r1',
  'runs': [
   ('capture', 'headless-capture-timeout-frozen-r1', '1a9fab22cce190dd798a151d77839ec354bf9090', 45624, 128, 2),
   ('scheduler', 'scheduler-headless-seam-frozen-r1', '1a9fab22cce190dd798a151d77839ec354bf9090', 45018, 15, 1),
   ('root', 'headless-capture-scheduler-root-r1', '914963a573e4e1d75dbc235d62c1830652420774', 93222, 21, 2)],
  'attempts': [],
  'description': '''# First capture, frozen timeout and scheduler checks

All three original native sessions closed with exit 1. Their original JUnit,
logs, raw noncredential runtime files and exact source archives are retained.
Each generation contains 809 unchanged source/document files.

The capture batch passed 126 of 128 checks. Two new nondefault-timeout checks
failed because train_provider_headless.configuration still required 60 seconds.
ROOT independently passed 19 of 21 checks, including all ten label-isolation
checks, and observed those same two adapter failures. Neither report is a pass.

The scheduler batch passed 14 of 15 checks. Its full actual stdio/Docker test
executed 16 synthetic solver calls and eight scores; the ordered signed closure,
eight eligible cells, provider/config bindings, 80 known MAIN tokens and unknown
title settlement assertions passed before its final assertion read the wrong
ledger path. That FileNotFoundError remains the test outcome. A subsequent
fixture path repair and adapter repair are checked at a separate source;
these old reports are never relabeled as success.

These are synthetic engineering checks, not actual model or scientific-effect
experiments. No real VAL data was opened and no paid API calls were made.
'''
 },
 'scorer-exchange': {
  'name': 'scorer-exchange-observations-r1',
  'runs': [
   ('isolated', 'scorer-exchange-frozen-r1', '4668c6e867c70af1f985342b307015a7740c9d12', 8696, 28),
   ('root', 'scorer-exchange-root-integration-r1', 'c10170e02103387426fb7ff2ed1ee45e81749bb7', 60061, 13)],
  'attempts': [],
  'description': '''# Ordinary scorer exchange observations

Linked and combination scoring preserve startup and cell request/response text
before parsing. Terminal cell catalogues retain the exact raw observation,
source/config/panel/cell bindings and receipt digest. Startup has no fabricated
task identity. Observations have neutral module attribution and cannot promote
module coverage or scientific eligibility on their own.

Authenticated observations follow durable success journals. Initial and cached
returns verify held anchors, raw bytes, signed receipts and legacy success records;
failed writes, deletion and tampering cannot emit an authenticated return.

The isolated source passed 28 checks, including a full eight-cell actual
stdio/Docker controller with 40 synthetic solver calls. Merged ROOT passed 13
checks covering ten label-isolation checks, both primary score routes and
first-return tampering/write failure. Both exact source generations and native
completion results are retained separately. These are synthetic engineering
checks; they make no real model/API calls or real VAL access.
'''
 },
 'provenance-followup': {
  'name': 'bounded-provenance-followup-r1',
  'runs': [
   ('account-root', 'account-freshness-root-integration-r1', 'a989a7855e6763f8e3ff3f7d80a4901c1c31d2b4', 2664, 12),
   ('c5-registration-isolated', 'c5-selection-artifacts-frozen-r1', 'bdbc01a6a5993a015196caeb489f76eba8863e42', 61910, 14)],
  'attempts': [],
  'description': '''# Bounded provenance follow-up checks

Merged account-freshness ROOT source a989a785 passed twelve checks: ten label
isolation checks, one actual synthetic producer/reader check, and a genuinely
delayed synthetic GET that still independently replayed. This is separate from
the earlier isolated 66-pass/one-timeout batch and its successful focused recheck.

Isolated C5 registration source bdbc01a6 passed fourteen checks. It retains the
exact authenticated selected-registration bytes and a task-neutral source-bound
sidecar. Registration reads back before returning; later verification reauthenticates
and rechecks originals. Missing sidecars can be completed only after fresh
authentication reconstructs the same target; differing originals are never overwritten,
and an already complete registration retains its FileExistsError behavior.

The C5 checks use an actual selected-snapshot projection but stub the expensive
upstream authentication call. They verify this storage adapter, including partial
write completion and tampering, not the complete 46-build/118-target controller.
That broader run remains separate and is not credited to these new source bytes.
Neither set makes real model/API calls or opens real VAL data.
'''
 },
 'account-freshness': {
  'name': 'account-freshness-runtime-checks-r1',
  'runs': [
   ('full-with-inspect-timeout', 'account-freshness-frozen-r1', '62695576080b974d3ebae7a265039f6d761a5aef', 76849, 67, 1),
   ('inspect-recheck', 'account-freshness-inspect-recheck-r1', '62695576080b974d3ebae7a265039f6d761a5aef', 37310, 1)],
  'attempts': [],
  'description': '''# Bounded account freshness repair

The three sequential account GETs can each use a ten-second transport timeout.
The former five-second oldest-observation guard rejected two real observations
before model dispatch in the separately retained M4/M5 r2 attempt. This source
records a 35-second maximum age in each new reservation, checks it before launch,
and independently requires that exact frozen value during replay. Zero-paid
fallback checks, at most two account-read attempts, and no MAIN retry remain.
Original failed runs retain their original source, policy, ledger and conclusion.

The frozen 67-check batch passed 66 and failed one first synthetic inspect at
its unchanged ten-second timeout, before any model dispatch. The exact same source
then passed a focused rerun of that single producer/reader test. The full failed
report is retained and is not relabeled as an uninterrupted 67-test pass.
The genuine six-second synthetic GET delay test passed in the first batch and
independently replayed; changing the recorded bound and coherently rehashing it
was rejected. All checks use synthetic accounts/models and do not open real VAL.
'''
 },
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
 },
 'admission-transitions': {
  'name': 'admission-attempt-transitions-r1',
  'runs': [
   ('isolated', 'admission-transition-frozen-r1', 'd71d2db3ef11c9bb1e880d991fab8a14df4265a0', 92528, 4),
   ('root', 'admission-transition-root-integration-r1', '9e7a7c58d1da76661761e37f7a212214c0e0c982', 9318, 14)],
  'attempts': [],
  'description': '''# Admission controller checkpoint retention

Every actual persist writes a separate exact checkpoint copy and chained source/config record.
The terminal checkpoint precedes the externally held receipt tail. Before returning, the controller
checks the persisted receipt against its intended bytes and independently re-reads the retained chain.
The sidecar is engineering custody evidence, with no invented module attribution or semantic parents.

The isolated frozen source passed four focused checks: actual poisoned-ledger controller prefix and
return, preflight-stopped prefix, coherent rehash rejection against the original external tail, and
persisted-receipt tampering rejection. The merged ROOT passed the same four plus ten label checks.
No full sixteen-cell experiment was rerun here. These synthetic checks made no real model or paid API
calls and did not read real VAL inputs. Exact original sources and noncredential runtime files are retained.
'''
 },
 'grok130-evaluator': {
  'name': 'grok130-evaluator-and-root-checks-r1',
  'runs': [
   ('r1-failed', 'grok130-evaluator-runtime-frozen-r1', '02420d758312a218d8897c4357224e799043b1f2', 47503, 24, 1),
   ('r2', 'grok130-evaluator-runtime-frozen-r2', '6ec1a7205680e8f21a0da1e826ea696aff0f1333', 61322, 25),
   ('root', 'grok130-provider-root-integration-r1', 'f9a53d3495e8c45dd87bcf072da85bedd4a4c3d9', 23011, 53)],
  'attempts': [],
  'description': '''# Grok 1.0.30 evaluator and merged provider checks

The explicit normal-CLI deployment now binds private evaluator configuration, pure factory descriptors,
actual native request context and independent replay. Successful synthetic factory calls verify the
outgoing account client headers; invalid deployment records are rejected before allocation. Legacy
declarations retain their prior fields and behavior. ACP is a separate interface.

r1 preserves 23 passes and one source-tamper fixture signature failure at source 02420d75.
After the legacy single-argument source-pin call was restored, r2 passed 25 checks at 6ec1a720.
Merged ROOT f9a53d34 passed 53 checks spanning TRAIN port, evaluator factory/port and label isolation.
Each generation preserves its own original native completion, exact source bytes and runtime files.
No real model/API/VAL call was made by these synthetic checks; live controls are separate evidence.
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
    tag, prefix, commit, sid, count, *extra = row
    expected_failures = extra[0] if extra else 0
    expected_exit = 1 if expected_failures else 0
    paths = {s: WORK/(prefix+s) for s in SUFFIXES}
    before, closed, started, joined, sources = [load(paths[s]) for s in SUFFIXES[:5]]
    require(before.get('commit') == closed.get('commit') == sources.get('commit') == joined.get('source_commit') == commit, tag+' commit')
    require(started.get('result', started).get('session_id') == joined.get('native_session_id') == sid, tag+' session')
    require(joined.get('result', {}).get('exit_code') == closed.get('exit_code') == expected_exit, tag+' exit')
    source_map = {r['path']: r['sha256'] for r in sources['members']}
    require(len(source_map) == len(sources['members']) == closed.get('source_count'), tag+' source count')
    require(before.get('source_before') == closed.get('source_after') == source_map and closed.get('source_unchanged') is True, tag+' source equality')
    require(closed.get('new_paid_calls') == 0, tag+' paid calls')
    xml = paths['.xml'].read_bytes()
    require(sha(xml) == closed.get('report_sha256'), tag+' XML hash')
    suites = list(ET.fromstring(xml).iter('testsuite'))
    actual = {k: sum(int(s.get(k, 0)) for s in suites) for k in JUNIT_FIELDS}
    require(actual == closed.get('junit') == dict(zip(JUNIT_FIELDS, (count, expected_failures, 0, 0))), tag+' JUnit')
    require(sha(paths['-sources.zip'].read_bytes()) == sources.get('archive_sha256'), tag+' source ZIP hash')
    with zipfile.ZipFile(paths['-sources.zip']) as archive:
        require(archive.testzip() is None and archive.namelist() == [r['path'] for r in sources['members']], tag+' ZIP inventory')
        for member in sources['members']:
            raw = archive.read(member['path'])
            require(len(raw) == member['bytes'] and sha(raw) == member['sha256'], tag+' ZIP member')
    return paths, {'tag': tag, 'prefix': prefix, 'commit': commit, 'native_session_id': sid,
                   'junit': actual, 'wall_seconds': closed['wall_seconds'], 'source_count': len(source_map)}

def main():
    require(len(sys.argv) == 2 and sys.argv[1] in CONFIGS, 'choose configured archive')
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
    extras = {name: WORK/name for name in config.get('extras', [])}
    metadata = [path for paths, _ in validated for path in paths.values()] + list(extras.values())
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
    public.update(extras)
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
