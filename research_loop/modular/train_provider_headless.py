"""Original-evidence adapter for the distinct headless Grok TRAIN port.

Acquisition reuses headless diagnostic receipts. Acceptance here establishes
request consumption and observed MAIN usage, not scientific or billing truth.
"""
import hashlib
import json
from pathlib import Path

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.grok_acp_transport import TRAIN_OPPORTUNITY_CONTRACT
from research_loop.modular.grok_headless_train_solver import (
    GrokHeadlessTrainModelPort, _replay_headless_native_call)
from research_loop.modular.grok_headless_transport import HEADLESS_TRAIN_TIMEOUT_MAX_SECONDS, inspect_grok_stream
from research_loop.ontology import ContractError, canonical

PROMPT = 'Return only JSON conforming to the supplied schema. Tools, browsing, filesystem access, and evaluation material are unavailable.\n'


def sha(raw): return hashlib.sha256(raw).hexdigest()
def read(path): return json.loads(Path(path).read_bytes())
def require(value, message):
    if not value: raise ContractError(message)


def configuration(backend):
    require(type(backend) is GrokHeadlessTrainModelPort, 'exact headless TRAIN port required')
    config = read(backend.ledger_path)['config']
    require(config == backend.ledger['config'], 'headless configuration memory/disk drift')
    require(type(backend.timeout_seconds) is int and 1 <= backend.timeout_seconds <= HEADLESS_TRAIN_TIMEOUT_MAX_SECONDS,
            'headless timeout outside frozen TRAIN bounds')
    expected = {'schema': 'grok-headless-train-solver-port-v1',
        'provider_kind': 'grok-headless-public-train-v1', 'model': 'grok-4.6',
        'opportunity_contract': TRAIN_OPPORTUNITY_CONTRACT,
        'reasoning_effort': 'low', 'timeout_seconds': backend.timeout_seconds, 'max_retries': 0,
        'paid_fallback': False, 'included_only': True, 'api_key_route_permitted': False,
        'title_opportunities_per_main': 1, 'title_usage_and_all_call_totals': 'unknown',
        'max_calls': backend.max_calls, 'schemas': backend.schemas,
        'slot_output_caps': backend.slot_output_caps,
        'slot_input_byte_caps': backend.slot_input_byte_caps,
        'observed_main_token_cap': backend.observed_main_token_cap,
        'account_read_recovery': backend.account_read_recovery,
        'executable': backend.executable, 'frozen_files': backend.frozen_files,
        'private_home': str(backend.private_home),
        'private_profile_root': str(backend.private_profile),
        'public_cwd_root': str(backend.public_cwd)}
    if backend.native_deployment is None:
        require('native_deployment' not in config and 'native_deployment_digest' not in config,
                'legacy headless deployment drift')
    else:
        expected.update(native_deployment=backend.native_deployment.record.data(),
                        native_deployment_digest=backend.native_deployment.digest)
    require(all(config.get(k) == v for k, v in expected.items()), 'headless launch or allocation drift')
    require(backend.model == 'grok-4.6' and backend.effort == 'low', 'headless live model drift')
    require(sha(Path(backend.executable).read_bytes()) == config['executable_sha256'], 'headless executable drift')
    require(all(sha(Path(p).read_bytes()) == h for p, h in config['frozen_files'].items()), 'headless source drift')
    return config


def originals(directory):
    # Login/configuration homes are excluded; native contains only observations.
    paths = [directory / name for name in ('request.private.json',
        'headless-request.private.json', 'observer-receipt.private.json',
        'response.private.json', 'native-reservation.json', 'native-home/config.toml')]
    native = directory / 'native'
    if native.is_dir():
        paths.extend(p for p in native.rglob('*') if p.is_file())
    require(not any(p.is_symlink() for p in paths), 'linked native evidence is not admitted')
    return {str(p): sha(p.read_bytes()) for p in sorted(set(paths)) if p.is_file()}


def observed_usage(backend, row, directory):
    """Reparse a raw stream even after rejection, without claiming full binding."""
    try:
        bound = read(directory / 'native-reservation.json')
        process = read(directory / 'native/process.json')
        result = inspect_grok_stream((directory / 'native/stdout.private.jsonl').read_bytes(),
            schema=backend.schemas[row['slot']], session_id=bound['session_id'],
            max_output_tokens=backend.slot_output_caps[row['slot']],
            max_total_tokens=backend.observed_main_token_cap,
            process_exit_code=process['process_exit_code'] if type(process.get('process_exit_code')) is int else -1)
        return result.receipt.data().get('usage')
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ContractError):
        return None


def observation(backend, row, *, failure=None):
    directory = backend.calls_root / f'{row["id"]:04d}-{row["slot"]}'
    files = originals(directory)
    usage = observed_usage(backend, row, directory)
    bound = False
    request_hash = row.get('request_sha256')
    prompt_bytes = schema_bytes = None
    if failure is None:
        descriptor = row['private_request']
        require(descriptor['path'] == str(directory / 'headless-request.private.json'), 'headless private request path drift')
        raw = Path(descriptor['path']).read_bytes()
        require(sha(raw) == descriptor['sha256'], 'headless private request digest drift')
        request = json.loads(raw)
        require(set(request) == {'prompt', 'output_schema'} and request['prompt'].startswith(PROMPT), 'headless public request shape drift')
        public = FrozenRecord.from_dict(json.loads(request['prompt'][len(PROMPT):]))
        require(public.content_hash == request_hash and public.data()['slot'] == row['slot'], 'headless public request binding drift')
        require(request['prompt'] == PROMPT + public.encoded and request['output_schema'] == backend.schemas[row['slot']], 'headless prompt/schema drift')
        prompt_bytes = len(request['prompt'].encode())
        schema_bytes = len(canonical(request['output_schema']).encode())
        if row['status'] == 'succeeded':
            checked = _replay_headless_native_call(backend, row).data()
            require(checked['accepted'] is True and checked['usage']['main'] == usage
                and usage == row['known_headless_main_usage'], 'headless usage/binding drift')
            bound = True
        else:
            # Failed operations retain all observed scalars but are never eligible.
            require(row['status'] in ('reserved', 'unknown_or_failed'), 'headless terminal status differs')
            require(usage == row.get('known_headless_main_usage'), 'headless failed usage drift')
    successful = failure is None and row['status'] == 'succeeded'
    view = {'schema': 'public-train-provider-call-v1', 'id': row['id'], 'slot': row['slot'],
        'request_digest': request_hash, 'response_digest': row.get('response_sha256') if successful else None,
        'native_status': row['status'], 'successful': successful,
        'originals_verified': failure is None and successful,
        'verification_error': None if failure is None else type(failure).__name__,
        'known_tokens': usage['total_tokens'] if usage else None,
        'known_usage_scope': 'native_main', 'known_usage_binding_verified': bound,
        'main_usage_incomplete': not bound or usage is None,
        'possible_initial_title_opportunities': 1, 'title_tokens': None,
        'all_opportunity_tokens': None, 'settled_additional_charge_usd': None,
        'prompt_bytes': prompt_bytes, 'schema_bytes': schema_bytes, 'request_stream_bytes': None,
        'evidence_digest': FrozenRecord.from_dict({'native_row': row, 'original_files': files}).content_hash}
    return {'native_row': row, 'original_files': files, 'view': view}
