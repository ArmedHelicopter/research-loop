"""Cross-repo export: lessons leave this controller only as MemoryHint records or
candidate policy proposals carrying complete, verifiable provenance.

契约来源（ai4s-gate ONTOLOGY-SELF-IMPROVING-DESIGN.md 跨仓库验收清单）：
- research-loop 导出的 lesson 必须保留 source run、scope 和 rule hash；
  缺任一必填来源信息一律抛 ExportError，宁可拒绝也不导出脏数据。
- lesson 提案只能导出为候选策略（非 active）：进入 active policy 必须另经冻结 trial、
  独立评分与独立 reviewer 晋升，本模块不提供绕过路径。
- 每条导出附带产生它的运行时 code_version_hash，供下游把过期经验降级为 unknown/soft
  warning，而不是静默复用。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .ontology import (
    ContractError, Task, code_version_hash, digest, distinct_ids, identifier, public, text,
)
from .store import Store

SCHEMA_VERSION = 1
HEX64 = re.compile(r"[a-f0-9]{64}")
# propose() 产生的 lesson 都带这些字段；它们共同构成"来源 run + scope + 规则哈希 + 证据引用"。
REQUIRED_LESSON_FIELDS = ("id", "source_run", "source_hash", "scope", "rule_hash", "instruction", "evidence_ids")


class ExportError(ContractError):
    """Refuse to export a lesson whose provenance is missing or inconsistent."""


def _hex64(value: Any, label: str) -> str:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise ExportError(f"lesson {label} must be a SHA256 hex digest")
    return value


def _iso_timestamp(value: Any) -> str:
    if not isinstance(value, str):
        raise ExportError("created_at must be an ISO 8601 timestamp string")
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise ExportError(f"created_at is not an ISO 8601 timestamp: {value!r}") from exc
    return value


def export_memory_hint(lesson: dict[str, Any], *, store: Store | None = None,
                       run: dict[str, Any] | None = None, task_fingerprint: str | None = None,
                       created_at: str | None = None,
                       policy_version: str | None = None) -> dict[str, Any]:
    """Export one controller lesson as a MemoryHint dict for the ai4s-gate sidecar.

    The hint keeps ``source_run`` (the producing development run), ``scope``,
    ``rule_hash``, ``task_fingerprint``, an ISO ``created_at`` and the lesson
    payload; missing provenance raises ExportError. 传入 store 时会核验来源 run
    已封存、scope/rule 与 run 一致、source_hash 与封存记录一致。绑定的任务还会
    在 hint 顶层携带 ``bindings``（artifact/subject/condition），供 ai4s-gate
    把记忆限定在同一科学对象上；无绑定任务的 hint 保持旧格式（省略该键）。
    """
    if not isinstance(lesson, dict):
        raise ExportError("lesson must be a controller lesson mapping")
    missing = [field for field in REQUIRED_LESSON_FIELDS if not lesson.get(field)]
    if missing:
        raise ExportError("lesson is missing required provenance: " + ", ".join(missing))
    try:
        lesson_id = text(lesson["id"], limit=200)
        source_run = identifier(lesson["source_run"])
        scope = identifier(lesson["scope"])
        instruction = text(lesson["instruction"], limit=2000)
        evidence_ids = distinct_ids(lesson["evidence_ids"])
    except ContractError as exc:
        raise ExportError(f"lesson provenance rejected: {exc}") from exc
    rule_hash = _hex64(lesson["rule_hash"], "rule_hash")
    source_hash = _hex64(lesson["source_hash"], "source_hash")

    bindings: dict[str, str] = {}
    if run is None and store is not None:
        try:
            run = store.get("run", source_run)
        except ContractError as exc:
            raise ExportError(f"lesson source run is not in the controller store: {source_run}") from exc
    if run is not None:
        if not isinstance(run, dict) or run.get("id") != source_run:
            raise ExportError("supplied run does not match the lesson source_run")
        if run.get("phase") != "development" or run.get("state") != "closed":
            raise ExportError("lessons may only be exported from closed development runs")
        if source_hash != digest(run):
            raise ExportError("lesson source_hash does not match the sealed source run")
        if store is not None:
            try:
                store.verify_seal("run", source_run, run)
            except ContractError as exc:
                raise ExportError(f"lesson source run has no completion seal: {exc}") from exc
        try:
            task = Task.parse(run["task"])
        except ContractError as exc:
            raise ExportError(f"source run task rejected: {exc}") from exc
        if task.scope != scope or task.rule_hash != rule_hash:
            raise ExportError("lesson scope/rule_hash does not match its source run")
        if not set(evidence_ids) <= {e.id for e in task.evidence}:
            raise ExportError("lesson evidence_ids do not reference the source run evidence")
        task_fingerprint = task.fingerprint
        bindings = dict(task.bindings)
    if not isinstance(task_fingerprint, str) or not HEX64.fullmatch(task_fingerprint):
        raise ExportError("task_fingerprint is required; export refuses hints without a resolvable task fingerprint")

    stamp = _iso_timestamp(created_at) if created_at is not None else \
        datetime.now(timezone.utc).isoformat(timespec="seconds")
    hint: dict[str, Any] = {
        "kind": "memory_hint",
        "schema_version": SCHEMA_VERSION,
        "lesson_id": lesson_id,
        "source_run": source_run,
        "scope": scope,
        "rule_hash": rule_hash,
        "task_fingerprint": task_fingerprint,
        "created_at": stamp,
        "payload": {"instruction": instruction, "evidence_ids": list(evidence_ids), "source_hash": source_hash},
        "code_version_hash": code_version_hash(),
    }
    if policy_version is not None:
        if not isinstance(policy_version, str) or not policy_version.strip():
            raise ExportError("policy_version must be a nonempty version identifier")
        hint["policy_version"] = policy_version
    if bindings:
        # Scientific binding travels with the hint so the importer can keep memory
        # scoped to the same subject/condition; unbound hints stay byte-compatible
        # with the previous format (no empty bindings key).
        hint["bindings"] = bindings
    try:
        public(hint)  # 导出内容绝不携带私有评分字段（gold_*、labels 等）。
    except ContractError as exc:
        raise ExportError(f"lesson payload rejected: {exc}") from exc
    hint["hint_hash"] = digest(hint)
    return hint


def export_candidate_policy(lessons: list[dict[str, Any]], *, candidate_version: str,
                            base_version: str | None = None, store: Store | None = None,
                            created_at: str | None = None, status: str = "candidate") -> dict[str, Any]:
    """Wrap controller lessons as a candidate policy proposal for ai4s-gate.

    The proposal is never active: ``status`` only accepts ``"candidate"`` and the
    body marks promotion as not eligible. 激活必须另经冻结 trial、独立评分与独立
    reviewer；传入 store 时会核验每个 lesson 确实属于该候选版本。
    """
    if status != "candidate":
        raise ExportError("lesson proposals export only as candidate policies; active policies require "
                          "the frozen-trial, independent-evaluation and separate-reviewer gates")
    if not isinstance(candidate_version, str) or not candidate_version.strip():
        raise ExportError("candidate_version must be a nonempty version identifier")
    if base_version is not None and (not isinstance(base_version, str) or not base_version.strip()):
        raise ExportError("base_version must be a nonempty version identifier")
    if not isinstance(lessons, list) or not lessons:
        raise ExportError("a candidate policy proposal requires at least one sourced lesson")
    stamp = created_at if created_at is not None else datetime.now(timezone.utc).isoformat(timespec="seconds")
    hints = [export_memory_hint(lesson, store=store, created_at=stamp, policy_version=candidate_version)
             for lesson in lessons]
    if store is not None:
        try:
            version = store.get("version", candidate_version)
        except ContractError as exc:
            raise ExportError(f"candidate version is not in the controller store: {candidate_version}") from exc
        known = {entry.get("id") for entry in version.get("lessons", [])}
        absent = [hint["lesson_id"] for hint in hints if hint["lesson_id"] not in known]
        if absent:
            raise ExportError("exported lessons are not part of the candidate version: " + ", ".join(absent))
    proposal: dict[str, Any] = {
        "kind": "policy_proposal",
        "schema_version": SCHEMA_VERSION,
        "status": "candidate",
        "candidate_version": candidate_version,
        "base_version": base_version,
        "created_at": stamp,
        "code_version_hash": code_version_hash(),
        "lessons": hints,
        "promotion": {"eligible": False,
                      "requires": ["frozen_trial", "independent_evaluation", "separate_reviewer"]},
    }
    try:
        public(proposal)
    except ContractError as exc:
        raise ExportError(f"proposal payload rejected: {exc}") from exc
    proposal["proposal_hash"] = digest(proposal)
    return proposal
