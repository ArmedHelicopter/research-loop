"""Public integration checks for the formal M8 Q3 scheduler drivers."""
from __future__ import annotations

from pathlib import Path

from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_receipts import PanelCell, opaque_panel_cell_binding
from research_loop.modular.runtime import AuditVerifier, RunSession
from research_loop.modular.scheduler_panel_drivers import M8SchedulerDriver, freeze_scheduler_bundle
from research_loop.modular.workflow import ModularWorkflow


SPLIT = "c" * 64
VARIANTS = {"Q3.3": ("one_worker", "k_workers"), "Q3.4": ("favorable_first", "unfavorable_first"),
            "Q3.5": ("write_conflict", "withdrawal", "crash", "expiry", "duplicate")}


def _task(benchmark: str) -> PublicTask:
    identity = DataIdentity(benchmark, "m8-" + benchmark, benchmark + ":m8", "public-v1", SPLIT, "train")
    if benchmark == "blade":
        return BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": "public", "research_question": "Use public inputs.", "data_schema": [{"name": "x"}]})
    return DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id, "question": "Use public inputs.", "source_kind": "synthetic", "dataset": [{"name": "public", "columns": [{"name": "x"}]}]})


def _bundle(task: PublicTask) -> FrozenRecord:
    schedules = {}
    for experiment, variants in VARIANTS.items():
        schedules[experiment] = {}
        for variant in variants:
            second_resource = ["subject-a"] if variant == "write_conflict" else ["subject-b"]
            schedules[experiment][variant] = {"jobs": [
                {"task_id": "public-first", "dependencies": [], "resources": ["subject-a"], "cost_units": 1},
                {"task_id": "public-second", "dependencies": [], "resources": second_resource, "cost_units": 1},
            ], "completion_order": ["public-first", "public-second"] if variant != "unfavorable_first" else ["public-second", "public-first"],
                "withdraw_subjects": ["subject-b"]}
    return freeze_scheduler_bundle(task, snapshot={"evidence": "public-evidence", "rules": "frozen-rules", "package": "candidate"}, schedules=schedules)


def _arms():
    rows = default_compatibility("base").conditional_factorial(("M8",)).data()["cells"]
    return [(row["id"], FrozenRecord.from_dict(row["arm"])) for row in rows if row["status"] == "executable"]


def _model(request: FrozenRecord) -> FrozenRecord:
    body = request.data(); context = body["module_context"]
    assert context["panel_cell"] and set(context) == {"panel_cell", "public_task", "scheduler_observation", "required_objective_digest"}
    encoded = request.encoded
    assert all(marker not in encoded for marker in ('"arm_id"', '"enabled"', '"variant"', '"controller_input"', '"package"'))
    return FrozenRecord.from_dict({"objective_digest": context["required_objective_digest"], "outcome": "unknown", "evidence_ids": [], "conclusion": "public scheduler engineering observation", "programme_complete": False})


def test_full_public_two_benchmark_m8_grid_runs_real_fifo_barrier_and_recovery(tmp_path: Path):
    tasks = [_task("blade"), _task("discoverybench")]
    package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([task.identity for task in tasks]), changes={"prompt": {"instructions": "public"}}, search_cost=0)
    seen = []
    for task in tasks:
        bundle = _bundle(task)
        for experiment, variants in VARIANTS.items():
            for variant in variants:
                scenario = FrozenRecord.from_dict({"experiment_id": experiment, "variant": variant, "base": {"task": task.content_hash, "evidence": bundle.content_hash, "budget": "fixed"}})
                for arm_id, arm in _arms():
                    cell = PanelCell(experiment, task.identity, "r1", variant, arm_id, arm, task.content_hash, scenario.content_hash, package.digest, "d" * 64)
                    sidecar = tmp_path / task.identity.benchmark / experiment / variant / arm_id
                    objective = FrozenRecord.from_dict({"objective": "M8 public scheduler wiring"})
                    session = RunSession(task, package_digest=package.digest, arm=arm, objective=objective, slots=("final",), execution_limit=0, sidecar=sidecar, verifier=AuditVerifier({"audit-a": b"a" * 32, "audit-b": b"b" * 32}), required_audit=("measurement",))
                    workflow = ModularWorkflow(session)
                    stage, candidate, _ = M8SchedulerDriver(experiment, material_resolver=lambda _task, _scenario, value=bundle: value).run(workflow, cell=cell, scenario=scenario, model=_model, package=package)
                    terminal = session.finish(candidate)
                    assert terminal.data()["decision"] == "unknown"
                    assert stage.status == "executed"
                    observed = stage.detail.data()["scheduler_observation"]
                    assert observed["total_cost_units"] == 2
                    if experiment == "Q3.3":
                        assert observed["merged_task_ids"] == ["public-first", "public-second"] and observed["prediction_ordering_used"] is False
                    elif experiment == "Q3.4":
                        assert observed["merge_barrier_blocked"] is True and len(observed["merged_snapshot_hashes"]) == 1
                    elif variant == "write_conflict": assert observed["double_execution"] is False
                    elif variant == "withdrawal": assert observed["snapshot_mutated"] is False
                    elif variant in {"crash", "expiry"}: assert observed["autorerun_blocked"] is True
                    else: assert observed["duplicate_receipt_rejected"] is True
                    seen.append(cell)
    assert len(seen) == 2 * sum(len(values) for values in VARIANTS.values()) * 2
