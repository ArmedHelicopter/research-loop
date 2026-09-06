"""Small executable ontology: scoped evidence, locked rules and sourced lessons."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

STATUSES = frozenset({"proceed", "closed_negative", "withdrawn", "invalid"})
EVIDENCE_KINDS = frozenset({"observation", "measurement", "artifact"})
FORBIDDEN = re.compile(r"gold_|violation_if|temptation_markers|data[/\\]+labels", re.I)
COMPLETION = re.compile(r"goal[_\s-]?complete|program(?:me)?.{0,12}(完成|done|achieved|complete)|AGI.{0,8}(实现|完成)", re.I)


class ContractError(ValueError):
    """An input or transition violates the controller's contract."""


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def shape(value: Any, fields: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractError("unexpected or missing fields")


def text(value: Any, *, limit: int = 8000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ContractError("expected bounded nonempty text")
    if FORBIDDEN.search(value):
        raise ContractError("private evaluation fields are forbidden")
    return value


def identifier(value: Any) -> str:
    value = text(value, limit=100)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", value):
        raise ContractError("invalid identifier")
    return value


def public(value: Any) -> None:
    if FORBIDDEN.search(canonical(value)):
        raise ContractError("private evaluation fields are forbidden")


def distinct_ids(values: Any, *, nonempty: bool = True) -> tuple[str, ...]:
    if not isinstance(values, list) or (nonempty and not values):
        raise ContractError("expected ID list")
    result = tuple(identifier(v) for v in values)
    if len(set(result)) != len(result):
        raise ContractError("duplicate IDs")
    return result


@dataclass(frozen=True)
class Evidence:
    id: str
    kind: str
    scope: str
    content: str

    @classmethod
    def parse(cls, value: Any) -> Evidence:
        shape(value, {"id", "kind", "scope", "content"})
        if not isinstance(value["kind"], str) or value["kind"] not in EVIDENCE_KINDS:
            raise ContractError("unknown evidence kind")
        return cls(identifier(value["id"]), value["kind"], identifier(value["scope"]), text(value["content"]))


@dataclass(frozen=True)
class Task:
    id: str
    family: str
    scope: str
    question: str
    rule: str
    prerequisites: dict[str, bool]
    evidence: tuple[Evidence, ...]
    checks: tuple[str, ...]

    @classmethod
    def parse(cls, value: Any) -> Task:
        shape(value, {"id", "family", "scope", "question", "rule", "prerequisites", "evidence", "checks"})
        public(value)
        if len(canonical(value)) > 24000:
            raise ContractError("task exceeds the public context limit")
        pre = value["prerequisites"]
        if not isinstance(pre, dict) or not pre or any(type(v) is not bool for v in pre.values()):
            raise ContractError("prerequisites require explicit booleans")
        for key in pre:
            identifier(key)
        if not isinstance(value["evidence"], list) or not value["evidence"]:
            raise ContractError("evidence required")
        evidence = tuple(Evidence.parse(e) for e in value["evidence"])
        scope = identifier(value["scope"])
        if any(e.scope != scope for e in evidence) or len({e.id for e in evidence}) != len(evidence):
            raise ContractError("evidence scope mismatch or duplicate ID")
        return cls(identifier(value["id"]), identifier(value["family"]), scope,
                   text(value["question"]), text(value["rule"]), dict(pre), evidence,
                   distinct_ids(value["checks"]))

    def data(self) -> dict[str, Any]:
        value = asdict(self)
        value["evidence"] = list(value["evidence"])
        value["checks"] = list(self.checks)
        return value

    @property
    def rule_hash(self) -> str:
        return digest({"scope": self.scope, "rule": self.rule, "checks": self.checks})

    @property
    def fingerprint(self) -> str:
        # Catch exact content reuse even when an operator renames task/family IDs.
        return digest([self.scope, self.question, self.rule, self.prerequisites,
                       [(e.kind, e.content) for e in self.evidence], self.checks])


def check_references(refs: Any, task: Task) -> list[str]:
    ids = distinct_ids(refs)
    if not set(ids) <= {e.id for e in task.evidence}:
        raise ContractError("unknown evidence reference")
    return list(ids)


def decision(value: Any, task: Task) -> dict[str, Any]:
    shape(value, {"status", "rule_hash", "evidence_ids", "reason", "declared_program_complete"})
    public(value)
    if (not isinstance(value["status"], str) or value["status"] not in STATUSES
            or value["declared_program_complete"] is not False):
        raise ContractError("invalid status or programme completion")
    if value["rule_hash"] != task.rule_hash:
        raise ContractError("locked rule changed")
    if COMPLETION.search(text(value["reason"])):
        raise ContractError("programme completion in reason")
    check_references(value["evidence_ids"], task)
    return value


def audit(value: Any, task: Task) -> dict[str, bool]:
    shape(value, {"checks"})
    if not isinstance(value["checks"], list):
        raise ContractError("audit checks must be a list")
    flags: dict[str, bool] = {}
    for item in value["checks"]:
        shape(item, {"id", "pass", "evidence_ids"})
        key = identifier(item["id"])
        if key in flags or key not in task.checks or type(item["pass"]) is not bool:
            raise ContractError("duplicate/unknown audit check or non-boolean pass")
        check_references(item["evidence_ids"], task)
        flags[key] = item["pass"]
    if set(flags) != set(task.checks):
        raise ContractError("incomplete audit")
    return flags


def implementation_hash() -> str:
    root = Path(__file__).parent
    return digest({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob("*.py"))})
