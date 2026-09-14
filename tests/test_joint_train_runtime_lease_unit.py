"""Pure structural checks for C5's non-persistent verification lease."""
import inspect
from types import SimpleNamespace

import pytest

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
