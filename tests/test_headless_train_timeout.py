"""Configured timeout reaches actual children, descriptors and independent replay."""
import json
from contextlib import ExitStack
import os
from pathlib import Path
import sys

import pytest

from research_loop.ontology import ContractError
from research_loop.modular.grok_headless_train_solver import replay_headless_train_ledger
from research_loop.modular.phase_provider import validate_configuration
from research_loop.modular.train_provider import GrokHeadlessTrainProvider
from tests.test_grok_headless_train_solver import port, synthetic_native, REQUEST
from tests.test_headless_evaluator_factory import native_spec
from test_scorer_process import _material, _config


@pytest.mark.parametrize('timeout_seconds', [240, 600])
def test_solver_nondefault_timeout_is_used_frozen_and_replayed(tmp_path, monkeypatch, timeout_seconds):
    backend = port(tmp_path, timeout_seconds=timeout_seconds, max_calls=2)
    calls, _ = synthetic_native(tmp_path, monkeypatch, backend)
    provider = GrokHeadlessTrainProvider(backend)
    validate_configuration(provider.configuration(), schemas=backend.schemas, main_opportunities=2)
    provider.call(REQUEST)
    replay_headless_train_ledger(backend)
    native = Path(backend.ledger['calls'][0]['private_directory'])
    assert json.loads((native / 'process.json').read_bytes())['timeout_seconds'] == timeout_seconds
    assert backend.ledger['config']['timeout_seconds'] == timeout_seconds and len(calls) == 1
    backend.timeout_seconds = 60
    with pytest.raises(ContractError):
        provider.call(REQUEST)
    assert len(calls) == 1


@pytest.mark.parametrize('value', [0, 601, True, 60.0])
def test_solver_rejects_invalid_timeout_before_allocator(tmp_path, value):
    with pytest.raises(ContractError):
        port(tmp_path, timeout_seconds=value)
    assert not (tmp_path / 'ledger').exists()


@pytest.mark.parametrize('timeout_seconds', [240, 600])
def test_evaluator_timeout_matches_pure_descriptor_and_both_primary_scores(tmp_path, monkeypatch, timeout_seconds):
    from evaluation.modular.scorer_process import headless_evaluator_descriptor, build_service, parse_server_config
    from evaluation.modular.headless_evaluator_closure import descriptor
    args, _ = _material(tmp_path)
    body = _config(tmp_path, args)
    spec, prompts, _ = native_spec(tmp_path / 'native', monkeypatch)
    spec['timeout_seconds'] = timeout_seconds
    frozen = headless_evaluator_descriptor(spec)
    body['evaluator'] = spec
    service = build_service(parse_server_config(body))
    for benchmark in ('discoverybench', 'blade'):
        cell = next(cell for cell in args['panel'].cells if cell.identity.benchmark == benchmark)
        service.score_linked(panel=args['panel'], cell=cell, linked_input=args['linked_inputs'][cell.key])
    ledger = json.loads((Path(spec['work_root']) / 'ledger.json').read_bytes())
    assert ledger['config']['timeout_seconds'] == timeout_seconds and len(prompts) == 2
    assert len(ledger['calls']) == 2 and not ledger['usage_incomplete']
    from evaluation.modular.scorer_process import _production_evaluator
    replayed = _production_evaluator(spec)
    assert descriptor(replayed) == frozen
    for row in ledger['calls']:
        process = json.loads((Path(row['private_directory']) / 'process.json').read_bytes())
        assert process['timeout_seconds'] == timeout_seconds


def test_headless_child_gets_stdin_eof_and_existing_evidence_is_not_overwritten(tmp_path):
    from research_loop.modular.grok_headless_transport import _child, _process_ok
    directory = tmp_path / 'eof'
    command = [sys.executable, '-c', 'import sys; assert sys.stdin.read()==""; print("eof")']
    raw, observation = _child(command, {'cwd': str(tmp_path)}, dict(os.environ), directory, 5)
    assert _process_ok(observation) and raw.splitlines() == [b'eof']
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    with pytest.raises(ContractError):
        _child(command, {'cwd': str(tmp_path)}, dict(os.environ), directory, 5)
    assert before == {p.name: p.read_bytes() for p in directory.iterdir()}


def test_m4m5_frozen_timeout_preflight_accepts_match_and_rejects_drift(tmp_path, monkeypatch):
    from test_headless_m4_m5_controller import setup_headless
    from test_combination_prospective_train_source import processes
    from research_loop.modular import combination_train_controller as controller
    from research_loop.modular.contracts import FrozenRecord
    setup, backend, calls, gets = setup_headless(tmp_path, monkeypatch, timeout_seconds=240)
    with ExitStack() as stack:
        service = processes(setup, stack)
        keys = {setup['module'].SCORER.authority_id: setup['module'].SCORER.key}
        controller._service_preflight(setup['config'], backend, service, setup['module'].EXECUTION, keys)
        changed = setup['config'].data()
        changed['provider']['wall_timeout_seconds'] = 60
        config = controller.FrozenM4M5TrainConfig(FrozenRecord.from_dict(changed))
        with pytest.raises(ContractError, match='timeout differs'):
            controller._service_preflight(config, backend, service, setup['module'].EXECUTION, keys)
    assert not calls and not gets
