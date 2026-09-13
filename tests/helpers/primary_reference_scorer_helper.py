"""Test-only reference verifier inside the real standard scorer process."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from evaluation.modular.scorer_process import _load, build_service, ScorerWorker, serve
from research_loop.modular.contracts import FrozenRecord

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--journal", required=True)
    args = parser.parse_args()
    config = _load(Path(args.config), args.config_sha256)
    def verify(request):
        body = request.data()
        expected = "SYNTHETIC-DISCOVERY-BRIDGE-REFERENCE" if body["benchmark"] == "discoverybench" else "SYNTHETIC-BLADE-BRIDGE-REFERENCE"
        assert expected in body["prompt"]
        assert "Compute the mean of x." in body["prompt"]
        assert "UNALLOCATED-REFERENCE-SENTINEL" not in body["prompt"]
        return FrozenRecord.from_dict(({"context": 1, "variable_f1": 1, "relation": 1}
            if body["benchmark"] == "discoverybench" else {"cvars": 2, "transform": 2, "model": 2})
            | {"reason": "synthetic fixture reference verified; no scientific claim"})
    return serve(ScorerWorker(build_service(config, evaluator=verify), config.panel, Path(args.journal)))

if __name__ == "__main__":
    raise SystemExit(main())
