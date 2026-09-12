"""Small shared validators for data that may enter a solver envelope."""

from __future__ import annotations

from typing import Any, Mapping

from research_loop.ontology import ContractError, public


PRIVATE_TOKENS = ("gold", "reference", "answer", "label", "scorer", "score")


def object_only(value: Any, allowed: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) - allowed:
        raise ContractError(f"{name} has non-public or unknown fields")
    return dict(value)


def public_text(value: Any, name: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 16000:
        raise ContractError(f"{name} must be bounded nonempty text")
    return value


def reject_private_names(value: Any) -> None:
    """Reject both hidden key names and forbidden values before canonicalising."""
    def walk(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                if not isinstance(key, str) or any(token in key.lower() for token in PRIVATE_TOKENS):
                    raise ContractError("private evaluation field in public benchmark payload")
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)
    walk(value)
    public(value)
