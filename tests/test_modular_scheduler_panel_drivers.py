"""Synthetic public M8 causal wiring: all 36 cells and fail-closed counterexamples."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3
import json

import pytest

from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.modules.scheduling import FifoScheduler
from research_loop.modular.panel_receipts import PanelCell
from research_loop.modular.runtime import AuditVerifier, RunSession
from research_loop.modular.scheduler_panel_drivers import (
    M8SchedulerDriver, freeze_scheduler_bundle, freeze_scheduler_source,
    scheduler_panel_injection, select_scheduler_material,
)
from research_loop.modular.workflow import ModularWorkflow
from research_loop.ontology import ContractError


SPLIT = "c" * 64
VARIANTS = {"Q3.3": ("one_worker", "k_workers"), "Q3.4": ("favorable_first", "unfavorable_first"),
            "Q3.5": ("write_conflict", "withdrawal", "crash", "expiry", "duplicate")}


def _task(benchmark: str = "blade") -> PublicTask:
    identity = DataIdentity(benchmark, "m8-" + benchmark, benchmark + ":m8", "synthetic-public-v1", SPLIT, "train")
    if benchmark == "blade":
        return BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": "synthetic-public",
            "research_question": "Use public inputs.", "data_schema": [{"name": "x"}]})
    return DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id, "question": "Use public inputs.",
        "source_kind": "synthetic", "dataset": [{"name": "public", "columns": [{"name": "x"}]}]})


def _package(task):
    return CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([task.identity]),
        changes={"prompt": {"instructions": "public"}}, search_cost=0)


def _schedules():
    schedules = {}
    for experiment, variants in VARIANTS.items():
        schedules[experiment] = {}
        for variant in variants:
            jobs = [
                {"task_id": "public-first", "dependencies": [], "resources": ["subject-a"], "cost_units": 2,
                 "payload": {"operation": "sum", "indices": [0, 1]}},
                {"task_id": "public-second", "dependencies": [],
                 "resources": ["subject-a"] if variant == "write_conflict" else ["subject-b"], "cost_units": 3,
                 "payload": {"operation": "sum_squares", "indices": [0, 1, 2]}},
            ]
            ids = [j["task_id"] for j in jobs]
            schedules[experiment][variant] = {"jobs": jobs,
                "completion_order": ids[::-1] if variant == "unfavorable_first" else ids,
                "withdraw_subjects": ["subject-b"] if variant == "withdrawal" else [],
                "budget_units": 7 if variant in ("crash", "expiry") else 5}
    return schedules


def _bundle(task, package):
    return freeze_scheduler_bundle(task, source=freeze_scheduler_source(task, values=[2, -3, 4]),
                                   package_digest=package.digest, schedules=_schedules())


def _arm(enabled):
    rows = default_compatibility("base").conditional_factorial(("M8",)).data()["cells"]
    return next(FrozenRecord.from_dict(row["arm"]) for row in rows if row["status"] == "executable"
                and ("M8" in row["arm"]["enabled"]) is enabled)


def _setup(path, *, benchmark="blade", experiment="Q3.3", variant="k_workers", enabled=True,
           bundle=None, controller=True):
    task = _task(benchmark)
    package = _package(task)
    bundle = _bundle(task, package) if bundle is None else bundle
    scenario_body = {"experiment_id": experiment, "variant": variant,
                     "base": {"task": task.content_hash, "evidence": bundle.content_hash, "budget": "fixed"}}
    if controller:
        scenario_body["controller_input"] = scheduler_panel_injection(experiment, variant,
            task=FrozenRecord.from_dict(task.data()), evidence=bundle)
    scenario = FrozenRecord.from_dict(scenario_body)
    arm = _arm(enabled)
    cell = PanelCell(experiment, task.identity, "r1", variant, "on" if enabled else "off", arm,
                     task.content_hash, scenario.content_hash, package.digest, "d" * 64)
    session = RunSession(task, package_digest=package.digest, arm=arm,
        objective=FrozenRecord.from_dict({"objective": "synthetic M8 engineering wiring"}), slots=("final",),
        execution_limit=0, sidecar=path, verifier=AuditVerifier({"audit-a": b"a" * 32, "audit-b": b"b" * 32}),
        required_audit=("measurement",))
    return ModularWorkflow(session), cell, scenario, package, bundle


def _run(setup):
    workflow, cell, scenario, package, bundle = setup
    calls = []
    def model(request):
        body = request.data()
        context = body["module_context"]
        calls.append(body)
        assert set(context) == {"panel_cell", "public_task", "scheduler_observation", "required_objective_digest"}
        observation = context["scheduler_observation"]
        assert set(observation) == {"schema", "input_binding", "outputs", "visibility", "missing_output_bindings"}
        assert observation["schema"] == "public-work-observation-v2"
        assert all(marker not in request.encoded for marker in (
            '"engine"', '"arm_id"', '"enabled"', '"variant"', '"controller_input"', '"package"',
            '"fault"', '"recovery"', 'durable_fifo', 'memory_fifo_baseline', '"states"'))
        for output in observation["outputs"]:
            assert set(output) == {"binding", "input_binding", "value", "operations"}
        return FrozenRecord.from_dict({"objective_digest": context["required_objective_digest"], "outcome": "unknown",
            "evidence_ids": [], "conclusion": "Synthetic scheduler engineering observation only.", "programme_complete": False})
    stage, candidate, _ = M8SchedulerDriver(cell.coverage_id,
        material_resolver=lambda *_: bundle).run(workflow, cell=cell, scenario=scenario, model=model, package=package)
    assert workflow.session.finish(candidate).data()["decision"] == "unknown"
    assert len(calls) == 1 and stage.status == "executed"
    return stage.detail.data()["scheduler_observation"], calls[0]


def _events(observed, operation):
    return [e for e in observed["events"] if e["operation"] == operation]


CELLS = [(benchmark, experiment, variant, enabled)
    for benchmark in ("blade", "discoverybench") for experiment, variants in VARIANTS.items()
    for variant in variants for enabled in (False, True)]


@pytest.mark.parametrize("benchmark,experiment,variant,enabled", CELLS)
def test_complete_36_cell_grid_executes_real_work_and_fault_operations(tmp_path, benchmark, experiment, variant, enabled):
    setup = _setup(tmp_path / "cell", benchmark=benchmark, experiment=experiment, variant=variant, enabled=enabled)
    observed, _ = _run(setup)
    task = setup[0].session.task
    source = setup[-1].data()["source"]
    assert observed["engine"] == ("durable_fifo" if enabled else "memory_fifo_baseline")
    assert observed["remaining_leases"] == observed["unknown_runs"] == []
    assert observed["allocated_budget_units"] == (7 if variant in ("crash", "expiry") else 5)
    spent = 7 if enabled and variant in ("crash", "expiry") else 5
    assert observed["actual_spent_cost_units"] == observed["reserved_cost_units"] == spent
    assert observed["remaining_budget_units"] == observed["allocated_budget_units"] - spent
    assert observed["prediction_ordering_used"] is False
    assert {s["snapshot_hash"] for s in observed["states"]} == {observed["snapshot_digest"]}
    for attempt in observed["attempts"]:
        output = attempt["output"]
        if output is not None:
            assert output["task_digest"] == task.content_hash
            assert output["source_digest"] == FrozenRecord.from_dict(source).content_hash
            assert output["value"] == ( -1 if attempt["task_id"] == "public-first" else 29)
            assert output["operations"] == (2 if attempt["task_id"] == "public-first" else 3)
        receipt = attempt["receipt"]
        if receipt:
            assert receipt["output"] == output and receipt["run_id"] == attempt["run_id"]
            assert receipt["attempt"] == attempt["attempt"] and receipt["snapshot_digest"] == attempt["snapshot_digest"]
    if enabled:
        with sqlite3.connect(tmp_path / "cell" / "m8-scheduler.sqlite") as conn:
            import json
            rows = conn.execute("SELECT run_id,receipt FROM runs WHERE receipt IS NOT NULL").fetchall()
        for run_id, receipt_text in rows:
            receipt = json.loads(receipt_text)
            match = next(a for a in observed["attempts"] if a["run_id"] == run_id)
            assert receipt == match["receipt"] and receipt["output"] == match["output"]
            compute = next(e for e in _events(observed, "work_computed") if e["run_id"] == run_id)
            accept = next(e for e in _events(observed, "delivery_accepted") if e["run_id"] == run_id)
            assert compute["sequence"] < accept["sequence"]
    if experiment == "Q3.3":
        assert observed["peak_active_workers"] == (1 if variant == "one_worker" else 2)
        assert observed["issued_task_ids"] == observed["merged_task_ids"] == ["public-first", "public-second"]
        assert [x["value"] for x in observed["work_outputs"]] == [-1, 29]
        starts = _events(observed, "worker_started")
        returns = _events(observed, "worker_returned")
        assert (starts[1]["sequence"] < returns[0]["sequence"]) == (variant == "k_workers")
        assert len(observed["attempts"]) == 2 and observed["duplicate_visible_count"] == 0
    elif experiment == "Q3.4":
        returned = _events(observed, "worker_returned")
        pending = _events(observed, "pending_context_observed")[0]
        start = next(e for e in _events(observed, "worker_started") if e["run_id"] == pending["run_id"])
        assert start["context_digest"] == pending["context_digest"]
        pending_attempt = next(a for a in observed["attempts"] if a["run_id"] == pending["run_id"])
        assert pending_attempt["receipt"]["context_digest"] == pending["context_digest"]
        assert pending["snapshot_digest"] == observed["snapshot_digest"]
        expected = [-1, 29] if variant == "favorable_first" else [29, -1]
        by_run = {a["run_id"]: a["output"]["value"] for a in observed["attempts"]}
        assert [by_run[e["run_id"]] for e in returned] == expected
        if enabled:
            assert len(_events(observed, "merge_blocked")) == 1 and pending["visible_receipts"] == []
            assert [x["value"] for x in observed["public_outputs"]] == [-1, 29]
            assert len(observed["public_visibility"]) == 1
            assert _events(observed, "merge_visible")[0]["sequence"] > returned[-1]["sequence"]
        else:
            assert len(pending["visible_receipts"]) == 1
            assert [[x["value"] for x in row] for row in observed["public_visibility"]] == [expected[:1], expected]
    elif variant == "write_conflict":
        starts = _events(observed, "worker_started")
        assert observed["peak_active_workers"] == (1 if enabled else 2)
        assert bool(starts[1]["overlapping_resource_runs"]) is (not enabled)
        assert bool(_events(observed, "dispatch_blocked")) is enabled
        writes = _events(observed, "resource_written")
        assert len(writes) == 2 and writes[0]["new_version"] == writes[1]["previous_version"] == 1
        assert writes[1]["stale_write"] is (not enabled)
        assert observed["simulated_resources"]["subject-a"]["version"] == 2
        assert observed["simulated_resources"]["subject-a"]["output_digest"] == observed["work_output_digests"][1]
        assert observed["merged_task_ids"] == ["public-first", "public-second"]
        assert len(observed["work_outputs"]) == 2 and observed["actual_computed_cost_units"] == 5
    elif variant == "withdrawal":
        assert len(_events(observed, "withdrawal_injected")) == 1
        if enabled:
            assert len(_events(observed, "runs_invalidated")[0]["run_ids"]) == 1
            assert [r["status"] for r in observed["states"]] == ["completed_waiting", "invalidated"]
            assert observed["cancelled_attempt_count"] == 1 and observed["actual_computed_cost_units"] == 2
            assert observed["public_outputs"] == [] and len(observed["unfinished_runs"]) == 1
        else:
            assert observed["cancelled_attempt_count"] == 0 and observed["actual_computed_cost_units"] == 5
            assert [x["value"] for x in observed["work_outputs"]] == [-1, 29]
    elif variant in ("crash", "expiry"):
        assert observed["failed_attempt_count"] == (1 if variant == "crash" else 0)
        if enabled:
            assert len(observed["attempts"]) == 3
            assert observed["attempts"][2]["task_id"] == observed["attempts"][0]["task_id"]
            assert observed["attempts"][2]["attempt"] == 2
            assert observed["attempts"][2]["output"] == observed["attempts"][0]["output"]
            assert _events(observed, "autorerun_probe")[0]["claimed_run_id"] is None
            assert len(_events(observed, "recovery_blocked")) == len(_events(observed, "termination_confirmed")) == 1
            assert _events(observed, "leases_expired")[0]["run_ids"] == [observed["attempts"][0]["run_id"]]
            assert observed["actual_computed_cost_units"] == 7 and observed["actual_completed_cost_units"] == 5
            assert set(observed["merged_task_ids"]) == {"public-first", "public-second"}
            if variant == "crash":
                assert len(_events(observed, "scheduler_reopened")) == 1
            else:
                assert len(_events(observed, "delivery_rejected")) == 1
                assert observed["actual_returned_cost_units"] == 7
        else:
            assert len(observed["attempts"]) == 2 and observed["actual_computed_cost_units"] == 5
            assert not _events(observed, "recovered")
            assert observed["merged_task_ids"] == (["public-second"] if variant == "crash" else ["public-first", "public-second"])
    else:
        assert variant == "duplicate"
        assert len(_events(observed, "delivery_attempt")) == 3
        assert len(_events(observed, "delivery_rejected")) == (1 if enabled else 0)
        assert observed["duplicate_visible_count"] == (0 if enabled else 1)
        assert [x["value"] for x in observed["work_outputs"]] == ([-1, 29] if enabled else [-1, -1, 29])
        assert observed["actual_computed_cost_units"] == observed["actual_completed_cost_units"] == 5


def test_both_arms_use_same_computation_source_budget_and_public_schema(tmp_path):
    left, request_left = _run(_setup(tmp_path / "off", enabled=False))
    right, request_right = _run(_setup(tmp_path / "on", enabled=True))
    assert left["work_outputs"] == right["work_outputs"]
    assert left["input_binding"] == right["input_binding"]
    assert left["allocated_budget_units"] == right["allocated_budget_units"] == 5
    assert set(request_left) == set(request_right)
    assert set(request_left["module_context"]) == set(request_right["module_context"])


def test_changed_public_source_changes_computed_value_and_all_input_bindings(tmp_path):
    task = _task()
    package = _package(task)
    ordinary, _ = _run(_setup(tmp_path / "ordinary"))
    changed_bundle = freeze_scheduler_bundle(task, source=freeze_scheduler_source(task, values=[10, 20, 30]),
        package_digest=package.digest, schedules=_schedules())
    changed, _ = _run(_setup(tmp_path / "changed", bundle=changed_bundle))
    assert [r["value"] for r in changed["work_outputs"]] == [30, 1400]
    assert changed["input_binding"] != ordinary["input_binding"]
    assert changed["work_output_digests"] != ordinary["work_output_digests"]


@pytest.mark.parametrize("bad_values", [[], [True], [1.0], ["2"], [None], [1000001], [0] * 129, "2", {"x": 2}])
def test_source_rejects_unbounded_or_untyped_values(bad_values):
    with pytest.raises(ContractError):
        freeze_scheduler_source(_task(), values=bad_values)


@pytest.mark.parametrize("mutation", [
    "source_identity", "source_task", "source_extra", "source_value", "snapshot_evidence", "snapshot_rules", "snapshot_package",
    "policy", "bundle_task", "missing_variant", "row_extra", "jobs_type", "dependencies_string", "dependencies_bool",
    "dependency_unknown", "resources_string", "resource_nested", "resource_duplicate", "cost_bool", "cost_mismatch",
    "indices_bool", "indices_oob", "indices_negative", "indices_nested", "payload_extra", "operation", "order_duplicate",
    "workload_drift", "budget_bool", "budget_under", "budget_over", "withdraw_unknown", "withdraw_wrong_job", "conflict_missing",
])
def test_malformed_deep_material_rejected_before_model_or_scheduler(tmp_path, monkeypatch, mutation):
    task = _task()
    package = _package(task)
    body = _bundle(task, package).data()
    row = body["schedules"]["Q3.3"]["k_workers"]
    job = row["jobs"][0]
    if mutation == "source_identity": body["source"]["identity"]["task_id"] = "other"
    elif mutation == "source_task": body["source"]["task_digest"] = "a" * 64
    elif mutation == "source_extra": body["source"]["private_reference"] = "forbidden"
    elif mutation == "source_value": body["source"]["values"][0] = True
    elif mutation == "snapshot_evidence": body["snapshot"]["evidence"] = "a" * 64
    elif mutation == "snapshot_rules": body["snapshot"]["rules"] = "a" * 64
    elif mutation == "snapshot_package": body["snapshot"]["package"] = "unbound-name"
    elif mutation == "policy": body["rules"]["max_attempts"] = 20
    elif mutation == "bundle_task": body["task_digest"] = "a" * 64
    elif mutation == "missing_variant": del body["schedules"]["Q3.5"]["crash"]
    elif mutation == "row_extra": row["favorable"] = True
    elif mutation == "jobs_type": row["jobs"] = "work"
    elif mutation == "dependencies_string": job["dependencies"] = "public-second"
    elif mutation == "dependencies_bool": job["dependencies"] = False
    elif mutation == "dependency_unknown": job["dependencies"] = ["missing"]
    elif mutation == "resources_string": job["resources"] = "subject-a"
    elif mutation == "resource_nested": job["resources"] = [["subject-a"]]
    elif mutation == "resource_duplicate": job["resources"] = ["a", "a"]
    elif mutation == "cost_bool": job["cost_units"] = True
    elif mutation == "cost_mismatch": job["cost_units"] = 1
    elif mutation == "indices_bool": job["payload"]["indices"] = [False, 1]
    elif mutation == "indices_oob": job["payload"]["indices"] = [0, 3]
    elif mutation == "indices_negative": job["payload"]["indices"] = [-1, 1]
    elif mutation == "indices_nested": job["payload"]["indices"] = [[0], 1]
    elif mutation == "payload_extra": job["payload"]["code"] = "execute"
    elif mutation == "operation": job["payload"]["operation"] = "exec"
    elif mutation == "order_duplicate": row["completion_order"] = ["public-first", "public-first"]
    elif mutation == "workload_drift": job["payload"]["operation"] = "sum_squares"
    elif mutation == "budget_bool": row["budget_units"] = True
    elif mutation == "budget_under": body["schedules"]["Q3.5"]["crash"]["budget_units"] = 5
    elif mutation == "budget_over": row["budget_units"] = 999
    elif mutation == "withdraw_unknown": body["schedules"]["Q3.5"]["withdrawal"]["withdraw_subjects"] = ["missing"]
    elif mutation == "withdraw_wrong_job": body["schedules"]["Q3.5"]["withdrawal"]["withdraw_subjects"] = ["subject-a"]
    elif mutation == "conflict_missing": body["schedules"]["Q3.5"]["write_conflict"]["jobs"][1]["resources"] = ["subject-b"]
    bundle = FrozenRecord.from_dict(body)
    setup = _setup(tmp_path / "invalid", bundle=bundle, controller=False)
    workflow, cell, scenario, package, _ = setup
    calls = []
    monkeypatch.setattr(FifoScheduler, "enqueue", lambda *a, **kw: pytest.fail("invalid material reached scheduling"))
    with pytest.raises(ContractError):
        M8SchedulerDriver(cell.coverage_id, material_resolver=lambda *_: bundle).run(workflow,
            cell=cell, scenario=scenario, package=package, model=lambda request: calls.append(request))
    assert calls == [] and not (tmp_path / "invalid" / "m8-scheduler.sqlite").exists()


@pytest.mark.parametrize("binding", ["cell_task", "cell_scenario", "cell_package", "cell_arm", "scenario_task", "bundle_package", "bundle_hash"])
def test_wrong_runtime_binding_rejected_before_any_work_or_model(tmp_path, binding):
    workflow, cell, scenario, package, bundle = _setup(tmp_path / "binding", controller=False)
    if binding == "cell_task": cell = replace(cell, task_digest="a" * 64)
    elif binding == "cell_scenario": cell = replace(cell, scenario_digest="a" * 64)
    elif binding == "cell_package": cell = replace(cell, package_digest="a" * 64)
    elif binding == "cell_arm": cell = replace(cell, runtime_arm=_arm(False))
    elif binding == "scenario_task":
        body = scenario.data(); body["base"]["task"] = "a" * 64
        scenario = FrozenRecord.from_dict(body); cell = replace(cell, scenario_digest=scenario.content_hash)
    elif binding == "bundle_package":
        body = bundle.data(); body["snapshot"]["package"] = "a" * 64; bundle = FrozenRecord.from_dict(body)
        body = scenario.data(); body["base"]["evidence"] = bundle.content_hash
        scenario = FrozenRecord.from_dict(body); cell = replace(cell, scenario_digest=scenario.content_hash)
    elif binding == "bundle_hash":
        body = scenario.data(); body["base"]["evidence"] = "a" * 64
        scenario = FrozenRecord.from_dict(body); cell = replace(cell, scenario_digest=scenario.content_hash)
    calls = []
    with pytest.raises(ContractError):
        M8SchedulerDriver(cell.coverage_id, material_resolver=lambda *_: bundle).run(workflow,
            cell=cell, scenario=scenario, package=package, model=lambda request: calls.append(request))
    assert calls == [] and not (tmp_path / "binding" / "m8-scheduler.sqlite").exists()


def test_validation_identity_never_enters_worker():
    task = _task()
    validation = PublicTask(replace(task.identity, domain="validation"), task.payload)
    with pytest.raises(ContractError, match="training"):
        freeze_scheduler_source(validation, values=[1, 2])


def test_legacy_unbound_snapshot_is_not_silently_upgraded():
    legacy = FrozenRecord.from_dict({"schema": "typed-m8-scheduler-panel-bundle-v1", "identity": _task().identity.data(),
        "snapshot": {"evidence": "arbitrary", "rules": "arbitrary", "package": "arbitrary"}, "schedules": _schedules()})
    with pytest.raises(ContractError):
        select_scheduler_material(legacy, _task(), "Q3.3", "k_workers")


def test_control_executes_without_calling_any_durable_scheduler_api(tmp_path, monkeypatch):
    import research_loop.modular.scheduler_panel_drivers as drivers
    monkeypatch.setattr(drivers, "FifoScheduler", lambda *a, **kw: pytest.fail("control invoked the treatment scheduler"))
    observed, _ = _run(_setup(tmp_path / "control", enabled=False))
    assert observed["peak_active_workers"] == 2 and len(observed["work_outputs"]) == 2
    assert not (tmp_path / "control" / "m8-scheduler.sqlite").exists()


@pytest.mark.parametrize("enabled", [False, True])
def test_model_failure_preserves_executed_work_cost_and_pre_model_journal(tmp_path, enabled):
    workflow, cell, scenario, package, bundle = _setup(tmp_path / "model-failure", enabled=enabled)
    def fail(_request):
        raise RuntimeError("synthetic transport failure")
    with pytest.raises(RuntimeError, match="transport failure"):
        M8SchedulerDriver(cell.coverage_id).run(workflow, cell=cell, scenario=scenario, package=package, model=fail)
    trace = [json.loads(line) for line in (workflow.session.sidecar / "trace.jsonl").read_text().splitlines()]
    stage = next(e for e in trace if e["stage"] == "modular_workflow")
    request = next(e for e in trace if e["stage"] == "model_request")
    assert stage["sequence"] < request["sequence"]
    observation = stage["data"]["scheduler_observation"]
    assert observation["actual_spent_cost_units"] == 5 and len(observation["work_outputs"]) == 2
    artifact = workflow.session.sidecar / "m8-controller-observation.json"
    saved = artifact.read_bytes()
    with pytest.raises(ContractError, match="already ran"):
        M8SchedulerDriver(cell.coverage_id).run(workflow, cell=cell, scenario=scenario, package=package, model=fail)
    assert artifact.read_bytes() == saved


@pytest.mark.parametrize("enabled", [False, True])
def test_unexpected_worker_failure_keeps_actual_residual_state_and_zero_model_calls(tmp_path, monkeypatch, enabled):
    import research_loop.modular.scheduler_panel_drivers as drivers
    workflow, cell, scenario, package, bundle = _setup(tmp_path / "worker-failure", enabled=enabled)
    def fail(*_args):
        raise RuntimeError("synthetic arithmetic failure")
    monkeypatch.setattr(drivers, "_compute", fail)
    calls = []
    with pytest.raises(RuntimeError, match="arithmetic failure"):
        M8SchedulerDriver(cell.coverage_id).run(workflow, cell=cell, scenario=scenario,
            package=package, model=lambda request: calls.append(request))
    assert calls == []
    saved = json.loads((workflow.session.sidecar / "m8-controller-observation.json").read_text())
    assert saved["actual_spent_cost_units"] == 5 and saved["actual_computed_cost_units"] == 0
    assert saved["work_outputs"] == [] and len(saved["unfinished_runs"]) == (2 if enabled else 0)
    assert len(saved["remaining_leases"]) == (2 if enabled else 0)
    assert saved["failed_attempt_count"] == saved["cancelled_attempt_count"] == 1
    if not enabled:
        assert [state["status"] for state in saved["states"]] == ["failed", "cancelled"]
    assert _events(saved, "controller_failed")[0]["error_type"] == "RuntimeError"


def test_typed_receipt_snapshot_tampering_is_rejected_by_durable_sink(tmp_path):
    setup = _setup(tmp_path / "sink")
    observed, _ = _run(setup)
    receipt = observed["receipts"][0].copy()
    # Fresh actual attempt with the correct ID but a forged snapshot binding.
    scheduler = FifoScheduler(tmp_path / "sink-counterexample.sqlite", max_concurrency=1, total_budget=2)
    snapshot = {"evidence": receipt["source_digest"], "rules": "r", "package": "p"}
    state = scheduler.enqueue(experiment_id="counterexample", task_id=receipt["task_id"],
        dependencies=[], resources=[], cost_units=2, snapshot=snapshot)
    lease = scheduler.claim_next("worker", lease_seconds=30)
    receipt["run_id"] = lease.run_id
    frozen = FrozenRecord.from_dict(receipt)
    with pytest.raises(ContractError, match="snapshot"):
        scheduler.complete(lease.run_id, receipt_id=frozen.content_hash, receipt=frozen.data(), cost_units=2)
    assert scheduler.state(state.run_id).status == "leased" and scheduler.reserved_cost_units() == 2
    with pytest.raises(ContractError, match="no persisted"):
        scheduler.receipt(state.run_id)
