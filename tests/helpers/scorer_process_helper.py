"""Test-only subprocess target with a canned evaluator; never production wiring."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evaluation.modular.scorer_process import _absolute, _load, build_service, ScorerWorker, serve
from research_loop.modular.contracts import FrozenRecord


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True); parser.add_argument("--config-sha256", required=True); parser.add_argument("--journal", required=True)
    args = parser.parse_args()
    config = _load(_absolute(args.config, "config"), args.config_sha256)
    def canned(request: FrozenRecord) -> FrozenRecord:
        return FrozenRecord.from_dict(({"context": 1, "variable_f1": 1, "relation": 1}
            if request.data()["benchmark"] == "discoverybench" else {"cvars": 2, "transform": 2, "model": 2}) | {"reason": "synthetic test-only evaluator"})
    return serve(ScorerWorker(build_service(config, evaluator=canned), config.panel, _absolute(args.journal, "journal")))


if __name__ == "__main__":
    raise SystemExit(main())
