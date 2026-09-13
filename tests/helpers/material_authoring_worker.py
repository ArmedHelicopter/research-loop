"""Synthetic subprocess seam; never chooses an authenticated executable."""
import argparse
import json
from pathlib import Path

from evaluation.modular.diagnostic_material_authoring import run_authoring
from evaluation.modular.diagnostic_subscription import sha
from tests.helpers.material_authoring_fixture import fixture_factory

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--input', required=True); p.add_argument('--sha256', required=True)
    p.add_argument('--output', required=True); p.add_argument('--mode', default='authoring')
    args = p.parse_args()
    try:
        result = run_authoring({'path': args.input, 'sha256': args.sha256}, args.output,
            fixture_factory=fixture_factory(args.mode))
        print(json.dumps({'status': 'completed', 'outcome_sha256': sha(Path(args.output) / 'public-outcome.json')}))
    except Exception:
        print('{"status":"failed"}')
        raise SystemExit(1)
