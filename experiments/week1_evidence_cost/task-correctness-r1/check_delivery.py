"""Verify appended review package, old frozen index and numerical known answers."""
import argparse
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError('Delivery receipts are append-only')
    base = args.source / 'experiments/week1_evidence_cost'
    package = base / 'task-correctness-r1'
    manifest = json.loads((package/'MANIFEST.json').read_text(encoding='utf-8'))
    for name, digest in manifest['files'].items():
        assert sha(base/name) == digest, name
    frozen = json.loads((base/'EVIDENCE-FILES.json').read_text(encoding='utf-8'))
    for item in frozen['files']:
        assert sha(base/item['path']) == item['sha256'], item['path']
    result = json.loads((package/'recomputation-r1.json').read_text(encoding='utf-8'))
    assert result['all_selected_checks_passed'] and not result['failures']
    assert result['check_count'] == len(result['checks']) == 401
    assert all(c['passed'] for c in result['checks'])
    for name, digest in result['input_sha256'].items():
        assert sha(Path(name)) == digest, name
    assert sha(package/'verify_existing.py') == result['script_sha256']
    spec = importlib.util.spec_from_file_location('review_verifier', package/'verify_existing.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.quantile([0, 0, 1, 2], .75) == 1.25
    assert module.ranks([3, 1, 1, 2]) == [4., 1.5, 1.5, 3.]
    beta, covariance, _ = module.logistic([-1,-1,0,0,1,1], [0,1,0,1,0,1])
    assert max(abs(beta)) < 1e-12
    assert abs(covariance[0,0] - 2/3) < 1e-12
    assert abs(covariance[1,1] - .8) < 1e-12
    assert module.corr([1,2,3], [3,2,1]) == -1
    receipt = dict(schema='existing-task-review-delivery-v1', recorded_at=datetime.now(timezone.utc).isoformat(),
        source_commit=manifest['source_commit'], package_files_verified=len(manifest['files']),
        old_index_files_unchanged=len(frozen['files']), read_input_files_unchanged=len(result['input_sha256']),
        old_index_sha256=sha(base/'EVIDENCE-FILES.json'), manifest_sha256=sha(package/'MANIFEST.json'),
        recomputation_checks=401, mismatches=0,
        known_answers=['linear quantile','tie-averaged ranks','balanced logistic coefficients',
                       'balanced logistic HC0 intercept variance','balanced logistic HC0 slope variance','negative correlation sign'],
        original_inputs_unchanged=True, new_model_calls=0, core_modified=False,
        script_sha256=sha(Path(__file__)), status='verified')
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    main()
