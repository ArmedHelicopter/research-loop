"""Pure aggregation helpers; they do not load references or invoke scorers."""

from __future__ import annotations

import math
from typing import Mapping

from research_loop.ontology import ContractError


def _unit(value: object, field: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)) or not 0 <= float(value) <= 1:
        raise ContractError(f"{field} must be a finite score in [0, 1]")
    return float(value)


def discovery_adapted_score(candidate: str, dimensions: Mapping[str, object]) -> dict[str, float]:
    if not isinstance(candidate, str) or not candidate.strip():
        return {"context": 0.0, "variable_f1": 0.0, "relation": 0.0, "adapted_score": 0.0}
    if not isinstance(dimensions, Mapping) or set(dimensions) != {"context", "variable_f1", "relation"}:
        raise ContractError("Discovery score dimensions must be exact")
    result = {key: _unit(value, key) for key, value in dimensions.items()}
    result["adapted_score"] = result["context"] * result["variable_f1"] * result["relation"]
    return result


def blade_adapted_score(candidate: str, dimensions: Mapping[str, object]) -> dict[str, float]:
    if not isinstance(candidate, str) or not candidate.strip():
        return {"cvars": 0.0, "transform": 0.0, "model": 0.0, "adapted_score": 0.0}
    if not isinstance(dimensions, Mapping) or set(dimensions) != {"cvars", "transform", "model"}:
        raise ContractError("BLADE score dimensions must be exact")
    result = {key: _unit(value, key) for key, value in dimensions.items()}
    result["adapted_score"] = sum(result.values()) / 3
    return result
