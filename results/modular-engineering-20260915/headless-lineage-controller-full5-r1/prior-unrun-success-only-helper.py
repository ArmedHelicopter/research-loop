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

sys.dont_write_bytecode = True
BASE = Path('E:/_ryanDev/AI/research-loop-modular')
WORK = BASE / 'work'
PREFIX = WORK / 'headless-lineage-controller-full5'
SPECIMEN = PREFIX / 'test_native_v4_headless_lineag0'
DEST = BASE / 'artifact-evidence-provenance/results/modular-engineering-20260915/headless-lineage-controller-full5-r1'
PRIVATE = BASE / 'retained-private-evidence/headless-lineage-controller-full5-r1'
COMMIT = '0a9ca90abfb16ded9a6d5f312739a56cf18e7bb9'
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
    require(join['native_session_id'] == 55470 and join['result']['exit_code'] == 0
            and not join['result'].get('session_id'), 'original native session has not joined successfully')
    closed = read_json(Path(str(PREFIX) + '-closed.json'))
    frozen = read_json(Path(str(PREFIX) + '-before.json'))
    source = read_json(Path(str(PREFIX) + '-source-members.json'))
    require(closed['exit_code'] == 0 and closed['source_unchanged'] is True
            and closed['junit'] == {'tests': 11, 'failures': 0, 'errors': 0, 'skipped': 0}
            and source['commit'] == frozen['commit'] == closed['commit'] == COMMIT
            and frozen['source_before'] == closed['source_after'], 'not the exact closed full5 checkpoint')
    source_zip = Path(str(PREFIX) + '-sources.zip')
    require(sha(source_zip.read_bytes()) == source['archive_sha256'], 'source archive digest differs')
    with zipfile.ZipFile(source_zip) as archive:
        require(archive.testzip() is None and archive.namelist() == [r['path'] for r in source['members']],
                'source archive membership differs')
        for row in source['members']:
            raw = archive.read(row['path'])
            require(sha(raw) == row['sha256'] == frozen['source_before'][row['path']]
                    and len(raw) == row['bytes'], 'source member differs from frozen input')
    attempt = read_json(SPECIMEN / 'run/controller-attempt.json')
    receipt = read_json(SPECIMEN / 'run/controller-receipt.json')
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
    external.append(args.join_receipt.resolve())
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
    summary = {'schema': 'lineage-full5-checkpoint-v1', 'source_commit': COMMIT,
        'junit': closed['junit'], 'source_files': closed['source_count'], 'source_bytes_unchanged': True,
        'wall_seconds': closed['wall_seconds'], 'native_session_joined': 55470,
        'controller_status': receipt['status'], 'expected_cells': 34, 'succeeded_cells': 34,
        'synthetic_solver_main_calls': 136, 'synthetic_evaluator_main_calls': 34, 'panel_gates': panels,
        'real_model_calls': 0, 'paid_api_calls': 0, 'validation_read': False,
        'scientific_effectiveness_proven': False, 'retained_noncredential_files': len(members),
        'original_bytes_and_mtimes_unchanged': True,
        'prior_full4': 'separate incomplete original remains incomplete; no cells reused or reclassified'}
    (DEST / 'summary.json').write_bytes((json.dumps(summary, indent=2) + '\n').encode())
    (DEST / 'README.md').write_text(f'''# Complete four-panel headless lineage engineering checkpoint

Source `{COMMIT}` passed the original 11-check run: label isolation and the
complete 34-cell controller. Its {closed['source_count']} Python/Markdown source
files match the pre-run ZIP snapshot and the post-run hash map. The original
native session 55470 was joined before preserving any run files.

All 34 cells succeeded and the four independent scoring workers produced
eligible signed final closures with no unscored cells. The test used 136
synthetic solver MAIN calls and 34 synthetic evaluator MAIN calls, with actual
Docker execution and stdio workers. These are engineering fixtures; there were
no real model, paid API, or validation-data calls. They do not measure any
module's scientific effectiveness or complete the real benchmark experiments.

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
    print(json.dumps({'destination': str(DEST), 'summary': summary,
                     'published_manifest_sha256': sha((DEST / 'published-manifest.json').read_bytes())}), flush=True)


if __name__ == '__main__':
    main()
