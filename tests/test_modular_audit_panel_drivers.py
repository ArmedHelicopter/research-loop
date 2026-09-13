"""Full-grid engineering checks for Q2.3/Q2.4 caller-owned audit ports."""
from __future__ import annotations

import hashlib
import hmac
import subprocess
from pathlib import Path

import pytest

from research_loop.modular import panel_runner
from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.modules.admission import AuditItem, ScientificState
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_plan import compile_train_panel, executable_arms, obligation_grids
from research_loop.modular.panel_receipts import PanelReceiptVerifier
from research_loop.modular.runtime import AuditAuthority, AuditVerifier
from research_loop.modular.audit_panel_drivers import freeze_audit_bundle, install_drivers
from research_loop.ontology import ContractError, canonical


SPLIT = "7" * 64
KEYS = {"synthetic-audit-a": b"a" * 32, "synthetic-audit-b": b"b" * 32}
Q23 = ("false", "string_false", "empty", "duplicate", "unknown", "missing", "parse_error")
Q24 = ("one_fail", "both_fail", "disagree", "same_wrong")


def _task(name: str):
    identity = DataIdentity(name, "audit-" + name, name + ":audit", "synthetic-v1", SPLIT, "train")
    if name == "blade":
        return BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": "public",
            "research_question": "Public audit material?", "data_schema": [{"name": "x", "dtype": "float"}]})
    return DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id, "question": "Public audit material?",
        "source_kind": "synthetic", "dataset": [{"name": "public.csv", "columns": [{"name": "x"}]}]})


def _bundle(task):
    selected = lambda profile: {"audit_material": {"receipt_profile": profile},
                                "independent_check": {"fixture_check": "retained-controller-only", "profile": profile}}
    return freeze_audit_bundle(task, subject={"task": task.identity.task_id, "subject": "synthetic-public-subject"},
        public_evidence={"observation": "PUBLIC-AUDIT-" + task.identity.benchmark},
        shadow_execution={"operation_id": "synthetic-restricted-shadow", "public_input": "synthetic-only"},
        q23={name: selected(name) for name in Q23}, q24={name: selected(name) for name in Q24})


def _shadow(session, _task, material):
    plan = material.data()["shadow_execution"]
    public = session.sidecar / "audit-public-input.txt"
    public.write_text(plan["public_input"], encoding="utf-8")
    broker = DockerExecutionBroker([session.sidecar], runner=lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, b"shadow-ok", b""))
    return session.execute("print('restricted audit shadow')", broker=broker,
        image="fixture@sha256:" + "a" * 64, inputs={"public": public})


def _signed(name, task, objective, execution, state, outcome, audit):
    return AuditAuthority(name, KEYS[name]).issue(identity=task.identity, objective_digest=objective.content_hash,
        execution_digest=execution.content_hash, state=state, outcome=outcome, audit=audit)


def _mutated(name, body):
    return FrozenRecord.from_dict({"body": body,
        "mac": hmac.new(KEYS[name], canonical(body).encode(), hashlib.sha256).hexdigest()})


def _receipt_port(task, material, objective, execution):
    profile = material.data()["audit_material"]["receipt_profile"]
    state = ScientificState("valid", "supported", "unknown", "explore")
    if profile in Q23:
        if profile == "parse_error":
            return (FrozenRecord.from_dict({"raw_text": "{invalid", "parse_status": "failed"}),) * 2
        records = []
        for name in KEYS:
            body = _signed(name, task, objective, execution, state, "positive", [AuditItem("measurement", True, True)]).data()["body"]
            if profile == "false": body["audit"][0]["passed"] = False
            elif profile == "string_false": body["audit"][0]["passed"] = "false"
            elif profile == "empty": body["audit"] = []
            elif profile == "duplicate": body["audit"] *= 2
            elif profile == "unknown": body["audit"][0]["name"] = "unregistered-check"
            elif profile == "missing": del body["audit"][0]["passed"]
            records.append(_mutated(name, body))
        return tuple(records)
    if profile == "disagree":
        return (_signed("synthetic-audit-a", task, objective, execution, state, "positive", [AuditItem("measurement", True, True)]),
                _signed("synthetic-audit-b", task, objective, execution, ScientificState("valid", "refuted", "unknown", "explore"), "negative", [AuditItem("measurement", True, True)]))
    audits = ([AuditItem("measurement", True, True)], [AuditItem("measurement", True, True)])
    if profile == "one_fail": audits = ([AuditItem("measurement", True, True)], [AuditItem("measurement", True, False)])
    elif profile == "both_fail": audits = ([AuditItem("measurement", True, False)],) * 2
    return tuple(_signed(name, task, objective, execution, state, "positive", audits[index]) for index, name in enumerate(KEYS))


def _model(rows):
    def call(request):
        body = request.data(); rows.append(body)
        assert "receipt_profile" not in FrozenRecord.from_dict(body).encoded
        assert "controller_only_independent_check" not in body["module_context"]
        if body["slot"] == "final":
            return FrozenRecord.from_dict({"objective_digest": body["module_context"]["required_objective_digest"],
                "outcome": "unknown", "evidence_ids": [], "conclusion": "bounded synthetic audit result", "programme_complete": False})
        return FrozenRecord.from_dict({"assessment": "synthetic", "evidence_refs": [], "counterexamples": [], "uncertainty": "unknown"})
    return call


