"""One source-pinned native smoke; existing subscription only, no retry."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent / 'integration'
sys.path.insert(0, str(REPO))
from research_loop.modular.grok_acp_transport import OPPORTUNITY_CONTRACT, run_native
from research_loop.modular.grok_native_deployment import FrozenNativeDeployment
from research_loop.modular.contracts import FrozenRecord


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def metadata(path):
    value = Path(path).stat()
    return {'byte_count': value.st_size, 'mtime_ns': value.st_mtime_ns}


def write(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, indent=2)


def main():
    envelope_path = HERE / 'envelope.json'
    envelope = json.loads(envelope_path.read_bytes())
    if (envelope['schema'] != 'grok130-single-readiness-envelope-v1'
            or envelope['limits'] != {'native_launches': 1, 'main_opportunities': 1,
                'possible_initial_title_opportunities': 1, 'main_output_cap': 128,
                'observed_main_token_cap': 20000, 'timeout_seconds': 60,
                'retries': 0, 'additional_paid_api_budget_usd': 0}):
        raise RuntimeError('readiness envelope contract differs')
    for path, expected in envelope['frozen_files'].items():
        if sha(path) != expected:
            raise RuntimeError('readiness original source drift')
    deployment = FrozenNativeDeployment(FrozenRecord.from_dict(envelope['deployment']))
    deployment.verify_executable(deployment.executable)
    auth = Path('C:/Users/Administrator/.grok/auth.json')
    private_auth = HERE / 'home/auth.json'
    before = {'global': metadata(auth), 'private': metadata(private_auth)}
    # A launch itself is single-use, even if no prompt reservation is reached.
    write(HERE / 'launch-reserved.json', {'envelope_sha256': sha(envelope_path),
        'started_utc': datetime.now(timezone.utc).isoformat(), 'native_launches_max': 1})
    start = time.monotonic()
    result = run_native(opportunity_contract=OPPORTUNITY_CONTRACT,
        executable=deployment.executable, cwd=HERE/'cwd', private_home=HERE/'home',
        private_profile=HERE/'profile', private_dir=HERE/'native',
        reservation=HERE/'prompt-reservation.json', frozen_files=envelope['frozen_files'],
        prompt=envelope['prompt'], schema=envelope['output_schema'], timeout=60,
        deployment=deployment)
    body = result.receipt.data()
    after = {'global': metadata(auth), 'private': metadata(private_auth)}
    source_unchanged = all(sha(path) == value for path, value in envelope['frozen_files'].items())
    closure = {'schema': 'grok130-readiness-closure-v1',
        'envelope_sha256': sha(envelope_path), 'native_receipt_digest': result.receipt.content_hash,
        'native_receipt_file_sha256': sha(HERE/'native/observer-receipt.json'),
        'elapsed_seconds': time.monotonic()-start, 'source_unchanged': source_unchanged,
        'auth_file_metadata_before': before, 'auth_file_metadata_after': after,
        'global_auth_metadata_unchanged': before['global'] == after['global'],
        'accepted': body['accepted'] and source_unchanged,
        'faults': body['faults'], 'prompt_requests_reserved': body['prompt_requests_reserved'],
        'known_usage': body['known_usage'], 'reported_main_cost_usd': body['reported_cost_usd'],
        'settled_additional_charge_usd': body['settled_additional_charge_usd'],
        'initial_title_usage': body['initial_title_usage'],
        'runtime_empty_inventory_count': body['runtime_empty_inventory_count'],
        'event_counts': body['event_counts'], 'retry_authorized': False,
        'scientific_validation': False}
    if result.response is not None:
        write(HERE/'response.json', result.response.data())
    write(HERE/'closure.json', closure)
    print(json.dumps(closure, sort_keys=True))


if __name__ == '__main__':
    main()
