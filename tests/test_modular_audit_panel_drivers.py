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
SHADOW_PROGRAM = "print('restricted audit shadow')"
SHADOW_INPUT = "synthetic-only"


def _task(name: str):
    identity = DataIdentity(name, "audit-" + name, name + ":audit", "synthetic-v1", SPLIT, "train")
    if name == "blade":
        return BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": "public",
            "research_question": "Public audit material?", "data_schema": [{"name": "x", "dtype": "float"}]})
    return DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id, "question": "Public audit material?",
        "source_kind": "synthetic", "dataset": [{"name": "public.csv", "columns": [{"name": "x"}]}]})


def _template(profile):
    state = {"validity": "valid", "support": "supported", "novelty": "unknown", "investment": "explore"}
    if profile == "parse_error": return {"kind": "raw_parse_error", "raw_text": "{invalid"}
    audits = ([{"name": "measurement", "executed": True, "passed": True}],) * 2
    outcomes = ("positive", "positive"); states = (state, state)
    if profile == "false": audits = ([{"name": "measurement", "executed": True, "passed": False}],) * 2
    elif profile == "string_false": audits = ([{"name": "measurement", "executed": True, "passed": "false"}],) * 2
    elif profile == "empty": audits = ([], [])
    elif profile == "duplicate": audits = ([{"name": "measurement", "executed": True, "passed": True}] * 2,) * 2
    elif profile == "unknown": audits = ([{"name": "unregistered-check", "executed": True, "passed": True}],) * 2
    elif profile == "missing": audits = ([{"name": "measurement", "executed": True}],) * 2
    elif profile == "one_fail": audits = ([{"name": "measurement", "executed": True, "passed": True}], [{"name": "measurement", "executed": True, "passed": False}])
    elif profile == "both_fail": audits = ([{"name": "measurement", "executed": True, "passed": False}],) * 2
    elif profile == "disagree":
        states = (state, {"validity": "valid", "support": "refuted", "novelty": "unknown", "investment": "explore"}); outcomes = ("positive", "negative")
    return {"kind": "signed_audit_pair", "receipts": [{"state": states[index], "outcome": outcomes[index], "audit": audits[index]} for index in range(2)]}


def _bundle(task):
    selected = lambda profile: {"audit_template": _template(profile),
                                "independent_check": {"fixture_check": "retained-controller-only", "profile": profile}}
    return freeze_audit_bundle(task, subject={"task": task.identity.task_id, "subject": "synthetic-public-subject"},
        public_evidence={"observation": "PUBLIC-AUDIT-" + task.identity.benchmark},
        shadow_execution={"schema": "frozen-shadow-execution-contract-v1",
            "program_sha256": hashlib.sha256(SHADOW_PROGRAM.encode("utf-8")).hexdigest(),
            "input_sha256": {"public": hashlib.sha256(SHADOW_INPUT.encode("utf-8")).hexdigest()}},
        q23={name: selected(name) for name in Q23}, q24={name: selected(name) for name in Q24})


def _shadow(session, _task, material):
    public = session.sidecar / "audit-public-input.txt"
    public.write_text(SHADOW_INPUT, encoding="utf-8")
    broker = DockerExecutionBroker([session.sidecar], runner=lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, b"shadow-ok", b""))
    return session.execute(SHADOW_PROGRAM, broker=broker,
        image="fixture@sha256:" + "a" * 64, inputs={"public": public})


def _signed(name, task, objective, execution, state, outcome, audit):
    return AuditAuthority(name, KEYS[name]).issue(identity=task.identity, objective_digest=objective.content_hash,
        execution_digest=execution.content_hash, state=state, outcome=outcome, audit=audit)


def _mutated(name, body):
    return FrozenRecord.from_dict({"body": body,
        "mac": hmac.new(KEYS[name], canonical(body).encode(), hashlib.sha256).hexdigest()})


def _receipt_port(task, material, objective, execution):
    template = material.data()["audit_template"]
    if template["kind"] == "raw_parse_error": payloads = [template["raw_text"], template["raw_text"]]
    else:
        payloads = []
        for index, name in enumerate(KEYS):
            expected = template["receipts"][index]
            body = _signed(name, task, objective, execution, ScientificState("valid", "supported", "unknown", "explore"), "positive", [AuditItem("measurement", True, True)]).data()["body"]
            body.update({"state": expected["state"], "outcome": expected["outcome"], "audit": expected["audit"]})
            payloads.append(_mutated(name, body).encoded)
    return FrozenRecord.from_dict({"schema": "caller-dual-audit-binding-v1", "material_digest": material.content_hash,
        "identity": task.identity.data(), "objective_digest": objective.content_hash, "execution_digest": execution.content_hash,
        "shadow_receipt_digest": execution.content_hash, "audit_payloads": payloads,
        "audit_payload_digests": [hashlib.sha256(value.encode("utf-8")).hexdigest() for value in payloads]})


