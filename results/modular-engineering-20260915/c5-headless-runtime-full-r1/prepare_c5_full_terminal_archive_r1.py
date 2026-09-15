"""Preserve the original C5 terminal result, including a failed/incomplete one.

Do not run before native session 94121 has returned its terminal result. This
reader performs storage checks only, never invokes a model or run verifier.
"""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import zipfile
import xml.etree.ElementTree as ET

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
WORK = BASE / 'work'
PREFIX = WORK / 'c5-headless-runtime-full-r1'
SPECIMEN = PREFIX / 'test_full_headless_c5_controll0'
COMMIT = '15c2088f950994584ffe7c416843eb1d4e21ff53'
DEST = BASE / 'artifact-evidence-provenance/results/modular-engineering-20260915/c5-headless-runtime-full-r1'
PRIVATE = BASE / 'retained-private-evidence/c5-headless-runtime-full-r1'
TEST = 'test_full_headless_c5_controller_then_registers_selected_bundle'
HELPER = WORK / 'prepare_headless_lineage_full4_archive_r1.py'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def write(path, value):
    with path.open('xb') as stream:
        stream.write((json.dumps(value, indent=2, ensure_ascii=True) + '\n').encode())


def stamp(path):
    raw = path.read_bytes()
    return {'sha256': sha(raw), 'bytes': len(raw), 'mtime_ns': path.stat().st_mtime_ns}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--join-receipt', required=True, type=Path)
    args = parser.parse_args()
    join = read(args.join_receipt)
    require(set(join) == {'schema', 'native_session_id', 'source_commit', 'prefix', 'result'}
            and join['schema'] == 'native-session-join-v1' and join['native_session_id'] == 94121
            and join['source_commit'] == COMMIT and join['prefix'] == PREFIX.as_posix(), 'wrong native join binding')
    result = join['result']
    require(type(result) is dict and type(result.get('exit_code')) is int and 'session_id' not in result
            and {'exit_code', 'output', 'wall_time_seconds'} <= set(result), 'native session is not terminal')
    before = read(Path(str(PREFIX) + '-before.json'))
    source = read(Path(str(PREFIX) + '-source-members.json'))
    require(before['commit'] == source['commit'] == COMMIT and before['pytest_args'] == [
        'tests/test_c5_headless_runtime_controller_full.py::' + TEST, '-p', 'no:cacheprovider'], 'wrong frozen invocation')
    source_zip = Path(str(PREFIX) + '-sources.zip')
    require(sha(source_zip.read_bytes()) == source['archive_sha256'], 'source ZIP digest differs')
    require({r['path']: r['sha256'] for r in source['members']} == before['source_before'], 'source membership differs')
    with zipfile.ZipFile(source_zip) as archive:
        require(archive.testzip() is None and archive.namelist() == [r['path'] for r in source['members']], 'source ZIP members differ')
        for row in source['members']:
            raw = archive.read(row['path'])
            require(sha(raw) == row['sha256'] and len(raw) == row['bytes'], 'source member bytes differ')

    # Missing terminal products remain missing. They are not reconstructed.
    closed_path = Path(str(PREFIX) + '-closed.json')
    closed = read(closed_path) if closed_path.exists() else None
    report_path = Path(str(PREFIX) + '.xml')
    if closed is not None:
        require(closed['commit'] == COMMIT and closed['exit_code'] == result['exit_code'], 'closed source or native outcome differs')
        require(closed['source_after'] == before['source_before'] and closed['source_unchanged'] is True,
                'original tested source changed')
        require(closed['source_count'] == len(before['source_before']), 'source count differs')
        require(report_path.exists() and sha(report_path.read_bytes()) == closed['report_sha256'], 'closed JUnit digest differs')
        suites = list(ET.parse(report_path).getroot().iter('testsuite'))
        require(closed['junit'] == {k: sum(int(s.get(k, 0)) for s in suites) for k in ('tests', 'failures', 'errors', 'skipped')},
                'closed JUnit counts differ')
    cases = list(ET.parse(report_path).getroot().iter('testcase')) if report_path.exists() else []
    junit_pass = (len(cases) == 1 and cases[0].get('name') == TEST
        and cases[0].get('classname') == 'tests.test_c5_headless_runtime_controller_full'
        and not any(cases[0].find(tag) is not None for tag in ('failure', 'error', 'skipped')))
    frozen_pass = (closed is not None and closed['commit'] == COMMIT and closed['exit_code'] == 0
        and closed['source_unchanged'] is True and closed['source_after'] == before['source_before']
        and closed['junit'] == {'tests': 1, 'failures': 0, 'errors': 0, 'skipped': 0}
        and report_path.exists() and sha(report_path.read_bytes()) == closed['report_sha256'])
    runtime = SPECIMEN / 'headless-common-run'
    receipt_path = runtime / 'common-controller-receipt.json'
    receipt = read(receipt_path) if receipt_path.exists() else None
    registration_path = SPECIMEN / 'registered-selected-bundle.json'
    registration = read(registration_path) if registration_path.exists() else None
    controller_pass = (receipt is not None and receipt['schema'] == 'c5-common-train-controller-receipt-v1'
        and receipt['status'] == 'complete_train_engineering' and receipt['final_provider_eligible'] is True
        and len(receipt['builds']) == 46 and len(receipt['targets']) == 118
        and all(r['status'] == 'succeeded' for r in receipt['builds'])
        and all(r['status'] == 'scored' for r in receipt['targets'])
        and receipt['actual']['model_calls'] == 930 and receipt['actual']['scorer_calls'] == 118
        and receipt['evaluator_final_verification']['score_eligible'] is True
        and receipt['scientific_effectiveness_proven'] is False and receipt['validation_opened'] is False)
    registration_pass = (registration is not None and registration['schema'] == 'c5-selected-artifact-registration-v1'
        and set(registration['components']) == {f'M{i}' for i in range(1, 10)}
        and len(registration['targets']) == 2
        and all(registration[k] is False for k in ('scientific_validated', 'acceptance_verified', 'deployment_authorized'))
        and registration['snapshot']['selection']['expected_cells'] == 118
        and registration['snapshot']['selection']['scored_cells'] == 118)
    passed = bool(result['exit_code'] == 0 and junit_pass and frozen_pass and controller_pass and registration_pass)

    # The old helper's main is never called; only no-reparse enumeration and ZIP
    # writing helpers are used. Credentials are excluded and exclusions retained.
    spec = importlib.util.spec_from_file_location('c5_retention_helpers', HELPER)
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    require(not DEST.exists() and not PRIVATE.exists(), 'archive requires fresh destinations')
    files = sorted(helpers.regular_files(PREFIX))
    externals = [Path(str(PREFIX) + suffix) for suffix in
                 ('-before.json', '-source-members.json', '-sources.zip', '-closed.json', '.xml', '.log', '-native-start.json')]
    missing = [p.name for p in externals if not p.exists()]
    externals = [p for p in externals if p.exists()] + [args.join_receipt, WORK / 'c5-headless-runtime-full-r1-plan.json']
    originals = {str(p): stamp(p) for p in [*files, *externals]}
    PRIVATE.mkdir(parents=True)
    archive_path = PRIVATE / 'originals-without-credentials.zip'
    members = helpers.add_zip(archive_path, ((p.relative_to(PREFIX).as_posix(), p.read_bytes(), str(p)) for p in files))
    with zipfile.ZipFile(archive_path) as archive:
        require(archive.testzip() is None and archive.namelist() == [r['path'] for r in members], 'retained ZIP membership differs')
        for row in members:
            raw = archive.read(row['path'])
            require(sha(raw) == row['sha256'] == originals[row['origin']]['sha256']
                    and len(raw) == row['byte_count'], 'retained original bytes differ')
    require(originals == {str(p): stamp(p) for p in [*files, *externals]}, 'original bytes or mtimes changed')
    retention = {'schema': 'c5-full-terminal-retention-v1', 'archive': str(archive_path),
        'archive_sha256': sha(archive_path.read_bytes()), 'members': members,
        'originals_before': originals, 'originals_after': originals,
        'excluded_credentials': helpers.EXCLUSIONS, 'pruned_reparse_paths': sorted(helpers.PRUNED_LINKS)}
    write(PRIVATE / 'retention-manifest.json', retention)
    DEST.mkdir(parents=True)
    (DEST / '.gitattributes').write_bytes(b'* -text\n')
    copies = [*externals, Path(__file__), PRIVATE / 'retention-manifest.json']
    require(len({p.name for p in copies}) == len(copies), 'public filenames overlap')
    for path in copies:
        shutil.copyfile(path, DEST / path.name)
        require((DEST / path.name).read_bytes() == path.read_bytes(), 'public copy differs')
    shutil.copyfile(HELPER, DEST / 'retention-helper-source.py')
    require((DEST / 'retention-helper-source.py').read_bytes() == HELPER.read_bytes(), 'helper copy differs')
    checkpoint_path = runtime / 'checkpoint.json'
    checkpoint = read(checkpoint_path) if checkpoint_path.exists() else None
    summary = {'schema': 'c5-full-terminal-archive-v1', 'source_commit': COMMIT,
        'native_session_id': 94121, 'native_exit_code': result['exit_code'],
        'status': 'complete_synthetic_engineering' if passed else 'closed_inconclusive',
        'junit_passed': junit_pass, 'frozen_check_passed': frozen_pass,
        'controller_complete': controller_pass, 'registration_present': registration_pass,
        'frozen_denominator': {'history': 46, 'targets': 118},
        'last_checkpoint_counts': None if checkpoint is None else dict(Counter(r['stage'] + ':' + r['status'] for r in checkpoint['rows'])),
        'missing_terminal_files': missing, 'retained_noncredential_files': len(files),
        'actual_synthetic_usage': None if receipt is None else receipt['actual'],
        'original_bytes_and_mtimes_unchanged': True, 'real_model_calls': 0, 'paid_api_calls': 0,
        'validation_access': False, 'scientific_effectiveness_proven': False,
        'authentication_scope': 'original frozen test authenticates runtime; archive helper only verifies stored bytes and outcome fields'}
    write(DEST / 'summary.json', summary)
    (DEST / 'README.md').write_text(
        '# Full C5 synthetic controller terminal archive\n\n'
        f"Original native session 94121 returned {result['exit_code']}; archive status: `{summary['status']}`.\n\n"
        'The frozen denominator is 46 history builds and 59 recipes × 2 TRAIN targets. '
        'The original JUnit, frozen source bytes, terminal products, failure prefixes and noncredential files are retained. '
        'Missing products are listed and not reconstructed. Summary flags describe the original run and stored fields; '
        'this archive helper performs no new cryptographic or scientific authentication.\n\n'
        'Models and account responses are synthetic. Docker and stdio use actual local interfaces. '
        'This run does not establish module effects, finish the real benchmark experiments, open VAL or authorize deployment. '
        'Earlier partial runs remain separate and were not resumed or reclassified.\n', encoding='utf-8')
    require(originals == {str(p): stamp(p) for p in [*files, *externals]}, 'originals changed during public preservation')
    inventory = [{'path': p.name, 'sha256': sha(p.read_bytes()), 'bytes': p.stat().st_size} for p in sorted(DEST.iterdir())]
    write(DEST / 'published-manifest.json', {'schema': 'published-files-v1', 'files': inventory})
    for row in read(DEST / 'published-manifest.json')['files']:
        raw = (DEST / row['path']).read_bytes()
        require(sha(raw) == row['sha256'] and len(raw) == row['bytes'], 'published member differs')
    print(json.dumps({'destination': str(DEST), 'summary': summary}), flush=True)


if __name__ == '__main__':
    main()
