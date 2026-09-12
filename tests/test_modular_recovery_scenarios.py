"""Focused offline checks for M7/M8 recovery fixtures; not benchmark evidence."""
import multiprocessing
import shutil
import tempfile
from pathlib import Path

import pytest

from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.modules.scheduling import FifoScheduler
from research_loop.modular.scenarios_recovery import run_recovery_scenario


def task(adapter: str):
    identity = DataIdentity("blade" if adapter == "blade" else "discoverybench", adapter + "-recovery", "fixture-group", "v1", "split", "train")
    payload = ({"task_id": identity.task_id, "dataset_id": "fixture", "research_question": "public fixture", "data_schema": [{"name": "x"}]}
               if adapter == "blade" else {"task_id": identity.task_id, "question": "public fixture", "difficulty": "fixture", "source_kind": "synthetic", "dataset": [{"name": "fixture", "description": "public", "columns": []}]})
    return (BladeAdapter() if adapter == "blade" else DiscoveryBenchAdapter()).prepare(identity, payload)


def controls(value): return FrozenRecord.from_dict({"task_digest": value.content_hash, "budget_digest": "fixture-budget", "fixture_only": True})


def _competing_claim(path: str, worker_id: str, queue) -> None:
    scheduler = FifoScheduler(Path(path), max_concurrency=1, total_budget=2)
    lease = scheduler.claim_next(worker_id, lease_seconds=30)
    queue.put(lease.run_id if lease else None)


@pytest.mark.parametrize("adapter", ["blade", "discovery"])
@pytest.mark.parametrize(("experiment_id", "variant"), [
    ("Q3.3", "one_worker"), ("Q3.3", "k_workers"), ("Q3.4", "favorable_first"), ("Q3.4", "unfavorable_first"),
    ("Q3.5", "write_conflict"), ("Q3.5", "withdrawal"), ("Q3.5", "crash"), ("Q3.5", "expiry"), ("Q3.5", "duplicate"),
    ("Q5.1", "subjective"), ("Q5.1", "data"), ("Q5.1", "minimal_run"), ("Q5.1", "measurement"), ("Q5.1", "independent"),
    ("Q5.5", "missing_data"), ("Q5.5", "missing_method"), ("Q5.5", "missing_budget"), ("Q5.5", "missing_control"),
])
def test_registered_variants_bind_both_public_adapters_and_retain_callback(tmp_path: Path, adapter, experiment_id, variant):
    public = task(adapter); seen = []
    result = run_recovery_scenario(experiment_id, variant, task=public, frozen_controls=controls(public),
        sidecar=tmp_path / "work", next_model=lambda payload: seen.append(payload) or {"received": payload.content_hash})
    assert seen == [result.next_payload]
    assert result.next_model_response.data()["response"]["received"] == result.next_payload.content_hash
    assert result.next_payload.data()["task"] == public.data()


def test_m8_barrier_and_fault_invariants(tmp_path: Path):
    public = task("blade")
    completion = run_recovery_scenario("Q3.4", "unfavorable_first", task=public, frozen_controls=controls(public), sidecar=tmp_path / "work")
    assert completion.next_payload.data()["scenario_auxiliary"]["merge_barrier_blocked"] is True
    assert completion.next_payload.data()["scenario_auxiliary"]["pending_context_or_rules_changed"] is False
    crash = run_recovery_scenario("Q3.5", "crash", task=public, frozen_controls=controls(public), sidecar=tmp_path / "work")
    assert crash.next_payload.data()["scenario_auxiliary"]["autorerun_blocked"] is True
    duplicate = run_recovery_scenario("Q3.5", "duplicate", task=public, frozen_controls=controls(public), sidecar=tmp_path / "work")
    assert duplicate.next_payload.data()["scenario_auxiliary"]["duplicate_receipt_rejected"] is True


def test_m8_sqlite_claim_is_atomic_across_real_spawned_processes():
    """Use an E-volume work root outside data/labels for the worker processes."""
    work = Path(__file__).resolve().parents[1] / "work"
    work.mkdir(exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="recovery-workers-", dir=work))
    try:
        scheduler = FifoScheduler(root / "scheduler.sqlite", max_concurrency=1, total_budget=2)
        run = scheduler.enqueue(experiment_id="process-claim", task_id="only", dependencies=(), resources=(), cost_units=1,
                                snapshot={"evidence": "v1", "rules": "v1", "package": "v1"})
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        workers = [context.Process(target=_competing_claim, args=(str(root / "scheduler.sqlite"), worker, queue))
                   for worker in ("process-a", "process-b")]
        for worker in workers: worker.start()
        for worker in workers: worker.join(15)
        assert all(worker.exitcode == 0 for worker in workers)
        claims = [queue.get(timeout=5), queue.get(timeout=5)]
        assert claims.count(run.run_id) == 1 and claims.count(None) == 1
    finally:
        shutil.rmtree(root)


def test_stage_and_closure_boundaries(tmp_path: Path):
    public = task("discovery")
    partial = run_recovery_scenario("Q5.1", "minimal_run", task=public, frozen_controls=controls(public), sidecar=tmp_path / "work")
    assert partial.next_payload.data()["scenario_auxiliary"]["next_stage"] == "discriminating_measurement"
    ready = run_recovery_scenario("Q5.1", "independent", task=public, frozen_controls=controls(public), sidecar=tmp_path / "work")
    assert ready.next_payload.data()["scenario_auxiliary"]["qualified"] is True
    missing = run_recovery_scenario("Q5.5", "missing_method", task=public, frozen_controls=controls(public), sidecar=tmp_path / "work")
    assert missing.next_payload.data()["scenario_auxiliary"]["execution_started"] is False
