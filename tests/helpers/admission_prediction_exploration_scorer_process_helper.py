"""Synthetic-only independent scorer worker for admission-prediction-exploration train panels."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evaluation.modular.scorer_process import _absolute, _load, build_service, ScorerWorker, serve
from research_loop.modular.contracts import FrozenRecord


def main() -> int:
    parser = argparse.ArgumentParser()
    for name in ("config", "config-sha256", "journal"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    config = _load(_absolute(args.config, "config"), args.config_sha256)
    from research_loop.modular.admission_prediction_exploration_driver import DESIGNS
    if config.panel.obligation_id not in DESIGNS:
        raise AssertionError('admission prediction exploration worker rejects other combination families')
    if config.evaluator not in ({"synthetic_mode": "normal"}, {"synthetic_mode": "fail"}):
        raise AssertionError("admission prediction exploration helper accepts only synthetic evaluator modes")

    def evaluate(request: FrozenRecord) -> FrozenRecord:
        if config.evaluator["synthetic_mode"] == "fail":
            raise RuntimeError("synthetic independent scorer outage")
        dimensions = ({"context": 1, "variable_f1": 1, "relation": 1}
                      if request.data()["benchmark"] == "discoverybench"
                      else {"cvars": 1, "transform": 1, "model": 1})
        return FrozenRecord.from_dict({**dimensions, "reason": "synthetic fixture; scientific quality not measured"})

    return serve(ScorerWorker(build_service(config, evaluator=evaluate), config.panel,
                              _absolute(args.journal, "journal")))


if __name__ == "__main__":
    raise SystemExit(main())
