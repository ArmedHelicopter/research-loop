"""Trusted, train-only Q3.1 panel controller.

This module deliberately owns orchestration but not custody qualification,
context review, scoring, or scientific state transitions.  Its input is a
canonical frozen record, and its only successful verdict is engineering-only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from evaluation.modular.custody import CustodyStore
from evaluation.modular.train_io import TrainPacketExporter
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.model_port import CodexModelPort, FrozenBaseContextPolicy
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.panel_plan import CompiledTrainPanel, compile_train_panel
from research_loop.modular.panel_receipts import PanelReceiptVerifier, PanelVerdict, RuntimeReceipt
from research_loop.modular.panel_runner import run_train_cell
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError, canonical


_SCHEMA = "q31-train-controller-v1"
_SCOPE = ("Q3.1",)


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
        if set(data) != required or data["schema"] != _SCHEMA:
            raise ContractError("unexpected train controller config schema")
        if data["engineering_scope"] != "train_only_q3_1_engineering" or data["scope_ids"] != list(_SCOPE):
            raise ContractError("controller is restricted to Q3.1 train engineering")
        if (not isinstance(data["stage"], str) or not data["stage"].strip() or not isinstance(data["item_ids"], list)
                or not data["item_ids"] or len(set(data["item_ids"])) != len(data["item_ids"])
                or any(not isinstance(item, str) or not item for item in data["item_ids"])):
            raise ContractError("controller needs an exact nonempty train allowlist")
        if not isinstance(data["evidence_by_task"], Mapping) or not data["evidence_by_task"]:
            raise ContractError("controller needs exact task evidence")
        for value in data["evidence_by_task"].values(): _record(value, "evidence")
        for name in ("budget", "p0_control", "scorer", "acceptance_criteria"):
            _record(data[name], name)
        if not isinstance(data["baseline_digest"], str) or len(data["baseline_digest"]) != 64:
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
            raise ContractError("Q3.1 controller requires frozen Luna/low budgets")
        if not isinstance(data["schemas"], Mapping) or set(data["schemas"]) != {"scenario", "final"}:
            raise ContractError("controller requires exact scenario and final response schemas")

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


def run_q31_train_panel(config: FrozenTrainControllerConfig, *, custody: CustodyStore,
                        snapshot_root: Path, export_root: Path, run_root: Path,
                        model: CodexModelPort, audit_verifier: AuditVerifier) -> TrainPanelRun:
    """Export exactly configured train data and execute every frozen Q3.1 cell."""
    if not isinstance(config, FrozenTrainControllerConfig) or not isinstance(custody, CustodyStore):
        raise ContractError("trusted typed controller inputs required")
    if not isinstance(model, CodexModelPort) or not isinstance(audit_verifier, AuditVerifier):
        raise ContractError("controller requires the real model port and trusted audit verifier")
    data = config.data()
    root = Path(run_root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    packets = TrainPacketExporter(custody, Path(snapshot_root), Path(export_root)).export(data["item_ids"])
    tasks = [packet.task for packet in packets]
    if {f"{task.identity.benchmark}:{task.identity.task_id}" for task in tasks} != set(data["item_ids"]):
        raise ContractError("export did not return the frozen allowlist")
    packages = {arm: CandidatePackage(_record(value, "candidate package")) for arm, value in data["packages_by_arm"].items()}
    compiled = compile_train_panel(stage=data["stage"], scope_ids=_SCOPE, tasks=tasks,
        evidence_by_task={key: _record(value, "evidence") for key, value in data["evidence_by_task"].items()},
        budget=_record(data["budget"], "budget"), baseline_digest=data["baseline_digest"],
        p0_control=_record(data["p0_control"], "p0 control"), packages_by_arm=packages,
        scorer=_record(data["scorer"], "scorer"), acceptance_criteria=_record(data["acceptance_criteria"], "criteria"),
        replicates=tuple(data["replicates"]))
    if (model.model != data["model"] or model.effort != data["effort"]
            or model.max_calls != data["max_calls"] or model.max_tokens != data["max_tokens"]):
        raise ContractError("live model port differs from frozen controller configuration")
    if model.max_calls < 2 * len(compiled.panel.cells):
        raise ContractError("frozen model call capacity cannot cover complete panel")
    runtimes = []
    for cell in compiled.panel.cells:
        result = run_train_cell(cell, task=compiled.tasks[cell.task_digest], scenario=compiled.scenarios[cell.key],
            package=compiled.packages[cell.runtime_arm.content_hash], objective=_record({"panel_digest": compiled.panel.digest}, "objective"),
            sidecar=root / "cells" / FrozenRecord.from_dict(cell.data()).content_hash,
            model=model, audit_verifier=audit_verifier, scorer=None)
        runtimes.append(result.runtime)
    verdict = PanelReceiptVerifier().verify(compiled.panel, tuple(runtimes))
    if verdict.decision != "engineering_verified" or verdict.scientific_verified:
        raise ContractError("Q3.1 controller cannot claim scientific measurement")
    receipt = FrozenRecord.from_dict({"schema": "q31-train-controller-receipt-v1", "config_digest": config.record.content_hash,
        "panel_digest": compiled.panel.digest, "packet_receipts": [packet.receipt.data() for packet in packets],
        "runtime_trace_digests": [runtime.trace_digest for runtime in runtimes], "verdict": verdict.__dict__,
        "scientific_status": "not_measured", "scope": "train_only_q3_1_engineering"})
    (root / "controller-receipt.json").write_text(receipt.encoded, encoding="utf-8")
    return TrainPanelRun(compiled, tuple(packets), tuple(runtimes), verdict, receipt)


def _keys(entries: Sequence[str]) -> dict[str, bytes]:
    values = {}
    for entry in entries:
        if "=" not in entry: raise ContractError("audit key needs AUTHORITY=absolute-path")
        authority, source = entry.split("=", 1)
        raw = Path(source).read_text(encoding="utf-8").strip()
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
    run_q31_train_panel(config, custody=CustodyStore(args.custody_state), snapshot_root=args.snapshot_root,
        export_root=args.export_root, run_root=args.run_root, model=port, audit_verifier=AuditVerifier(_keys(args.audit_key)))


if __name__ == "__main__": main()
