"""Pure, per-panel construction for frozen headless lineage scorer workers.

This module deliberately prepares JSON-compatible server bodies and client
bindings only.  Starting a worker remains a separate, explicit operation, so
obtaining its immutable descriptor cannot create a ledger or contact a model.
"""
from __future__ import annotations

from typing import Mapping, Sequence

from evaluation.modular.lineage_scorer_process import _lineage_headless_source_pin
from evaluation.modular.scorer_process import headless_evaluator_descriptor, serialize_combination_panel
from research_loop.modular.lineage_combination_driver import DESIGNS
from research_loop.ontology import ContractError, digest


_USAGE_SCHEMA = "lineage-headless-evaluator-usage-declaration-v1"
_PROVIDER_KIND = "grok-headless-frozen-evaluator-v1"
_USAGE_CONTRACT = "grok-headless-lineage-usage-v1"


def headless_lineage_evaluator_bindings(*, panels: Sequence[object], evaluator_specs: Mapping[str, Mapping[str, object]],
                                        tokens_per_cell: int) -> dict[str, dict[str, dict[str, str]]]:
    """Derive the four pre-launch declarations and private worker descriptors.

    ``evaluator_specs`` is keyed by panel obligation id and every value is the
    exact evaluator declaration which will appear in that worker's server
    config.  Its work root is required to be distinct for every panel.
    """
    by_obligation = {getattr(panel, "obligation_id", None): panel for panel in panels}
    if (set(by_obligation) != set(DESIGNS) or len(by_obligation) != len(panels)
            or set(evaluator_specs) != set(DESIGNS) or type(tokens_per_cell) is not int or tokens_per_cell < 1):
        raise ContractError("headless lineage workers need the exact four compiled panels")
    roots: set[str] = set()
    result = {}
    for obligation in DESIGNS:
        panel, spec = by_obligation[obligation], evaluator_specs[obligation]
        if not isinstance(spec, Mapping) or spec.get("provider_kind") != _PROVIDER_KIND:
            raise ContractError("headless lineage evaluator declaration is invalid")
        if (spec.get("max_calls") != len(panel.cells)
                or spec.get("max_tokens") != len(panel.cells) * tokens_per_cell
                or not isinstance(spec.get("work_root"), str) or not spec["work_root"]):
            raise ContractError("headless lineage evaluator allocation differs from its panel")
        if spec["work_root"] in roots:
            raise ContractError("headless lineage evaluators need separate work roots")
        roots.add(spec["work_root"])
        declaration = dict(spec)
        descriptor = headless_evaluator_descriptor(_lineage_headless_source_pin(declaration), rubric_mode="lineage_v1")
        usage = {"schema": _USAGE_SCHEMA, "provider_kind": _PROVIDER_KIND,
                 "usage_contract": _USAGE_CONTRACT, "evaluator_config_digest": digest(declaration)}
        result[obligation] = {"evaluator_usage": usage, "evaluator_provider": descriptor}
    return result


def compose_headless_lineage_server_configs(*, panels: Sequence[object], base: Mapping[str, object],
                                            lineage_reference_root: str,
                                            lineage_reference_binding: Mapping[str, object],
                                            evaluator_specs: Mapping[str, Mapping[str, object]],
                                            tokens_per_cell: int) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, dict[str, str]]]]:
    """Return one distinct frozen server body and client binding per panel.

    The caller supplies a shared base without ``evaluator`` and a shared
    train-only lineage reference binding.  Evaluator declarations are kept
    local to individual bodies; neither declaration nor descriptor enters the
    shared reference binding.
    """
    if (not isinstance(base, Mapping) or "evaluator" in base or not isinstance(lineage_reference_root, str)
            or not isinstance(lineage_reference_binding, Mapping)
            or set(lineage_reference_binding) != {"manifest_sha256", "references", "subjects", "limits"}):
        raise ContractError("headless lineage worker composition input is invalid")
    bindings = headless_lineage_evaluator_bindings(panels=panels, evaluator_specs=evaluator_specs,
                                                   tokens_per_cell=tokens_per_cell)
    by_obligation = {panel.obligation_id: panel for panel in panels}
    configs = {}
    for obligation in DESIGNS:
        panel = by_obligation[obligation]
        configs[obligation] = {
            "schema": "lineage-scorer-process-config-v1",
            "base": {**dict(base), "evaluator": dict(evaluator_specs[obligation])},
            "panel": serialize_combination_panel(panel, lineage=True),
            "lineage_references": {"root": lineage_reference_root, **dict(lineage_reference_binding),
                                    "evaluator_usage": bindings[obligation]["evaluator_usage"]},
        }
    return configs, bindings
