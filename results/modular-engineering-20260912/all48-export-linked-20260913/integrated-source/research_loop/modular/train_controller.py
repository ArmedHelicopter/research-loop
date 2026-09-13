"""Trusted, train-only production-panel controller.

This module deliberately owns orchestration but not custody qualification,
context review, scoring, or scientific state transitions.  Its input is a
canonical frozen record, and its only successful verdict is engineering-only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from evaluation.modular.custody import CustodyStore
from evaluation.modular.train_io import TrainPacketExporter
from evaluation.modular.primary_prospective_exporter import PrimaryProspectiveTrainExporter
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.experiments import registry
from research_loop.modular.model_port import CodexModelPort, FrozenBaseContextPolicy
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.panel_plan import CompiledTrainPanel, compile_train_panel, executable_arms, obligation_grids
from research_loop.modular.panel_receipts import PanelReceiptVerifier, PanelVerdict, RuntimeReceipt
from research_loop.modular.panel_runner import DRIVERS, run_train_cell
from research_loop.modular.history_panel_drivers import AdmissionPort
from research_loop.modular.audit_panel_drivers import AuditReceiptPort, ShadowExecutionPort
from research_loop.modular.feasibility_panel_drivers import FeasibilityAuthorityPort
from research_loop.modular.exploration_panel_drivers import ExplorationAuthorityPort, BUDGET as EXPLORATION_BUDGET
from research_loop.modular.exploration_extended_panel_drivers import BUDGET as EXTENDED_EXPLORATION_BUDGET
from research_loop.modular.q54_causal_driver import DiagnosticAuthority
from research_loop.modular.q55_causal_driver import Authority as Q55Authority
from research_loop.modular.benchmark_cell import LinkedBenchmarkCellResult, run_benchmark_cell, verify_linked_benchmark_cell
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.protocol_panel_driver import (ProtocolAuditPort, ProtocolReplayAuthority,
    verify_protocol_replay_receipt, _no_links)
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError, canonical, digest


_LEGACY_SCHEMA = "q31-train-controller-v1"
_SCHEMA = "train-panel-controller-v1"
_LEGACY_SCOPE = ("Q3.1",)


def _record(value: Any, name: str) -> FrozenRecord:
    if not isinstance(value, Mapping):
        raise ContractError(f"{name} must be a frozen record object")
    return FrozenRecord.from_dict(value)


@dataclass(frozen=True)
class FrozenTrainControllerConfig:
    """Exact controller material; paths and authority keys stay outside it."""

    record: FrozenRecord

    def __post_init__(self) -> None:
        data = self.record.data()
        required = {"schema", "engineering_scope", "stage", "scope_ids", "item_ids",
                    "evidence_by_task", "budget", "baseline_digest", "p0_control",
                    "packages_by_arm", "scorer", "acceptance_criteria", "replicates",
                    "model", "effort", "max_calls", "max_tokens", "schemas"}
        if (not required <= set(data) or set(data) - required - {"execution_mode", "objective_by_task"}
                or data["schema"] not in {_LEGACY_SCHEMA, _SCHEMA}):
            raise ContractError("unexpected train controller config schema")
        scope = tuple(data["scope_ids"]) if isinstance(data["scope_ids"], list) else ()
        if (not scope or len(set(scope)) != len(scope) or set(scope) - set(DRIVERS)
                or any(not isinstance(item, str) for item in scope)):
            raise ContractError("controller scope must use closed production drivers")
        if data["schema"] == _LEGACY_SCHEMA:
            if data["engineering_scope"] != "train_only_q3_1_engineering" or scope != _LEGACY_SCOPE:
                raise ContractError("legacy controller is restricted to Q3.1 train engineering")
        elif data["engineering_scope"] != "train_only_panel_engineering":
            raise ContractError("production panel controller must remain train-only engineering")
        if (not isinstance(data["stage"], str) or not data["stage"].strip() or not isinstance(data["item_ids"], list)
                or not data["item_ids"] or len(set(data["item_ids"])) != len(data["item_ids"])
                or any(not isinstance(item, str) or not item for item in data["item_ids"])):
            raise ContractError("controller needs an exact nonempty train allowlist")
        if not isinstance(data["evidence_by_task"], Mapping) or not data["evidence_by_task"]:
            raise ContractError("controller needs exact task evidence")
        for value in data["evidence_by_task"].values(): _record(value, "evidence")
        if "Q2.6" in scope and "objective_by_task" not in data:
            raise ContractError("goal-lock controller requires predeclared task objectives")
        if "objective_by_task" in data:
            objectives = data["objective_by_task"]
            if not isinstance(objectives, Mapping) or set(objectives) != set(data["evidence_by_task"]):
                raise ContractError("task objectives must exactly cover the frozen task evidence")
            for value in objectives.values():
                if not _record(value, "task objective").data():
                    raise ContractError("task objectives must be nonempty")
        for name in ("budget", "p0_control", "scorer", "acceptance_criteria"):
            _record(data[name], name)
        if set(scope) & {"Q7.1", "Q7.2"} and (data["budget"] != EXPLORATION_BUDGET
                or any(type(value) is not int for value in data["budget"].values())):
            raise ContractError("exploration controller requires exact matched opportunity budget")
        if set(scope) & set(EXTENDED_EXPLORATION_BUDGET) and (data["budget"] != EXTENDED_EXPLORATION_BUDGET
                or any(type(value) is not int for row in data["budget"].values() for value in row.values())):
            raise ContractError("extended exploration controller requires exact matched opportunity budgets")
        if "Q5.4" in scope and (data["budget"] != {"model_calls":3, "execution_opportunities":1, "verification_calls":1}
                or any(type(value) is not int for value in data["budget"].values())):
            raise ContractError("diagnostic controller requires exact matched opportunity budget")
        if "Q2.7" in scope and any(type(data["budget"].get(key)) is not int or data["budget"][key] != 1
                for key in ("docker_attempts", "audit_calls", "model_calls")):
            raise ContractError("protocol budget must freeze one Docker, audit batch and model call per cell")
        if set(scope) & {"Q2.2", "Q6.4", "Q2.7"}:
            from research_loop.modular.p0_panel import fixed_control_design
            expected_grid = fixed_control_design(data["baseline_digest"], _record(data["p0_control"], "P0 control").content_hash)
            if any(value.get("p0_fixed_control") != expected_grid.data() for value in data["evidence_by_task"].values()):
                raise ContractError("semantic material must bind the controller's frozen P0 control")
        if (not isinstance(data["baseline_digest"], str) or len(data["baseline_digest"]) != 64
                or any(char not in "0123456789abcdef" for char in data["baseline_digest"])):
            raise ContractError("baseline digest must be frozen")
        if not isinstance(data["packages_by_arm"], Mapping) or not data["packages_by_arm"]:
            raise ContractError("controller needs actual packages for every arm")
        for arm, package in data["packages_by_arm"].items():
            if not isinstance(arm, str) or len(arm) != 64:
                raise ContractError("package map uses runtime-arm digests")
            CandidatePackage(_record(package, "candidate package"))
        if (not isinstance(data["replicates"], list) or not data["replicates"]
                or len(set(data["replicates"])) != len(data["replicates"])):
            raise ContractError("replicates must be frozen and unique")
        if (data["model"] != "gpt-5.6-luna" or data["effort"] != "low"
                or type(data["max_calls"]) is not int or data["max_calls"] < 1
                or type(data["max_tokens"]) is not int or data["max_tokens"] < 1):
            raise ContractError("production controller requires frozen Luna/low budgets")
        mode = data.get("execution_mode", "mechanism_pilot")
        if mode not in {"mechanism_pilot", "linked_benchmark_solve"} or (mode == "linked_benchmark_solve" and set(scope) - {"Q1.5", "Q3.1", "Q4.3", "Q8.2", "Q8.3"}):
            raise ContractError("controller linked mode has an unsupported scope")
        expected_slots = {slot for coverage in scope for slot in DRIVERS[coverage].slots}
        if mode == "linked_benchmark_solve": expected_slots |= {"analysis_program", "final_answer"}
        if not isinstance(data["schemas"], Mapping) or set(data["schemas"]) != expected_slots:
            raise ContractError("controller requires exact production-driver response schemas")

    @classmethod
    def from_path(cls, path: Path, expected_sha256: str) -> "FrozenTrainControllerConfig":
        raw = Path(path).read_bytes()
        if not isinstance(expected_sha256, str) or hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise ContractError("frozen controller config hash mismatch")
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise ContractError("controller config is not JSON") from exc
        if not isinstance(data, Mapping) or raw.decode("utf-8") != canonical(data):
            raise ContractError("controller config must be canonical frozen JSON")
        return cls(_record(data, "controller config"))

    def data(self) -> dict[str, Any]: return self.record.data()


@dataclass(frozen=True)
class TrainPanelRun:
    compiled: CompiledTrainPanel
    packets: tuple[Any, ...]
    runtimes: tuple[RuntimeReceipt, ...]
    verdict: PanelVerdict
    receipt: FrozenRecord
    linked_results: tuple[LinkedBenchmarkCellResult, ...] = ()


def _driver_plan(scope_ids: Sequence[str], *, baseline_digest: str, p0_control: FrozenRecord,
                 item_count: int, replicates: Sequence[str], linked: bool = False) -> tuple[int, int]:
    """Return frozen complete-cell and model-call obligations before export."""
    grids = obligation_grids(scope_ids, baseline_digest=baseline_digest, p0_control=p0_control)
    cells_per_task = sum(len(registry().get(coverage).variants) * len(executable_arms(grids[coverage]))
                         for coverage in scope_ids)
    def variant_call_count(coverage, variant):
        driver = DRIVERS[coverage]
        schedule = getattr(driver, "slots_for_variant", None)
        slots = schedule(variant) if callable(schedule) else driver.slots
        if not isinstance(slots, tuple) or not slots or any(slot not in driver.slots for slot in slots):
            raise ContractError("driver variant schedule must be a nonempty subset of frozen slots")
        return len(slots) + (2 if linked else 0)
    calls_per_task = sum(len(executable_arms(grids[coverage])) * variant_call_count(coverage, variant)
                         for coverage in scope_ids for variant in registry()[coverage].variants)
    return item_count * cells_per_task * len(replicates), item_count * calls_per_task * len(replicates)


def run_train_panel(config: FrozenTrainControllerConfig, *, custody: CustodyStore | None,
                        snapshot_root: Path, export_root: Path, run_root: Path,
                        model: CodexModelPort, audit_verifier: AuditVerifier,
                        history_admission_port: AdmissionPort | None = None,
                        audit_receipt_port: AuditReceiptPort | None = None,
                        shadow_execution_port: ShadowExecutionPort | None = None,
                        feasibility_authority: FeasibilityAuthorityPort | None = None,
                        exploration_authority: ExplorationAuthorityPort | None = None,
                        diagnostic_authority: DiagnosticAuthority | None = None,
                        q55_authority: Q55Authority | None = None,
                        q55_authority_keys: Mapping[str, bytes] | None = None,
                        q55_provider=None,
                        retrieval_provider=None,
                        retrieval_admission_port=None,
                        retrieval_stage_authority=None,
                        retrieval_final_authority=None,
                        protocol_audit_port: ProtocolAuditPort | None = None,
                        protocol_replay_authority: ProtocolReplayAuthority | None = None,
                        prospective_exporter: PrimaryProspectiveTrainExporter | None = None) -> TrainPanelRun:
    """Export and execute every cell selected by closed production drivers."""
    legacy_export = isinstance(custody, CustodyStore) and prospective_exporter is None
    prospective_export = custody is None and type(prospective_exporter) is PrimaryProspectiveTrainExporter
    if not isinstance(config, FrozenTrainControllerConfig) or not (legacy_export or prospective_export):
        raise ContractError("trusted typed controller inputs required")
    if not isinstance(model, CodexModelPort) or not isinstance(audit_verifier, AuditVerifier):
        raise ContractError("controller requires the real model port and trusted audit verifier")
    data = config.data()
    extended_exploration = bool(set(data["scope_ids"]) & set(EXTENDED_EXPLORATION_BUDGET))
    exploration = extended_exploration or bool(set(data["scope_ids"]) & {"Q7.1", "Q7.2"})
    diagnostic = "Q5.4" in data["scope_ids"]
    q55 = "Q5.5" in data["scope_ids"]
    if q55 and (not callable(getattr(q55_authority, "verify_closure", None)) or not isinstance(q55_authority_keys, Mapping) or not callable(getattr(q55_provider, "search", None))):
        raise ContractError("Q5.5 controller requires dual closure authority and keys before export")
    retrieval = bool(set(data["scope_ids"]) & {"Q8.1", "Q8.2", "Q8.3", "Q8.4", "Q8.5", "Q8.6"})
    retrieval_final = bool(set(data["scope_ids"]) & {"Q8.5", "Q8.6", "Q8.7"})
    if retrieval_final and not all(callable(getattr(retrieval_final_authority, name, None)) for name in ("qualify_origin", "freeze_version")):
        raise ContractError("final retrieval requires caller origin and version authority before export")
    retrieval_stage = bool(set(data["scope_ids"]) & {"Q8.1", "Q8.4"})
    if retrieval_stage and not all(callable(getattr(retrieval_stage_authority, name, None)) for name in ("verify_execution", "verify_provenance")):
        raise ContractError("retrieval stages require caller execution and provenance authority before export")
    if retrieval and (not callable(getattr(retrieval_provider, "search", None)) or not callable(retrieval_admission_port)):
        raise ContractError("retrieval controller requires caller-owned provider and source admission before export")
    if diagnostic and not callable(getattr(diagnostic_authority, "verify_diagnostic", None)):
        raise ContractError("diagnostic controller requires its caller-owned verification port before export")
    if exploration and not all(callable(getattr(exploration_authority, method, None))
                               for method in ("verify_preflight", "verify_observation")):
        raise ContractError("exploration controller requires its caller-owned verification ports before export")
    protocol = "Q2.7" in data["scope_ids"]
    if protocol and (not callable(protocol_audit_port) or not isinstance(protocol_replay_authority, ProtocolReplayAuthority)):
        raise ContractError("protocol controller requires trusted audit and replay authorities before export")
    feasibility = bool(set(data["scope_ids"]) & {"Q5.1", "Q5.2"})
    if feasibility and (not callable(getattr(feasibility_authority, "verify_stage", None))
            or ("Q5.2" in data["scope_ids"] and not callable(getattr(feasibility_authority, "verify_prediction_outcome", None)))):
        raise ContractError("feasibility controller requires its caller-owned verification ports before export")
    snapshot, exported, root, model_root = _checked_roots(snapshot_root, export_root, run_root, model.root)
    if prospective_export and (snapshot != Path(prospective_exporter.config["snapshot_root"]).resolve()
                               or exported != prospective_exporter.output_root):
        raise ContractError("prospective exporter roots differ from the frozen controller roots")
    policy = _reviewed_model_policy(model)
    if (model.model != data["model"] or model.effort != data["effort"]
            or model.max_calls != data["max_calls"] or model.max_tokens != data["max_tokens"]
            or model.schemas != data["schemas"]):
        raise ContractError("live model port differs from frozen controller configuration")
    if model.ledger.get("calls") or model.ledger.get("tokens") != 0 or model.ledger.get("usage_incomplete") is not False:
        raise ContractError("controller requires a fresh empty model ledger")
    expected_cells, expected_calls = _driver_plan(data["scope_ids"], baseline_digest=data["baseline_digest"],
        p0_control=_record(data["p0_control"], "p0 control"), item_count=len(data["item_ids"]), replicates=data["replicates"], linked=data.get("execution_mode") == "linked_benchmark_solve")
    if model.max_calls < expected_calls:
        raise ContractError("frozen model call capacity cannot cover complete panel")
    # The root and attempt receipt exist before export because export itself is
    # an irreversible materialization.  A subsequent rejection therefore has
    # an auditable blocked controller record rather than pretending no action.
    root.mkdir(parents=True, exist_ok=False)
    attempt = {"schema": "train-panel-controller-attempt-v1", "config_digest": config.record.content_hash,
               "scope": data["engineering_scope"], "scope_ids": data["scope_ids"], "expected_cells": expected_cells,
               "expected_model_calls": expected_calls, "status": "exporting", "model_policy_sha256": model.frozen_base_context.sha256,
               "model_context_binding_digest": digest(policy["binding"]), "model_root": str(model_root),
               "snapshot_root": str(snapshot), "export_root": str(exported), "packet_receipts": [], "runtime_trace_digests": []}
    _write(root / "controller-attempt.json", attempt)
    try:
        protocol_broker = DockerExecutionBroker([root]) if protocol else None
        packets = (prospective_exporter.export_controller_packets(data["item_ids"]) if prospective_export
                   else TrainPacketExporter(custody, snapshot, exported).export(data["item_ids"]))
        attempt.update({"status": "exported", "packet_receipts": [packet.receipt.data() for packet in packets]})
        _write(root / "controller-attempt.json", attempt)
        tasks = [packet.task for packet in packets]
        returned_ids = ({packet.receipt.data().get("export_token") for packet in packets} if prospective_export
                        else {f"{task.identity.benchmark}:{task.identity.task_id}" for task in tasks})
        if returned_ids != set(data["item_ids"]):
            raise ContractError("export did not return the frozen allowlist")
        packages = {arm: CandidatePackage(_record(value, "candidate package")) for arm, value in data["packages_by_arm"].items()}
        compiled = compile_train_panel(stage=data["stage"], scope_ids=tuple(data["scope_ids"]), tasks=tasks,
            evidence_by_task={key: _record(value, "evidence") for key, value in data["evidence_by_task"].items()},
            budget=_record(data["budget"], "budget"), baseline_digest=data["baseline_digest"],
            p0_control=_record(data["p0_control"], "p0 control"), packages_by_arm=packages,
            scorer=_record(data["scorer"], "scorer"), acceptance_criteria=_record(data["acceptance_criteria"], "criteria"),
            replicates=tuple(data["replicates"]))
        if protocol:
            _bind_protocol_custody_inputs(packets, compiled, exported)
        attempt.update({"status": "executing", "panel_digest": compiled.panel.digest,
                        "compiled_manifest": compiled.manifest.data(),
                        "cell_plan": [cell.data() for cell in compiled.panel.cells], "runtime_receipts": []})
        _write(root / "controller-attempt.json", attempt)
    except Exception as exc:
        attempt.update({"status": "blocked_before_execution", "error_type": type(exc).__name__})
        _write(root / "controller-attempt.json", attempt)
        raise
    runtimes = []
    linked_results = []
    try:
        feasibility_broker = DockerExecutionBroker([exported, root]) if feasibility else None
        exploration_broker = DockerExecutionBroker([exported, root]) if exploration else None
        diagnostic_broker = DockerExecutionBroker([exported, root]) if diagnostic else None
        q55_broker = DockerExecutionBroker([exported, root]) if q55 else None
        retrieval_stage_broker = DockerExecutionBroker([exported, root]) if "Q8.1" in data["scope_ids"] else None
        retrieval_final_broker = DockerExecutionBroker([exported, root]) if "Q8.7" in data["scope_ids"] else None
        packets_by_digest = {packet.task.content_hash: packet for packet in packets}
        def retrieval_stage_inputs(task, bundle):
            packet = packets_by_digest.get(task.content_hash)
            if packet is None or packet.task != task: raise ContractError("retrieval stage input must be exported train data")
            spec = bundle.data()["execution"]; raw = packet.csv_path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != spec["input_sha256"] or len(raw) != spec["input_byte_count"]:
                raise ContractError("retrieval stage input differs from custody-exported CSV")
            return {"public_csv": packet.csv_path}
        def diagnostic_inputs(task, bundle):
            packet = packets_by_digest.get(task.content_hash)
            if packet is None or packet.task != task:
                raise ContractError("diagnostic input is not an exported train task")
            rows = [row for item in bundle.data()["variants"].values() for row in item["diagnostics"]]
            names = {tuple(sorted(row["inputs"])) for row in rows}
            if len(names) != 1 or len(next(iter(names))) != 1:
                raise ContractError("diagnostic controller requires one shared exported CSV identity")
            name = next(iter(names))[0]
            content = packet.csv_path.read_bytes()
            expected = {"sha256":hashlib.sha256(content).hexdigest(), "byte_count":len(content)}
            if any(row["inputs"][name] != expected for row in rows):
                raise ContractError("diagnostic material differs from exported train CSV bytes")
            return {name:packet.csv_path}
        if diagnostic:
            for task in compiled.tasks.values():
                diagnostic_inputs(task, _record(data["evidence_by_task"][task.content_hash], "diagnostic material"))
        def q55_inputs(task, bundle):
            packet = packets_by_digest.get(task.content_hash)
            if packet is None or packet.task != task: raise ContractError("Q5.5 input is not an exported train task")
            rows = list(bundle.data()["items"].values()); names={tuple(sorted(row["inputs"])) for row in rows}
            if len(names)!=1 or len(next(iter(names)))!=1: raise ContractError("Q5.5 requires one shared exported CSV identity")
            name=next(iter(names))[0]; raw=packet.csv_path.read_bytes(); expected={"sha256":hashlib.sha256(raw).hexdigest(),"byte_count":len(raw)}
            if any(row["inputs"][name] != expected for row in rows): raise ContractError("Q5.5 material differs from exported train CSV bytes")
            return {name:packet.csv_path}
        if q55:
            for task in compiled.tasks.values(): q55_inputs(task, _record(data["evidence_by_task"][task.content_hash], "Q5.5 material"))
        def exploration_inputs(task, bundle):
            packet = packets_by_digest.get(task.content_hash)
            if packet is None or packet.task != task:
                raise ContractError("exploration input is not an exported train task")
            if extended_exploration:
                diagnostics = [job for variants in bundle.data()["materials"].values()
                               for item in variants.values() for job in item["jobs"]]
            else:
                diagnostics = [diagnostic for key in ("q71", "q72") for item in bundle.data()[key].values()
                               for diagnostic in item["diagnostics"]]
            names = {tuple(sorted(row["inputs"])) for row in diagnostics}
            if len(names) != 1 or len(next(iter(names))) != 1:
                raise ContractError("exploration controller requires one shared exported CSV identity")
            name = next(iter(names))[0]
            content = packet.csv_path.read_bytes()
            expected = {"sha256": hashlib.sha256(content).hexdigest(), "byte_count": len(content)}
            if any(row["inputs"][name] != expected for row in diagnostics):
                raise ContractError("exploration material differs from exported train CSV bytes")
            return {name: packet.csv_path}
        if exploration:
            # Validate every declared diagnostic before any panel model or
            # authority call; a later cell cannot introduce a foreign input.
            for task in compiled.tasks.values():
                exploration_inputs(task, _record(data["evidence_by_task"][task.content_hash], "exploration material"))
        def feasibility_inputs(task, bundle):
            packet = packets_by_digest.get(task.content_hash)
            if packet is None or packet.task != task:
                raise ContractError("feasibility input is not an exported train task")
            # The core adapters export exactly one CSV. Every declared input
            # must refer to that frozen train export; arbitrary source paths
            # and additional caller files are not accepted by this controller.
            rows = [row for key in ("q51", "q52") for row in bundle.data()[key].values()]
            names = {tuple(sorted(row["inputs"])) for row in rows}
            if len(names) != 1 or len(next(iter(names))) != 1:
                raise ContractError("feasibility controller requires one shared exported CSV identity")
            name = next(iter(names))[0]
            return {name: packet.csv_path}
        for cell in compiled.panel.cells:
            objective = _record(data["objective_by_task"][cell.task_digest], "task objective") if "objective_by_task" in data else _record({"panel_digest": compiled.panel.digest}, "objective")
            if data.get("execution_mode") == "linked_benchmark_solve":
                packet = next(packet for packet in packets if packet.task.content_hash == cell.task_digest)
                result = run_benchmark_cell(cell=cell, task=compiled.tasks[cell.task_digest], scenario=compiled.scenarios[cell.key],
                    package=compiled.packages[cell.runtime_arm.content_hash], objective=objective,
                    mechanism_sidecar=root / "cells" / FrozenRecord.from_dict(cell.data()).content_hash / "mechanism",
                    solver_sidecar=root / "cells" / FrozenRecord.from_dict(cell.data()).content_hash / "solver",
                    public_inputs={"public_csv": packet.csv_path}, image="research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349",
                    broker=DockerExecutionBroker([exported, root]), model=model, audit_verifier=audit_verifier,
                    retrieval_provider=retrieval_provider, retrieval_admission_port=retrieval_admission_port)
                verification = verify_linked_benchmark_cell(result, task=compiled.tasks[cell.task_digest],
                    scenario=compiled.scenarios[cell.key], package=compiled.packages[cell.runtime_arm.content_hash])
                if verification.data().get("engineering_verified") is not True:
                    raise ContractError("linked cell verification did not establish engineering provenance")
                linked_results.append(result); runtimes.append(result.mechanism.runtime)
                attempt.setdefault("linked_receipts", []).append(result.receipt.data())
                attempt.setdefault("linked_verifications", []).append(verification.data())
                attempt["runtime_receipts"].append(PanelReceiptVerifier._runtime_data(result.mechanism.runtime))
                attempt["runtime_trace_digests"].append(result.mechanism.runtime.trace_digest)
                _write(root / "controller-attempt.json", attempt); continue
            result = run_train_cell(cell, task=compiled.tasks[cell.task_digest], scenario=compiled.scenarios[cell.key],
                package=compiled.packages[cell.runtime_arm.content_hash], objective=objective,
                sidecar=root / "cells" / FrozenRecord.from_dict(cell.data()).content_hash,
                model=model, audit_verifier=audit_verifier, scorer=None, history_admission_port=history_admission_port,
                audit_receipt_port=audit_receipt_port, shadow_execution_port=shadow_execution_port,
                p0_control=compiled.control, feasibility_broker=feasibility_broker,
                feasibility_input_resolver=feasibility_inputs if feasibility else None,
                feasibility_authority=feasibility_authority, protocol_broker=protocol_broker,
                exploration_broker=exploration_broker,
                exploration_input_resolver=exploration_inputs if exploration else None,
                exploration_authority=exploration_authority,
                diagnostic_broker=diagnostic_broker,
                diagnostic_input_resolver=diagnostic_inputs if diagnostic else None,
                diagnostic_authority=diagnostic_authority,
                q55_broker=q55_broker, q55_input_resolver=q55_inputs if q55 else None,
                q55_authority=q55_authority, q55_authority_keys=q55_authority_keys, q55_provider=q55_provider,
                retrieval_provider=retrieval_provider,
                retrieval_admission_port=retrieval_admission_port,
                retrieval_final_authority=retrieval_final_authority,
                retrieval_final_broker=retrieval_final_broker,
                retrieval_final_input_resolver=retrieval_stage_inputs if retrieval_final else None,
                retrieval_stage_authority=retrieval_stage_authority,
                retrieval_stage_broker=retrieval_stage_broker,
                retrieval_stage_input_resolver=retrieval_stage_inputs if retrieval_stage else None,
                protocol_audit_port=protocol_audit_port, protocol_replay_authority=protocol_replay_authority)
            runtimes.append(result.runtime)
            attempt.setdefault("runtime_call_plans", []).append(result.call_plan.data())
            attempt["runtime_receipts"].append(PanelReceiptVerifier._runtime_data(result.runtime))
            attempt["runtime_trace_digests"].append(result.runtime.trace_digest)
            _write(root / "controller-attempt.json", attempt)
        post_verifier = protocol_post_runtime_verifier(compiled, protocol_replay_authority) if protocol else None
        verdict = PanelReceiptVerifier(post_runtime_verifier=post_verifier).verify(compiled.panel, tuple(runtimes))
    except Exception as exc:
        attempt.update({"status": "execution_interrupted", "error_type": type(exc).__name__})
        _write(root / "controller-attempt.json", attempt)
        raise
    if verdict.decision not in {"engineering_verified", "engineering_incomplete"} or verdict.scientific_verified:
        raise ContractError("production controller cannot claim scientific measurement")
    linked_complete = (data.get("execution_mode") != "linked_benchmark_solve"
                       or (len(linked_results) == len(compiled.panel.cells)
                           and all(result.status == "linked_succeeded" for result in linked_results)))
    execution_complete = verdict.failures == verdict.unscored == verdict.blocked == 0 and linked_complete
    receipt = FrozenRecord.from_dict({"schema": "train-panel-controller-receipt-v1", "config_digest": config.record.content_hash,
        "panel_digest": compiled.panel.digest, "packet_receipts": [packet.receipt.data() for packet in packets],
        "runtime_trace_digests": [runtime.trace_digest for runtime in runtimes], "verdict": verdict.__dict__,
        "linked_receipt_digests": [result.receipt.content_hash for result in linked_results],
        "linked_statuses": [result.status for result in linked_results],
        "execution_status": "engineering_complete" if execution_complete else "execution_incomplete",
        "scientific_status": "not_measured", "scope": data["engineering_scope"], "scope_ids": data["scope_ids"],
        "model_policy_sha256": model.frozen_base_context.sha256,
        "model_context_binding_digest": digest(policy["binding"]),
        "model_ledger_config_digest": digest(model.ledger["config"])})
    (root / "controller-receipt.json").write_text(receipt.encoded, encoding="utf-8")
    attempt.update({"status": receipt.data()["execution_status"], "packet_receipts": [packet.receipt.data() for packet in packets],
                    "runtime_trace_digests": [runtime.trace_digest for runtime in runtimes],
                    "linked_statuses": [result.status for result in linked_results]})
    _write(root / "controller-attempt.json", attempt)
    return TrainPanelRun(compiled, tuple(packets), tuple(runtimes), verdict, receipt, tuple(linked_results))


def _bind_protocol_custody_inputs(packets, compiled, exported: Path) -> None:
    """Bind the one complete named input set to actual custody-export bytes."""
    for packet in packets:
        path = Path(packet.csv_path)
        _no_links(path)
        if not path.is_file() or exported not in path.resolve().parents:
            raise ContractError("protocol custody CSV path is outside the actual export")
        raw = path.read_bytes()
        metadata = packet.receipt.data()
        spec = next(compiled.scenarios[cell.key].data()["controller_input"]["bundle"]["execution"]
                    for cell in compiled.panel.cells if cell.coverage_id == "Q2.7" and cell.task_digest == packet.task.content_hash)
        if (metadata.get("identity") != packet.task.identity.data()
                or metadata.get("packet_hash") != packet.task.content_hash
                or metadata.get("csv_sha256") != hashlib.sha256(raw).hexdigest()
                or spec["csv_sha256"] != metadata["csv_sha256"]
                or spec["csv_byte_count"] != len(raw) or bytes.fromhex(spec["csv_bytes_hex"]) != raw):
            raise ContractError("protocol custody CSV differs from frozen literal input set")


def protocol_post_runtime_verifier(compiled: CompiledTrainPanel, authority: ProtocolReplayAuthority):
    """Configured read-only verifier of source, immutable sidecars and fault material.

    The authority authenticates host provenance; it does not establish science.
    """
    if not isinstance(compiled, CompiledTrainPanel) or not isinstance(authority, ProtocolReplayAuthority):
        raise ContractError("typed compiled panel and replay authority required")
    def verify(runtime, cell, panel):
        if panel.digest != compiled.panel.digest or cell not in compiled.panel.cells:
            raise ContractError("post-runtime verifier received a foreign panel cell")
        sidecar = runtime.trace_path.parent
        post_path = sidecar / "protocol-post-runtime.json"
        plan_path = sidecar / "call-plan.json"
        _no_links(post_path); _no_links(plan_path)
        post = FrozenRecord(post_path.read_text(encoding="utf-8").strip()).data()
        plan = FrozenRecord(plan_path.read_text(encoding="utf-8").strip()).data()
        required = {"schema", "status", "reason", "receipt_path", "receipt_digest", "source_trace_digest",
                    "source_output_digest", "cell_key", "scenario_digest"}
        if (set(post) != required or post["schema"] != "q27-post-runtime-check-v1"
                or post["status"] != "refused" or post["reason"] is not None
                or post["receipt_path"] != "q27-replay/receipt.json"
                or post["source_trace_digest"] != runtime.trace_digest or post["source_output_digest"] != runtime.output_digest
                or post["cell_key"] != list(cell.key) or post["scenario_digest"] != cell.scenario_digest
                or plan.get("protocol_replay") != post):
            raise ContractError("post-runtime immutable sidecar binding mismatch")
        receipt_path = sidecar / post["receipt_path"]
        _no_links(receipt_path)
        receipt = FrozenRecord(receipt_path.read_text(encoding="utf-8").strip())
        if receipt.content_hash != post["receipt_digest"]:
            raise ContractError("post-runtime actual replay receipt digest mismatch")
        return verify_protocol_replay_receipt(receipt, cell=cell, scenario=compiled.scenarios[cell.key],
            source_trace_path=runtime.trace_path, replay_authority=authority,
            expected_p0_control_digest=compiled.control.content_hash)
    return verify


# Stable compatibility entry point for pre-existing frozen Q3.1 configurations.
run_q31_train_panel = run_train_panel


def _write(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(canonical(dict(value)), encoding="utf-8")
    os.replace(temporary, path)


def _label_ancestor(path: Path) -> bool:
    return any((ancestor / "data" / "labels").exists() or (ancestor.name == "labels" and ancestor.parent.name == "data")
               for ancestor in (path, *path.parents))


def _checked_roots(snapshot_root: Path, export_root: Path, run_root: Path, model_root: Path) -> tuple[Path, Path, Path, Path]:
    snapshot = Path(snapshot_root).resolve(strict=True)
    roots = tuple(Path(path).resolve() for path in (export_root, run_root, model_root))
    if any(_label_ancestor(path) for path in roots):
        raise ContractError("export, run, and model roots must be outside label-containing ancestors")
    for left in roots:
        for right in (*roots, snapshot):
            if left is right:
                continue
            if left == right or left in right.parents or right in left.parents:
                raise ContractError("snapshot, export, run, and model roots must be pairwise separate")
    return snapshot, roots[0], roots[1], roots[2]


def _reviewed_model_policy(model: CodexModelPort) -> Mapping[str, Any]:
    if model.mock_context or model.frozen_base_context is None or model.policy_data is None:
        raise ContractError("controller requires reviewed frozen model context material")
    policy = model.frozen_base_context.data()
    if policy.get("status") != "REVIEWED" or policy != model.policy_data:
        raise ContractError("controller model context policy drifted or is unreviewed")
    return policy


def _keys(entries: Sequence[str]) -> dict[str, bytes]:
    values = {}
    for entry in entries:
        if "=" not in entry: raise ContractError("audit key needs AUTHORITY=absolute-path")
        authority, source = entry.split("=", 1)
        path = Path(source)
        if not path.is_absolute() or not path.is_file(): raise ContractError("audit key must be an absolute regular file")
        raw = path.read_text(encoding="utf-8").strip()
        try: key = bytes.fromhex(raw)
        except ValueError as exc: raise ContractError("audit key must be hex") from exc
        if authority in values: raise ContractError("duplicate audit authority")
        values[authority] = key
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True); parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--custody-state", type=Path, required=True); parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--export-root", type=Path, required=True); parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True); parser.add_argument("--codex-executable", type=Path, required=True)
    parser.add_argument("--reviewed-policy", type=Path, required=True); parser.add_argument("--reviewed-policy-sha256", required=True)
    parser.add_argument("--audit-key", action="append", default=[])
    args = parser.parse_args()
    config = FrozenTrainControllerConfig.from_path(args.config, args.config_sha256)
    policy = FrozenBaseContextPolicy(args.reviewed_policy, args.reviewed_policy_sha256)
    policy.data()  # fail closed before the port or any train export
    data = config.data()
    port = CodexModelPort(args.codex_executable, args.model_root, model=data["model"], effort=data["effort"],
        max_calls=data["max_calls"], max_tokens=data["max_tokens"], schema_by_slot=data["schemas"], frozen_base_context=policy)
    run_train_panel(config, custody=CustodyStore(args.custody_state), snapshot_root=args.snapshot_root,
        export_root=args.export_root, run_root=args.run_root, model=port, audit_verifier=AuditVerifier(_keys(args.audit_key)))


if __name__ == "__main__": main()
