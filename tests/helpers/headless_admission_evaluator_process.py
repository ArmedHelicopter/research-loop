"""Synthetic stdio scorer worker with the production headless evaluator factory."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evaluation.modular.scorer_process import _absolute, _load, build_service, ScorerWorker, serve


def main() -> int:
    parser = argparse.ArgumentParser()
    for name in ('config', 'config-sha256', 'journal'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    config = _load(_absolute(args.config, 'config'), args.config_sha256)
    return serve(ScorerWorker(build_service(config), config.panel, _absolute(args.journal, 'journal')))


if __name__ == '__main__':
    raise SystemExit(main())

