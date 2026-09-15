"""Synthetic native fixture around the production C5 scorer worker's UTF-8 stdio."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import pytest

from evaluation.modular.scorer_process import _absolute, _load, build_service, ScorerWorker, serve
from research_loop.modular.grok_acp_transport import ProcessTree
import research_loop.modular.grok_headless_transport as transport
from tests.helpers.headless_authoring_fixture import install_synthetic_native


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--journal", required=True)
    args = parser.parse_args()
    config = _load(_absolute(args.config, "config"), args.config_sha256)
    from research_loop.modular.joint_train_panel import JointTrainPanel
    if type(config.panel) is not JointTrainPanel or config.evaluator.get("provider_kind") != "grok-headless-frozen-evaluator-v1":
        raise AssertionError("C5 headless test worker requires its exact production scope")
    peer = ROOT / "tests/fixtures/headless_train_peer.py"
    spec = config.evaluator
    with pytest.MonkeyPatch.context() as patch:
        install_synthetic_native(patch, {"native_deployment": {
            "executable": spec["executable"], "slots": {"base": {"private_home": spec["private_home"]}}}})

        def spawn(command, cwd, env, stderr):
            assert env["GROK_DISABLE_API_KEY_AUTH"] == "1"
            assert not {"XAI_API_KEY", "GROK_API_KEY"} & set(env)
            if "inspect" in command:
                peer_args = ["inspect"]
            else:
                prompt = Path(command[command.index("--prompt-file") + 1])
                content = prompt.read_text(encoding="utf-8")
                assert "PRIVATE-REFERENCE-SENTINEL" in content
                assert "public-model-request-v1" not in content
                schema = json.loads(command[command.index("--json-schema") + 1])
                value = ({"cvars": 2, "transform": 2, "model": 2, "reason": "synthetic"}
                         if "cvars" in schema["properties"] else
                         {"context": 1, "variable_f1": 1, "relation": 1, "reason": "synthetic"})
                answer = prompt.parent.parent / "synthetic-answer.json"
                answer.write_text(json.dumps(value), encoding="utf-8")
                peer_args = [command[command.index("--session-id") + 1], str(answer)]
            return ProcessTree([sys.executable, str(peer), *peer_args], cwd=cwd, env=env, stderr=stderr)

        patch.setattr(transport, "ProcessTree", spawn)
        return serve(ScorerWorker(build_service(config), config.panel, _absolute(args.journal, "journal")))


if __name__ == "__main__":
    raise SystemExit(main())
