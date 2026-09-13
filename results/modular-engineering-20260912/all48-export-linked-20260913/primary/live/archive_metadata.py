import contextlib, hashlib, io, json, subprocess, sys
from pathlib import Path
BASE = Path('E:/_ryanDev/AI/research-loop-modular')
TREE = BASE / 'primary-prospective-export'
WORK = BASE / 'work/primary-prospective-export-live-r1'
sys.path.insert(0, str(TREE))
from evaluation.modular.fresh_airs_custodian import _write_new

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_bytes())

def main():
    report = read(WORK / 'actual-result-r1.json')
    assert report['status'] == 'success' and report['all_bindings_unchanged']
    before = read(WORK / 'before-bindings-r1.json')
    after = dict(before)
    after['schema'] = 'primary-export-after-bindings-v1'
    after['input_pins'] = {key: {'path': row['path'], 'sha256': sha(row['path'])} for key, row in before['input_pins'].items()}
    after['protected_files'] = [{'path': row['path'], 'sha256': sha(row['path'])} for row in before['protected_files']]
    after['source_files'] = {key: sha(TREE / key) for key in before['source_files']}
    assert all(after[key] == before[key] for key in ('input_pins', 'protected_files', 'source_files'))
    assert len(report['packets']) == 4
    root = WORK / 'public-train'
    expected = {root / 'export-receipt.json'}
    for row in report['packets']:
        for key in ('public', 'csv', 'receipt'):
            path = Path(row[key + '_path'])
            assert path.is_relative_to(root) and sha(path) == row[key + '_sha256']
            expected.add(path)
    assert set(root.rglob('*')) == expected | {Path(row['public_path']).parent for row in report['packets']}
    after['exact_public_file_count'] = len(expected)
    after['all_protected_and_input_bytes_unchanged'] = True
    _write_new(WORK / 'after-bindings-r1.json', after)
    paths = [WORK / name for name in ('prepare_request.py', 'run_export.py', 'archive_metadata.py',
        'frozen-request-r1.json', 'primary-eligibility-r1.json', 'before-bindings-r1.json',
        'after-bindings-r1.json', 'actual-result-r1.json', 'export-audit/exports.jsonl')]
    paths += sorted(expected)
    checks = BASE / 'work/primary-prospective-export-checks'
    paths += [checks / name for name in ('delivery-verification-r1.json', 'source-freeze-r1.json', 'frozen-r1.xml')]
    paths += [BASE / 'work/primary-seal-root-verification-r1.json']
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=TREE, text=True).strip()
    assert head == '3558a7895de0b2369b691ab7c142a59cae6c3b15'
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=TREE)
    manifest = {'schema': 'primary-live-train-export-delivery-v1', 'status': 'success', 'source_commit': head,
        'worktree_clean': True, 'source_modified_for_actual_run': False,
        'attempts': 1, 'failed_attempts': 0, 'completed_attempts': 1, 'public_tasks': 4,
        'source_counts': {'discoverybench': 2, 'blade': 2}, 'input_pins_unchanged': 24,
        'protected_files_unchanged': 4, 'journal_events': 7, 'validation_exports': 0,
        'validation_leases_created': 0, 'model_calls': 0, 'scorer_calls': 0, 'docker_calls': 0,
        'network_calls': 0, 'known_cost_units': 0, 'cost_status': 'local_export_no_model_or_network_io',
        'scientific_execution_qualified': False, 'license_qualification_claimed': False,
        'scope': 'fixed_original_train_members_public_projection_and_csv_only',
        'artifacts': [{'path': str(path), 'sha256': sha(path), 'bytes': path.stat().st_size} for path in paths]}
    _write_new(WORK / 'delivery-manifest-r1.json', manifest)
    return {'status': 'success', 'manifest_path': str(WORK / 'delivery-manifest-r1.json'),
        'manifest_sha256': sha(WORK / 'delivery-manifest-r1.json'), 'artifact_count': len(paths),
        'after_bindings_sha256': sha(WORK / 'after-bindings-r1.json'),
        'export_receipt_sha256': sha(root / 'export-receipt.json')}

if __name__ == '__main__':
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        result = main()
    print(json.dumps(result))