def _model(rows):
    def call(request):
        body = request.data(); rows.append(body)
        encoded = FrozenRecord.from_dict(body).encoded
        for hidden in ("signed_audit_pair", "controller_only_independent_check", "arm_id", "enabled_modules",
                       "frozen_shadow_control", "candidate_package", "same_wrong", "retained-controller-only"):
            assert hidden not in encoded
        assert "candidate_package" not in body["module_context"]
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
    rows, runtimes = [], []
    for number, cell in enumerate(compiled.panel.cells):
        result = panel_runner.run_train_cell(cell, task=tasks[cell.identity.benchmark], scenario=compiled.scenarios[cell.key],
            package=compiled.packages[cell.runtime_arm.content_hash], objective=FrozenRecord.from_dict({"objective": "audit"}),
            sidecar=tmp_path / str(number), model=_model(rows), audit_verifier=AuditVerifier(KEYS),
            audit_receipt_port=_receipt_port, shadow_execution_port=_shadow)
        assert result.runtime.status == "succeeded"
        assert result.call_plan.data()["model_calls"] == 2 and result.call_plan.data()["execution_attempts"] == 1
        runtimes.append(result.runtime)
        events = _trace(result.runtime)
        assert any(event["stage"] == "execution_result" for event in events)
        assert any(event["stage"] in {"host_audit_verified", "host_audit_rejected"} for event in events)
        final = next(event["data"] for event in events if event["stage"] == "final_decision")
        assert final["decision"] == "unknown" and final["scientific_validated"] is False
        stages = [event["data"] for event in events if event["stage"] == "modular_workflow"]
        assert stages[-1]["host_audit_verifier"] == "always_on"
        assert stages[-1]["stage"] == ("stage_1" if "M1" in cell.runtime_arm.data()["enabled"] else "operation_m1_shadow_control")
        m1 = "M1" in cell.runtime_arm.data()["enabled"]
        host_verified = cell.variant in {"false", "empty", "duplicate", "unknown", "both_fail", "same_wrong"}
        if host_verified:
            assert any(event["stage"] == "host_audit_verified" for event in events)
        else:
            assert any(event["stage"] == "host_audit_rejected" for event in events)
        if not m1:
            assert not any(event["stage"] == "scientific_audit_inputs" for event in events)
            assert stages[-1]["processing"]["m1_policy"] != "applied"
        elif cell.coverage_id == "Q2.3":
            if host_verified:
                assert any(event["stage"] == "scientific_audit_inputs" for event in events)
                if cell.variant == "false":
                    assert any(event["stage"] == "scientific_admission" and event["data"]["admitted"] is False for event in events)
                else:
                    assert any(event["stage"] == "audit_rejected" for event in events)
            else:
                assert not any(event["stage"] == "scientific_audit_inputs" for event in events)
                assert stages[-1]["processing"]["m1_policy"] == "not_applied_common_p0_rejection"
        elif cell.variant == "same_wrong":
            admission = next(event["data"] for event in events if event["stage"] == "scientific_admission")
            assert admission["admitted"] is True
            assert stages[-1]["controller_only_independent_check"]["fixture_check"] == "retained-controller-only"
        else:
            if cell.variant == "both_fail": assert any(event["stage"] == "scientific_admission" and event["data"]["admitted"] is False for event in events)
            else: assert not any(event["stage"] == "scientific_admission" for event in events)
    assert len(runtimes) == len(compiled.panel.cells)
    assert PanelReceiptVerifier().verify(compiled.panel, tuple(runtimes)).decision == "engineering_verified"
    assert all(row["module_context"]["panel_cell"].keys() == {"schema", "cell_digest"} for row in rows)
    assert all(row["slot"] == "audit_initial" or "audit_processing" in row["module_context"] for row in rows)
    final_rows = [row for row in rows if row["slot"] == "final"]
    assert all(row["module_context"]["audit_processing"].keys() ==
               {"schema", "execution_status", "host_verification", "admission"} for row in final_rows)


