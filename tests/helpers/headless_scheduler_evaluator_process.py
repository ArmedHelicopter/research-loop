"""Synthetic native peer around the production M7xM8 scorer stdio worker."""
import argparse
import inspect
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]

import pytest
from evaluation.modular.scorer_process import _absolute, _load, build_service, ScorerWorker, serve
from research_loop.modular.combination_panels import CombinationPanel
from research_loop.modular.grok_acp_transport import ProcessTree
import research_loop.modular.grok_headless_transport as transport
from tests.helpers.headless_authoring_fixture import install_synthetic_native


def main() -> int:
    parser = argparse.ArgumentParser()
    for name in ('config', 'config-sha256', 'journal'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    config = _load(_absolute(args.config, 'config'), args.config_sha256)
    if (type(config.panel) is not CombinationPanel or config.panel.obligation_id != 'pair:M7+M8'
            or config.evaluator.get('provider_kind') != 'grok-headless-frozen-evaluator-v1'):
        raise AssertionError('scheduler headless worker requires its exact production scope')
    peer = ROOT / 'tests/fixtures/headless_train_peer.py'; spec = config.evaluator
    with pytest.MonkeyPatch.context() as patch:
        install_synthetic_native(patch, {'native_deployment': {
            'executable': spec['executable'], 'slots': {'base': {'private_home': spec['private_home']}}}})
        def spawn(command, cwd, env, stderr, stdout=subprocess.PIPE):
            assert env['GROK_DISABLE_API_KEY_AUTH'] == '1'
            assert not {'XAI_API_KEY', 'GROK_API_KEY'} & set(env)
            if 'inspect' in command:
                peer_args = ['inspect']
            else:
                prompt = Path(command[command.index('--prompt-file') + 1]); content = prompt.read_text(encoding='utf-8')
                assert 'PRIVATE-REFERENCE-SENTINEL' in content and 'public-model-request-v1' not in content
                schema = json.loads(command[command.index('--json-schema') + 1])
                answer = prompt.parent.parent / 'synthetic-answer.json'
                answer.write_text(json.dumps({key: ('synthetic' if key == 'reason' else 1) for key in schema['properties']}), encoding='utf-8')
                peer_args = [command[command.index('--session-id') + 1], str(answer)]
            kwargs = {'cwd': cwd, 'env': env, 'stderr': stderr}
            if 'stdout' in inspect.signature(ProcessTree).parameters:
                kwargs['stdout'] = stdout
            return ProcessTree([sys.executable, str(peer), *peer_args], **kwargs)
        patch.setattr(transport, 'ProcessTree', spawn)
        return serve(ScorerWorker(build_service(config), config.panel, _absolute(args.journal, 'journal')))


if __name__ == '__main__':
    raise SystemExit(main())
