"""Synthetic public integration check for the train-only panel runner.

The model callback and Docker environment are test doubles. Q3.1 does not ask
for Docker execution, so no broker is supplied or claimed in this test.
"""
from itertools import combinations
from pathlib import Path

import pytest

from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.experiments import ControllerInputs, registry, scenario
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_receipts import CombinationObligations, FrozenPanel, PanelCell, PanelReceiptVerifier, ScientificScorerReceipt, opaque_panel_cell_binding
from research_loop.modular.panel_runner import run_train_cell
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError

SCORER, SPLIT = "b" * 64, "c" * 64


def obligations() -> CombinationObligations:
    modules = tuple(f"M{number}" for number in range(1, 10))
    return CombinationObligations(tuple(combinations(modules, 2)),
        (("M2", "M3", "M5"), ("M4", "M5", "M6"), ("M1", "M4", "M7"), ("M3", "M6", "M9"), ("M7", "M8", "M9")),
        modules, modules)


def public_task(benchmark: str) -> PublicTask:
    identity = DataIdentity(benchmark, f"synthetic-{benchmark}", f"{benchmark}:synthetic", "synthetic-v1", SPLIT, "train")
    if benchmark == "discoverybench":
        return DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id, "question": "Which public mechanism is plausible?",
            "source_kind": "synthetic", "dataset": [{"name": "public.csv", "columns": [{"name": "x"}]}]})
    return BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": "public", "research_question": "Estimate a public association.",
        "data_schema": [{"name": "outcome", "dtype": "float"}], "task_instructions": "Use only supplied public data."})


def panel() -> tuple[FrozenPanel, dict[tuple[str, str, str], FrozenRecord], dict[tuple[str, str], PublicTask], CandidatePackage]:
    spec = registry()["Q3.1"]
    design = default_compatibility("base").conditional_factorial(("M4",))
    arms = {row["id"]: FrozenRecord.from_dict(row["arm"]) for row in design.data()["cells"] if row["status"] == "executable"}
    tasks = {benchmark: public_task(benchmark) for benchmark in ("discoverybench", "blade")}
    manifest = TrainingManifest(FrozenRecord.from_dict({"domain": "train", "identities": [task.identity.data() for task in tasks.values()]}))
    package = CandidatePackage.create(parent_digest=None, manifest=manifest,
                                      changes={"prompt": {"instructions": "synthetic public train package"}}, search_cost=0)
    cells, scenarios = [], {}
    for benchmark, task in tasks.items():
        for variant in spec.variants:
            controlled = scenario(spec, variant, inputs=ControllerInputs(FrozenRecord.from_dict(task.data()),
                                  FrozenRecord.from_dict({"evidence": "public"}), FrozenRecord.from_dict({"budget": "fixed"})))
            for arm_id, arm in arms.items():
                cell = PanelCell("Q3.1", task.identity, "r1", variant, arm_id, arm, task.content_hash,
                                 controlled.content_hash, package.digest, SCORER)
                cells.append(cell)
                scenarios[(benchmark, variant, arm_id)] = controlled
    frozen = FrozenPanel("train-q31", "train", SPLIT, package.digest, ("Q3.1",), {"Q3.1": design},
                         FrozenRecord.from_dict({"criterion": "synthetic wiring only"}), tuple(cells), obligations())
    return frozen, scenarios, {(benchmark, "task"): task for benchmark, task in tasks.items()}, package


def model(request: FrozenRecord) -> FrozenRecord:
    body = request.data()
    if body["slot"] == "scenario":
        branches = []
        for number in range(1, 4):
            branches.append({"hypothesis_id": f"h{number}", "mechanism_key": f"m{number}",
                "mechanism": f"mechanism {number}", "intervention": "public intervention",
                "elimination_condition": "shared observation disagrees", "predictions": [{
                    "prediction_id": f"p{number}", "discriminator_id": "shared-public-observation",
                    "observable": "public measure", "direction": ("increase" if number != 2 else "decrease"), "value_range": None,
                    "failure_condition": "does not increase"}]})
        return FrozenRecord.from_dict({"question": "public mechanism", "budget_units": 3, "branches": branches})
    objective_digest = FrozenRecord.from_dict(body["objective"]).content_hash
    return FrozenRecord.from_dict({"objective_digest": objective_digest, "outcome": "unknown", "evidence_ids": [],
                                    "conclusion": "synthetic train-only candidate", "programme_complete": False})


def audit() -> AuditVerifier:
    return AuditVerifier({"audit-a": b"a" * 32, "audit-b": b"b" * 32})