def test_bundle_is_identity_bound_and_ports_fail_closed_before_audit(tmp_path: Path, monkeypatch):
    task = _task("blade")
    bundle = _bundle(task).data()
    with pytest.raises(ContractError):
        freeze_audit_bundle(task, subject={"task": "other", "subject": "x"}, public_evidence=bundle["public_evidence"],
            shadow_execution=bundle["shadow_execution"], q23=bundle["q23"], q24=bundle["q24"])
    malformed_shadow = dict(bundle["shadow_execution"])
    malformed_shadow["unbound_summary"] = "not an execution contract"
    with pytest.raises(ContractError):
        freeze_audit_bundle(task, subject=bundle["subject"], public_evidence=bundle["public_evidence"],
            shadow_execution=malformed_shadow, q23=bundle["q23"], q24=bundle["q24"])
    compiled, tasks = _setup()
    cell = next(item for item in compiled.panel.cells if item.coverage_id == "Q2.3" and item.variant == "false")
    def wrong_binding(*args):
        body = _receipt_port(*args).data(); body["material_digest"] = "0" * 64
        return FrozenRecord.from_dict(body)
    def wrong_template(*args):
        body = _receipt_port(*args).data(); first = FrozenRecord(body["audit_payloads"][0]).data()
        first["body"]["audit"][0]["passed"] = True
        body["audit_payloads"][0] = _mutated("synthetic-audit-a", first["body"]).encoded
        body["audit_payload_digests"] = [hashlib.sha256(value.encode("utf-8")).hexdigest() for value in body["audit_payloads"]]
        return FrozenRecord.from_dict(body)
    for number, port in enumerate((wrong_binding, wrong_template)):
        local = dict(panel_runner.DRIVERS)
        install_drivers(local, receipt_port=port, shadow_execution_port=_shadow)
        monkeypatch.setattr(panel_runner, "DRIVERS", local)
        calls = []
        result = panel_runner.run_train_cell(cell, task=tasks[cell.identity.benchmark], scenario=compiled.scenarios[cell.key],
            package=compiled.packages[cell.runtime_arm.content_hash], objective=FrozenRecord.from_dict({"objective": "bad"}),
            sidecar=tmp_path / str(number), model=_model(calls), audit_verifier=AuditVerifier(KEYS))
        assert result.runtime.status == "failed" and result.call_plan.data()["model_calls"] == 1
        assert not any(event["stage"].startswith("host_audit_") for event in _trace(result.runtime))


@pytest.mark.parametrize("substitution", ("program", "input"))
def test_shadow_port_cannot_substitute_an_unbound_program_or_input_before_receipt_verification(tmp_path: Path, monkeypatch,
                                                                                                 substitution: str):
    compiled, tasks = _setup()
    cell = next(item for item in compiled.panel.cells if item.coverage_id == "Q2.3" and item.variant == "false")

    def wrong_shadow(session, _task, _material):
        public = session.sidecar / "wrong-audit-public-input.txt"
        public.write_text("unbound public input" if substitution == "input" else SHADOW_INPUT, encoding="utf-8")
        broker = DockerExecutionBroker([session.sidecar], runner=lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, b"wrong", b""))
        return session.execute("print('unbound shadow program')" if substitution == "program" else SHADOW_PROGRAM, broker=broker,
            image="fixture@sha256:" + "a" * 64, inputs={"public": public})

    local = dict(panel_runner.DRIVERS)
    install_drivers(local, receipt_port=_receipt_port, shadow_execution_port=wrong_shadow)
    monkeypatch.setattr(panel_runner, "DRIVERS", local)
    calls = []
    result = panel_runner.run_train_cell(cell, task=tasks[cell.identity.benchmark], scenario=compiled.scenarios[cell.key],
        package=compiled.packages[cell.runtime_arm.content_hash], objective=FrozenRecord.from_dict({"objective": "bad"}),
        sidecar=tmp_path / ("wrong-shadow-" + substitution), model=_model(calls), audit_verifier=AuditVerifier(KEYS))
    assert result.runtime.status == "failed" and result.call_plan.data()["model_calls"] == 1
    events = _trace(result.runtime)
    assert any(event["stage"] == "execution_result" for event in events)
    assert not any(event["stage"].startswith("host_audit_") for event in events)
