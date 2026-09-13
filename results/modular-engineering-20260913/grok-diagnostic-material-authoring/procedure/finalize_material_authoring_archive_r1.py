"""Add requested safe handshake/time/cleanup metadata before archive commit."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

WORK = Path('E:/_ryanDev/AI/research-loop-modular/work')
OUT = WORK.parent / 'grok-materials/results/modular-engineering-20260913/grok-diagnostic-material-authoring'
RUN = WORK / 'material-authoring-actual-run-r1'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
old = json.loads((OUT / 'payload-sha256.json').read_text())
with zipfile.ZipFile(OUT / 'evidence.zip') as archive:
    assert set(archive.namelist()) == {e['path'] for e in old}
    for e in old:
        assert sha(OUT / e['path']) == e['sha256']
        assert archive.read(e['path']) == (OUT / e['path']).read_bytes()
native = next((RUN / 'private-output').glob('*/native/observer-receipt.json')).parent
requests = [json.loads(line) for line in (native / 'requests.private.jsonl').read_text().splitlines()]
methods = [r['method'] for r in requests]
assert methods == ['initialize']
receipt = json.loads((native / 'observer-receipt.json').read_text())
closure = json.loads((RUN / 'public-parent-closure.json').read_text())
def utc(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
paths = {'parent_reservation': RUN / 'parent-reservation.json',
    'native_initialize_request_stream': native / 'requests.private.jsonl',
    'native_terminal_receipt': native / 'observer-receipt.json',
    'parent_terminal_closure': RUN / 'public-parent-closure.json'}
metadata = {'schema': 'authoring-safe-terminal-protocol-metadata-v1',
    'outbound_method_counts': {'initialize': 1, 'session/new': 0, '_x.ai/billing': 0,
        '_x.ai/auto-topup-rule': 0, 'session/prompt': 0},
    'received_stdout_bytes': (native / 'stdout.private.jsonl').stat().st_size,
    'received_stderr_bytes': (native / 'stderr.private.txt').stat().st_size,
    'handshake': {'initialize_written': True, 'initialize_response_received': False,
        'session_new_reached': False, 'account_gates_reached': False,
        'selected_model_verified': False, 'same_session_empty_tools_verified': False},
    'filesystem_timestamps_utc': {name: {'created': utc(p.stat().st_birthtime),
        'last_write': utc(p.stat().st_mtime)} for name, p in paths.items()},
    'timestamps_are_filesystem_observations_not_rpc_server_timestamps': True,
    'parent_elapsed_seconds': closure['elapsed_seconds'], 'worker_exit_code': closure['worker_exit'],
    'native_process_exit_code': None, 'native_exit_code_not_recorded_by_original_transport': True,
    'parent_tree_closed': closure['parent_tree_closed'],
    'native_tree_cleanup_failure_reported': 'process_tree_shutdown_failure' in receipt['faults'],
    'owned_native_processes_remaining_observed': 0,
    'process_observation_method': 'Win32_Process Name=grok.exe and exact preparation directory in command line',
    'error_classes': receipt['faults'], 'retry_allowed': False}
path = WORK / 'material-authoring-terminal-protocol-metadata-r1.json'
with path.open('x', encoding='utf-8') as out:
    json.dump(metadata, out, indent=2, sort_keys=True); out.write('\n')
shutil.copyfile(path, OUT / 'actual/terminal-protocol-metadata.json')
shutil.copyfile(__file__, OUT / 'procedure/finalize_material_authoring_archive_r1.py')
entries = [{'path': p.relative_to(OUT).as_posix(), 'size': p.stat().st_size, 'sha256': sha(p)}
    for p in sorted(OUT.rglob('*')) if p.is_file() and p.name not in ('payload-sha256.json', 'evidence.zip')]
(OUT / 'payload-sha256.json').write_text(json.dumps(entries, indent=2) + '\n')
with zipfile.ZipFile(OUT / 'evidence.zip', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
    for item in entries:
        info = zipfile.ZipInfo(item['path'], date_time=(2026, 9, 14, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, (OUT / item['path']).read_bytes())
print(json.dumps({'payload_files': len(entries), 'archive_files': len(entries) + 2,
    'protocol_metadata_sha256': sha(path), 'error_classes': metadata['error_classes'],
    'handshake': metadata['handshake']}))