def _setup():
    tasks = {name: _task(name) for name in ("blade", "discoverybench")}
    bundles = {task.content_hash: _bundle(task) for task in tasks.values()}
    package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([task.identity for task in tasks.values()]),
        changes={"prompt": {"instructions": "audit"}}, search_cost=0)
    control = FrozenRecord.from_dict({"source": "synthetic", "always_enabled": True})
    grids = obligation_grids(("Q2.3", "Q2.4"), baseline_digest="b" * 64, p0_control=control)
    packages = {arm.content_hash: package for grid in grids.values() for arm in executable_arms(grid).values()}
    compiled = compile_train_panel(stage="audit", scope_ids=("Q2.3", "Q2.4"), tasks=tuple(tasks.values()), evidence_by_task=bundles,
        budget=FrozenRecord.from_dict({"calls": 2, "shadow_executions": 1}), baseline_digest="b" * 64, p0_control=control,
        packages_by_arm=packages, scorer=FrozenRecord.from_dict({"identity": "none"}),
        acceptance_criteria=FrozenRecord.from_dict({"scope": "engineering"}), replicates=("r1",))
    return compiled, tasks


def _trace(runtime):
    return [FrozenRecord(line).data() for line in runtime.trace_path.read_text(encoding="utf-8").splitlines()]


def test_compiled_q23_q24_grid_runs_real_audit_verifier_and_final_gate(tmp_path: Path, monkeypatch):
    compiled, tasks = _setup()
    local = dict(panel_runner.DRIVERS)
    install_drivers(local, receipt_port=_receipt_port, shadow_execution_port=_shadow)
    monkeypatch.setattr(panel_runner, "DRIVERS", local)
    rows, runtimes = [], []
    for number, cell in enumerate(compiled.panel.cells):
        result = panel_runner.run_train_cell(cell, task=tasks[cell.identity.benchmark], scenario=compiled.scenarios[cell.key],
            package=compiled.packages[cell.runtime_arm.content_hash], objective=FrozenRecord.from_dict({"objective": "audit"}),
            sidecar=tmp_path / str(number), model=_model(rows), audit_verifier=AuditVerifier(KEYS))
        assert result.runtime.status == "succeeded"
        assert result.call_plan.data()["model_calls"] == 2 and result.call_plan.data()["execution_attempts"] == 1
        runtimes.append(result.runtime)
        events = _trace(result.runtime)
        assert any(event["stage"] == "execution_result" for event in events)
        assert any(event["stage"] == "scientific_audit_inputs" for event in events)
        final = next(event["data"] for event in events if event["stage"] == "final_decision")
        assert final["decision"] == "unknown" and final["scientific_validated"] is False
        stages = [event["data"] for event in events if event["stage"] == "modular_workflow"]
        assert stages[-1]["host_audit_verifier"] == "always_on"
        assert stages[-1]["stage"] == ("stage_1" if "M1" in cell.runtime_arm.data()["enabled"] else "operation_m1_shadow_control")
        if cell.coverage_id == "Q2.3":
            assert not any(event["stage"] == "scientific_admission" and event["data"]["admitted"] for event in events)
            if cell.variant == "false":
                assert any(event["stage"] == "scientific_admission" and event["data"]["admitted"] is False for event in events)
            else:
                assert any(event["stage"] == "audit_rejected" for event in events)
        elif cell.variant == "same_wrong":
            admission = next(event["data"] for event in events if event["stage"] == "scientific_admission")
            assert admission["admitted"] is True
            assert stages[-1]["controller_only_independent_check"]["fixture_check"] == "retained-controller-only"
        else:
            assert not any(event["stage"] == "scientific_admission" and event["data"]["admitted"] for event in events)
            if cell.variant == "both_fail":
                assert any(event["stage"] == "scientific_admission" and event["data"]["admitted"] is False for event in events)
            else:
                assert any(event["stage"] == "audit_rejected" for event in events)
    assert len(runtimes) == len(compiled.panel.cells)
    assert PanelReceiptVerifier().verify(compiled.panel, tuple(runtimes)).decision == "engineering_verified"
    assert all(row["module_context"]["panel_cell"].keys() == {"schema", "cell_digest"} for row in rows)
    assert all(row["slot"] == "audit_initial" or "audit_processing" in row["module_context"] for row in rows)


def test_bundle_is_identity_bound_and_ports_fail_closed_before_audit(tmp_path: Path, monkeypatch):
    task = _task("blade")
    bundle = _bundle(task).data()
    with pytest.raises(ContractError):
        freeze_audit_bundle(task, subject={"task": "other", "subject": "x"}, public_evidence=bundle["public_evidence"],
            shadow_execution=bundle["shadow_execution"], q23=bundle["q23"], q24=bundle["q24"])
    compiled, tasks = _setup()
    cell = next(item for item in compiled.panel.cells if item.coverage_id == "Q2.3")
    local = dict(panel_runner.DRIVERS)
    install_drivers(local, receipt_port=lambda *_: (), shadow_execution_port=_shadow)
    monkeypatch.setattr(panel_runner, "DRIVERS", local)
    calls = []
    result = panel_runner.run_train_cell(cell, task=tasks[cell.identity.benchmark], scenario=compiled.scenarios[cell.key],
        package=compiled.packages[cell.runtime_arm.content_hash], objective=FrozenRecord.from_dict({"objective": "bad"}),
        sidecar=tmp_path / "bad", model=_model(calls), audit_verifier=AuditVerifier(KEYS))
    assert result.runtime.status == "failed" and result.call_plan.data()["model_calls"] == 1
