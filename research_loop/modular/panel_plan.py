"""Compile train-only research obligations into complete paired panels.

This controller consumes already prepared public tasks. It neither acquires data
nor grants custody, driver, scorer or scientific qualification.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from types import MappingProxyType
from typing import Mapping, Sequence

from research_loop.modular.benchmarks.catalog import REQUIRED_BENCHMARKS
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import FrozenRecord, PublicTask
from research_loop.modular.experiments import ControllerInputs, registry, scenario
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.p0_panel import fixed_control_design
from research_loop.modular.panel_receipts import (
    CombinationObligations, FrozenPanel, PanelCell, RESEARCH_MODULES, REQUIRED_TRIPLES,
)
from research_loop.ontology import ContractError


def obligation_grids(scope_ids: Sequence[str], *, baseline_digest: str,
                     p0_control: FrozenRecord) -> Mapping[str, FrozenRecord]:
    """Keep every legal arm regardless of any previously observed score."""
    specs = registry()
    if (isinstance(scope_ids, (str, bytes)) or not scope_ids
            or len(set(scope_ids)) != len(scope_ids) or set(scope_ids) - set(specs)):
        raise ContractError("panel scope needs unique registered obligations")
    if not isinstance(p0_control, FrozenRecord):
        raise ContractError("P0 control must be a frozen source and protocol record")
    compatibility = default_compatibility(baseline_digest)
    result = {}
    for name in scope_ids:
        modules = tuple(module for module in specs[name].modules if module != "P0")
        result[name] = (compatibility.conditional_factorial(modules) if modules
                        else fixed_control_design(baseline_digest, p0_control.content_hash))
    return MappingProxyType(result)


def executable_arms(grid: FrozenRecord) -> Mapping[str, FrozenRecord]:
    body = grid.data()
    if body["schema"] == "p0-fixed-control-grid-v1":
        return MappingProxyType({"p0-fixed": FrozenRecord.from_dict(body["runtime_arm"])})
    return MappingProxyType({row["id"]: FrozenRecord.from_dict(row["arm"])
                             for row in body["cells"] if row["status"] == "executable"})


@dataclass(frozen=True)
class CompiledTrainPanel:
    panel: FrozenPanel
    scenarios: Mapping[tuple[str, ...], FrozenRecord]
    tasks: Mapping[str, PublicTask]
    packages: Mapping[str, CandidatePackage]
    control: FrozenRecord
    manifest: FrozenRecord


def compile_train_panel(*, stage: str, scope_ids: Sequence[str], tasks: Sequence[PublicTask],
                        evidence_by_task: Mapping[str, FrozenRecord], budget: FrozenRecord,
                        baseline_digest: str, p0_control: FrozenRecord,
                        packages_by_arm: Mapping[str, CandidatePackage], scorer: FrozenRecord,
                        acceptance_criteria: FrozenRecord, replicates: Sequence[str] = ("r1",),
                        required_benchmarks: tuple[str, ...] = REQUIRED_BENCHMARKS) -> CompiledTrainPanel:
    """Freeze variants × compatible arms × identical tasks × replicates.

    Package keys are runtime-arm hashes, not display names. The derived bundle
    identity binds actual package records. Budget is a declaration to be checked
    by each executable driver; compiling it is not proof of matched compute.
    """
    if not tasks or any(not isinstance(task, PublicTask) for task in tasks):
        raise ContractError("compiler needs prepared public training tasks")
    for task in tasks:
        task.identity.require_train()
    if len({task.identity for task in tasks}) != len(tasks):
        raise ContractError("compiler received duplicate task identities")
    if {task.identity.benchmark for task in tasks} != set(required_benchmarks):
        raise ContractError("prepared tasks must cover exactly the required benchmarks")
    splits = {task.identity.split_id for task in tasks}
    if len(splits) != 1:
        raise ContractError("paired panel needs one frozen data split")
    if (isinstance(replicates, (str, bytes)) or not replicates or len(set(replicates)) != len(replicates)
            or any(not isinstance(x, str) or not x.strip() for x in replicates)):
        raise ContractError("replicate identifiers must be nonempty and unique")
    task_map = {task.content_hash: task for task in tasks}
    if set(evidence_by_task) != set(task_map) or any(not isinstance(x, FrozenRecord) for x in evidence_by_task.values()):
        raise ContractError("evidence records must bind exactly the prepared task hashes")
    if any(not isinstance(x, FrozenRecord) for x in (budget, scorer, acceptance_criteria)):
        raise ContractError("budget, scorer and acceptance criteria must be frozen records")
    grids = obligation_grids(scope_ids, baseline_digest=baseline_digest, p0_control=p0_control)
    arms = {arm.content_hash: arm for grid in grids.values() for arm in executable_arms(grid).values()}
    if set(packages_by_arm) != set(arms) or any(not isinstance(x, CandidatePackage) for x in packages_by_arm.values()):
        raise ContractError("exactly one actual candidate package per legal runtime arm is required")
    bundle = FrozenRecord.from_dict({"schema": "train-panel-package-bundle-v1",
        "baseline_digest": baseline_digest,
        "packages": {key: package.record.data() for key, package in sorted(packages_by_arm.items())}})
    cells, scenarios = [], {}
    specs = registry()
    for coverage in scope_ids:
        for task in sorted(tasks, key=lambda task: task.content_hash):
            inputs = ControllerInputs(FrozenRecord.from_dict(task.data()), evidence_by_task[task.content_hash], budget)
            for variant in specs[coverage].variants:
                material = scenario(specs[coverage], variant, inputs=inputs)
                for arm_id, arm in executable_arms(grids[coverage]).items():
                    package = packages_by_arm[arm.content_hash]
                    for replicate in replicates:
                        cell = PanelCell(coverage, task.identity, replicate, variant, arm_id, arm,
                            task.content_hash, material.content_hash, package.digest, scorer.content_hash)
                        cells.append(cell)
                        scenarios[cell.key] = material
    obligations = CombinationObligations(tuple(combinations(RESEARCH_MODULES, 2)), REQUIRED_TRIPLES,
                                         RESEARCH_MODULES, RESEARCH_MODULES)
    panel = FrozenPanel(stage, "train", next(iter(splits)), bundle.content_hash, tuple(scope_ids),
                        grids, acceptance_criteria, tuple(cells), obligations, required_benchmarks)
    manifest = FrozenRecord.from_dict({"schema": "compiled-train-panel-v1", "panel_digest": panel.digest,
        "package_bundle": bundle.data(), "p0_control": p0_control.data(), "scorer": scorer.data(),
        "budget": budget.data(), "scope_ids": list(scope_ids), "cell_count": len(cells),
        "scenario_digests": sorted({value.content_hash for value in scenarios.values()}),
        "status": "planned_only", "driver_qualification": "checked_separately_at_execution",
        "scientific_status": "not_measured", "combination_status": "routing_only"})
    return CompiledTrainPanel(panel, MappingProxyType(scenarios), MappingProxyType(task_map),
                              MappingProxyType(dict(packages_by_arm)), p0_control, manifest)
