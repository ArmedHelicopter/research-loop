"""Synthetic worker: real stdio subprocess transport, never native login/network."""
import argparse
import json
import os
from pathlib import Path
import sys
import subprocess

from evaluation.modular.diagnostic_subscription import run_private, sha
from research_loop.modular.grok_acp_transport import SinglePromptACP, DIAGNOSTIC_OPPORTUNITY_CONTRACT, ProcessTree


def fixture_environment():
    return dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2]))


def run_fixture_worker(command, *, stream_root, timeout=240):
    """Bound the multi-call fixture parent separately from its native sessions."""
    stdout_path = stream_root / 'fixture-worker.stdout.bin'
    stderr_path = stream_root / 'fixture-worker.stderr.bin'
    with stderr_path.open('xb') as stderr:
        tree = ProcessTree(command, stream_root, fixture_environment(), stderr)
        try:
            stdout, _ = tree.process.communicate(timeout=timeout)
            stdout_path.write_bytes(stdout)
            code = tree.process.returncode
        except subprocess.TimeoutExpired as exc:
            (stream_root / 'fixture-worker.timeout-stdout.bin').write_bytes(exc.stdout or b'')
            raise
        finally:
            tree.close()
    return subprocess.CompletedProcess(command, code, stdout, stderr_path.read_bytes())


def fixture_factory(mode='diagnostic'):
    def call(entry, prompt, schema, directory, frozen_files, spec):
        peer = Path(__file__).resolve().parents[1] / 'fixtures' / 'grok_acp_peer.py'
        return SinglePromptACP([sys.executable, str(peer), mode, str(directory / 'peer.private.jsonl')],
            cwd=directory, env=fixture_environment(), private_dir=directory / 'native',
            reservation=directory / 'native-reservation.json',
            # Allow a cold synthetic Python peer to import its fixture helpers.
            # The actual Grok native session remains separately bounded at60s.
            frozen_files=frozen_files, timeout=20,
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
