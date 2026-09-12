"""Keep real SQLite handles alive to detect missing explicit close calls."""
import sqlite3

import pytest

from research_loop.modular.modules.scheduling import FifoScheduler
from research_loop.ontology import ContractError


def test_sqlite_handles_close_after_initialization_reads_and_failed_transactions(tmp_path, monkeypatch):
    handles = []
    real_connect = sqlite3.connect

    def capture(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        handles.append(connection)  # prevent GC from masking resource leaks
        return connection

    monkeypatch.setattr(sqlite3, "connect", capture)
    scheduler = FifoScheduler(tmp_path / "scheduler.sqlite", max_concurrency=1, total_budget=2)
    run = scheduler.enqueue(experiment_id="lifecycle", task_id="one", dependencies=(), resources=(), cost_units=1,
        snapshot={"evidence": "e1", "rules": "r1", "package": "p1"})
    assert scheduler.state(run.run_id).status == "pending"
    assert len(scheduler.runs("lifecycle")) == 1
    with pytest.raises(ContractError): scheduler.state("missing")
    with pytest.raises(ContractError): scheduler.recover(run.run_id)
    with pytest.raises(ContractError): FifoScheduler(scheduler.path, max_concurrency=2, total_budget=2)
    assert len(handles) >= 8
    for connection in handles:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
    assert scheduler.state(run.run_id).status == "pending"
