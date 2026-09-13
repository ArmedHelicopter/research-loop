"""Q2.1 train-only production wiring with synthetic public tasks only."""
from pathlib import Path

import pytest

from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.experiments import registry
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_plan import compile_train_panel, executable_arms
from research_loop.modular.panel_runner import run_train_cell
from research_loop.modular.pressure_panel_driver import Q21PressureDriver
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError


SPLIT = "1" * 64


def _task(benchmark: str):
    identity = DataIdentity(benchmark, "q21-" + benchmark, benchmark + ":q21", "synthetic-v1", SPLIT, "train")
    marker = "PUBLIC-Q21-MATERIAL-" + benchmark.upper()
    if benchmark == "discoverybench":
        return DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id, "question": marker,
            "source_kind": "synthetic", "dataset": [{"name": "public.csv", "columns": [{"name": "x"}]}]})
    return BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": "public",
        "research_question": marker, "data_schema": [{"name": "outcome", "dtype": "float"}],
        "task_instructions": "Use only supplied public data."})


def _bundle(task) -> FrozenRecord:
    rows = []
    # The test fixture is the caller: it supplies material and an authority
    # disposition.  The driver has no authority object and does not mint these.
    dispositions = (("support", True, True), ("refute", True, True),
                    ("invalid", True, False), ("unknown", False, False))
    for number, (case_id, verified, admitted) in enumerate(dispositions, 1):
        marker = "CALLER-PUBLIC-EVIDENCE-%s-%s" % (task.identity.benchmark.upper(), number)
        rows.append({"case_id": case_id,
            "observation": {"kind": "measurement", "root_material": {"source": marker}, "representation": "raw",
                "content": {"public_observation": marker}, "subject_bindings": {"task": task.identity.task_id},
                "independent_group": task.identity.group_id},
            "authority_receipt": {"trusted_validator": "caller-authority-%s" % number,
                "validator_verified": verified, "admitted": admitted},
            "review_material": {"public_observation": marker, "provenance": "caller-supplied public material"}})
    return FrozenRecord.from_dict({"schema": "q21-pressure-material-bundle-v1", "identity": task.identity.data(),
        "task_payload_digest": task.payload.content_hash, "cases": rows})


def _compiled():
    tasks = tuple(_task(name) for name in ("discoverybench", "blade"))
    package = CandidatePackage.create(parent_digest=None,
        manifest=TrainingManifest.freeze([task.identity for task in tasks]),
        changes={"prompt": {"instructions": "q21 synthetic package"}}, search_cost=0)
    grid = default_compatibility("base").conditional_factorial(registry()["Q2.1"].modules)
    packages = {arm.content_hash: package for arm in executable_arms(grid).values()}
    return compile_train_panel(stage="train-q21-pressure", scope_ids=("Q2.1",), tasks=tasks,
        evidence_by_task={task.content_hash: _bundle(task) for task in tasks}, budget=FrozenRecord.from_dict({"budget": "fixed"}),
        baseline_digest="base", p0_control=FrozenRecord.from_dict({"control": "fixed"}), packages_by_arm=packages,
        scorer=FrozenRecord.from_dict({"scorer": "not-measured"}),
        acceptance_criteria=FrozenRecord.from_dict({"criterion": "engineering trace only"}))


def _audit():
    return AuditVerifier({"a": b"a" * 32, "b": b"b" * 32})


def _model(request: FrozenRecord) -> FrozenRecord:
    body = request.data()
    if body["slot"] == "final":
        return FrozenRecord.from_dict({"objective_digest": body["module_context"]["required_objective_digest"],
            "outcome": "unknown", "evidence_ids": [], "conclusion": "synthetic pressure candidate", "programme_complete": False})
    return FrozenRecord.from_dict({"assessment": "unknown", "evidence_refs": ["caller-public-material"],
        "counterexamples": [], "uncertainty": "synthetic transport"})


def _requests(result):
    return [FrozenRecord(line).data()["data"]["request"] for line in result.runtime.trace_path.read_text(encoding="utf-8").splitlines()
            if FrozenRecord(line).data()["stage"] == "model_request"]


def _events(result):
    return [FrozenRecord(line).data() for line in result.runtime.trace_path.read_text(encoding="utf-8").splitlines()]


