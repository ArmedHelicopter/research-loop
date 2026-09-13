"""Bounded audit metadata only; never parse task or reference payloads."""
import hashlib
import json
import subprocess
from pathlib import Path

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
REPO = BASE / 'integration'
OUT = BASE / 'work/primary-scoring-calibration-audit-r1'
SNAP = Path('E:/_ryanDev/AI/research-loop-benchmark-20260912')
AUDIT_REF = '8d8ff1028db8572431db78018f920c01e35bf47c'
FILES = '''evaluation/modular/scoring_service.py
evaluation/modular/calibration.py
evaluation/modular/custody.py
evaluation/modular/scorer_process.py
evaluation/modular/evaluator_model_port.py
evaluation/modular/reference_store.py
evaluation/modular/primary_reference_bridge.py
evaluation/modular/linked_scoring.py
evaluation/modular/combination_scoring.py
research_loop/modular/benchmarks/scoring.py
tests/test_modular_calibration.py
docs/MODULAR-ADAPTED-SCORING-SERVICE.md
docs/MODULAR-EXPERIMENT-PROTOCOL.md
docs/MODULAR-TRAIN-REFERENCE-STORE.md
docs/MODULAR-LINKED-SCORER-PROCESS.md
docs/MODULAR-IMPLEMENTATION-STATUS.md
docs/MODULAR-SCORING-SCENARIOS.md
docs/MODULAR-CHECKPOINT-20260913-SCORING-RECOVERY.md
docs/MODULAR-CHECKPOINT-20260913-SCORER.md
docs/AUDIT-SCORER-READ-SCOPE-DEVIATION-20260913.md'''.splitlines()
UPSTREAM = '''discovery/upstream/discovery_eval.py
discovery/upstream/eval/eval.py
discovery/upstream/eval/new_eval.py
scienceagent/work/BLADE/blade_bench/eval/evaluator.py
scienceagent/work/BLADE/blade_bench/eval/match/match_submission.py
scienceagent/work/BLADE/blade_bench/eval/match/conceptual_variable.py
scienceagent/work/BLADE/blade_bench/eval/match/model.py
scienceagent/work/BLADE/blade_bench/eval/match/transform.py
scienceagent/work/BLADE/blade_bench/eval/metrics/all_metrics.py
scienceagent/work/BLADE/blade_bench/eval/metrics/base.py
scienceagent/work/BLADE/blade_bench/eval/metrics/cvar.py
scienceagent/work/BLADE/blade_bench/eval/metrics/model.py
scienceagent/work/BLADE/blade_bench/eval/metrics/transform.py
scienceagent/work/BLADE/blade_bench/eval/metrics/calc_metrics.py'''.splitlines()
EVIDENCE = '''work/primary-reference-checks/frozen-r1.xml
work/primary-reference-checks/delivery-verification-r1.json
work/primary-reference-checks/actual-four-train-reference-plan-r1.json
work/primary-reference-checks/actual-four-train-reference-descriptor-r2.json
work/primary-prospective-reference-live-r1/delivery-manifest-r1.json
work/primary-prospective-reference-live-r1/actual-result-r1.json
work/primary-prospective-reference-live-r1/frozen-reference-request-r1.json
work/primary-prospective-reference-live-r1/attempt-metadata-r1.json
work/primary-prospective-reference-live-r1/reference-publication-r1.json
work/primary-prospective-export-live-r1/frozen-request-r1.json
work/primary-prospective-export-live-r1/delivery-manifest-r1.json
work/primary-prospective-export-live-r1/public-train/export-receipt.json
work/primary-prospective-export-live-r1/export-audit/exports.jsonl'''.splitlines()
def sha(data):
    return hashlib.sha256(data).hexdigest()
def pin(path):
    if not path.is_file():
        return {'path': str(path), 'status': 'missing'}
    b = path.read_bytes()
    return {'path': str(path), 'status': 'present', 'size_bytes': len(b), 'sha256': sha(b)}
def git(*args):
    return subprocess.check_output(['git', '-C', str(REPO), *args], stderr=subprocess.DEVNULL)
def main():
    target = OUT / 'evidence-manifest-r1.json'
    if target.exists():
        raise RuntimeError('exclusive_output_exists')
    source = []
    for rel in FILES:
        row = pin(REPO / rel)
        blob = git('show', AUDIT_REF + ':' + rel)
        row.update({'repository_path': rel, 'audit_commit_blob_sha256': sha(blob),
                    'working_bytes_equal_audit_commit': row.get('sha256') == sha(blob)})
        source.append(row)
    official = [pin(SNAP / rel) for rel in UPSTREAM]
    evidence = [pin(BASE / rel) for rel in EVIDENCE]
    body = {'schema': 'primary-scoring-calibration-readonly-audit-evidence-v1',
            'audit_started_head': '0063ca1f08a91658022f87ff4443f32e71c9eefa',
            'audit_reference_commit': AUDIT_REF, 'head_at_manifest': git('rev-parse', 'HEAD').decode().strip(),
            'integration_was_concurrently_advanced_by_parent': True,
            'source_files': source, 'official_local_code': official, 'prior_metadata_evidence': evidence,
            'official_discovery_upstream_revision': 'unknown',
            'official_blade_upstream_revision': '6118fa8d5007b91aa8c91c518182db82446a4547',
            'scope': {'source_edits': 0, 'reference_payload_reads': 0, 'validation_payload_reads': 0,
                      'model_calls': 0, 'scorer_calls': 0, 'docker_calls': 0,
                      'tests_run': 0, 'new_validation_leases': 0,
                      'public_web_source_inspection': True,
                      'official_code_executed_or_imported': False,
                      'historical_claims_are_receipt_scoped': True},
            'source_binding_note': 'Discovery source pin remains unknown; local code hashes identify inspected bytes. Current online main is not asserted identical to these bytes. Only scorer_process.py among the six primary endpoint files compared changed during the initial audit interval; read diff adds a separate retrieval combination scope, leaving primary rubric unchanged.',
            'official_urls': ['https://github.com/allenai/discoverybench/blob/main/discovery_eval.py',
                              'https://github.com/allenai/discoverybench/blob/main/eval/new_eval.py',
                              'https://github.com/behavioral-data/BLADE',
                              'https://blade-bench.github.io/'],
            'calibration_claim': 'not_measured', 'official_metric_equivalence': 'not_established',
            'scientific_effectiveness': 'not_measured'}
    target.write_text(json.dumps(body, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': 'metadata_written', 'source_count': len(source), 'official_code_count': len(official),
                      'prior_evidence_count': len(evidence), 'missing_evidence_count': sum(r['status']=='missing' for r in evidence),
                      'source_commit_mismatches': sum(not r['working_bytes_equal_audit_commit'] for r in source),
                      'manifest': str(target), 'sha256': sha(target.read_bytes())}))
if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'status': 'failed', 'error_class': type(exc).__name__}))
        raise SystemExit(1)
