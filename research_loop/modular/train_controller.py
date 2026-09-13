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
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.experiments import registry
from research_loop.modular.model_port import CodexModelPort, FrozenBaseContextPolicy
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.panel_plan import CompiledTrainPanel, compile_train_panel, executable_arms, obligation_grids
from research_loop.modular.panel_receipts import PanelReceiptVerifier, PanelVerdict, RuntimeReceipt
from research_loop.modular.panel_runner import DRIVERS, run_train_cell
from research_loop.modular.history_panel_drivers import AdmissionPort
from research_loop.modular.audit_panel_drivers import AuditReceiptPort, ShadowExecutionPort
from research_loop.modular.benchmark_cell import LinkedBenchmarkCellResult, run_benchmark_cell, verify_linked_benchmark_cell
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
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
        if set(scope) & {"Q2.2", "Q6.4"}:
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
        if mode not in {"mechanism_pilot", "linked_benchmark_solve"} or (mode == "linked_benchmark_solve" and set(scope) - {"Q1.5", "Q3.1", "Q4.3"}):
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
    calls_per_task = sum(len(registry().get(coverage).variants) * len(executable_arms(grids[coverage]))
                         * (len(DRIVERS[coverage].slots) + (2 if linked else 0)) for coverage in scope_ids)
    return item_count * cells_per_task * len(replicates), item_count * calls_per_task * len(replicates)


def run_train_panel(config: FrozenTrainControllerConfig, *, custody: CustodyStore,
                        snapshot_root: Path, export_root: Path, run_root: Path,
                        model: CodexModelPort, audit_verifier: AuditVerifier,
                        history_admission_port: AdmissionPort | None = None,
                        audit_receipt_port: AuditReceiptPort | None = None,
                        shadow_execution_port: ShadowExecutionPort | None = None) -> TrainPanelRun:
    """Export and execute every cell selected by closed production drivers."""
    if not isinstance(config, FrozenTrainControllerConfig) or not isinstance(custody, CustodyStore):
        raise ContractError("trusted typed controller inputs required")
    if not isinstance(model, CodexModelPort) or not isinstance(audit_verifier, AuditVerifier):
        raise ContractError("controller requires the real model port and trusted audit verifier")
    data = config.data()
    snapshot, exported, root, model_root = _checked_roots(snapshot_root, export_root, run_root, model.root)
    policy = _reviewed_model_policy(model)
    if (model.model != data["model"] or model.effort != data["effort"]
            or model.max_calls != data["max_calls"] or model.max_tokens != data["max_tokens"]):
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
        packets = TrainPacketExporter(custody, snapshot, exported).export(data["item_ids"])
        attempt.update({"status": "exported", "packet_receipts": [packet.receipt.data() for packet in packets]})
        _write(root / "controller-attempt.json", attempt)
        tasks = [packet.task for packet in packets]
        if {f"{task.identity.benchmark}:{task.identity.task_id}" for task in tasks} != set(data["item_ids"]):
            raise ContractError("export did not return the frozen allowlist")
        packages = {arm: CandidatePackage(_record(value, "candidate package")) for arm, value in data["packages_by_arm"].items()}
        compiled = compile_train_panel(stage=data["stage"], scope_ids=tuple(data["scope_ids"]), tasks=tasks,
            evidence_by_task={key: _record(value, "evidence") for key, value in data["evidence_by_task"].items()},
            budget=_record(data["budget"], "budget"), baseline_digest=data["baseline_digest"],
            p0_control=_record(data["p0_control"], "p0 control"), packages_by_arm=packages,
            scorer=_record(data["scorer"], "scorer"), acceptance_criteria=_record(data["acceptance_criteria"], "criteria"),
            replicates=tuple(data["replicates"]))
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
        for cell in compiled.panel.cells:
            objective = _record(data["objective_by_task"][cell.task_digest], "task objective") if "objective_by_task" in data else _record({"panel_digest": compiled.panel.digest}, "objective")
            if data.get("execution_mode") == "linked_benchmark_solve":
                packet = next(packet for packet in packets if packet.task.content_hash == cell.task_digest)
                result = run_benchmark_cell(cell=cell, task=compiled.tasks[cell.task_digest], scenario=compiled.scenarios[cell.key],
                    package=compiled.packages[cell.runtime_arm.content_hash], objective=objective,
                    mechanism_sidecar=root / "cells" / FrozenRecord.from_dict(cell.data()).content_hash / "mechanism",
                    solver_sidecar=root / "cells" / FrozenRecord.from_dict(cell.data()).content_hash / "solver",
                    public_inputs={"public_csv": packet.csv_path}, image="research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349",
                    broker=DockerExecutionBroker([exported, root]), model=model, audit_verifier=audit_verifier)
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
                p0_control=compiled.p0_control)
            runtimes.append(result.runtime)
            attempt["runtime_receipts"].append(PanelReceiptVerifier._runtime_data(result.runtime))
            attempt["runtime_trace_digests"].append(result.runtime.trace_digest)
            _write(root / "controller-attempt.json", attempt)
        verdict = PanelReceiptVerifier().verify(compiled.panel, tuple(runtimes))
    except Exception as exc:
        attempt.update({"status": "execution_interrupted", "error_type": type(exc).__name__})
        _write(root / "controller-attempt.json", attempt)
        raise
    if verdict.decision != "engineering_verified" or verdict.scientific_verified:
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
