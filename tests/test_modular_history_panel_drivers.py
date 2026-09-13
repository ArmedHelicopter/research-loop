"""Synthetic public-grid checks for the unregistered Q1.1/Q1.2 drivers."""
from __future__ import annotations

from pathlib import Path

import pytest

from research_loop.modular import panel_runner
from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.experiments import registry
from research_loop.modular.history_panel_drivers import (
    freeze_history_bundle, install_drivers, select_history_material,
)
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_plan import compile_train_panel, executable_arms, obligation_grids
from research_loop.modular.panel_receipts import PanelReceiptVerifier
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError, canonical


SPLIT = "f" * 64
AUDIT = AuditVerifier({"a": b"a" * 32, "b": b"b" * 32})


def _task(benchmark: str):
    identity = DataIdentity(benchmark, "history-" + benchmark, benchmark + ":history", "synthetic-v1", SPLIT, "train")
    if benchmark == "blade":
        return BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": "public", "research_question": "What does public evidence show?", "data_schema": [{"name": "x", "dtype": "float"}]})
    return DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id, "question": "What does public evidence show?", "source_kind": "synthetic", "dataset": [{"name": "public.csv", "columns": [{"name": "x"}]}]})


def _q12(pre: str, post: str, upstream: str, downstream: str, *, withdrawal: bool, dependency: bool):
    return {"pre_transition_summary": pre, "post_transition_summary": post,
            "upstream_claim": upstream, "downstream_claim": downstream,
            "withdrawal": withdrawal, "dependency": dependency}


def _bundle(task, _scenario=None):
    return freeze_history_bundle(
        task,
        before_evidence={"measurement_id": "before-" + task.identity.benchmark, "observation": "BEFORE-SENTINEL public grouped measurement.", "value": 1.5},
        current_evidence={"measurement_id": "current-" + task.identity.benchmark, "observation": "CURRENT-SENTINEL public grouped measurement after update.", "value": 1.6},
        transition={"action": "replace_public_measurement", "reason": "frozen public replacement"},
        q11={"correct": {"historical_summary": "Earlier report says treatment exceeded control."},
             "wrong": {"historical_summary": "Earlier report says treatment was below control."},
             "neutral": {"historical_summary": "Earlier report has no interpretation."}},
        q12={"summary_only": _q12("PRE-SUMMARY-ONLY-SENTINEL", "POST-SUMMARY-ONLY-SENTINEL", "Summary upstream public claim.", "Summary downstream public claim.", withdrawal=False, dependency=False),
             "registered": _q12("PRE-REGISTERED-SENTINEL", "POST-REGISTERED-SENTINEL", "Registered upstream public claim.", "Registered downstream public claim.", withdrawal=False, dependency=True),
             "withdraw": _q12("PRE-WITHDRAW-SENTINEL", "POST-WITHDRAWAL-SENTINEL", "Withdrawn upstream public claim.", "Withdrawn downstream public claim.", withdrawal=True, dependency=True)},
    )


def _rows(coverage: str):
    tasks = {name: _task(name) for name in ("discoverybench", "blade")}
    package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([task.identity for task in tasks.values()]), changes={"prompt": {"instructions": "public history package"}}, search_cost=0)
    bundles = {task.content_hash: _bundle(task) for task in tasks.values()}
    control = FrozenRecord.from_dict({"source": "synthetic", "always_enabled": True})
    grids = obligation_grids((coverage,), baseline_digest="b" * 64, p0_control=control)
    packages = {arm.content_hash: package for grid in grids.values() for arm in executable_arms(grid).values()}
    compiled = compile_train_panel(stage="history-" + coverage, scope_ids=(coverage,), tasks=tuple(tasks.values()), evidence_by_task=bundles,
        budget=FrozenRecord.from_dict({"calls": 3}), baseline_digest="b" * 64, p0_control=control,
        packages_by_arm=packages, scorer=FrozenRecord.from_dict({"identity": "not-configured"}),
        acceptance_criteria=FrozenRecord.from_dict({"scope": "engineering-only"}), replicates=("r1",))
    return compiled, tasks, bundles


def _model(seen):
    def call(request: FrozenRecord):
        row = request.data(); seen.append(row)
        if row["slot"] == "final":
            return FrozenRecord.from_dict({"objective_digest": row["module_context"]["required_objective_digest"], "outcome": "unknown", "evidence_ids": [], "conclusion": "synthetic history candidate", "programme_complete": False})
        return FrozenRecord.from_dict({"assessment": "concern", "evidence_refs": ["public"], "counterexamples": [], "uncertainty": "synthetic"})
    return call


def _admit(_task, record):
    return {"trusted_validator": "synthetic-independent-admission", "validator_verified": True,
            "admitted": True, "record_digest": record.content_hash}


