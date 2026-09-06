"""Controller-owned learning loop. Models propose data; they cannot mutate state."""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Collection
from typing import Any

from .ontology import (
    COMPLETION, ContractError, Task, audit, canonical, check_references, code_version_hash, decision,
    digest, identifier, implementation_hash, public, shape, text,
)
from .provider import Provider
from .store import Store

DEFAULT_CRITERIA = {
    "min_pairs": 20, "min_families": 2, "min_error_reduction": 1,
    "max_token_ratio": 1.25, "max_call_ratio": 1.0,
}


def validate_criteria(value: Any) -> dict[str, Any]:
    shape(value, set(DEFAULT_CRITERIA))
    for key in ("min_pairs", "min_families", "min_error_reduction"):
        if type(value[key]) is not int or value[key] < 1:
            raise ContractError("positive integer trial thresholds required")
    for key in ("max_token_ratio", "max_call_ratio"):
        if type(value[key]) not in (int, float) or not math.isfinite(value[key]) or value[key] <= 0:
            raise ContractError("finite positive cost ratio required")
    return dict(value)


def version_id(version: dict[str, Any]) -> str:
    return digest({k: v for k, v in version.items() if k != "id"})


def task_commitments(tasks: list[Task]) -> list[dict[str, str]]:
    """Freeze per-task task hash, locked rule hash and fingerprint into the trial record.

    跨仓库验收：task/rule/labels commitment 必须在冻结时成为 trial 记录里可显式核验的
    一等承诺；labels commitment 即冻结前 SHA256 标签文件哈希（label_commitment）。
    """
    return [{"id": t.id, "task_hash": digest(t.data()), "rule_hash": t.rule_hash,
             "fingerprint": t.fingerprint} for t in tasks]


def role_identities(provider: Provider, auditor_provider: Provider | None,
                    auditor2_provider: Provider | None) -> dict[str, str]:
    """Fail-closed audit independence gate: the three role identities must be pairwise distinct.

    executor / auditor_1 / auditor_2 共用同一个 provider（同一 identity = 同一模型/部署）时，
    两个 auditor 可以共享同样的错误或幻觉，audits[0] == audits[1] 不代表事实正确；当前实现
    只存在角色隔离，缺少信息隔离，因此身份隔离是强制门槛而不是建议。identity 即隔离边界：
    同一 base_url 下不同 model 名是最低要求（不同 model 名即不同 identity，可接受），推荐
    不同 base_url 的独立部署；完全相同的部署必然共享权重与幻觉模式，直接拒绝。缺少任一
    auditor provider（例如未提供第二个独立部署）同样拒绝。
    """
    roles: dict[str, Provider | None] = {"executor": provider, "auditor_1": auditor_provider,
                                         "auditor_2": auditor2_provider}
    missing = [role for role, value in roles.items() if value is None]
    if missing:
        hint = ("; a second independent auditor deployment (auditor2_provider) is required"
                if "auditor_2" in missing else "")
        raise ContractError("audit independence requires pairwise-distinct provider identities; missing: "
                            + ", ".join(role + "_provider" for role in missing) + hint)
    identities: dict[str, str] = {}
    for role, value in roles.items():
        identity = getattr(value, "identity", None)
        if type(identity) is not str or not identity:
            raise ContractError("each role requires a provider exposing a nonempty string identity")
        identities[role] = identity
    if len(set(identities.values())) != len(identities):
        raise ContractError("audit independence requires pairwise-distinct provider identities: "
                            + canonical(identities))
    return identities


LESSON_STATUSES = frozenset({"proceed", "closed_negative"})


def require_lesson_worthy_run(run: dict[str, Any]) -> None:
    """Shared quality gate: only a run that walked the full protocol may become memory.

    ``Agent.propose`` 和跨仓库导出（export.export_memory_hint）共用这道门禁：run 必须
    有非空 decision、双审计一致（audit_valid is True）、科学状态落在
    {proceed, closed_negative} 且 evidence_admitted is True。四项逐项独立拒绝——被
    拒绝/未走完协议的 run 绝不能回收成"经验"记忆，也不能导出为 memory hint。
    """
    if not run.get("decision"):
        raise ContractError("run has no decision; lessons require a completed protocol")
    if run.get("audit_valid") is not True:
        raise ContractError("run audit is not valid; lessons require admitted evidence")
    if run.get("status") not in LESSON_STATUSES:
        raise ContractError("run status does not admit lessons; lessons require proceed or closed_negative")
    if run.get("evidence_admitted") is not True:
        raise ContractError("run evidence was not admitted; lessons require admitted evidence")


