"""Legal module configurations and frozen factorial panels.

Standalone efficacy is deliberately absent from the compatibility contract.
All legal configurations remain research candidates, regardless of singleton score.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, product
from typing import Iterable

from .contracts import ContractError, FrozenRecord, digest, required_text


def _names(values: Iterable[str], field: str, *, nonempty: bool = False) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, dict)):
        raise ContractError(f"{field} must be a collection of names")
    items = tuple(values)
    for item in items:
        required_text(item, field)
    if len(items) != len(set(items)) or (nonempty and not items):
        raise ContractError(f"{field} must contain unique names")
    return items


@dataclass(frozen=True)
class ModuleSpec:
    id: str
    requires: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        required_text(self.id, "module id")
        for field in (self.requires, self.conflicts):
            if not isinstance(field, tuple):
                raise ContractError("module relationships must be unique immutable tuples")
            _names(field, "module relationship")
        if self.id in self.requires or self.id in self.conflicts:
            raise ContractError("module cannot require or conflict with itself")

    def data(self) -> dict:
        return {"id": self.id, "requires": list(self.requires), "conflicts": list(self.conflicts)}


class Compatibility:
    def __init__(self, specs: Iterable[ModuleSpec], *, baseline_digest: str):
        self.baseline_digest = required_text(baseline_digest, "baseline digest")
        items = tuple(specs)
        if not items or any(not isinstance(s, ModuleSpec) for s in items):
            raise ContractError("typed module specifications required")
        self._specs = {s.id: s for s in items}
        if len(self._specs) != len(items):
            raise ContractError("duplicate module ids")
        for spec in items:
            if not set(spec.requires + spec.conflicts) <= self._specs.keys():
                raise ContractError("unknown module relationship")
        for name in self.names:
            self._dependencies(name, ())

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def _dependencies(self, name: str, path: tuple[str, ...]) -> set[str]:
        if name in path:
            raise ContractError("cyclic module dependency")
        found = {name}
        for required in self._specs[name].requires:
            found.update(self._dependencies(required, path + (name,)))
        return found

    def manifest(self) -> FrozenRecord:
        return FrozenRecord.from_dict({
            "schema": "module-compatibility-v1", "baseline_digest": self.baseline_digest,
            "modules": [self._specs[name].data() for name in self.names],
        })

    def arm(self, enabled: Iterable[str]) -> FrozenRecord:
        items = _names(enabled, "activation")
        if not set(items) <= self._specs.keys():
            raise ContractError("unknown or duplicate activation")
        active = set(items)
        for name in active:
            missing = self._dependencies(name, ()) - active
            if missing:
                raise ContractError(f"{name} requires {','.join(sorted(missing))}")
            conflicts = active.intersection(self._specs[name].conflicts)
            if conflicts:
                raise ContractError(f"{name} conflicts with {','.join(sorted(conflicts))}")
        return FrozenRecord.from_dict({
            "schema": "module-arm-v1", "baseline_digest": self.baseline_digest,
            "compatibility_digest": self.manifest().content_hash, "enabled": sorted(active),
        })

    def factorial(self, factors: Iterable[str], *, background: Iterable[str] = ()) -> FrozenRecord:
        factor_names = _names(factors, "factor", nonempty=True)
        fixed = _names(background, "background")
        if not set(factor_names) <= self._specs.keys() or set(factor_names).intersection(fixed):
            raise ContractError("unknown factors or factors overlap fixed background")
        self.arm(fixed)
        cells = []
        for bits in product((0, 1), repeat=len(factor_names)):
            enabled = fixed + tuple(name for name, bit in zip(factor_names, bits) if bit)
            cell = {"id": "".join(map(str, bits)), "levels": list(bits)}
            try:
                arm = self.arm(enabled)
                cell.update(status="executable", arm=arm.data(), arm_digest=arm.content_hash)
            except ContractError as exc:
                cell.update(status="structurally_unavailable", reason=str(exc))
            cells.append(cell)
        identifiable = all(c["status"] == "executable" for c in cells)
        # Inclusion-exclusion contrast: (-1)^(k-number-of-enabled-factors).
        contrast = {c["id"]: (-1) ** (len(factor_names) - sum(c["levels"])) for c in cells}
        return FrozenRecord.from_dict({
            "schema": "factorial-design-v1", "compatibility_digest": self.manifest().content_hash,
            "compatibility": self.manifest().data(),
            "factors": list(factor_names), "background": sorted(fixed), "cells": cells,
            "interaction_status": "identifiable" if identifiable else "not_identifiable",
            "contrast": contrast if identifiable else None,
        })

    def all_pairs(self) -> tuple[FrozenRecord, ...]:
        return tuple(self.conditional_factorial(pair) for pair in combinations(self.names, 2))

    def conditional_factorial(self, factors: Iterable[str]) -> FrozenRecord:
        """Fix only external prerequisites; never silently switch a factor on."""
        names = _names(factors, "factor", nonempty=True)
        if not set(names) <= self._specs.keys():
            raise ContractError("unknown factor")
        fixed = set().union(*(self._dependencies(name, ()) for name in names)) - set(names)
        return self.factorial(names, background=sorted(fixed))

    def leave_one_out(self, full: Iterable[str]) -> FrozenRecord:
        items = tuple(sorted(_names(full, "full configuration", nonempty=True)))
        complete = self.arm(items)
        cells = [{"id": "full", "status": "executable", "arm": complete.data(),
                  "arm_digest": complete.content_hash}]
        for excluded in items:
            try:
                arm = self.arm(name for name in items if name != excluded)
                cells.append({"id": f"without-{excluded}", "status": "executable",
                              "arm": arm.data(), "arm_digest": arm.content_hash})
            except ContractError as exc:
                cells.append({"id": f"without-{excluded}", "status": "structurally_unavailable",
                              "reason": str(exc)})
        return FrozenRecord.from_dict({"schema": "leave-one-out-v1", "cells": cells,
                                       "compatibility": self.manifest().data(),
                                       "estimand": "conditional_at_full"})


def validate_design(design: FrozenRecord) -> None:
    """Rebuild a submitted design before accepting its cells or estimands."""
    body = design.data()
    try:
        manifest = body["compatibility"]
        if set(manifest) != {"schema", "baseline_digest", "modules"} or manifest["schema"] != "module-compatibility-v1":
            raise ContractError("invalid compatibility manifest")
        specs = []
        for row in manifest["modules"]:
            if set(row) != {"id", "requires", "conflicts"}:
                raise ContractError("invalid module manifest")
            specs.append(ModuleSpec(row["id"], tuple(row["requires"]), tuple(row["conflicts"])))
        compatibility = Compatibility(specs, baseline_digest=manifest["baseline_digest"])
        if body["schema"] == "factorial-design-v1":
            rebuilt = compatibility.factorial(body["factors"], background=body["background"])
        elif body["schema"] == "leave-one-out-v1":
            rebuilt = compatibility.leave_one_out(body["cells"][0]["arm"]["enabled"])
        else:
            raise ContractError("unrecognized experiment design")
        if rebuilt != design:
            raise ContractError("design cells, bindings, or contrast were modified")
    except (KeyError, TypeError, IndexError) as exc:
        raise ContractError("malformed experiment design") from exc


def freeze_panel(design: FrozenRecord, *, package_digests: dict[str, str],
                 task_groups: dict[str, list[str]], schedule_digest: str,
                 criteria: dict, target_arm: str | None = None) -> FrozenRecord:
    """Commit all arms at once; no result values are accepted here.

    Does not issue a validation lease or certify statistical/data qualification.
    Custody must independently authorize the frozen panel and task groups.
    """
    validate_design(design)
    body = design.data()
    cells = body.get("cells", [])
    legal = {cell["id"] for cell in cells if cell["status"] == "executable"}
    if not isinstance(package_digests, dict) or not legal or set(package_digests) != legal:
        raise ContractError("exactly one package digest per legal design cell required")
    if target_arm is not None and target_arm not in legal:
        raise ContractError("target must be a predeclared legal arm")
    for value in package_digests.values():
        required_text(value, "package digest")
    if not isinstance(task_groups, dict) or not task_groups:
        raise ContractError("nonempty unique task groups required for every benchmark")
    for benchmark, groups in task_groups.items():
        required_text(benchmark, "benchmark")
        _names(groups, "source group", nonempty=True)
    if not isinstance(criteria, dict) or not criteria:
        raise ContractError("frozen evaluation criteria required")
    return FrozenRecord.from_dict({
        "schema": "frozen-panel-v1", "design": body, "design_digest": design.content_hash,
        "packages": dict(package_digests), "task_groups": task_groups,
        "schedule_digest": required_text(schedule_digest, "schedule digest"),
        "criteria": criteria, "target_arm": target_arm,
    })


def default_compatibility(baseline_digest: str) -> Compatibility:
    """Initial hard dependencies; outcome-based pruning is intentionally forbidden."""
    return Compatibility([
        ModuleSpec("M1"), ModuleSpec("M2"), ModuleSpec("M3", requires=("M2",)),
        ModuleSpec("M4"), ModuleSpec("M5"), ModuleSpec("M6"), ModuleSpec("M7"),
        ModuleSpec("M8"), ModuleSpec("M9", requires=("M2",)),
    ], baseline_digest=baseline_digest)