def _run_grid(tmp_path: Path, monkeypatch, coverage: str):
    compiled, tasks, bundles = _rows(coverage)
    runtimes, requests = [], []
    for number, cell in enumerate(compiled.panel.cells):
        run = panel_runner.run_train_cell(cell, task=tasks[cell.identity.benchmark], scenario=compiled.scenarios[cell.key], package=compiled.packages[cell.runtime_arm.content_hash],
            objective=FrozenRecord.from_dict({"objective": coverage}), sidecar=tmp_path / str(number), model=_model(requests), audit_verifier=AUDIT,
            history_admission_port=_admit)
        runtimes.append(run.runtime)
        assert run.runtime.status == "succeeded" and run.call_plan.data()["model_calls"] == 3
    assert PanelReceiptVerifier().verify(compiled.panel, tuple(runtimes)).decision == "engineering_verified"
    return requests


def _by_binding(rows, slot):
    return {row["module_context"]["panel_cell"]["cell_digest"]: row for row in rows if row["slot"] == slot}


def _claims(context):
    return [entry for entry in context["entries"]["entries"] if entry["kind"] == "claim"]


@pytest.mark.parametrize("coverage", ["Q1.1", "Q1.2"])
def test_full_public_grid_uses_phase_bound_material_and_real_m2_m3_state(tmp_path: Path, monkeypatch, coverage: str):
    requests = _run_grid(tmp_path, monkeypatch, coverage)
    assert all(row["task"]["identity"]["benchmark"] in {"blade", "discoverybench"} for row in requests)
    assert all(row["module_context"]["panel_cell"].keys() == {"schema", "cell_digest"} for row in requests)
    if coverage == "Q1.1":
        first, second, final = _by_binding(requests, "history_baseline"), _by_binding(requests, "history_rebuilt"), _by_binding(requests, "final")
        assert set(first) == set(second) == set(final)
        paired = {}
        for binding, row in first.items():
            material = row["module_context"]["history_material"]
            assert set(material) == {"schema", "identity", "phase", "public_record", "historical_summary"}
            assert material["phase"] == "before" and "CURRENT-SENTINEL" not in canonical(material)
            assert row["module_context"]["public_record_digest"] == FrozenRecord.from_dict(material["public_record"]).content_hash
            assert row["module_context"]["admission_receipt"]["record_digest"] == row["module_context"]["public_record_digest"]
            paired.setdefault((row["task"]["identity"]["task_id"], material["historical_summary"]), {})[row["module_context"]["m3"]] = material["public_record"]
        for pair in paired.values():
            assert pair["enabled"] == pair["frozen_control"]
        for binding, row in second.items():
            material = row["module_context"]["history_material"]
            assert material["phase"] == "current" and "CURRENT-SENTINEL" in canonical(material)
            assert row["module_context"]["public_record_digest"] == FrozenRecord.from_dict(material["public_record"]).content_hash
            assert material["public_record"] == final[binding]["module_context"]["history_material"]["public_record"]
            assert row["module_context"]["admission_receipt"]["record_digest"] == row["module_context"]["public_record_digest"]
            paired.setdefault((row["task"]["identity"]["task_id"], material["historical_summary"]), {})[row["module_context"]["m3"] + "-current"] = material["public_record"]
        for pair in paired.values():
            assert pair["enabled-current"] == pair["frozen_control-current"]
        for binding, before_row in first.items():
            after_row = second[binding]
            if before_row["module_context"]["m3"] == "enabled":
                assert before_row["context"]["mode"] == after_row["context"]["mode"] == "candidate"
                assert "BEFORE-SENTINEL" in canonical(before_row["context"])
                assert "CURRENT-SENTINEL" in canonical(after_row["context"])
            else:
                assert before_row["context"]["mode"] == after_row["context"]["mode"] == "baseline"
                assert before_row["context"]["entries"] == after_row["context"]["entries"]
                assert before_row["module_context"]["context_material"] == after_row["module_context"]["context_material"]
    else:
        first, second = _by_binding(requests, "upstream_before_withdrawal"), _by_binding(requests, "downstream_after_withdrawal")
        assert set(first) == set(second)
        for binding, row in first.items():
            material = row["module_context"]["history_material"]
            assert set(material) == {"schema", "identity", "phase", "public_record", "pre_transition_summary", "upstream_claim"}
            assert material["phase"] == "before"
            assert "POST-" not in canonical(material) and "replace_public_measurement" not in canonical(material) and "withdrawal" not in canonical(material)
            assert row["module_context"]["public_record_digest"] == FrozenRecord.from_dict(material["public_record"]).content_hash
        for binding, row in second.items():
            material = row["module_context"]["history_material"]
            assert material["phase"] == "current" and "POST-" in canonical(material) and material["transition"]["action"] == "replace_public_measurement"
            if row["module_context"]["m3"] == "frozen_control":
                assert row["module_context"]["reconstructed_context"] == first[binding]["module_context"]["claim_context"]
        enabled_first = [row for row in first.values() if row["module_context"]["m2"] == "enabled" and row["module_context"]["m3"] == "enabled"]
        summary = next(row for row in enabled_first if row["module_context"]["history_material"]["pre_transition_summary"] == "PRE-SUMMARY-ONLY-SENTINEL")
        registered = next(row for row in enabled_first if row["module_context"]["history_material"]["pre_transition_summary"] == "PRE-REGISTERED-SENTINEL")
        withdrawn = next(row for row in enabled_first if row["module_context"]["history_material"]["pre_transition_summary"] == "PRE-WITHDRAW-SENTINEL")
        assert all(not claim["depends_on"] for claim in _claims(summary["module_context"]["claim_context"]))
        assert any(claim["depends_on"] and claim["support_roots"] for claim in _claims(registered["module_context"]["claim_context"]))
        withdrawn_after = second[withdrawn["module_context"]["panel_cell"]["cell_digest"]]
        assert withdrawn_after["module_context"]["withdrawal_applied"]
        assert any(claim["depends_on"] and claim["needs_review"] and not claim["support_roots"] for claim in _claims(withdrawn_after["module_context"]["reconstructed_context"]))