class Agent:
    def __init__(self, store: Store, approvers: Collection[str] = ()):
        """Create a controller over ``store``.

        ``approvers`` is the explicit deployment allowlist: reviewer identifiers that may
        execute :meth:`Agent.promote` or :meth:`Agent.rollback`. Entries are validated with
        identifier(), deduplicated and frozen into a frozenset. The default empty allowlist
        is deliberate fail-closed design: promotion and rollback stay disabled until an
        operator names authorized approvers, so a merely well-formed reviewer string never
        carries deployment authority by itself.
        """
        if isinstance(approvers, str) or not isinstance(approvers, Collection):
            raise ContractError("approvers must be a collection of reviewer identifiers")
        self.store = store
        self.approvers = frozenset(identifier(entry) for entry in approvers)

    def initialize(self) -> str:
        with self.store.transaction():
            current = self.store.value("active_version")
            if current:
                self.version(current)
                return current
            base = {"parent": None, "core_hash": implementation_hash(), "code_version_hash": code_version_hash(),
                    "lessons": [], "proposer": "controller", "source_run": None}
            base["id"] = version_id(base)
            self.store.put("version", base["id"], base)
            self.store.set_value("active_version", base["id"])
            self.store.event("initialized", {"version": base["id"]})
            return base["id"]

    def version(self, key: str | None = None) -> dict[str, Any]:
        key = key or self.store.value("active_version")
        if not key:
            raise ContractError("initialize the store first")
        value = self.store.get("version", key)
        if value["id"] != key or version_id(value) != key or value["core_hash"] != implementation_hash():
            raise ContractError("version content or runtime implementation changed")
        if value.get("code_version_hash") != code_version_hash():
            # Old versions (policies) are never silently reused after a runtime upgrade.
            raise ContractError("stale version: runtime code_version_hash changed; start a new package database")
        return value

    def enqueue(self, task: Task) -> None:
        task = Task.parse(task.data())
        with self.store.transaction():
            for trial in self.store.all("trial"):
                if any(t["family"] == task.family or Task.parse(t).fingerprint == task.fingerprint
                       for t in trial["tasks"]):
                    raise ContractError("evaluation tasks/families cannot return as development feedback")
            self.store.put("task", task.id, task.data())
            self.store.db.execute("INSERT INTO queue(task_id,state) VALUES (?, 'queued')", (task.id,))
            self.store.event("enqueued", {"task_id": task.id, "fingerprint": task.fingerprint})

    def run_next(self, provider: Provider, *, auditor_provider: Provider | None = None,
                 auditor2_provider: Provider | None = None) -> dict[str, Any] | None:
        # Fail closed before any queue mutation: a misconfigured audit triple must not
        # leave an entry stuck in the running state.
        role_identities(provider, auditor_provider, auditor2_provider)
        with self.store.transaction():
            if self.store.db.execute("SELECT 1 FROM queue WHERE state='running'").fetchone():
                raise ContractError("a development run is active; recover it explicitly after interruption")
            row = self.store.db.execute("SELECT * FROM queue WHERE state='queued' ORDER BY seq LIMIT 1").fetchone()
            if row is None:
                return None
            run_id = "dev-" + uuid.uuid4().hex
            version = self.version()
            self.store.db.execute("UPDATE queue SET state='running',run_id=? WHERE seq=?", (run_id, row["seq"]))
        result = self.execute(Task.parse(self.store.get("task", row["task_id"])), version["id"],
                              provider, phase="development", run_id=run_id,
                              auditor_provider=auditor_provider, auditor2_provider=auditor2_provider)
        with self.store.transaction():
            self.store.db.execute("UPDATE queue SET state='closed' WHERE run_id=?", (run_id,))
        return result

    def recover(self, run_id: str) -> None:
        # No automatic retry: an interrupted request may already have incurred cost.
        with self.store.transaction():
            row = self.store.db.execute("SELECT * FROM queue WHERE run_id=? AND state='running'", (run_id,)).fetchone()
            if row is None:
                raise ContractError("no interrupted development queue entry")
            self.store.db.execute("UPDATE queue SET state='closed' WHERE run_id=?", (run_id,))
            self.store.event("interruption_closed", {"run_id": run_id, "usage": "possibly incomplete"})

    def _call(self, provider: Provider, role: str, payload: dict[str, Any], run_id: str) -> dict[str, Any]:
        public(payload)
        call_id = run_id + ":" + role
        with self.store.transaction():
            # An incomplete request is never silently retried.
            if any(x["call_id"] == call_id for x in self.store.all("request")):
                raise ContractError("call already attempted")
            self.store.put("request", call_id, {"call_id": call_id, "run_id": run_id, "role": role,
                           "payload_hash": digest(payload), "input_chars": len(canonical(payload)),
                           "provider": provider.identity})
            self.store.event("call_started", {"call_id": call_id})
        response = provider.call(role, payload)
        if any(type(n) is not int or n < 0 for n in (response.input_tokens, response.output_tokens)):
            raise ContractError("missing token accounting")
        if not math.isfinite(response.elapsed_s) or response.elapsed_s < 0:
            raise ContractError("invalid timing")
        with self.store.transaction():
            self.store.put("usage", call_id, {"call_id": call_id, "run_id": run_id,
                           "input_tokens": response.input_tokens, "output_tokens": response.output_tokens,
                           "elapsed_s": response.elapsed_s})
            self.store.event("call_finished", {"call_id": call_id, "response_hash": digest(response.value)})
        return response.value

    def usage(self, run_id: str) -> dict[str, Any]:
        requests = [r for r in self.store.all("request") if r["run_id"] == run_id]
        usage = [r for r in self.store.all("usage") if r["run_id"] == run_id]
        complete = len(requests) == len(usage)
        return {
            "calls": len(requests), "complete": complete,
            "input_chars": sum(r["input_chars"] for r in requests),
            "input_tokens": sum(r["input_tokens"] for r in usage) if complete else None,
            "output_tokens": sum(r["output_tokens"] for r in usage) if complete else None,
            "elapsed_s": sum(r["elapsed_s"] for r in usage) if complete else None,
        }

    def execute(self, task: Task, version_key: str, provider: Provider, *, phase: str,
                run_id: str, auditor_provider: Provider | None = None,
                auditor2_provider: Provider | None = None) -> dict[str, Any]:
        """Run one task under a frozen version: an executor decision plus two independent audits.

        Audit independence is fail-closed: executor, auditor_1 and auditor_2 must be
        providers with pairwise-distinct identities (see :func:`role_identities`). Two
        auditors sharing one deployment share weights and failure modes, so
        ``audits[0] == audits[1]`` alone proves nothing about factual correctness —
        identity is the isolation boundary. A different model name on the same base_url
        is the minimum acceptable separation; a distinct base_url is recommended.

        The per-role identity mapping is frozen into the attempt and run records
        (``providers``) and sealed by the run_closed record hash; the legacy
        ``provider`` field is kept for backwards compatibility and equals the executor
        identity.
        """
        task = Task.parse(task.data())
        if phase not in {"development", "evaluation"}:
            raise ContractError("unknown run phase")
        identities = role_identities(provider, auditor_provider, auditor2_provider)
        version = self.version(version_key)
        start = {"id": run_id, "task": task.data(), "task_hash": digest(task.data()),
                 "version": version_key, "phase": phase, "provider": provider.identity,
                 "providers": identities}
        with self.store.transaction():
            existing = self.store.db.execute("SELECT 1 FROM objects WHERE kind='attempt' AND id=?", (run_id,)).fetchone()
            if existing:
                if self.store.get("attempt", run_id) != start:
                    raise ContractError("frozen run configuration changed")
                return self.store.get("run", run_id)  # Incomplete attempts require operator investigation.
            self.store.put("attempt", run_id, start)
            self.store.event("run_started", {"run_id": run_id, "task_hash": start["task_hash"],
                                           "version": version_key, "phase": phase})
        # Retrieval is scoped: same scope, same locked rule AND the exact same
        # scientific binding. Lessons without a bindings key (legacy) count as
        # unbound and only serve unbound tasks; a bound task never inherits
        # experience gathered on another molecule/receptor/condition.
        lessons = [x for x in version["lessons"] if x["scope"] == task.scope
                   and x["rule_hash"] == task.rule_hash
                   and x.get("bindings", {}) == task.bindings][-3:]
        result: dict[str, Any] = {
            **start, "state": "closed", "status": "withdrawn", "decision": None,
            "audit_valid": None, "evidence_admitted": False, "protocol_violations": [],
            "lesson_ids": [x["id"] for x in lessons],
        }
        if all(task.prerequisites.values()):
            role = "executor"
            try:
                value = self._call(provider, role, {"task": task.data(), "rule_hash": task.rule_hash,
                                   "lessons": lessons}, run_id)
                result["decision"] = decision(value, task)
                audits = []
                for role, auditor in (("auditor_1", auditor_provider), ("auditor_2", auditor2_provider)):
                    # Auditors get the evidence and decision, not each other's judgments or
                    # the memory; each runs on its own provider identity so a shared
                    # hallucination cannot masquerade as double agreement.
                    value = self._call(auditor, role, {"task": task.data(), "rule_hash": task.rule_hash,
                                       "decision": result["decision"]}, run_id)
                    audits.append(audit(value, task))
                result["audits"] = audits
                result["audit_valid"] = audits[0] == audits[1] and all(audits[0].values())
                result["status"] = result["decision"]["status"]
                if not result["audit_valid"]:
                    result["status"] = "invalid"
                    result["protocol_violations"].append("audit_failed_or_disagreed")
                result["evidence_admitted"] = result["audit_valid"] and result["status"] in {"proceed", "closed_negative"}
            except ContractError:
                result["status"] = "invalid"
                result["protocol_violations"].append("contract_rejected:" + role)
            except Exception:
                # Do not persist endpoint exceptions, credentials, private data or fabricated answers.
                result["state"], result["status"] = "failed", "invalid"
                result["protocol_violations"].append("backend_failed:" + role)
        result["usage"] = self.usage(run_id)
        with self.store.transaction():
            self.store.put("run", run_id, result)
            self.store.event("run_closed", {"run_id": run_id, "record_hash": digest(result)})
        return result

    def propose(self, source_run: str, provider: Provider, *, proposer: str) -> str:
        """Turn a completed development run into a lesson candidate on the current version.

        The reflector deliberately rides the executor provider — reflection is not an
        auditor role — so the sealed run must have been executed by exactly this
        provider identity (``run["providers"]["executor"]``); a different provider may
        not propose from a run it did not execute.
        """
        proposer = identifier(proposer)
        run = self.store.get("run", source_run)
        self.store.verify_seal("run", source_run, run)
        if run["phase"] != "development" or run["state"] != "closed":
            raise ContractError("only completed development runs may generate lessons")
        parent = self.version()
        executor_identity = (run.get("providers") or {}).get("executor") or run["provider"]
        if run["version"] != parent["id"] or executor_identity != provider.identity:
            raise ContractError("proposal requires a run of the current version and provider")
        # Quality gates: only a run that walked the full protocol (a decision, two
        # agreeing audits, a completed scientific status and admitted evidence) may
        # turn its record into a lesson; a rejected/failed protocol must never be
        # recycled into "experience" memory. The exporter applies the same gate.
        require_lesson_worthy_run(run)
        task = Task.parse(run["task"])
        proposal_id = "proposal-" + uuid.uuid4().hex
        value = self._call(provider, "reflector", {
            "task": task.data(), "rule_hash": task.rule_hash,
            "record": {"decision": run["decision"], "audit_valid": run["audit_valid"],
                       "status": run["status"], "protocol_violations": run["protocol_violations"],
                       "audits": run.get("audits", []),
                       "failed_prerequisites": [k for k, passed in task.prerequisites.items() if not passed]},
        }, proposal_id)
        shape(value, {"instruction", "evidence_ids"})
        instruction = text(value["instruction"], limit=2000)
        if COMPLETION.search(instruction):
            raise ContractError("completion claims cannot become memory")
        refs = check_references(value["evidence_ids"], task)
        lesson = {"scope": task.scope, "rule_hash": task.rule_hash, "source_run": source_run,
                  "source_hash": digest(run), "instruction": instruction, "evidence_ids": refs,
                  "bindings": dict(task.bindings)}
        lesson["id"] = digest(lesson)
        lessons = parent["lessons"] + [lesson]
        if len(lessons) > 32:
            raise ContractError("memory full; review and design explicit retirement before growing it")
        candidate = {"parent": parent["id"], "core_hash": parent["core_hash"],
                     "code_version_hash": code_version_hash(), "lessons": lessons,
                     "proposer": proposer, "source_run": source_run}
        candidate["id"] = version_id(candidate)
        with self.store.transaction():
            if self.store.value("active_version") != parent["id"]:
                raise ContractError("active version changed during proposal")
            self.store.put("version", candidate["id"], candidate)
            self.store.event("candidate_proposed", {"version": candidate["id"], "source_run": source_run,
                             "proposal_run": proposal_id, "usage": self.usage(proposal_id)})
        return candidate["id"]

    def freeze_trial(self, candidate_key: str, tasks: list[Task], criteria: dict[str, Any],
                     *, evaluator: str, label_commitment: str) -> str:
        criteria = validate_criteria(criteria)
        if not isinstance(label_commitment, str) or not re.fullmatch(r"[a-f0-9]{64}", label_commitment):
            raise ContractError("a pre-run SHA256 commitment to private labels is required")
        evaluator = identifier(evaluator)
        candidate, baseline = self.version(candidate_key), self.version()
        tasks = [Task.parse(t.data()) for t in tasks]
        if candidate["parent"] != baseline["id"] or candidate["proposer"] == evaluator:
            raise ContractError("trial needs current parent and a separate evaluator")
        if len(tasks) < criteria["min_pairs"] or len({t.family for t in tasks}) < criteria["min_families"]:
            raise ContractError("insufficient pairs or independent task families")
        if len({t.id for t in tasks}) != len(tasks) or len({t.fingerprint for t in tasks}) != len(tasks):
            raise ContractError("duplicate evaluation task")
        with self.store.transaction():
            dev_tasks = [Task.parse(self.store.get("task", r["task_id"]))
                         for r in self.store.db.execute("SELECT task_id FROM queue")]
            past_tasks = [Task.parse(t) for trial in self.store.all("trial") for t in trial["tasks"]]
            seen = dev_tasks + past_tasks
            if any(t.family == old.family or t.fingerprint == old.fingerprint for t in tasks for old in seen):
                raise ContractError("evaluation family/content already used")
            commitments = task_commitments(tasks)
            trial = {"baseline": baseline["id"], "candidate": candidate_key, "tasks": [t.data() for t in tasks],
                     "criteria": criteria, "evaluator": evaluator, "core_hash": implementation_hash(),
                     "code_version_hash": code_version_hash(), "label_commitment": label_commitment,
                     "task_commitments": commitments}
            trial["id"] = digest(trial)
            self.store.put("trial", trial["id"], trial)
            # The freeze event mirrors every commitment into the hash chain: a rewritten
            # trial record cannot silently detach from what was frozen before the run.
            self.store.event("trial_frozen", {"trial": trial["id"], "candidate": candidate_key,
                                            "criteria": criteria, "task_commitments": commitments,
                                            "label_commitment": label_commitment,
                                            "evaluator": evaluator, "core_hash": trial["core_hash"],
                                            "code_version_hash": trial["code_version_hash"]})
            return trial["id"]

    def trial(self, key: str) -> dict[str, Any]:
        # Single reuse checkpoint: run_trial, evaluate and promote all load trials here,
        # so tampered records, runtime upgrades and commitment drift are rejected once.
        self.store.verify_journal()
        trial = self.store.get("trial", key)
        if digest({k: v for k, v in trial.items() if k != "id"}) != key or trial["core_hash"] != implementation_hash():
            raise ContractError("frozen trial changed")
        if trial.get("code_version_hash") != code_version_hash():
            raise ContractError("stale trial: runtime code_version_hash changed after the freeze")
        # Fail closed: the freeze event is located by THIS trial's id (freeze_trial
        # writes "trial": trial["id"]), so promises can no longer be borrowed from
        # other trials of the same candidate, and a self-consistent trial written
        # directly into the store (digest self-computed, no freeze_trial) has no
        # freeze event at all and is rejected outright — the minimal-sample, family
        # dedup, development-task exclusion and evaluator commitment gates of
        # freeze_trial cannot be bypassed by a direct store write.
        frozen = self.store.find_events("trial_frozen", trial=key)
        if not frozen:
            raise ContractError("trial has no freeze event; direct store writes cannot substitute freeze_trial")
        if len({canonical(event) for event in frozen}) > 1:
            # Several freeze events claim this trial id with different content: the
            # frozen commitment set is ambiguous, so no reading of it may run. Only
            # byte-identical replays of one freeze event are tolerated.
            raise ContractError("ambiguous freeze events for this trial: divergent frozen commitments")
        anchors = ("task_commitments", "label_commitment", "criteria", "evaluator",
                   "core_hash", "code_version_hash")
        for event in frozen:
            missing = [field for field in anchors if field not in event]
            if missing:
                raise ContractError("freeze event for this trial is missing anchoring fields: "
                                    + ", ".join(missing))
            if any(event[field] != trial.get(field) for field in anchors):
                raise ContractError("frozen trial changed: commitments diverge from the hash-chained freeze events")
        commitments = trial.get("task_commitments") or []
        if commitments and len(commitments) != len(trial["tasks"]):
            raise ContractError("frozen trial changed: task commitments do not cover the frozen task set")
        for data, commitment in zip(trial["tasks"], commitments):
            task = Task.parse(data)
            if (digest(task.data()) != commitment["task_hash"] or task.rule_hash != commitment["rule_hash"]
                    or task.fingerprint != commitment["fingerprint"]):
                raise ContractError("frozen trial changed: task/rule commitment does not match the frozen task")
        return trial

    def run_trial(self, key: str, provider: Provider, *, auditor_provider: Provider | None = None,
                  auditor2_provider: Provider | None = None) -> list[dict[str, Any]]:
        trial = self.trial(key)
        role_identities(provider, auditor_provider, auditor2_provider)
        results = []
        for index, value in enumerate(trial["tasks"]):
            task = Task.parse(value)
            # Counterbalance paired execution order deterministically; no result-based ordering.
            arms = ("baseline", "candidate") if index % 2 == 0 else ("candidate", "baseline")
            for arm in arms:
                results.append(self.execute(task, trial[arm], provider, phase="evaluation",
                               run_id=f"{key}:{task.id}:{arm}", auditor_provider=auditor_provider,
                               auditor2_provider=auditor2_provider))
        return results

    def promote(self, trial_key: str, *, reviewer: str) -> str:
        """Promote the trial's candidate with an explicitly authorized reviewer.

        Symmetric with :meth:`rollback`: ``reviewer`` must be a member of the approvers
        allowlist passed to :class:`Agent`; a well-formed reviewer string alone carries
        no deployment authority, and with the default empty allowlist promotion is
        disabled entirely. The reviewer is still recorded in the version_promoted event
        for the audit trail.
        """
        reviewer = identifier(reviewer)
        if reviewer not in self.approvers:
            raise ContractError("promotion requires an authorized approver")
        with self.store.transaction():
            trial = self.trial(trial_key)
            candidate = self.version(trial["candidate"])
            receipt = self.store.get("evaluation", trial_key)
            self.store.verify_journal()
            self.store.verify_seal("evaluation", trial_key, receipt)
            if reviewer in {candidate["proposer"], trial["evaluator"]}:
                raise ContractError("promotion requires a reviewer separate from proposer and evaluator")
            if not receipt["eligible"] or receipt["trial_hash"] != digest(trial):
                raise ContractError("independent evaluation did not pass the frozen gates")
            # Detect accidental edits after evaluation; this is not hostile-user authentication.
            for run_id, expected in receipt["run_hashes"].items():
                if digest(self.store.get("run", run_id)) != expected:
                    raise ContractError("evaluated run changed")
            if self.store.value("active_version") != trial["baseline"]:
                raise ContractError("stale trial cannot replace the current version")
            self.store.set_value("active_version", candidate["id"])
            self.store.event("version_promoted", {"trial": trial_key, "version": candidate["id"], "reviewer": reviewer})
            return candidate["id"]

    def rollback(self, *, reviewer: str, reason: str) -> str:
        """Roll the active version back to its parent — explicitly authorized only.

        Fail closed: ``reviewer`` must be a member of the approvers allowlist passed to
        :class:`Agent`. A well-formed reviewer string alone carries no authority; with
        the default empty allowlist rollback is disabled entirely until an operator
        configures authorized approvers. The reviewer/reason are still recorded in the
        version_rolled_back event for the audit trail.
        """
        reviewer, reason = identifier(reviewer), text(reason, limit=1000)
        if reviewer not in self.approvers:
            raise ContractError("rollback requires an authorized approver")
        with self.store.transaction():
            active = self.version()
            if active["parent"] is None:
                raise ContractError("base version has no parent")
            parent = self.version(active["parent"])
            self.store.set_value("active_version", parent["id"])
            self.store.event("version_rolled_back", {"from": active["id"], "to": parent["id"],
                                                   "reviewer": reviewer, "reason": reason})
            return parent["id"]
