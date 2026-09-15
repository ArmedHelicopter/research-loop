"""Production scorer factory with real local child processes and synthetic HTTP."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

from evaluation.modular.scorer_process import (headless_evaluator_descriptor, _production_evaluator,
    build_service, parse_server_config)
from evaluation.modular.headless_evaluator_closure import descriptor
from evaluation.modular.linked_scoring import verify_linked_adapted_receipt
from research_loop.modular.grok_acp_transport import ProcessTree
from research_loop.ontology import ContractError
from tests.helpers.headless_authoring_fixture import install_synthetic_native
from test_scorer_process import _material, _config
from test_train_adapted_selection import EXEC, SCORER


def native_spec(root, patch):
    root.mkdir()
    exe = root / 'synthetic.exe'; exe.write_bytes(b'synthetic native executable identity')
    home = root / 'home'; home.mkdir()
    _, gets = install_synthetic_native(patch, {'native_deployment': {
        'executable': str(exe), 'slots': {'base': {'private_home': str(home)}}}})
    import research_loop.modular.grok_headless_transport as transport
    peer = Path(__file__).parent / 'fixtures/headless_train_peer.py'
    prompts = []
    def spawn(command, cwd, env, stderr):
        assert env['GROK_DISABLE_API_KEY_AUTH'] == '1'
        assert not {'XAI_API_KEY', 'GROK_API_KEY'} & set(env)
        if 'inspect' in command:
            args = ['inspect']
        else:
            prompt_path = Path(command[command.index('--prompt-file') + 1])
            prompt = prompt_path.read_text(encoding='utf-8'); prompts.append(prompt)
            assert 'PRIVATE-REFERENCE-SENTINEL' in prompt
            assert 'public-model-request-v1' not in prompt
            schema = json.loads(command[command.index('--json-schema') + 1])
            answer = {key: ('synthetic' if key == 'reason' else 1) for key in schema['properties']}
            path = prompt_path.parent.parent / 'synthetic-answer.json'
            path.write_text(json.dumps(answer), encoding='utf-8')
            args = [command[command.index('--session-id') + 1], str(path)]
        return ProcessTree([sys.executable, str(peer), *args], cwd=cwd, env=env, stderr=stderr)
    patch.setattr(transport, 'ProcessTree', spawn)
    return {'provider_kind': 'grok-headless-frozen-evaluator-v1', 'executable': str(exe),
        'work_root': str(root / 'ledger'), 'private_home': str(home),
        'private_profile': str(root / 'profile'), 'public_cwd': str(root / 'context'),
        'frozen_files': {str(exe): hashlib.sha256(exe.read_bytes()).hexdigest()},
        'evaluator_id': 'synthetic-evaluator', 'evaluator_version': 'v1',
        'model': 'grok-4.6', 'effort': 'low', 'max_calls': 2, 'max_tokens': 262144,
        'timeout_seconds': 60,
        'account_read_recovery': {'schema': 'headless-account-read-recovery-v1', 'max_attempts': 2}}, prompts, gets


def test_primary_scorer_factory_consumes_both_benchmark_native_evaluator_results(tmp_path, monkeypatch):
    args, _ = _material(tmp_path)
    body = _config(tmp_path, args)
    body['evaluator'], prompts, gets = native_spec(tmp_path / 'native', monkeypatch)
    service = build_service(parse_server_config(body))
    receipts = []
    for benchmark in ('discoverybench', 'blade'):
        cell = next(cell for cell in args['panel'].cells if cell.identity.benchmark == benchmark)
        receipt = service.score_linked(panel=args['panel'], cell=cell, linked_input=args['linked_inputs'][cell.key])
        verify_linked_adapted_receipt(receipt, authority_keys={SCORER.authority_id: SCORER.key},
            config=args['config'], panel=args['panel'], cell=cell, linked_input=args['linked_inputs'][cell.key],
            execution_authority_keys={EXEC.authority_id: EXEC.key})
        receipts.append(receipt)
    assert len(prompts) == 2 and len(gets) == 12
    assert all('PRIVATE-REFERENCE-SENTINEL' not in receipt.receipt.encoded for receipt in receipts)
    ledger = json.loads((Path(body['evaluator']['work_root']) / 'ledger.json').read_bytes())
    assert ledger['tokens'] == 20 and not ledger['usage_incomplete']
    assert all(row['status'] == 'succeeded' for row in ledger['calls'])


@pytest.mark.parametrize('rubric_mode', ['primary_v1', 'lineage_v1'])
def test_pure_descriptor_matches_constructed_port_without_allocator_side_effects(tmp_path, monkeypatch, rubric_mode):
    spec, prompts, gets = native_spec(tmp_path / 'native', monkeypatch)
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob('*'))
    pure = headless_evaluator_descriptor(spec, rubric_mode=rubric_mode)
    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob('*'))
    assert after == before and not (Path(spec['work_root']) / 'ledger.json').exists()
    assert not prompts and not gets
    port = _production_evaluator(spec, rubric_mode=rubric_mode)
    assert pure == descriptor(port)


@pytest.mark.parametrize('field,value', [('provider_kind', 'grok-acp-public-train-v1'),
    ('effort', 'high'), ('timeout_seconds', 61), ('max_calls', True), ('private_home', 'relative')])
def test_headless_factory_rejects_inexact_transport_before_native(tmp_path, monkeypatch, field, value):
    spec, prompts, gets = native_spec(tmp_path / 'native', monkeypatch)
    spec[field] = value
    with pytest.raises(ContractError):
        _production_evaluator(spec)
    assert not prompts and not gets