def test_rejects_unbound_bundle_or_missing_q11_admission_before_model_call(tmp_path: Path, monkeypatch):
    compiled, tasks, bundles = _rows("Q1.1")
    foreign = next(bundle for digest, bundle in bundles.items() if digest != tasks["blade"].content_hash)
    called = []
    local = dict(panel_runner.DRIVERS)
    install_drivers(local, material_resolver=lambda _task, _scenario: foreign, admission_port=_admit)
    monkeypatch.setattr(panel_runner, "DRIVERS", local)
    cell = next(item for item in compiled.panel.cells if item.identity.benchmark == "blade")
    result = panel_runner.run_train_cell(cell, task=tasks["blade"], scenario=compiled.scenarios[cell.key], package=compiled.packages[cell.runtime_arm.content_hash],
        objective=FrozenRecord.from_dict({"objective": "guard"}), sidecar=tmp_path / "foreign", model=lambda request: called.append(request), audit_verifier=AUDIT)
    assert result.runtime.status == "failed" and called == []
    local = dict(panel_runner.DRIVERS)
    install_drivers(local, material_resolver=lambda task, _scenario: bundles[task.content_hash])
    monkeypatch.setattr(panel_runner, "DRIVERS", local)
    result = panel_runner.run_train_cell(cell, task=tasks["blade"], scenario=compiled.scenarios[cell.key], package=compiled.packages[cell.runtime_arm.content_hash],
        objective=FrozenRecord.from_dict({"objective": "guard"}), sidecar=tmp_path / "missing-admission", model=lambda request: called.append(request), audit_verifier=AUDIT)
    assert result.runtime.status == "failed" and called == []


def test_transition_parser_rejects_nonreplacement_before_driver_execution():
    task = _task("blade")
    bundle = _bundle(task)
    malformed = bundle.data(); malformed["transition"] = {"action": "arbitrary", "reason": "still not valid"}
    with pytest.raises(ContractError):
        select_history_material(FrozenRecord.from_dict(malformed), task, "Q1.1", "neutral")
    with pytest.raises(ContractError):
        freeze_history_bundle(task, before_evidence={"id": "a"}, current_evidence={"id": "b"}, transition={"action": "replace_public_measurement", "reason": ""}, q11=bundle.data()["q11"], q12=bundle.data()["q12"])


def test_registered_history_driver_runs_from_custody_controller_with_caller_admission(tmp_path, monkeypatch):
    from evaluation.modular.train_io import TrainPacketExporter
    from research_loop.modular.train_controller import FrozenTrainControllerConfig, run_train_panel
    from test_modular_train_controller import snapshot_and_custody, config, model_port, REVIEW, FINAL

    snapshot, custody = snapshot_and_custody(tmp_path)
    base = config(custody, snapshot, tmp_path).data()
    packets = TrainPacketExporter(custody, snapshot, tmp_path / "material-input").export(base["item_ids"])
    grids = obligation_grids(("Q1.1",), baseline_digest=base["baseline_digest"], p0_control=FrozenRecord.from_dict(base["p0_control"]))
    package = next(iter(base["packages_by_arm"].values()))
    schemas = {"history_baseline": REVIEW, "history_rebuilt": REVIEW, "final": FINAL}
    frozen = FrozenTrainControllerConfig(FrozenRecord.from_dict({**base, "schema": "train-panel-controller-v1",
        "engineering_scope": "train_only_panel_engineering", "scope_ids": ["Q1.1"], "stage": "history-controller",
        "evidence_by_task": {packet.task.content_hash: _bundle(packet.task).data() for packet in packets},
        "packages_by_arm": {arm.content_hash: package for grid in grids.values() for arm in executable_arms(grid).values()},
        "schemas": schemas, "max_calls": 36, "budget": {"model_calls": 3, "execution_limit": 0}}))
    port = model_port(tmp_path, monkeypatch, max_calls=36, schemas=schemas)
    admissions = []
    def caller_admission(task, record):
        admissions.append((task.identity, record.content_hash))
        return _admit(task, record)
    run = run_train_panel(frozen, custody=custody, snapshot_root=snapshot, export_root=tmp_path / "run-export",
        run_root=tmp_path / "controller", model=port, audit_verifier=AUDIT, history_admission_port=caller_admission)
    assert len(run.runtimes) == 12 and all(row.status == "succeeded" for row in run.runtimes)
    assert len(admissions) == 24 and len(port.ledger["calls"]) == 36
    assert run.verdict.decision == "engineering_verified" and not run.verdict.scientific_verified
