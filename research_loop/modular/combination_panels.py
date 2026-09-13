"""Frozen execution surfaces for preregistered module combinations.

These panels are deliberately separate from Q1--Q8 coverage.  They preserve
the compatibility design's unavailable cells as design facts and can verify
trace-bound engineering journals, but do not manufacture scores, custody
leases, scientific effects, or promotion decisions.  A candidate-package record
in a request binds controller intent; it is not proof that a module effect was
actually applied by a model or benchmark executor.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Iterable, Mapping, Sequence

from research_loop.modular.benchmarks.catalog import REQUIRED_BENCHMARKS, SUPPORTED_BENCHMARKS
from research_loop.modular.combinations import Compatibility, default_compatibility, validate_design
from research_loop.modular.contracts import FrozenRecord, PublicTask, required_text
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_receipts import (
    PanelCell, PanelReceiptVerifier, RuntimeReceipt, ScientificScorerReceipt,
    ValidationAcceptance,
)
from research_loop.modular.panel_receipts import RESEARCH_MODULES, REQUIRED_TRIPLES
from research_loop.modular.runtime import AuditVerifier, RunSession
from research_loop.ontology import ContractError, canonical


def _digest(value: str, field: str) -> str:
    required_text(value, field)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ContractError(f"{field} must be a sha256 digest")
    return value


def _names(values: Iterable[str], field: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, Mapping)):
        raise ContractError(f"{field} must be a collection")
    result = tuple(values)
    if not result or len(result) != len(set(result)):
        raise ContractError(f"{field} must be nonempty and unique")
    for value in result:
        required_text(value, field)
    return result


def _design_arms(design: FrozenRecord) -> Mapping[str, FrozenRecord]:
    body = design.data()
    return MappingProxyType({row["id"]: FrozenRecord.from_dict(row["arm"])
                             for row in body["cells"] if row["status"] == "executable"})


def _unavailable(design: FrozenRecord) -> tuple[Mapping[str, str], ...]:
    return tuple(MappingProxyType({"id": row["id"], "reason": row["reason"]})
                 for row in design.data()["cells"] if row["status"] != "executable")


def _obligation_id(kind: str, modules: Sequence[str]) -> str:
    return f"{kind}:" + "+".join(modules)


@dataclass(frozen=True)
class CombinationPanel:
    """One complete, pre-outcome combination design over public tasks."""
    stage: str
    domain: str
    split_digest: str
    obligation_id: str
    estimand: str
    design: FrozenRecord
    package_bundle: FrozenRecord
    acceptance_criteria: FrozenRecord
    cells: tuple[PanelCell, ...]
    required_benchmarks: tuple[str, ...] = REQUIRED_BENCHMARKS

    def __post_init__(self) -> None:
        object.__setattr__(self, "cells", tuple(self.cells))
        object.__setattr__(self, "required_benchmarks", _names(self.required_benchmarks, "required benchmark"))
        required_text(self.stage, "stage")
        if self.domain != "train":
            # A validation panel needs a separately frozen train candidate and
            # a contrast receipt design.  Neither is available yet, so never
            # turn a train combination bundle into a validation surface.
            raise ContractError("combination validation panels are not implemented")
        _digest(self.split_digest, "split digest")
        required_text(self.obligation_id, "combination obligation id")
        if self.estimand not in {"interaction_on_scale", "joint_bundle", "leave_one_out_at_full"}:
            raise ContractError("unknown combination estimand")
        if not isinstance(self.design, FrozenRecord) or not isinstance(self.package_bundle, FrozenRecord) or not isinstance(self.acceptance_criteria, FrozenRecord):
            raise ContractError("combination panel needs frozen design, packages, and criteria")
        validate_design(self.design)
        design = self.design.data()
        if design["schema"] == "factorial-design-v1" and self.estimand != "interaction_on_scale":
            raise ContractError("factorial combination panel needs interaction estimand")
        if design["schema"] == "leave-one-out-v1" and self.estimand != "leave_one_out_at_full":
            raise ContractError("full/LOO panel needs leave-one-out estimand")
        factors = tuple(design.get("factors", ()))
        if design["schema"] == "factorial-design-v1":
            kind = "pair" if len(factors) == 2 else "triple" if len(factors) == 3 else None
            if kind is None or self.obligation_id != _obligation_id(kind, factors):
                raise ContractError("combination owner does not bind the frozen design factors")
        elif self.obligation_id != "full-loo":
            raise ContractError("leave-one-out owner must be full-loo")
        if not set(self.required_benchmarks) <= set(SUPPORTED_BENCHMARKS) or not set(REQUIRED_BENCHMARKS) <= set(self.required_benchmarks):
            raise ContractError("combination panel must include the core public benchmarks")
        arms = _design_arms(self.design)
        if not arms:
            raise ContractError("combination panel has no executable design cells")
        bundle = self.package_bundle.data()
        if set(bundle) != {"schema", "packages"} or bundle["schema"] != "combination-package-bundle-v1" or not isinstance(bundle["packages"], dict):
            raise ContractError("invalid combination package bundle")
        if set(bundle["packages"]) != {arm.content_hash for arm in arms.values()}:
            raise ContractError("combination package bundle must bind every executable arm")
        packages = {key: CandidatePackage(FrozenRecord.from_dict(value)) for key, value in bundle["packages"].items()}
        if not self.cells or any(not isinstance(cell, PanelCell) for cell in self.cells):
            raise ContractError("combination panel requires typed cells")
        if any(cell.coverage_id != self.obligation_id or cell.variant != "combination" for cell in self.cells):
            raise ContractError("combination cells must bind their typed owner")
        if any(cell.identity.domain != self.domain or cell.identity.split_id != self.split_digest for cell in self.cells):
            raise ContractError("combination cell domain or split differs from panel")
        if any(cell.arm_id not in arms or cell.runtime_arm != arms[cell.arm_id] for cell in self.cells):
            raise ContractError("combination cell arm is not a frozen executable design arm")
        if len({cell.key for cell in self.cells}) != len(self.cells):
            raise ContractError("duplicate combination panel cell")
        if {(cell.identity.benchmark) for cell in self.cells} != set(self.required_benchmarks):
            raise ContractError("combination panel must cover every required benchmark")
        for cell in self.cells:
            package = packages.get(cell.runtime_arm.content_hash)
            if package is None or package.digest != cell.package_digest:
                raise ContractError("combination cell package does not bind its exact arm")
        panel_identities = {canonical(cell.identity.data()) for cell in self.cells}
        training_identities = self._training_identities(panel_identities)
        for package in packages.values():
            manifest = TrainingManifest(FrozenRecord.from_dict(package.record.data()["training_manifest"]))
            package_identities = {canonical(identity.data()) for identity in manifest.identities()}
            if package_identities != training_identities:
                raise ContractError("combination train package must bind exactly this panel task set")
        grouped: dict[tuple[str, str, str, str], list[PanelCell]] = {}
        for cell in self.cells:
            grouped.setdefault((cell.identity.benchmark, cell.identity.task_id, cell.identity.group_id, cell.replicate), []).append(cell)
        for rows in grouped.values():
            if {row.arm_id for row in rows} != set(arms) or len(rows) != len(arms):
                raise ContractError("combination task lacks a complete feasible arm grid")
            if len({row.identity for row in rows}) != 1:
                raise ContractError("combination arms must share one exact task identity")
            if len({row.task_digest for row in rows}) != 1 or len({row.scenario_digest for row in rows}) != 1:
                raise ContractError("combination arms must share exact frozen task and scenario bindings")
        if len({cell.scorer_digest for cell in self.cells}) != 1:
            raise ContractError("combination panel must use one frozen scorer")

    def _training_identities(self, panel_identities):
        """Ordinary panels retain their exact target-manifest contract."""
        return panel_identities

    @property
    def digest(self) -> str:
        return FrozenRecord.from_dict({"stage": self.stage, "domain": self.domain, "split_digest": self.split_digest,
            "obligation_id": self.obligation_id, "estimand": self.estimand, "design_digest": self.design.content_hash,
            "package_bundle_digest": self.package_bundle.content_hash, "acceptance_criteria_digest": self.acceptance_criteria.content_hash,
            "required_benchmarks": list(self.required_benchmarks), "cells": [cell.data() for cell in sorted(self.cells, key=lambda cell: cell.key)]}).content_hash

    @property
    def interaction_status(self) -> str:
        body = self.design.data()
        return body.get("interaction_status", "not_identifiable" if _unavailable(self.design) else "not_measured")

    @property
    def structurally_unavailable(self) -> tuple[Mapping[str, str], ...]:
        return _unavailable(self.design)

    @property
    def candidate_digest(self) -> str:
        """The immutable multi-arm package bundle bound by this panel."""
        return self.package_bundle.content_hash

    @property
    def arm_schedule(self) -> tuple[str, ...]:
        return tuple(sorted({f"{self.obligation_id}:{cell.arm_id}" for cell in self.cells
                             if cell.arm_id in _design_arms(self.design)}))

    @property
    def validation_groups(self) -> tuple[str, ...]:
        return tuple(sorted({cell.identity.group_id for cell in self.cells}))


@dataclass(frozen=True)
class CombinationPanelVerdict:
    panel_digest: str
    engineering_verified: bool
    scientific_verified: bool
    acceptance_verified: bool
    decision: str
    observed_cells: int
    failures: int
    blocked: int
    interaction_status: str
    scientific_status: str
    limitation: str


class CombinationPanelVerifier:
    """Reuse the common trace verifier, but never turn engineering into science."""
    def __init__(self, *, scorer_verifier: Callable[[ScientificScorerReceipt, PanelCell, CombinationPanel], None] | None = None,
                 custody_keys: Mapping[str, bytes] | None = None, acceptance_keys: Mapping[str, bytes] | None = None,
                 calibration_keys: Mapping[str, bytes] | None = None):
        self._scorer_verifier = scorer_verifier
        self._custody_keys = dict(custody_keys or {})
        self._acceptance_keys = dict(acceptance_keys or {})
        self._calibration_keys = dict(calibration_keys or {})

    def verify(self, panel: CombinationPanel, runtime: Iterable[RuntimeReceipt], *,
               scorer_receipts: Iterable[ScientificScorerReceipt] = (),
               validation: ValidationAcceptance | None = None) -> CombinationPanelVerdict:
        if not isinstance(panel, CombinationPanel):
            raise ContractError("typed combination panel required")
        rows = tuple(runtime)
        expected = {cell.key: cell for cell in panel.cells}
        actual = {row.cell_key: row for row in rows}
        if len(actual) != len(rows) or set(actual) != set(expected):
            missing, unexpected = set(expected) - set(actual), set(actual) - set(expected)
            raise ContractError(f"combination runtime coverage mismatch: missing={len(missing)} unexpected={len(unexpected)}")
        if len({row.trace_path.resolve() for row in rows}) != len(rows) or len({row.trace_digest for row in rows}) != len(rows):
            raise ContractError("combination runtime receipts must retain distinct journals")
        common = PanelReceiptVerifier()
        for key, row in actual.items():
            common._verify_runtime(row, expected[key])
        scored = tuple(scorer_receipts)
        if len({row.cell_key for row in scored}) != len(scored) or not set(row.cell_key for row in scored) <= set(expected):
            raise ContractError("duplicate or unexpected combination scorer receipt")
        scientific = False
        if self._scorer_verifier is not None:
            successful = {key for key, row in actual.items() if row.status == "succeeded"}
            by_key = {row.cell_key: row for row in scored}
            if not successful or set(by_key) != successful:
                raise ContractError("independent combination scorer receipts must exactly cover successful cells")
            for key, receipt in by_key.items():
                self._scorer_verifier(receipt, expected[key], panel)
                raw = receipt.receipt.data()
                # The legacy fixture receipt is an unsigned body.  The adapted
                # scorer carries the same generic bindings inside a signed
                # envelope, which the injected verifier has already checked.
                body = raw["body"] if set(raw) == {"body", "mac"} and isinstance(raw["body"], dict) else raw
                if (body.get("schema") not in {"independent-scored-cell-v1", "combination-adapted-scored-cell-v1", "lineage-combination-scored-cell-v1"}
                        or body.get("runtime_trace_digest") != actual[key].trace_digest
                        or body.get("scorer_digest") != expected[key].scorer_digest):
                    raise ContractError("combination scorer receipt lacks typed runtime and scorer binding")
            scientific = True
        elif scored:
            raise ContractError("combination scorer receipts require an independent verifier")
        common = PanelReceiptVerifier(scorer_verifier=lambda *_: None, custody_keys=self._custody_keys,
                                     acceptance_keys=self._acceptance_keys, calibration_keys=self._calibration_keys)
        acceptance = None
        if validation is not None:
            raise ContractError("combination validation requires an independent frozen contrast receipt design")
        status = panel.interaction_status
        if status == "identifiable":
            status = "not_measured"
        # Per-cell scores do not estimate the frozen interaction or LOO
        # estimand. Until an independently verified contrast receipt exists,
        # these records remain engineering provenance only.
        return CombinationPanelVerdict(panel.digest, True, False, False, "engineering_verified",
                                       len(rows), sum(row.status == "failed" for row in rows),
                                       sum(row.status == "blocked" for row in rows), status, "not_measured",
                                       "no common scientific combination driver or contrast estimator is configured")


@dataclass(frozen=True)
class CompiledCombinationCatalogue:
    panels: Mapping[str, CombinationPanel]
    tasks: Mapping[str, PublicTask]
    scenarios: Mapping[tuple[str, ...], FrozenRecord]
    packages: Mapping[str, CandidatePackage]
    manifest: FrozenRecord


def compile_combination_catalogue(*, stage: str, tasks: Sequence[PublicTask], baseline_digest: str,
                                  packages_by_arm: Mapping[str, CandidatePackage], scorer: FrozenRecord,
                                  acceptance_criteria: FrozenRecord, replicates: Sequence[str] = ("r1",),
                                  required_benchmarks: tuple[str, ...] = REQUIRED_BENCHMARKS) -> CompiledCombinationCatalogue:
    """Freeze all C2/C3/C4 designs before any runtime outcome exists."""
    compatibility = default_compatibility(baseline_digest)
    designs: dict[str, tuple[str, FrozenRecord, str]] = {}
    for pair in combinations(RESEARCH_MODULES, 2):
        designs[_obligation_id("pair", pair)] = ("interaction_on_scale", compatibility.conditional_factorial(pair), "pair")
    for triple in REQUIRED_TRIPLES:
        designs[_obligation_id("triple", triple)] = ("interaction_on_scale", compatibility.conditional_factorial(triple), "triple")
    full = compatibility.leave_one_out(RESEARCH_MODULES)
    designs["full-loo"] = ("leave_one_out_at_full", full, "full_loo")
    task_map = _validate_tasks(tasks, required_benchmarks)
    if not isinstance(scorer, FrozenRecord) or not isinstance(acceptance_criteria, FrozenRecord):
        raise ContractError("combination compiler needs frozen scorer and criteria")
    if isinstance(replicates, (str, bytes)) or not replicates or len(set(replicates)) != len(replicates):
        raise ContractError("combination replicates must be nonempty and unique")
    panels: dict[str, CombinationPanel] = {}
    for obligation, (estimand, design, _kind) in designs.items():
        arms = _design_arms(design)
        if not set(arm.content_hash for arm in arms.values()) <= set(packages_by_arm):
            raise ContractError("actual package missing for a combination arm")
        bundle = FrozenRecord.from_dict({"schema": "combination-package-bundle-v1",
            "packages": {arm.content_hash: packages_by_arm[arm.content_hash].record.data() for arm in arms.values()}})
        cells = []
        for task in task_map.values():
            for replicate in replicates:
                scenario = FrozenRecord.from_dict({"schema": "combination-public-scenario-v1", "obligation_id": obligation,
                    "design_digest": design.content_hash, "task_digest": task.content_hash, "replicate": replicate,
                    "status": "predeclared"})
                for arm_id, arm in arms.items():
                    package = packages_by_arm[arm.content_hash]
                    cells.append(PanelCell(obligation, task.identity, replicate, "combination", arm_id, arm,
                                           task.content_hash, scenario.content_hash, package.digest, scorer.content_hash))
        panels[obligation] = CombinationPanel(stage, "train", next(iter(task_map.values())).identity.split_id,
                                               obligation, estimand, design, bundle, acceptance_criteria,
                                               tuple(cells), required_benchmarks)
    manifest = FrozenRecord.from_dict({"schema": "combination-catalogue-v1", "stage": stage,
        "baseline_digest": baseline_digest, "panel_digests": {key: panel.digest for key, panel in sorted(panels.items())},
        "obligation_count": len(panels), "pair_count": 36, "triple_count": 5, "full_loo_count": 1,
        "status": "planned_only", "scientific_status": "not_measured"})
    scenarios = {}
    for panel in panels.values():
        for cell in panel.cells:
            scenarios[cell.key] = FrozenRecord.from_dict({"schema": "combination-public-scenario-v1",
                "obligation_id": panel.obligation_id, "design_digest": panel.design.content_hash,
                "task_digest": cell.task_digest, "replicate": cell.replicate, "status": "predeclared"})
    return CompiledCombinationCatalogue(MappingProxyType(panels), task_map, MappingProxyType(scenarios),
                                        MappingProxyType(dict(packages_by_arm)), manifest)


def run_combination_cell(panel: CombinationPanel, cell: PanelCell, *, task: PublicTask,
                         scenario: FrozenRecord, package: CandidatePackage, objective: FrozenRecord,
                         sidecar: Path, model: Callable[[FrozenRecord], FrozenRecord],
                         audit_verifier: AuditVerifier) -> RuntimeReceipt:
    """Minimal production journal for one frozen train combination cell."""
    if not isinstance(panel, CombinationPanel) or cell not in panel.cells:
        raise ContractError("cell does not belong to the typed combination panel")
    if (not isinstance(task, PublicTask) or task.identity != cell.identity or task.content_hash != cell.task_digest
            or not isinstance(scenario, FrozenRecord) or scenario.content_hash != cell.scenario_digest
            or not isinstance(package, CandidatePackage) or package.digest != cell.package_digest):
        raise ContractError("combination runner binding mismatch")
    body = scenario.data()
    if body.get("obligation_id") != panel.obligation_id or body.get("design_digest") != panel.design.content_hash or body.get("task_digest") != task.content_hash:
        raise ContractError("combination scenario is not this frozen cell")
    session = RunSession(task, package_digest=package.digest, arm=cell.runtime_arm, objective=objective,
                         slots=("combination",), execution_limit=0, sidecar=sidecar,
                         verifier=audit_verifier, required_audit=("measurement",))
    binding = {"experiment_id": cell.coverage_id, "variant": cell.variant, "replicate": cell.replicate,
               "arm_id": cell.arm_id, "scenario_digest": scenario.content_hash}
    try:
        candidate = session.invoke("combination", model, instruction=(
            "Return a bounded train-only combination candidate; unknown is allowed. "
            "Copy module_context.required_objective_digest verbatim into objective_digest. "
            "The package is supplied as context; no module effect has been established."),
            module_context=FrozenRecord.from_dict({"panel_cell": binding, "combination_scenario": body,
                                                    "required_objective_digest": session.objective.content_hash,
                                                    "candidate_package": package.record.data(),
                                                    "package_application_status": "controller_binding_only_not_module_effect"}))
    except Exception as exc:
        if not session._terminal:
            session.controller_failure(driver_id=cell.coverage_id, error_type=type(exc).__name__, panel_cell=binding)
        trace = sidecar / "trace.jsonl"
        lines = trace.read_text(encoding="utf-8").splitlines()
        return RuntimeReceipt(cell.key, "failed", trace, FrozenRecord(lines[-1]).content_hash, None,
                              f"{type(exc).__name__}: model_port_rejected")
    terminal = session.finish(candidate)
    trace = sidecar / "trace.jsonl"
    lines = trace.read_text(encoding="utf-8").splitlines()
    # Keep this exact common receipt shape so PanelReceiptVerifier and the
    # combination verifier reconstruct the same output commitment.
    output = FrozenRecord.from_dict({"responses": [candidate.data()], "terminal": terminal.data()}).content_hash
    return RuntimeReceipt(cell.key, "blocked" if terminal.data()["decision"] == "blocked" else "succeeded",
                          trace, FrozenRecord(lines[-1]).content_hash, output,
                          "terminal decision blocked" if terminal.data()["decision"] == "blocked" else None)


def _validate_tasks(tasks: Sequence[PublicTask], required_benchmarks: tuple[str, ...]) -> Mapping[str, PublicTask]:
    if not tasks or any(not isinstance(task, PublicTask) for task in tasks):
        raise ContractError("combination compiler needs public tasks")
    for task in tasks:
        task.identity.require_train()
    if len({task.identity for task in tasks}) != len(tasks):
        raise ContractError("combination compiler received duplicate tasks")
    if {task.identity.benchmark for task in tasks} != set(required_benchmarks):
        raise ContractError("combination tasks must cover exactly the required benchmarks")
    splits = {task.identity.split_id for task in tasks}
    if len(splits) != 1:
        raise ContractError("combination panel needs one frozen split")
    return MappingProxyType({task.content_hash: task for task in tasks})
