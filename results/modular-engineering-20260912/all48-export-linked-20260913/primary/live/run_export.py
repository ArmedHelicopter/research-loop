import contextlib, hashlib, io, json, subprocess, sys, time
from pathlib import Path

PROJECT = Path('E:/_ryanDev/AI/research-loop-modular')
TREE = PROJECT / 'primary-prospective-export'
WORK = PROJECT / 'work/primary-prospective-export-live-r1'
SEALED = PROJECT / 'custody-private/primary-process-split-20260913-r2'
sys.path.insert(0, str(TREE))
from evaluation.modular.primary_prospective_exporter import PrimaryProspectiveTrainExporter, PrimaryTrainExportItem
from evaluation.modular.fresh_airs_custodian import _write_new
from evaluation.modular.train_io import PublicTrainPacket
from research_loop.modular.contracts import PublicTask, DataIdentity, FrozenRecord
from research_loop.ontology import digest

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def read(path):
    return json.loads(Path(path).read_bytes())

def source():
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=TREE, text=True).strip()

def check_bindings(request, before):
    assert source() == request['source_commit'] == '3558a7895de0b2369b691ab7c142a59cae6c3b15'
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=TREE)
    assert sha(WORK / 'frozen-request-r1.json') == before['request_sha256'] == '8713df0bccbd7dfd499e4461790bb5c983fe0b89b37d3eac98867df250cb6685'
    assert sha(WORK / 'primary-eligibility-r1.json') == before['eligibility_sha256'] == '1963e2684ea024af19a798b89cf8d1665f25008cc6fb5200310de41fa0dd3917'
    assert sha(request['config_path']) == request['config_raw_sha256']
    assert sha(PROJECT / 'work/primary-seal-root-verification-r1.json') == request['root_review_sha256']
    assert sha(PROJECT / 'work/primary-prospective-export-checks/delivery-verification-r1.json') == request['source_verification_sha256']
    assert sha(SEALED / 'prospective-split.json') == before['split_raw_sha256'] == request['split_raw_sha256']
    assert sha(SEALED / 'process-audit.json') == before['audit_raw_sha256'] == request['audit_raw_sha256']
    assert len(before['input_pins']) == 24
    assert all(sha(row['path']) == row['sha256'] for row in before['input_pins'].values())
    assert all(sha(row['path']) == row['sha256'] for row in before['protected_files'])
    assert all(sha(TREE / path) == value for path, value in before['source_files'].items())
    return {'input_pins_verified': 24, 'protected_files_verified': 4, 'source_files_verified': len(before['source_files']),
            'request_eligibility_and_seal_unchanged': True, 'source_commit': source(), 'worktree_clean': True}

