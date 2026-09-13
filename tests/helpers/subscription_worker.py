"""Synthetic worker: real stdio subprocess transport, never native login/network."""
import argparse
import json
import os
from pathlib import Path
import sys

from evaluation.modular.diagnostic_subscription import run_private, sha
from research_loop.modular.grok_acp_transport import SinglePromptACP, DIAGNOSTIC_OPPORTUNITY_CONTRACT


def fixture_factory(mode='diagnostic'):
    def call(entry, prompt, schema, directory, frozen_files, spec):
        peer = Path(__file__).resolve().parents[1] / 'fixtures' / 'grok_acp_peer.py'
        return SinglePromptACP([sys.executable, str(peer), mode, str(directory / 'peer.private.jsonl')],
            cwd=directory, env=dict(os.environ), private_dir=directory / 'native',
            reservation=directory / 'native-reservation.json',
            frozen_files=frozen_files, timeout=5,
            opportunity_contract=DIAGNOSTIC_OPPORTUNITY_CONTRACT,
            main_output_cap=spec['main_output_cap'], max_total_tokens=spec['observed_main_token_cap'],
            input_byte_cap=spec['max_input_bytes']).invoke(prompt, schema)
    return call


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True); parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', required=True); parser.add_argument('--mode', default='diagnostic')
    args = parser.parse_args()
    try:
        result = run_private({'path': args.config, 'sha256': args.sha256}, fixture_factory=fixture_factory(args.mode))
        with Path(args.output).open('x', encoding='utf-8') as out:
            out.write(result.encoded)
        print(json.dumps({'status': 'completed', 'receipt_sha256': sha(args.output)}))
    except Exception:
        print('{"status":"failed","receipt_sha256":null}')
        raise SystemExit(1)
