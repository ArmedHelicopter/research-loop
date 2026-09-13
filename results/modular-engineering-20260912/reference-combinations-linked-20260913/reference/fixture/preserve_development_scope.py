import hashlib,json
from pathlib import Path
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
base=Path('E:/_ryanDev/AI/research-loop-modular')
work=base/'work/primary-reference-checks'
source=base/'pr-ref/evaluation/modular/primary_reference_bridge.py'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
raw=source.read_bytes()
before=raw.decode().replace(', FrozenTrainReferenceResolver\n','\n')
before=before.replace('        lock_path = self.audit_root / "reference.lock"\n        try:\n            _concrete(self.audit_root)\n            self.audit_root.mkdir(parents=True, exist_ok=True)\n            _concrete(self.audit_root)\n', '        self.audit_root.mkdir(parents=True, exist_ok=True)\n        _concrete(self.audit_root)\n        lock_path = self.audit_root / "reference.lock"\n        try:\n')
start=before.index('                published = publication.data()\n')
end=before.index('                self._finish_checks(items, audit)\n', start)
before=before[:start]+before[end:]
before=before.replace('            try:\n                lock_path.unlink()\n            except BaseException:\n                raise CustodyError() from None\n','            lock_path.unlink()\n')
(work/'boundary-r3-source-reconstructed-before.py').write_bytes(before.encode())
(work/'boundary-r3-source-after.py').write_bytes(raw)
junit=work/'boundary-r3.xml'
suite=ET.parse(junit).getroot().find('testsuite')
record={'schema':'development-test-source-change-receipt-v1','status':'invalid_for_frozen_verification',
    'process_tool_session_id':25716,'process_exit_code':0,'reported_tests':24,'reported_failures':0,
    'junit_path':str(junit),'junit_sha256':sha(junit),'started_at':suite.attrib['timestamp'],
    'duration_seconds':float(suite.attrib['time']),
    'source_edit_mtime_utc':datetime.fromtimestamp(source.stat().st_mtime,timezone.utc).isoformat(),
    'changed_file':'evaluation/modular/primary_reference_bridge.py',
    'pre_edit_sha256_reconstructed':sha(work/'boundary-r3-source-reconstructed-before.py'),
    'pre_edit_hash_provenance':'reconstructed_by_reversing_exact_in_turn_patch_not_independent_pre_run_snapshot',
    'post_edit_sha256':sha(work/'boundary-r3-source-after.py'),
    'observed_sequence':['pytest_started','source_edited_while_process_running','parent_notified','pytest_exited_0','later_test_edits_started'],
    'disposition':'retain_original_report_and_repeat_full_suite_after_source_commit_freeze'}
with (work/'boundary-r3-source-change.json').open('x') as f:json.dump(record,f,indent=2)
live=base/'work/primary-prospective-export-live-r1'
request=json.loads((live/'frozen-request-r1.json').read_bytes())
result=json.loads((live/'actual-result-r1.json').read_bytes())
assert result['status']=='success' and result['all_bindings_unchanged'] and len(result['packets'])==4
packets=[]
for item,row in zip(request['items'],result['packets'],strict=True):
    assert item['token']==row['token'] and item['source']==row['source']
    for role in ('public','csv','receipt'):
        assert sha(Path(row[role+'_path']))==row[role+'_sha256']
    packets.append({'item':item,'task_sha256':row['public_task_sha256'],
        'public_sha256':row['public_sha256'],'csv_sha256':row['csv_sha256'],'receipt_sha256':row['receipt_sha256']})
plan={'schema':'prospective-primary-reference-preparation-plan-v1','status':'awaiting_contract_review_and_explicit_reference_preparation_authorization',
    'selection_rule':request['selection_rule'],'requests':packets,
    'frozen_public_request':{'path':str(live/'frozen-request-r1.json'),'sha256':sha(live/'frozen-request-r1.json')},
    'frozen_public_receipt':{'path':result['export_receipt']['path'],'sha256':result['export_receipt']['sha256']},
    'public_task_and_csv_byte_pins_rechecked':4,'original_public_artifacts_mutated':False,
    'split_digest':request['split_digest'],'audit_digest':request['audit_digest'],
    'split_raw_sha256':request['split_raw_sha256'],'audit_raw_sha256':request['audit_raw_sha256'],
    'discovery_answer_key_descriptors':'requires_reviewed_exact_path_sha256_and_encoding_no_answer_file_read_in_this_stage',
    'blade_reference_binding':'existing_inventory_and_audit_exact_annotations_locator_and_sha256_required_by_bridge',
    'next_steps':['root_reviews_bridge_contract_and_frozen_checks','freeze_explicit_answer_key_descriptors_and_four_item_request',
        'root_authorizes_custodian_reference_preparation','prepare_one_new_scorer_private_store_and_journal_without_solver_mount',
        'verify_standard_resolver_and_reference_publication_metadata_without_task_substitution'],
    'actual_reference_preparation_executed':False,'actual_answer_or_reference_payload_reads':0,
    'validation_reference_count':0,'validation_lease_created':False,'model_calls':0,'network_calls':0,
    'scientific_validity':'not_measured','calibration':'not_measured','license_qualification_claimed':False}
with (work/'actual-four-train-reference-plan-r1.json').open('x') as f:json.dump(plan,f,indent=2)
print(json.dumps({'development_source_change_receipt_sha256':sha(work/'boundary-r3-source-change.json'),
    'actual_plan_sha256':sha(work/'actual-four-train-reference-plan-r1.json'),
    'metadata_only_plan':True,'actual_reference_reads':0}))
