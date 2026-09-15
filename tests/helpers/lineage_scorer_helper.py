"""Explicit fixture launcher: real child + CodexEvaluatorModelPort, no paid CLI."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from evaluation.modular.evaluator_model_port import CodexEvaluatorModelPort
from evaluation.modular.lineage_scorer_process import load_lineage_service, LineageScorerWorker
from evaluation.modular.scorer_process import ScorerWorker, serve


def main():
    parser = argparse.ArgumentParser()
    for name in ('config', 'config-sha256', 'journal'): parser.add_argument('--'+name, required=True)
    parser.add_argument('--fault', default='none')
    args = parser.parse_args(); b = json.loads(Path(args.config).read_text(encoding='utf-8'))
    root = Path(args.journal).parent/'evaluator'
    spec = b['base']['evaluator']
    if spec.get('provider_kind') == 'grok-headless-frozen-evaluator-v1':
        # This launcher is test-only: replace the OS peer and account reads
        # before loading the real frozen headless evaluator port.
        import pytest
        from research_loop.modular.grok_acp_transport import ProcessTree
        from tests.helpers.headless_authoring_fixture import install_synthetic_native
        import research_loop.modular.grok_headless_transport as native
        patch = pytest.MonkeyPatch()
        install_synthetic_native(patch, {'native_deployment': {'executable': spec['executable'],
            'slots': {'lineage': {'private_home': spec['private_home']}}}})
        peer = Path(__file__).resolve().parents[1] / 'fixtures' / 'headless_train_peer.py'
        def spawn(command, cwd, env, stderr, stdout=None):
            if 'inspect' in command:
                child = ['inspect']
            else:
                schema = json.loads(command[command.index('--json-schema') + 1])
                answer = {}
                for name, definition in schema['properties'].items():
                    if name == 'reason': answer[name] = 'synthetic headless lineage response'
                    elif name == 'lineage_endpoints': answer[name] = {key: .5 for key in definition['properties']}
                    elif name in {'context', 'relation'}: answer[name] = 1
                    elif name == 'variable_f1': answer[name] = .5
                    else: answer[name] = 1
                answer_path = Path(command[command.index('--prompt-file') + 1]).parent.parent / 'synthetic-answer.json'
                answer_path.write_text(json.dumps(answer), encoding='utf-8')
                child = [command[command.index('--session-id') + 1], str(answer_path)]
            return ProcessTree([sys.executable, str(peer), *child], cwd=cwd, env=env, stderr=stderr, stdout=stdout)
        patch.setattr(native, 'ProcessTree', spawn)
        panel, service = load_lineage_service(args.config, args.config_sha256)
        return serve(LineageScorerWorker(service, panel, Path(args.journal)))
    count = 0
    def probe(argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout='[{"role":"developer","content":[{"type":"input_text","text":"base"}]}]', stderr='')
    def transport(argv, *, input, **kwargs):
        nonlocal count
        count += 1
        ledger = json.loads((root/'ledger.json').read_text(encoding='utf-8'))
        assert ledger['calls'][-1]['status'] == 'reserved'
        assert '独立训练注释哨兵' in input and 'ANONYMOUS_CANDIDATE=' in input
        assert 'lineage-execution' not in input and 'lineage-scoring' not in input
        assert 'arm_id' not in input and 'runtime_arm' not in input
        (root/'child-pid.txt').write_text(str(os.getpid()), encoding='utf-8')
        if args.fault == 'hang' and count == 1:
            import time
            time.sleep(30)  # The bounded client must terminate this actual child.
        if args.fault == 'timeout' and count == 1:
            raise subprocess.TimeoutExpired(argv, 1)
        if args.fault == 'exception' and count == 1: raise RuntimeError('fixture transport failure')
        schema = json.loads(Path(argv[argv.index('--output-schema')+1]).read_text(encoding='utf-8'))
        fields = schema['properties']
        output = ({'context':1,'variable_f1':.5,'relation':1} if 'context' in fields else {'cvars':2,'transform':1,'model':2})
        output.update(reason='synthetic schema/plumbing response, not calibrated',
            lineage_endpoints={name:.5 for name in fields['lineage_endpoints']['properties']})
        if args.fault == 'schema' and count == 1: output['lineage_endpoints']['root_attribution'] = True
        if args.fault == 'refusal' and count == 1: output = {'refusal':'synthetic refusal'}
        Path(argv[argv.index('-o')+1]).write_text(json.dumps(output), encoding='utf-8')
        return SimpleNamespace(returncode=0, stdout='{"type":"turn.completed","usage":{"input_tokens":3,"output_tokens":2,"cached_input_tokens":0,"cache_write_input_tokens":0,"reasoning_output_tokens":0}}\n', stderr='')
    port = CodexEvaluatorModelPort('codex', root, evaluator_id=spec['evaluator_id'], evaluator_version=spec['evaluator_version'],
        rubric_mode='lineage_v1', max_calls=len(b['panel']['panel']['cells']), max_tokens=spec['max_tokens'],
        process_runner=transport, context_probe_runner=probe, allow_mock_context=True)
    panel, service = load_lineage_service(args.config, args.config_sha256, evaluator=port)
    return serve(LineageScorerWorker(service, panel, Path(args.journal)))


if __name__ == '__main__': raise SystemExit(main())
