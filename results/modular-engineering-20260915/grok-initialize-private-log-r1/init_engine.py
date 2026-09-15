"""One constant initialize write; no session/prompt dispatcher or material input."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import queue
import subprocess
import threading
import time

from research_loop.modular.grok_acp_transport import ProcessTree

REQUEST = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
    'protocolVersion': 1, 'clientCapabilities': {},
    'clientInfo': {'name': 'research-loop-bounded-acp', 'version': '1'},
    '_meta': {'startupHints': {'nonInteractive': True, 'skipGitStatus': True, 'skipProjectLayout': True}}}}
WIRE = (json.dumps(REQUEST, separators=(',', ':'), sort_keys=True) + '\n').encode()
MAX_BYTES = 1024 * 1024


def decode(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate field')
            result[key] = value
        return result
    return json.loads(data.decode('utf-8'), object_pairs_hook=pairs)


def run_once(command, *, cwd, env, directory, frozen_files, timeout=60, close_stdin=False):
    """Synthetic commands are injected for fixtures; production caller pins exe.

    There is exactly one stdin write in this function, using the constant WIRE.
    No caller argument can select an RPC method, session, prompt, or material.
    """
    root = Path(directory); root.mkdir(parents=True, exist_ok=False)
    for name, expected in frozen_files.items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != expected:
            raise ValueError('source pin differs')
    reservation = {'schema': 'initialize-only-reservation-v1', 'initialize_writes_max': 1,
        'session_new_writes_max': 0, 'prompt_writes_max': 0, 'retry': False,
        'wire_sha256': hashlib.sha256(WIRE).hexdigest(), 'timeout_seconds': timeout,
        'source_manifest_sha256': hashlib.sha256(json.dumps(frozen_files, sort_keys=True).encode()).hexdigest()}
    with (root / 'reservation.json').open('x', encoding='utf-8') as stream:
        import os
        json.dump(reservation, stream, sort_keys=True); stream.flush(); os.fsync(stream.fileno())
    started = time.monotonic(); started_utc = datetime.now(timezone.utc).isoformat()
    deadline = started + timeout; events = queue.Queue(); tree = None; threads = []
    faults = []; response = None; write_attempted = False; writes_completed = 0
    stdout_frames = 0; server_requests = 0; reader_bytes = {'stdout': 0, 'stderr': 0}
    shutdown_elapsed = None; exit_code = None; pid = None; cleanup = False
    raw_out = (root / 'stdout.private.bin').open('xb')
    raw_err = (root / 'stderr.private.bin').open('xb')
    def reader(pipe, stream, kind):
        try:
            while True:
                data = pipe.readline(MAX_BYTES + 1) if kind == 'stdout' else pipe.read(65536)
                if not data:
                    break
                room = MAX_BYTES - reader_bytes[kind]
                stream.write(data[:max(room, 0)]); stream.flush()
                reader_bytes[kind] += len(data)
                if reader_bytes[kind] > MAX_BYTES or len(data) > MAX_BYTES:
                    events.put(('fault', kind + '_byte_limit')); return
                if kind == 'stdout':
                    events.put(('frame', data))
        except (OSError, ValueError):
            events.put(('fault', kind + '_reader_failure'))
        finally:
            if kind == 'stdout': events.put(('eof', None))
    try:
        tree = ProcessTree(command, cwd, env, subprocess.PIPE); pid = tree.process.pid
        for pipe, stream, kind in ((tree.process.stdout, raw_out, 'stdout'),
                                   (tree.process.stderr, raw_err, 'stderr')):
            thread = threading.Thread(target=reader, args=(pipe, stream, kind), daemon=True)
            thread.start(); threads.append(thread)
        write_attempted = True
        tree.process.stdin.write(WIRE); tree.process.stdin.flush(); writes_completed = 1
        if close_stdin: tree.process.stdin.close()
        (root / 'request.private.jsonl').write_bytes(WIRE)
        quiet_deadline = None
        while not faults:
            now = time.monotonic()
            if now >= deadline:
                faults.append('timeout'); break
            if response is not None and quiet_deadline is not None and now >= quiet_deadline:
                break
            wait = min(deadline - now, .05)
            if quiet_deadline is not None: wait = min(wait, max(quiet_deadline - now, .001))
            try:
                kind, data = events.get(timeout=wait)
            except queue.Empty:
                continue
            if kind == 'fault': faults.append(data); break
            if kind == 'eof':
                if response is None: faults.append('unexpected_eof')
                break
            stdout_frames += 1
            try:
                frame = decode(data)
            except (ValueError, UnicodeError):
                faults.append('malformed_json'); break
            if not isinstance(frame, dict) or frame.get('jsonrpc') != '2.0':
                faults.append('invalid_envelope'); break
            if 'method' in frame:
                server_requests += int('id' in frame)
                faults.append('unsolicited_server_request' if 'id' in frame else 'unexpected_notification'); break
            if response is not None:
                faults.append('extra_response'); break
            if type(frame.get('id')) is not int or frame['id'] != 1:
                faults.append('response_id_mismatch'); break
            if 'error' in frame:
                faults.append('initialize_rpc_error'); break
            if set(frame) != {'jsonrpc', 'id', 'result'} or not isinstance(frame['result'], dict):
                faults.append('initialize_result_shape'); break
            result = frame['result']
            if (type(result.get('protocolVersion')) is not int or result['protocolVersion'] != 1
                    or set(result) - {'protocolVersion', 'agentCapabilities', 'agentInfo', 'authMethods', '_meta'}):
                faults.append('initialize_result_contract'); break
            response = {'protocol_version': 1, 'result_keys': sorted(result),
                'response_sha256': hashlib.sha256(data).hexdigest(),
                'response_elapsed_seconds': time.monotonic() - started}
            quiet_deadline = min(deadline, time.monotonic() + .1)
    except (OSError, ValueError, subprocess.SubprocessError):
        faults.append('local_io_failure')
    finally:
        shutdown_elapsed = time.monotonic() - started
        if tree:
            try:
                tree.close(); exit_code = tree.process.returncode; cleanup = True
            except (OSError, subprocess.SubprocessError):
                faults.append('process_tree_shutdown_failure')
            for thread in threads: thread.join(timeout=2)
            if tree.process.stderr: tree.process.stderr.close()
        raw_out.close(); raw_err.close()
    for name, expected in frozen_files.items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != expected:
            faults.append('source_drift')
    # Any already-captured extra frame remains visible and rejects acceptance.
    while not events.empty():
        kind, data = events.get_nowait()
        if kind == 'frame': faults.append('extra_captured_frame')
        elif kind == 'fault': faults.append(data)
    result = {'schema': 'initialize-only-closure-v1', 'accepted_initialize': response is not None and not faults,
        'faults': sorted(set(faults)), 'initialize_write_attempted': write_attempted,
        'initialize_writes_completed': writes_completed, 'outbound_method_counts': {'initialize': writes_completed,
            'session/new': 0, 'authenticate': 0, '_x.ai/billing': 0, '_x.ai/auto-topup-rule': 0, 'session/prompt': 0},
        'stdout_frames_parsed': stdout_frames, 'server_requests_observed': server_requests,
        'response': response, 'started_utc': started_utc, 'shutdown_started_seconds': shutdown_elapsed,
        'elapsed_seconds': time.monotonic() - started, 'native_process_id': pid,
        'native_exit_code_after_shutdown': exit_code, 'process_tree_closed': cleanup,
        'stdout_bytes': (root / 'stdout.private.bin').stat().st_size,
        'stderr_bytes': (root / 'stderr.private.bin').stat().st_size,
        'stream_hashes': {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in ('stdout.private.bin', 'stderr.private.bin')},
        'retry_allowed': False, 'model_account_tools_verified': False,
        'known_model_usage': None, 'settled_additional_charge_usd': None}
    (root / 'public-closure.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result

