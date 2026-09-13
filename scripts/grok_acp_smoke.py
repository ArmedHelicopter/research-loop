"""Prepare, then run one separately frozen synthetic two-opportunity smoke.

No benchmark inputs. Auth file provisioning is an opaque same-user copy;
neither its contents nor its hash enter the public envelope. Never retry after
the shared reservation exists. The native process alone reads the login.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from research_loop.modular.grok_acp_transport import (
    MODEL, OPPORTUNITY_CONTRACT, SAFE_CONFIG, digest, encoded, profile, run_native,
)

PROMPT = 'Return exactly this JSON object and nothing else: {"ok":true}'
SCHEMA = {'type': 'object', 'properties': {'ok': {'type': 'boolean', 'enum': [True]}},
          'required': ['ok'], 'additionalProperties': False}


def git(*args):
    return subprocess.check_output(['git', *args], cwd=REPO, text=True).strip()


def source_manifest():
    paths = git('ls-files', '*.py', 'pyproject.toml', 'docs/GROK_ACP_TRANSPORT.md',
                'docs/GROK_ACP_PROTOCOL_REVIEW.md').splitlines()
    return {str(REPO / p): digest((REPO / p).read_bytes()) for p in paths}


def prepare(args):
    assert not git('status', '--porcelain'), 'source must be committed and clean'
    check = json.loads(args.verification.read_text())
    assert (check['commit'] == git('rev-parse', 'HEAD') and check['pytest_exit'] == 0
            and check['source_hashes_unchanged'] and check['label_isolation_included'])
    root = args.directory.resolve(); root.mkdir(parents=True, exist_ok=False)
    for name in ('private-home', 'private-profile', 'empty-cwd'):
        (root / name).mkdir()
    # Native login reuse was explicitly authorized; do not deserialize credentials.
    shutil.copyfile(args.auth_file, root / 'private-home' / 'auth.json')
    config = root / 'private-home' / 'config.toml'
    config.write_text(SAFE_CONFIG, encoding='utf-8', newline='\n')
    executable = args.executable.resolve()
    files = source_manifest()
    files[str(config)] = digest(config.read_bytes())
    files[str(executable)] = digest(executable.read_bytes())
    envelope = {'schema': 'grok-acp-two-opportunity-smoke-envelope-v2',
        'created_at': datetime.now(timezone.utc).isoformat(), 'source_commit': git('rev-parse', 'HEAD'),
        'opportunity_contract': OPPORTUNITY_CONTRACT, 'model': MODEL,
        'main_prompt_opportunities': 1, 'initial_title_opportunities': 1,
        'main_requested_output_cap': 128, 'title_requested_output_cap': 100,
        'max_retries': 0, 'wall_timeout_seconds': 60,
        'initial_title_internal_function': 'session_title',
        'initial_title_usage_and_cost': 'unknown unless separately reported',
        'exact_total_calls_tokens_and_cost_claimed': False,
        'native_existing_grok_com_login': True, 'api_key_route_permitted': False,
        'billing_gate': 'fresh successful unified cap0 used0 prepaid0 no-topup-rule',
        'same_session_runtime_tools_must_be_empty_before_prompt': True,
        'executable': str(executable), 'cwd': str(root / 'empty-cwd'),
        'private_home': str(root / 'private-home'), 'private_profile': str(root / 'private-profile'),
        'private_dir': str(root / 'private-streams'), 'reservation': str(args.reservation.resolve()),
        'profile': profile(), 'prompt': PROMPT, 'output_schema': SCHEMA,
        'frozen_files': files, 'verification_sha256': digest(args.verification.read_bytes()),
        'public_allowlist': ['frozen-envelope.json', 'observer-receipt.json', 'postrun-source-check.json']}
    (root / 'frozen-envelope.json').write_bytes(encoded(envelope) + b'\n')
    print(json.dumps({'prepared': True, 'source_commit': envelope['source_commit'],
        'envelope_sha256': digest((root / 'frozen-envelope.json').read_bytes()),
        'model_generation_requests': 0, 'source_files': len(files)}))


def execute(args):
    root = args.directory.resolve(); path = root / 'frozen-envelope.json'
    envelope = json.loads(path.read_text())
    assert not git('status', '--porcelain') and git('rev-parse', 'HEAD') == envelope['source_commit']
    assert envelope['opportunity_contract'] == OPPORTUNITY_CONTRACT
    assert envelope['prompt'] == PROMPT and envelope['output_schema'] == SCHEMA
    assert not Path(envelope['reservation']).exists(), 'terminal reservation: do not retry'
    result = run_native(opportunity_contract=envelope['opportunity_contract'],
        executable=envelope['executable'], cwd=envelope['cwd'],
        private_home=envelope['private_home'], private_profile=envelope['private_profile'],
        private_dir=envelope['private_dir'], reservation=envelope['reservation'],
        frozen_files=envelope['frozen_files'], prompt=PROMPT, schema=SCHEMA, timeout=60)
    receipt = result.receipt.data()
    (root / 'observer-receipt.json').write_bytes(encoded(receipt) + b'\n')
    source = source_manifest()
    after = {'source_commit_unchanged': git('rev-parse', 'HEAD') == envelope['source_commit'],
        'source_files_unchanged': all(envelope['frozen_files'].get(p) == h for p, h in source.items()),
        'clean_worktree': not git('status', '--porcelain'),
        'envelope_sha256': digest(path.read_bytes()), 'source_files': len(source)}
    (root / 'postrun-source-check.json').write_bytes(encoded(after) + b'\n')
    print(json.dumps(receipt))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('prepare', 'run'))
    parser.add_argument('directory', type=Path)
    parser.add_argument('--verification', type=Path)
    parser.add_argument('--auth-file', type=Path)
    parser.add_argument('--executable', type=Path)
    parser.add_argument('--reservation', type=Path)
    args = parser.parse_args()
    if args.mode == 'prepare':
        assert all((args.verification, args.auth_file, args.executable, args.reservation))
        prepare(args)
    else:
        execute(args)