def test_q31_train_panel_runs_real_journals_for_both_public_adapters(tmp_path: Path) -> None:
    frozen, scenarios, tasks, package = panel()
    result = []
    for cell in frozen.cells:
        scenario_record = scenarios[(cell.identity.benchmark, cell.variant, cell.arm_id)]
        task = tasks[(cell.identity.benchmark, "task")]
        run = run_train_cell(cell, task=task, scenario=scenario_record, package=package,
                             objective=FrozenRecord.from_dict({"objective": "train"}),
                             sidecar=tmp_path / cell.identity.benchmark / cell.variant / cell.arm_id,
                             model=model, audit_verifier=audit())
        result.append(run)
        assert run.scorer is None and run.call_plan.data()["model_calls"] == 2
        events = [FrozenRecord(line).data() for line in run.runtime.trace_path.read_text(encoding="utf-8").splitlines()]
        requests = [event["data"]["request"] for event in events if event["stage"] == "model_request"]
        assert len(requests) == 2
        assert all(request["module_context"]["panel_cell"] == opaque_panel_cell_binding(cell) for request in requests)
        controller = scenario_record.data()["controller_input"]
        assert requests[0]["module_context"]["public_diagnostic"] == {
            name: controller[name] for name in ("diagnostic_focus", "operational_constraints")}
        encoded = FrozenRecord.from_dict({"requests": requests}).encoded
        for marker in ('"arm_id"', '"candidate_package"', '"control"', '"variant"',
                       '"driver_stage"', '"prediction_scenario_variant"', '"fixture_only"',
                       'synthetic public train package'):
            assert marker not in encoded
    diagnostic_material = {scenario_record.data()["controller_input"]["diagnostic_focus"]
                           for scenario_record in scenarios.values()}
    assert diagnostic_material == {"mechanism perturbation", "independent recomputation", "measurement negative control and calibration"}
    assert PanelReceiptVerifier().verify(frozen, tuple(run.runtime for run in result)).decision == "engineering_verified"
    off = next(run for run in result if run.call_plan.data()["enabled_modules"] == [])
    on = next(run for run in result if run.call_plan.data()["enabled_modules"] == ["M4"])
    assert off.call_plan.data()["workflow_stage"] == "operation_m4_control"
    assert on.call_plan.data()["workflow_stage"] == "stage_1"


def test_runner_rejects_validation_identity_scenario_package_and_unsupported_driver(tmp_path: Path) -> None:
    frozen, scenarios, tasks, package = panel()
    cell = frozen.cells[0]
    task = tasks[(cell.identity.benchmark, "task")]
    kwargs = dict(task=task, scenario=scenarios[(cell.identity.benchmark, cell.variant, cell.arm_id)], package=package,
                  objective=FrozenRecord.from_dict({"objective": "train"}), sidecar=tmp_path / "run", model=model, audit_verifier=audit())
    with pytest.raises(ContractError, match="package digest"):
        run_train_cell(cell, **{**kwargs, "package": object()})
    wrong = FrozenRecord.from_dict({**kwargs["scenario"].data(), "variant": "wrong"})
    with pytest.raises(ContractError, match="scenario digest"):
        run_train_cell(cell, **{**kwargs, "scenario": wrong})
    validation_identity = DataIdentity(cell.identity.benchmark, cell.identity.task_id, cell.identity.group_id, cell.identity.dataset_version, cell.identity.split_id, "validation")
    validation = PanelCell(cell.coverage_id, validation_identity, cell.replicate, cell.variant, cell.arm_id, cell.runtime_arm,
                           cell.task_digest, cell.scenario_digest, cell.package_digest, cell.scorer_digest)
    with pytest.raises(ContractError, match="training cells only"):
        run_train_cell(validation, **kwargs)
    q27 = scenario(registry()["Q2.7"], "missing_lock", inputs=ControllerInputs(FrozenRecord.from_dict(task.data()),
                   FrozenRecord.from_dict({"evidence": "public"}), FrozenRecord.from_dict({"budget": "fixed"})))
    unsupported = PanelCell("Q2.7", cell.identity, cell.replicate, "missing_lock", cell.arm_id, cell.runtime_arm,
                            cell.task_digest, q27.content_hash, cell.package_digest, cell.scorer_digest)
    with pytest.raises(ContractError, match="no production panel driver"):
        run_train_cell(unsupported, **{**kwargs, "scenario": q27})