def main():
    started = time.time()
    request = read(WORK / 'frozen-request-r1.json')
    before = read(WORK / 'before-bindings-r1.json')
    report = {'schema': 'primary-live-train-export-verification-v1', 'status': 'pending', 'attempts': 1,
              'requested_train_count': 4, 'model_calls': 0, 'scorer_calls': 0, 'docker_calls': 0,
              'network_calls': 0, 'validation_exports': 0, 'validation_leases_created': 0,
              'scientific_execution_qualified': False, 'license_qualification_claimed': False,
              'script_sha256': sha(__file__), 'request_sha256': sha(WORK / 'frozen-request-r1.json'),
              'eligibility_sha256': sha(WORK / 'primary-eligibility-r1.json')}
    phase = 'before_bindings'
    try:
        report['before'] = check_bindings(request, before)
        audit = read(SEALED / 'process-audit.json')
        split = read(SEALED / 'prospective-split.json')
        allocation = {token: group for group in split['groups'] for token in group['member_tokens']}
        expected = []
        for benchmark in ('discoverybench', 'blade'):
            tokens = sorted(row['token'] for row in audit['rows'] if row['source'] == benchmark and row['original_train'] is True and allocation[row['token']]['split'] == 'train')[:2]
            expected.extend({'source': benchmark, 'token': token, 'group_sha256': allocation[token]['group_sha256'],
                             'input_bindings_digest': digest(audit['input_bindings'])} for token in tokens)
        assert expected == request['items'] and len(expected) == 4
        items = [PrimaryTrainExportItem(**row) for row in request['items']]
        phase = 'export'
        exporter = PrimaryProspectiveTrainExporter(read(request['config_path']), SEALED,
            expected_split_digest=request['split_digest'], expected_audit_digest=request['audit_digest'],
            expected_split_sha256=request['split_raw_sha256'], expected_audit_sha256=request['audit_raw_sha256'],
            eligibility_path=WORK / 'primary-eligibility-r1.json', eligibility_sha256=report['eligibility_sha256'],
            output_root=WORK / 'public-train', audit_root=WORK / 'export-audit')
        packets = exporter.export_packets(items)
        report['export_returned_success'] = True
        phase = 'public_train_verification'
        assert len(packets) == 4 and all(type(packet) is PublicTrainPacket for packet in packets)
        packet_rows = []
        for item, packet in zip(items, packets, strict=True):
            envelope = read(packet.packet_path)
            restored = PublicTask(DataIdentity.parse(envelope['task']['identity']), FrozenRecord.from_dict(envelope['task']['payload']))
            restored.identity.require_train()
            metadata = packet.receipt.data()
            assert restored == packet.task and envelope['receipt'] == metadata
            assert read(packet.packet_path.parent / 'receipt.json') == metadata
            assert metadata['export_token'] == item.token and restored.identity.benchmark == item.source
            assert restored.identity.group_id == item.group_sha256 and restored.identity.split_id == request['split_digest']
            assert metadata['input_bindings_digest'] == item.input_bindings_digest
            assert metadata['packet_hash'] == restored.content_hash
            data = packet.csv_path.read_bytes()
            assert hashlib.sha256(data).hexdigest() == metadata['csv_sha256'] and len(data) == metadata['csv_byte_count']
            if item.source == 'discoverybench':
                selector = metadata['source_selector']
                assert set(selector) == {'metadata_file', 'metadata_sha256', 'query_index'} and selector['query_index'] == 0
                assert selector['metadata_sha256'] in {binding['sha256'] for binding in audit['input_bindings']}
            else:
                assert 'source_selector' not in metadata
            packet_rows.append({'source': item.source, 'token': item.token, 'group_sha256': item.group_sha256,
                'public_path': str(packet.packet_path), 'public_sha256': sha(packet.packet_path),
                'csv_path': str(packet.csv_path), 'csv_sha256': sha(packet.csv_path), 'csv_byte_count': len(data),
                'receipt_path': str(packet.packet_path.parent / 'receipt.json'),
                'receipt_sha256': sha(packet.packet_path.parent / 'receipt.json'),
                'public_task_sha256': restored.content_hash, 'public_packet_consumer_verified': True,
                'source_selector_verified': True})
        report['packets'] = packet_rows
        phase = 'journal_verification'
        journal = WORK / 'export-audit/exports.jsonl'
        rows = [json.loads(line) for line in journal.read_bytes().splitlines()]
        assert [row['event'] for row in rows] == ['export_reserved', 'sources_verified'] + ['exposure_reserved'] * 4 + ['export_completed']
        previous = '0' * 64
        for index, row in enumerate(rows, 1):
            core = {key: value for key, value in row.items() if key != 'entry_sha256'}
            assert row['entry_sha256'] == digest(core) and row['sequence'] == index and row['previous_sha256'] == previous
            assert row['request_sha256'] == digest([item.data() for item in items])
            assert row['model_calls'] == row['network_calls'] == row['known_cost_units'] == 0
            assert row['split_sha256'] == request['split_digest'] and row['audit_sha256'] == request['audit_digest']
            previous = row['entry_sha256']
        assert rows[-1]['possibly_exposed_tokens'] == sorted(item.token for item in items)
        export_receipt = WORK / 'public-train/export-receipt.json'
        assert rows[-1]['receipt_sha256'] == digest(read(export_receipt))
        report['journal'] = {'path': str(journal), 'sha256': sha(journal), 'events': len(rows), 'hash_chain_verified': True,
                             'failed_attempts': 0, 'completed_attempts': 1, 'possibly_exposed_train_tokens': 4}
        report['export_receipt'] = {'path': str(export_receipt), 'sha256': sha(export_receipt)}
        report['source_counts'] = {'discoverybench': 2, 'blade': 2}
        report['status'] = 'success'
    except BaseException as error:
        report['status'] = 'failed'
        report['failure_phase'] = phase
        report['error_category'] = type(error).__name__ if type(error).__name__ in {'CustodyError', 'AssertionError', 'ContractError', 'OSError', 'ValueError', 'KeyError', 'TypeError'} else 'other_exception'
        journal = WORK / 'export-audit/exports.jsonl'
        if journal.is_file():
            rows = [json.loads(line) for line in journal.read_bytes().splitlines()]
            report['journal'] = {'path': str(journal), 'sha256': sha(journal), 'events': len(rows),
                'failed_attempts': sum(row['event'] == 'export_failed' for row in rows),
                'completed_attempts': sum(row['event'] == 'export_completed' for row in rows),
                'possibly_exposed_train_tokens': len(rows[-1]['possibly_exposed_tokens']) if rows else 0}
    try:
        report['after'] = check_bindings(request, before)
        report['all_bindings_unchanged'] = True
    except BaseException:
        report['all_bindings_unchanged'] = False
        report['status'] = 'failed'
    report['elapsed_seconds'] = round(time.time() - started, 3)
    _write_new(WORK / 'actual-result-r1.json', report)
    return {'status': report['status'], 'phase': report.get('failure_phase'), 'actual_result_path': str(WORK / 'actual-result-r1.json'),
            'actual_result_sha256': sha(WORK / 'actual-result-r1.json'), 'export_returned_success': report.get('export_returned_success', False),
            'all_bindings_unchanged': report['all_bindings_unchanged'], 'journal': report.get('journal')}

if __name__ == '__main__':
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        result = main()
    print(json.dumps(result))
