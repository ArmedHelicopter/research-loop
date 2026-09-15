"""Preserve full5 only after its original native wrapper has been joined.

No execution, scoring, account query, replay constructor, or input mutation.
The closed original source snapshot is checked independently of Git text filters.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import zipfile
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
BASE = Path('E:/_ryanDev/AI/research-loop-modular')
WORK = BASE / 'work'
PREFIX = WORK / 'headless-lineage-controller-full5'
SPECIMEN = PREFIX / 'test_native_v4_headless_lineag0'
DEST = BASE / 'artifact-evidence-provenance/results/modular-engineering-20260915/headless-lineage-controller-full5-r1'
PRIVATE = BASE / 'retained-private-evidence/headless-lineage-controller-full5-r1'
COMMIT = '0a9ca90abfb16ded9a6d5f312739a56cf18e7bb9'
LABEL = WORK / 'lineage-full5-label-audit-r1'
LABEL_NAMES = {
    'test_every_task_has_a_label', 'test_prompts_do_not_contain_label_payloads',
    'test_error_catching_every_task_has_a_label', 'test_error_catching_prompts_do_not_contain_label_payloads',
    'test_iteration_every_task_has_a_label', 'test_iteration_prompts_do_not_contain_label_payloads',
    'test_audit_contrast_every_task_has_a_label', 'test_audit_contrast_prompts_do_not_contain_label_payloads',
    'test_true_lock_every_task_has_a_label', 'test_true_lock_prompts_omit_gold_rule',
}
CONTROLLER_NAME = 'test_native_v4_headless_lineage_controller_closes_all_four_34_cell_workers'
spec = importlib.util.spec_from_file_location('retention_helpers', WORK / 'prepare_headless_lineage_full4_archive_r1.py')
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    return json.loads(path.read_bytes())


def stamp(path):
    raw = path.read_bytes()
    return {'sha256': sha(raw), 'bytes': len(raw), 'mtime_ns': path.stat().st_mtime_ns}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--join-receipt', required=True, type=Path)
    args = parser.parse_args()
    join = read_json(args.join_receipt)
    require(type(join) is dict and set(join) == {'schema', 'native_session_id', 'source_commit', 'prefix', 'result'}
            and join['schema'] == 'native-session-join-v1' and join['native_session_id'] == 55470
            and join['source_commit'] == COMMIT and join['prefix'] == PREFIX.as_posix(), 'join binding differs')
    result = join['result']
    require(type(result) is dict and {'exit_code', 'output', 'wall_time_seconds'} <= set(result)
            <= {'exit_code', 'output', 'wall_time_seconds', 'chunk_id', 'original_token_count'}
            and type(result['exit_code']) is int and result['exit_code'] == 1
            and type(result['output']) is str and type(result['wall_time_seconds']) in (int, float),
            'original native mixed-result session is not joined')
    closed = read_json(Path(str(PREFIX) + '-closed.json'))
    frozen = read_json(Path(str(PREFIX) + '-before.json'))
    source = read_json(Path(str(PREFIX) + '-source-members.json'))
    require(closed['exit_code'] == 1 and closed['source_unchanged'] is True
            and closed['junit'] == {'tests': 11, 'failures': 10, 'errors': 0, 'skipped': 0}
            and source['commit'] == frozen['commit'] == closed['commit'] == COMMIT
            and frozen['source_before'] == closed['source_after'], 'not the exact closed full5 checkpoint')
    require(frozen['pytest_args'] == ['tests/test_label_isolation.py', 'tests/test_headless_lineage_controller.py', '-p', 'no:cacheprovider'],
            'original pytest invocation differs')
    report_path = Path(str(PREFIX) + '.xml')
    require(sha(report_path.read_bytes()) == closed['report_sha256'], 'original JUnit hash differs')
    cases = list(ET.parse(report_path).getroot().iter('testcase'))
    require(len(cases) == 11 and len({(c.get('classname'), c.get('name')) for c in cases}) == 11,
            'JUnit testcase inventory differs')
    label_cases = [c for c in cases if c.get('classname') == 'tests.test_label_isolation']
    control_cases = [c for c in cases if c.get('classname') == 'tests.test_headless_lineage_controller']
    require({c.get('name') for c in label_cases} == LABEL_NAMES
            and all(len(c.findall('failure')) == 1 and c.find('error') is None and c.find('skipped') is None for c in label_cases)
            and len(control_cases) == 1 and control_cases[0].get('name') == CONTROLLER_NAME
            and not any(control_cases[0].find(tag) is not None for tag in ('failure', 'error', 'skipped')),
            'JUnit does not retain ten failing label fixtures and one passing complete controller')
    label_closed = read_json(Path(str(LABEL) + '-closed.json'))
    label_before = read_json(Path(str(LABEL) + '-before.json'))
    label_report = Path(str(LABEL) + '.xml')
    label_repeat = list(ET.parse(label_report).getroot().iter('testcase'))
    require(label_closed['commit'] == label_before['commit'] == COMMIT and label_closed['exit_code'] == 0
            and label_closed['source_unchanged'] is True
            and label_closed['source_after'] == label_before['source_before']
            and set(label_before['source_before']) == set(frozen['source_before'])
            and label_before['source_before']['tests/test_label_isolation.py'] == frozen['source_before']['tests/test_label_isolation.py']
            and label_closed['junit'] == {'tests': 10, 'failures': 0, 'errors': 0, 'skipped': 0}
            and sha(label_report.read_bytes()) == label_closed['report_sha256']
            and label_before['pytest_args'] == ['tests/test_label_isolation.py', '-p', 'no:cacheprovider']
            and len(label_repeat) == 10 and {c.get('name') for c in label_repeat} == LABEL_NAMES
            and all(c.get('classname') == 'tests.test_label_isolation'
                    and not any(c.find(t) is not None for t in ('failure', 'error', 'skipped')) for c in label_repeat),
            'independent label-only audit is not exact, passing and bound to the same label-test bytes')
    source_zip = Path(str(PREFIX) + '-sources.zip')
    require(sha(source_zip.read_bytes()) == source['archive_sha256'], 'source archive digest differs')
    with zipfile.ZipFile(source_zip) as archive:
        require(archive.testzip() is None and archive.namelist() == [r['path'] for r in source['members']],
                'source archive membership differs')
        for row in source['members']:
            raw = archive.read(row['path'])
            require(sha(raw) == row['sha256'] == frozen['source_before'][row['path']]
                    and len(raw) == row['bytes'], 'source member differs from frozen input')
    label_source = read_json(Path(str(LABEL) + '-source-members.json'))
    label_zip = Path(str(LABEL) + '-sources.zip')
    require(label_source['commit'] == COMMIT and sha(label_zip.read_bytes()) == label_source['archive_sha256'],
            'independent label-audit source archive digest differs')
    with zipfile.ZipFile(label_zip) as archive:
        require(archive.testzip() is None and archive.namelist() == [r['path'] for r in label_source['members']]
                and {r['path'] for r in label_source['members']} == set(label_before['source_before']),
                'independent label-audit source membership differs')
        for row in label_source['members']:
            raw = archive.read(row['path'])
            require(sha(raw) == row['sha256'] == label_before['source_before'][row['path']]
                    and len(raw) == row['bytes'], 'label-audit source member differs from frozen input')
    cross_checkout_differences = []
    with zipfile.ZipFile(source_zip) as full_archive, zipfile.ZipFile(label_zip) as audit_archive:
        for name in frozen['source_before']:
            raw, other = full_archive.read(name), audit_archive.read(name)
            if raw != other:
                require(raw.replace(b'\r\n', b'\n') == other.replace(b'\r\n', b'\n'),
                        'cross-checkout difference is not limited to line endings')
                cross_checkout_differences.append(name)
    attempt = read_json(SPECIMEN / 'run/controller-attempt.json')
    receipt = read_json(SPECIMEN / 'run/controller-receipt.json')
    require(attempt['schema'] == 'lineage-train-attempt-v2' and receipt['schema'] == 'lineage-train-receipt-v2'
            and attempt['config_digest'] == receipt['config_digest']
            and receipt['scientific_effectiveness_proven'] is False and receipt['validation_opened'] is False
            and receipt['pruned_cells'] == [] and receipt['failed_cells'] == receipt['blocked_cells'] == 0,
            'original controller schema or scientific boundary differs')
    gate = receipt['lineage_evaluator_final_gate']
    require(attempt['status'] == receipt['status'] == 'complete_train_engineering'
            and len(attempt['cells']) == receipt['expected_cells'] == receipt['observed_cells'] == receipt['scored_cells'] == 34
            and all(row['status'] == 'succeeded' for row in attempt['cells'])
            and attempt['actual_scorer_calls'] == receipt['actual_scorer_calls'] == 34,
            'original full34 controller denominator or terminal status differs')
    require(attempt['lineage_evaluator_final_gate'] == gate and gate['status'] == 'eligible'
            and len(gate['panels']) == 4, 'four-panel final gate is incomplete')
    panels = []
    for row in gate['panels']:
        require(row['status'] == 'eligible' and row['native_MAIN'] == len(row['receipt_digests']) * 10
                and row['closure']['body']['scope']['unscored_cell_count'] == 0,
                'one panel has an incomplete original closure')
        panels.append({'obligation_id': row['obligation_id'], 'score_count': len(row['receipt_digests']),
                       'known_synthetic_main_tokens': row['native_MAIN'], 'status': row['status']})
    require(sum(row['score_count'] for row in panels) == 34, 'closed panel denominator differs')
    require(not DEST.exists() and not PRIVATE.exists(), 'archive requires fresh paths')

    # Checks above occur before any new archive is created. Every retained input
    # is read again after writing; a partial archive never counts as closed.
    files = sorted(helpers.regular_files(PREFIX))
    external = [Path(str(PREFIX) + suffix) for suffix in
                ('-before.json', '-closed.json', '-source-members.json', '-sources.zip', '.xml', '.log')]
    external.extend(Path(str(LABEL) + suffix) for suffix in
                    ('-before.json', '-closed.json', '-source-members.json', '-sources.zip', '.xml', '.log'))
    external.append(args.join_receipt.resolve())
    require(len({p.name for p in external}) == len(external) and all(not helpers.excluded(p) for p in external),
            'external public metadata paths overlap or resemble credentials')
    before = {str(path): stamp(path) for path in [*files, *external]}
    PRIVATE.mkdir(parents=True)
    members = helpers.add_zip(PRIVATE / 'test-originals-without-credentials.zip',
        ((p.relative_to(PREFIX).as_posix(), p.read_bytes(), str(p)) for p in files))
    with zipfile.ZipFile(PRIVATE / 'test-originals-without-credentials.zip') as archive:
        require(archive.testzip() is None and archive.namelist() == [r['path'] for r in members],
                'retained archive membership differs')
        for row in members:
            raw = archive.read(row['path'])
            require(sha(raw) == row['sha256'] and len(raw) == row['byte_count'], 'retained bytes differ')
    after = {str(path): stamp(path) for path in [*files, *external]}
    require(before == after, 'original bytes or modification times changed')
    retention = {'schema': 'lineage-full5-retention-v1',
        'private_archive': str(PRIVATE / 'test-originals-without-credentials.zip'),
        'private_archive_sha256': sha((PRIVATE / 'test-originals-without-credentials.zip').read_bytes()),
        'members': members, 'original_files_before': before, 'original_files_after': after,
        'excluded_credentials': helpers.EXCLUSIONS, 'pruned_reparse_paths': sorted(helpers.PRUNED_LINKS)}
    (PRIVATE / 'retention-manifest.json').write_bytes((json.dumps(retention, indent=2) + '\n').encode())
    DEST.mkdir(parents=True)
    (DEST / '.gitattributes').write_bytes(b'* -text\n')
    for path in external:
        shutil.copyfile(path, DEST / path.name)
    shutil.copyfile(PRIVATE / 'retention-manifest.json', DEST / 'retention-manifest.json')
    shutil.copyfile(Path(__file__), DEST / Path(__file__).name)
    shutil.copyfile(WORK / 'prepare_headless_lineage_full4_archive_r1.py', DEST / 'retention-helper-source.py')
    shutil.copyfile(WORK / 'archive_lineage_full5_r1.py', DEST / 'prior-unrun-success-only-helper.py')
    expected_copies = {p.name: p.read_bytes() for p in external}
    expected_copies['retention-manifest.json'] = (PRIVATE / 'retention-manifest.json').read_bytes()
    expected_copies[Path(__file__).name] = Path(__file__).read_bytes()
    expected_copies['retention-helper-source.py'] = (WORK / 'prepare_headless_lineage_full4_archive_r1.py').read_bytes()
    expected_copies['prior-unrun-success-only-helper.py'] = (WORK / 'archive_lineage_full5_r1.py').read_bytes()
    for name, raw in expected_copies.items():
        require((DEST / name).read_bytes() == raw, 'public copy differs from retained original')
    require({str(path): stamp(path) for path in [*files, *external]} == before,
            'originals changed during public preservation')
    summary = {'schema': 'lineage-full5-checkpoint-v1', 'source_commit': COMMIT,
        'junit': closed['junit'], 'source_files': closed['source_count'], 'source_bytes_unchanged': True,
        'original_pytest_exit_code': 1, 'label_only_junit': label_closed['junit'],
        'label_only_exit_code': 0, 'combined_suite_passed': False,
        'cross_checkout_raw_source_bytes_identical': not cross_checkout_differences,
        'cross_checkout_line_ending_only_differences': sorted(cross_checkout_differences),
        'label_test_source_bytes_identical': True,
        'wall_seconds': closed['wall_seconds'], 'native_session_joined': 55470,
        'controller_status': receipt['status'], 'expected_cells': 34, 'succeeded_cells': 34,
        'synthetic_solver_main_calls': 136, 'synthetic_evaluator_main_calls': 34, 'panel_gates': panels,
        'real_model_calls': 0, 'paid_api_calls': 0, 'validation_read': False,
        'scientific_effectiveness_proven': False, 'retained_noncredential_files': len(members),
        'original_bytes_and_mtimes_unchanged': True,
        'prior_full4': 'separate incomplete original remains incomplete; no cells reused or reclassified'}
    (DEST / 'summary.json').write_bytes((json.dumps(summary, indent=2) + '\n').encode())
    (DEST / 'README.md').write_text(f'''# Full5 controller completion and separate label-audit correction

The original 11-test command at source `{COMMIT}` exited 1: ten label-dependent
tests failed in a worktree that deliberately excluded data/labels; the complete
34-cell controller test passed. The original failure report is preserved and
is not relabeled as an 11-test success. The controller was not restarted.

The same ten label tests passed in a separate label-audit process in the root
checkout. That process performed no model/controller execution. Each run's
{closed['source_count']} Python/Markdown files match its own pre/post hashes.
The label-test file has identical bytes in the two checkouts. They share a Git
revision but {len(cross_checkout_differences)} other files differ only in CRLF/LF
bytes. Both exact archives are preserved separately, without normalizing either
original or treating their raw source digests as interchangeable. No labels
were restored to the isolated execution worktree. This corrects the test
arrangement without weakening isolation or repeating the full controller.
The original native session 55470 was joined before run-file preservation.

All 34 cells succeeded and the four independent scoring workers produced
eligible signed final closures with no unscored cells. The test used 136
synthetic solver MAIN calls and 34 synthetic evaluator MAIN calls, with actual
Docker execution and stdio workers. These are engineering fixtures; there were
no real model, paid API, or validation-data calls. They do not measure any
module's scientific effectiveness or complete the real benchmark experiments.
The archive retains the controller's already-checked signed envelopes; the
archive script itself does not perform a new cryptographic authentication.

The private archive retains {len(members)} noncredential run files. Its exact
member list, hashes, byte counts, origins, credential exclusions and reparse-path
exclusions are recorded. CRC, each archived member, and unchanged original
bytes/modification times were checked. Public checkpoint files retain their
original bytes through directory-specific Git attributes. This archive is not
a credential-bearing or standalone reconstruction of the machine environment.

The older full4 run remains an independently archived incomplete attempt.
This full5 run used a new worktree and new output root, retained all 34 cells,
and did not resume, overwrite, or promote full4's partial results. C5's full
history/target selection, all remaining real single/combination experiments,
and independent validation acceptance still have their own completion criteria.
''', encoding='utf-8')
    inventory = [{'path': p.name, 'sha256': sha(p.read_bytes()), 'bytes': p.stat().st_size}
                 for p in sorted(DEST.iterdir()) if p.is_file()]
    (DEST / 'published-manifest.json').write_bytes((json.dumps({'schema': 'published-files-v1', 'files': inventory}, indent=2) + '\n').encode())
    published = read_json(DEST / 'published-manifest.json')
    require(published == {'schema': 'published-files-v1', 'files': inventory}, 'public manifest readback differs')
    for row in published['files']:
        raw = (DEST / row['path']).read_bytes()
        require(sha(raw) == row['sha256'] and len(raw) == row['bytes'], 'published member differs from manifest')
    print(json.dumps({'destination': str(DEST), 'summary': summary,
                     'published_manifest_sha256': sha((DEST / 'published-manifest.json').read_bytes())}), flush=True)


if __name__ == '__main__':
    main()