def test_scorer_port_must_return_trace_and_scorer_bound_typed_receipt(tmp_path: Path) -> None:
    frozen, scenarios, tasks, package = panel()
    cell = frozen.cells[0]
    def bad_scorer(_cell, _runtime):
        return ScientificScorerReceipt(cell.key, FrozenRecord.from_dict({"schema": "independent-scored-cell-v1", "runtime_trace_digest": "0" * 64, "scorer_digest": SCORER}))
    with pytest.raises(ContractError, match="exact runtime"):
        run_train_cell(cell, task=tasks[(cell.identity.benchmark, "task")], scenario=scenarios[(cell.identity.benchmark, cell.variant, cell.arm_id)],
                       package=package, objective=FrozenRecord.from_dict({"objective": "train"}), sidecar=tmp_path / "scored",
                       model=model, audit_verifier=audit(), scorer=bad_scorer)


def test_model_or_plan_failure_returns_a_trace_bound_failed_cell(tmp_path: Path) -> None:
    frozen, scenarios, tasks, package = panel()
    cell = next(row for row in frozen.cells if row.runtime_arm.data()["enabled"] == ["M4"])
    def invalid_plan(_request: FrozenRecord) -> FrozenRecord:
        return FrozenRecord.from_dict({"not": "a prediction plan"})
    result = run_train_cell(cell, task=tasks[(cell.identity.benchmark, "task")],
                            scenario=scenarios[(cell.identity.benchmark, cell.variant, cell.arm_id)], package=package,
                            objective=FrozenRecord.from_dict({"objective": "train"}), sidecar=tmp_path / "invalid",
                            model=invalid_plan, audit_verifier=audit())
    assert result.runtime.status == "failed" and result.runtime.output_digest is None
    assert FrozenRecord(result.runtime.trace_path.read_text(encoding="utf-8").splitlines()[-1]).data()["stage"] == "driver_failure"


def test_q31_driver_rejects_a_schema_valid_but_underfilled_prediction_response(tmp_path: Path) -> None:
    frozen, scenarios, tasks, package = panel()
    cell = next(row for row in frozen.cells if row.runtime_arm.data()["enabled"] == ["M4"])
    def two_branches(request: FrozenRecord) -> FrozenRecord:
        response = model(request)
        if request.data()["slot"] == "scenario":
            body = response.data(); body["branches"] = body["branches"][:2]
            return FrozenRecord.from_dict(body)
        return response
    result = run_train_cell(cell, task=tasks[(cell.identity.benchmark, "task")],
        scenario=scenarios[(cell.identity.benchmark, cell.variant, cell.arm_id)], package=package,
        objective=FrozenRecord.from_dict({"objective": "train"}), sidecar=tmp_path / "two-branches",
        model=two_branches, audit_verifier=audit())
    assert result.runtime.status == "failed"
    assert FrozenRecord(result.runtime.trace_path.read_text(encoding="utf-8").splitlines()[-1]).data()["stage"] == "driver_failure"


def test_complete_panel_accepts_bound_driver_and_model_failures_and_rejects_tampering(tmp_path: Path) -> None:
    frozen, scenarios, tasks, package = panel()
    rows = []
    invalid_done = model_failed = False
    for index, cell in enumerate(frozen.cells):
        if not invalid_done and cell.runtime_arm.data()["enabled"] == ["M4"]:
            callback = lambda _request: FrozenRecord.from_dict({"invalid": "plan"})
            invalid_done = True
        elif not model_failed:
            def callback(_request):
                raise RuntimeError("synthetic model port failure")
            model_failed = True
        else:
            callback = model
        rows.append(run_train_cell(cell, task=tasks[(cell.identity.benchmark, "task")],
            scenario=scenarios[(cell.identity.benchmark, cell.variant, cell.arm_id)], package=package,
            objective=FrozenRecord.from_dict({"objective": "train"}), sidecar=tmp_path / str(index),
            model=callback, audit_verifier=audit()).runtime)
    verdict = PanelReceiptVerifier().verify(frozen, rows)
    assert verdict.engineering_verified and verdict.failures == 2
    driver = next(row for row in rows if FrozenRecord(row.trace_path.read_text(encoding="utf-8").splitlines()[-1]).data()["stage"] == "driver_failure")
    lines = driver.trace_path.read_text(encoding="utf-8").splitlines()
    changed = FrozenRecord(lines[-1]).data()
    changed["data"]["response_digest"] = "0" * 64
    driver.trace_path.write_text("\n".join([*lines[:-1], FrozenRecord.from_dict(changed).encoded]) + "\n", encoding="utf-8")
    tampered = list(rows)
    position = tampered.index(driver)
    tampered[position] = type(driver)(driver.cell_key, driver.status, driver.trace_path,
                                      FrozenRecord(FrozenRecord.from_dict(changed).encoded).content_hash, None,
                                      driver.failure_reason)
    with pytest.raises(ContractError):
        PanelReceiptVerifier().verify(frozen, tampered)



