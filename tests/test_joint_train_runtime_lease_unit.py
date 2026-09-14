"""Pure structural checks for C5's non-persistent verification lease."""
import inspect
from types import SimpleNamespace

import pytest

import research_loop.modular.joint_train_controller as controller
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.joint_train_runtime import (
    JointTrainBarrier,
    JointTrainStageExecutor,
    _barrier_validation_scope,
    compile_panel,
)
from research_loop.ontology import ContractError


R = FrozenRecord.from_dict


def _barrier():
    barrier = object.__new__(JointTrainBarrier)
    plan = SimpleNamespace(record=R({'plan': 'p'}), protocol=SimpleNamespace(digest='q'))
    object.__setattr__(barrier, 'record', R({'build_receipts': {}}))
    object.__setattr__(barrier, 'executor', SimpleNamespace(plan=plan))
    object.__setattr__(barrier, 'builds', ())
    return barrier


def test_barrier_lease_revokes_and_rejects_different_barrier(monkeypatch):
    calls = []
    monkeypatch.setattr(JointTrainBarrier, 'verify', lambda self: calls.append(self))
    first_barrier, second_barrier = _barrier(), _barrier()
    with _barrier_validation_scope(first_barrier) as lease:
        lease.require(first_barrier)
        with pytest.raises(ContractError, match='context differs'):
            lease.require(second_barrier)
    with pytest.raises(ContractError, match='context differs'):
        lease.require(first_barrier)
    assert calls == [first_barrier]


def test_public_verifiers_accept_no_cached_lease_parameters():
    assert tuple(inspect.signature(JointTrainStageExecutor.verify).parameters) == ('self', 'result')
    assert tuple(inspect.signature(compile_panel).parameters) == ('barrier',)


def test_final_loop_uses_one_supplied_lease_and_reads_ledger_last(monkeypatch):
    events, context = [], object()
    class Cell:
        def __init__(self, key): self.key = key
    class Target:
        def __init__(self, key): self.inner = SimpleNamespace(cell=Cell(key))
    class Envelope:
        def __init__(self, key): self.key = key
        def data(self): return {'key': self.key, 'authority': 'test'}
    targets = (Target(('a',)), Target(('b',)))
    inputs = {target.inner.cell.key: Envelope(target.inner.cell.key) for target in targets}
    scores = {target.inner.cell.key: object() for target in targets}
    ledger = SimpleNamespace(verify=lambda: events.append('ledger'))
    monkeypatch.setattr(controller, '_verify_target_in_context',
        lambda target, **kwargs: events.append(('target', target.inner.cell.key, kwargs['context'])))
    monkeypatch.setattr(controller, 'verify_combination_score_input',
        lambda score_input, **kwargs: events.append(('input', score_input.key)) or SimpleNamespace(data=lambda: {'key': score_input.key}))
    monkeypatch.setattr(controller, '_score_input_payload', lambda panel, inner: SimpleNamespace(data=lambda: {'key': inner.cell.key}))
    monkeypatch.setattr(controller, 'verify_combination_adapted_receipt',
        lambda score, **kwargs: events.append(('score', kwargs['cell'].key)))
    monkeypatch.setattr(controller, 'ScorerConfig', lambda value: value)
    plan = SimpleNamespace(protocol=SimpleNamespace(record=R({'scorer': {}})))
    controller._verify_final_targets_in_context(targets, ({}, {}), barrier=object(), panel=object(), ledger=ledger,
        context=context, inputs=inputs, scores=scores, execution_authority_keys={}, scorer_authority_keys={}, plan=plan)
    assert [event[0] for event in events[:-1] if isinstance(event, tuple) and event[0] == 'target'] == ['target', 'target']
    assert all(event[2] is context for event in events if isinstance(event, tuple) and event[0] == 'target')
    assert events[-1] == 'ledger'