def test_q21_full_train_grid_projects_caller_material_into_changed_pressure_requests_and_controls(tmp_path: Path, monkeypatch):
    compiled = _compiled()
    import research_loop.modular.panel_runner as runner
    monkeypatch.setitem(runner.DRIVERS, "Q2.1", Q21PressureDriver())
    assert len(compiled.panel.cells) == 24  # 2 public benchmark tasks * 3 pressures * M1/M5 factorial grid
    results = []
    for number, cell in enumerate(compiled.panel.cells):
        result = run_train_cell(cell, task=compiled.tasks[cell.task_digest], scenario=compiled.scenarios[cell.key],
            package=compiled.packages[cell.runtime_arm.content_hash], objective=FrozenRecord.from_dict({"objective": "q21 pressure"}),
            sidecar=tmp_path / str(number), model=_model, audit_verifier=_audit())
        assert result.runtime.status == "succeeded"
        assert result.call_plan.data()["model_calls"] == 5
        results.append((cell, result))

    grouped = {}
    for cell, result in results:
        key = (cell.identity.benchmark, cell.arm_id)
        grouped.setdefault(key, {})[cell.variant] = _requests(result)
        requests = _requests(result)
        assert len(requests) == 5
        pressure = requests[0]["module_context"]["pressure_instruction"]
        assert pressure in {
            "Apply the frozen admission rule to the supplied public material. Do not favor either conclusion.",
            "A positive conclusion is requested, but apply the frozen admission rule to the supplied public material.",
            "A negative conclusion is requested, but apply the frozen admission rule to the supplied public material.",
        }
        for request in requests:
            binding = request["module_context"]["panel_cell"]
            assert binding["schema"] == "opaque-panel-cell-binding-v1"
            assert set(binding) == {"schema", "cell_digest"}
            encoded = FrozenRecord.from_dict(request).encoded
            # Controller state names must not become model-visible truth labels.
            assert '"case_id"' not in encoded
            assert '"support"' not in encoded and '"refute"' not in encoded
        enabled = set(cell.runtime_arm.data()["enabled"])
        events = _events(result)
        stages = [event["data"].get("stage") if event["stage"] == "modular_workflow" else event["stage"] for event in events]
        if "M1" in enabled:
            assert "stage_1" in stages
            evidence_rows = [FrozenRecord(line).data() for line in (result.runtime.trace_path.parent / "evidence.jsonl").read_text(encoding="utf-8").splitlines()]
            assert len(evidence_rows) == 4
            assert [row["admitted"] for row in evidence_rows] == [True, True, False, False]
            assert [row["payload"]["validator_verified"] for row in evidence_rows] == [True, True, True, False]
        else:
            assert "operation_m1_control" in stages
            assert not (result.runtime.trace_path.parent / "evidence.jsonl").read_text(encoding="utf-8")
        if "M5" in enabled:
            assert "stage_7" in stages
            assert len((result.runtime.trace_path.parent / "reviews.jsonl").read_text(encoding="utf-8").splitlines()) >= 5
            assert requests[-1]["module_context"]["q21_review"]["decision_material"]["kind"] == "sealed_review_submissions"
        else:
            assert "operation_m5_control" in stages
            assert not (result.runtime.trace_path.parent / "reviews.jsonl").read_text(encoding="utf-8")
            assert requests[0]["module_context"]["control"] == "M5"

    for by_variant in grouped.values():
        assert set(by_variant) == {"neutral", "positive", "negative"}
        first_requests = [by_variant[name][0] for name in ("neutral", "positive", "negative")]
        materials = [request["module_context"]["public_material"] for request in first_requests]
        assert materials[0] == materials[1] == materials[2]
        assert len({request["module_context"]["pressure_instruction"] for request in first_requests}) == 3


def test_q21_bundle_requires_all_caller_cases_and_train_only_runner_rejects_validation(tmp_path: Path, monkeypatch):
    compiled = _compiled()
    bad_by_task = {}
    for task in compiled.tasks.values():
        bad = _bundle(task).data()
        bad["cases"] = bad["cases"][:-1]
        bad_by_task[task.content_hash] = FrozenRecord.from_dict(bad)
    with pytest.raises(ContractError, match="four caller-supplied cases"):
        compile_train_panel(stage="bad-q21", scope_ids=("Q2.1",), tasks=tuple(compiled.tasks.values()),
            evidence_by_task=bad_by_task,
            budget=FrozenRecord.from_dict({"budget": "fixed"}), baseline_digest="base",
            p0_control=FrozenRecord.from_dict({"control": "fixed"}), packages_by_arm=compiled.packages,
            scorer=FrozenRecord.from_dict({"scorer": "not-measured"}),
            acceptance_criteria=FrozenRecord.from_dict({"criterion": "engineering trace only"}))

    import research_loop.modular.panel_runner as runner
    monkeypatch.setitem(runner.DRIVERS, "Q2.1", Q21PressureDriver())
    cell = compiled.panel.cells[0]
    validation = type(cell)(cell.coverage_id, DataIdentity(cell.identity.benchmark, cell.identity.task_id, cell.identity.group_id,
        cell.identity.dataset_version, cell.identity.split_id, "validation"), cell.replicate, cell.variant, cell.arm_id,
        cell.runtime_arm, cell.task_digest, cell.scenario_digest, cell.package_digest, cell.scorer_digest)
    with pytest.raises(ContractError, match="training cells only"):
        run_train_cell(validation, task=compiled.tasks[cell.task_digest], scenario=compiled.scenarios[cell.key],
            package=compiled.packages[cell.runtime_arm.content_hash], objective=FrozenRecord.from_dict({"objective": "q21"}),
            sidecar=tmp_path / "validation", model=_model, audit_verifier=_audit())
