"""Small executable ontology: scoped evidence, locked rules and sourced lessons."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

STATUSES = frozenset({"proceed", "closed_negative", "inconclusive", "withdrawn", "invalid"})
EVIDENCE_KINDS = frozenset({"observation", "measurement", "artifact"})
FORBIDDEN = re.compile(r"gold_|violation_if|temptation_markers|data[/\\]+labels", re.I)
COMPLETION = re.compile(r"goal[_\s-]?complete|program(?:me)?.{0,12}(完成|done|achieved|complete)|AGI.{0,8}(实现|完成)", re.I)


class ContractError(ValueError):
    """An input or transition violates the controller's contract."""


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def shape(value: Any, fields: set[str], *, optional: frozenset[str] = frozenset()) -> None:
    """Exact-shape check: every required field present, nothing beyond fields+optional."""
    if (not isinstance(value, dict) or not fields <= set(value)
            or set(value) - fields - optional):
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
    # Scientific binding (artifact/subject/condition): lessons learned on one binding
    # must never be reused on another. Keys and values are identifiers; an empty
    # mapping means the task is unbound. Included in data() and fingerprint, so the
    # task hash, task commitments and dedup all cover the binding automatically.
    bindings: dict[str, str] = field(default_factory=dict)

    @classmethod
    def parse(cls, value: Any) -> Task:
        shape(value, {"id", "family", "scope", "question", "rule", "prerequisites", "evidence", "checks"},
              optional=frozenset({"bindings"}))
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
        bindings = value.get("bindings", {})
        if not isinstance(bindings, dict):
            raise ContractError("task bindings require an identifier mapping")
        try:
            binding = {identifier(k): identifier(v) for k, v in bindings.items()}
        except ContractError as exc:
            raise ContractError(f"invalid task binding: {exc}") from exc
        return cls(identifier(value["id"]), identifier(value["family"]), scope,
                   text(value["question"]), text(value["rule"]), dict(pre), evidence,
                   distinct_ids(value["checks"]), binding)

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
        # Bindings are part of the scientific identity: the same content bound to a
        # different subject/condition is a different evaluation task.
        return digest([self.scope, self.question, self.rule, self.prerequisites,
                       [(e.kind, e.content) for e in self.evidence], self.checks, self.bindings])


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


# 仓库内版本标记：承诺字段、门禁或导出契约发生语义变化时递增。文件内容变化本身已由
# implementation_hash 捕获；标记保证即使模块内容巧合不变，跨仓库契约升级也会使旧记录失效。
RUNTIME_MARK = "research-loop-self-improving-3"


def code_version_hash() -> str:
    """Deterministic invalidation stamp written into version (policy) and trial records.

    确定性方案：仓库内版本标记 + 全部运行时模块内容哈希，经 store 哈希链同一 digest 组合。
    任一运行时模块内容变化或标记升级都会改变该值；version/trial 记录创建时写入，加载或
    复用路径上与当前值比较，不一致即判定 stale 并显式拒绝（SELF_IMPROVING.md：升级源码后
    不隐式迁移旧数据库，也没有忽略实现变化的开关）。
    """
    return digest({"runtime_mark": RUNTIME_MARK, "implementation": implementation_hash()})
