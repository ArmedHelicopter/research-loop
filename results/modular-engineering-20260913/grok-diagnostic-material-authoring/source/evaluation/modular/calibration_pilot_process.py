"""Explicit one-shot calibration worker/parent boundary; no benchmark runtime spoofing.

The deployment owns billable and deterministic capacity ports. A worker entry
point calls serve_once with those explicit ports; there is no implicit model,
pricing, tokenizer or free review fallback. Tests use a separate canned helper.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from evaluation.modular.calibration_pilot import (
    DiagnosticAuthority, DiagnosticPilot, PrivateJournal, exact, pin, validate_manifest, verify,
)
from evaluation.modular.reference_store import FrozenTrainReferenceResolver, _plain, _read_bound
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError


def load_record(descriptor):
    exact(descriptor, ('path', 'sha256'))
    path = Path(descriptor['path'])
    if not path.is_absolute():
        raise ContractError('pilot file descriptor must be absolute')
    raw, _ = _read_bound(path, {pin(descriptor['sha256'])})
    try:
        return FrozenRecord.from_dict(json.loads(raw.decode('utf-8')))
    except Exception:
        raise ContractError('pilot frozen JSON is invalid') from None


def run_config(config: FrozenRecord, *, reviewer1, reviewer2, arbitrator, evaluator, capacity_port):
    body = exact(config.data(), ('schema', 'manifest', 'materials', 'key_files', 'reference_store', 'input_files', 'journal_path'))
    if body['schema'] != 'diagnostic-calibration-worker-config-v1':
        raise ContractError('worker configuration is not diagnostic calibration')
    manifest = load_record(body['manifest'])
    pilot_body, _, _ = validate_manifest(manifest)  # TRAIN grid before reference IO.
    if set(body['input_files']) != set(pilot_body['input_pins']):
        raise ContractError('worker source inventory differs')
    def check_sources():
        for name, path in body['input_files'].items():
            if not Path(path).is_absolute():
                raise ContractError('worker source path must be absolute')
            _read_bound(Path(path), {pilot_body['input_pins'][name]})
        for descriptor in (body['manifest'], body['materials'], *body['key_files'].values()):
            exact(descriptor, ('path', 'sha256'))
            if not Path(descriptor['path']).is_absolute():
                raise ContractError('worker custody path must be absolute')
            _read_bound(Path(descriptor['path']), {pin(descriptor['sha256'])})
    check_sources()
    materials = load_record(body['materials'])
    material_rows = {sid: FrozenRecord.from_dict(receipt) for sid, receipt in materials.data().items()}
    exact(body['key_files'], pilot_body['authorities'])
    keys = {}
    for role, descriptor in body['key_files'].items():
        exact(descriptor, ('path', 'sha256'))
        keys[role], _ = _read_bound(Path(descriptor['path']), {pin(descriptor['sha256'])})
    store = exact(body['reference_store'], ('root', 'manifest_sha256', 'inventory_digest', 'split_digest'))
    if not Path(store['root']).is_absolute() or not Path(body['journal_path']).is_absolute():
        raise ContractError('worker store and journal must be absolute')
    resolver = FrozenTrainReferenceResolver(Path(store['root']), manifest_sha256=pin(store['manifest_sha256']),
        inventory_digest=store['inventory_digest'], split_digest=store['split_digest'])
    authority = DiagnosticAuthority(pilot_body['authorities']['diagnostic'], keys['diagnostic'])
    pilot = DiagnosticPilot(manifest=manifest, resolver=resolver, materials=material_rows, keys=keys,
        journal_path=Path(body['journal_path']), capacity_port=capacity_port,
        reviewer1=reviewer1, reviewer2=reviewer2, arbitrator=arbitrator, evaluator=evaluator, authority=authority,
        source_guard=check_sources)
    result = pilot.run()
    try:
        check_sources()
        load_record(body['manifest'])
        load_record(body['materials'])
    except Exception:
        pilot.journal.append('postrun_source_rejected', {'status': 'ineligible_diagnostic'})
        raise ContractError('worker inputs changed during diagnostic run') from None
    return result


def serve_once(config_descriptor, *, reviewer1, reviewer2, arbitrator, evaluator, capacity_port, output_path):
    """Worker entry: stdout contains only a fixed status/hash, never private errors."""
    output = _plain(Path(output_path))
    if output.exists():
        raise ContractError('worker output already exists')
    try:
        config = load_record(config_descriptor)
        result = run_config(config, reviewer1=reviewer1, reviewer2=reviewer2,
            arbitrator=arbitrator, evaluator=evaluator, capacity_port=capacity_port)
        with output.open('x', encoding='utf-8') as stream:
            stream.write(result.encoded)
        print(json.dumps({'status': 'completed', 'receipt_sha256': hashlib.sha256(output.read_bytes()).hexdigest()}))
        return 0
    except Exception:
        print(json.dumps({'status': 'failed', 'receipt_sha256': None}))
        return 1


def launch_once(*, command: list[str], executable_sha256: str, worker_sha256: str, config_descriptor,
                result_path: Path, parent_journal_path: Path, timeout_seconds: int):
    """Caller supplies its pinned worker deployment. No shell or auto-retry.

    The command must include the frozen config and output arguments supplied by
    the deployment. The signed diagnostic receipt still needs caller verification.
    This boundary deliberately does not claim OS isolation.
    """
    if not command or any(not isinstance(arg, str) or not arg for arg in command):
        raise ContractError('pilot subprocess command is invalid')
    if len(command) != 8 or command[2:] != ['--config', config_descriptor['path'], '--sha256', config_descriptor['sha256'], '--output', str(result_path)]:
        raise ContractError('pilot subprocess command does not bind exact config and output')
    if not Path(command[0]).is_absolute() or not Path(command[1]).is_absolute():
        raise ContractError('pilot executable and worker must be absolute')
    _read_bound(Path(command[0]), {pin(executable_sha256)})
    _read_bound(Path(command[1]), {pin(worker_sha256)})
    config = load_record(config_descriptor).data()
    manifest = load_record(config['manifest'])
    manifest_body, _, _ = validate_manifest(manifest)
    key_descriptor = config['key_files']['diagnostic']
    key, _ = _read_bound(Path(key_descriptor['path']), {pin(key_descriptor['sha256'])})
    if type(timeout_seconds) is not int or timeout_seconds <= 0:
        raise ContractError('pilot process timeout must be explicit')
    if _plain(result_path).exists():
        raise ContractError('pilot subprocess result exists')
    journal = PrivateJournal(parent_journal_path)
    journal.append('process_reserved', {'config_sha256': config_descriptor['sha256'],
        'executable_sha256': executable_sha256, 'command_digest': FrozenRecord.from_dict({'command': command}).content_hash})
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout_seconds, check=False, shell=False)
        for suffix, raw in (('.stdout.bin', result.stdout), ('.stderr.bin', result.stderr)):
            with _plain(Path(str(parent_journal_path) + suffix)).open('xb') as stream:
                stream.write(raw)
        journal.append('process_closed', {'exit_code': result.returncode,
            'stdout_sha256': hashlib.sha256(result.stdout).hexdigest(), 'stderr_sha256': hashlib.sha256(result.stderr).hexdigest()})
        if result.returncode != 0:
            raise ContractError('pilot subprocess failed')
        receipt = FrozenRecord(_plain(result_path).read_text(encoding='utf-8'))
        body = verify(receipt, role='diagnostic', subject=manifest.content_hash,
            authority_id=manifest_body['authorities']['diagnostic'], key=key)
        if (body.get('schema') != 'four-train-diagnostic-observation-v1' or body.get('validation_eligible') is not False
                or body.get('calibration_eligible') is not False or body.get('manifest_digest') != manifest.content_hash
                or body.get('evaluator_opportunity_count') != 72 or len(body.get('observations', [])) != 72):
            raise ContractError('pilot subprocess emitted non-diagnostic receipt')
        _read_bound(Path(command[1]), {worker_sha256})
        load_record(config_descriptor)
        return receipt
    except subprocess.TimeoutExpired as exc:
        captured = {}
        for suffix, raw in (('.timeout-stdout.bin', exc.stdout), ('.timeout-stderr.bin', exc.stderr)):
            if isinstance(raw, str):
                raw = raw.encode('utf-8')
            if raw is not None:
                with _plain(Path(str(parent_journal_path) + suffix)).open('xb') as stream:
                    stream.write(raw)
                captured[suffix] = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'complete': False}
            else:
                captured[suffix] = {'sha256': None, 'bytes': None, 'complete': False}
        journal.append('process_unknown', {'reason': 'timeout', 'automatic_retry': False, 'captured_partial_streams': captured,
            'child_call_count': None, 'child_tokens': None, 'child_microusd': None,
            'child_cost_status': 'unknown_requires_private_journal_reconciliation'})
        raise ContractError('pilot subprocess outcome unknown') from None
    except Exception:
        journal.append('process_rejected', {'reason': 'failed_or_invalid_bound_result', 'automatic_retry': False})
        raise ContractError('pilot subprocess failed or returned an invalid bound result') from None
