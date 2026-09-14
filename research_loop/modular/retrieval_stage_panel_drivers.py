"""Caller-bound Q8.1 stage coverage and Q8.4 source provenance factorial."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from typing import Any, Mapping
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask, required_text, strict_bool
from research_loop.modular.modules.evidence import EvidenceLedger
from research_loop.modular.modules.improvement import TrainingManifest
from research_loop.modular.modules.retrieval import FrozenSourceBundle
from research_loop.modular.benchmarks.execution import DockerExecutionBroker, ExecutionRequest
from research_loop.modular.panel_receipts import opaque_panel_cell_binding
from research_loop.modular.recorded_retrieval import RecordedRetrievalProvider
from research_loop.modular.retrieval_panel_drivers import _docs, _map, _digest, _candidate, _select_sources
from research_loop.modular.workflow import STAGES
from research_loop.ontology import ContractError

SCOPE = {"Q8.1": ("research", "competition", "distinguish", "adversarial", "retrospective", "frontier"),
         "Q8.4": ("shared_root", "independent_roots")}
STAGE = dict(zip(SCOPE["Q8.1"], STAGES))
SLOTS = {"research": ("research", "final"), "competition": ("competition", "final"),
         "distinguish": ("distinguish", "final"), "adversarial": ("review_a", "review_b", "final"),
         "retrospective": ("retro_blind", "retro_reveal", "final"), "frontier": ("frontier", "final")}


def freeze_retrieval_stage_bundle(task: PublicTask, *, query, budget, sources, history, execution):
    task.identity.require_train()
    if not isinstance(query, Mapping) or set(query) != {"question", "task_digest"} or query["task_digest"] != task.content_hash:
        raise ContractError("stage query must bind the caller task")
    required_text(query["question"], "question")
    if not isinstance(budget, Mapping) or set(budget) != {"provider_calls", "source_cap", "context_bytes"} or any(type(x) is not int for x in budget.values()):
        raise ContractError("stage retrieval budget requires strict total integers")
    if budget["provider_calls"] != 3 or budget["source_cap"] != 3 or budget["context_bytes"] < 1024:
        raise ContractError("stage retrieval contract fixes three total calls and source slots")
    if not isinstance(sources, Mapping) or set(sources) != {"research", "shared_root", "independent_roots"}:
        raise ContractError("stage sources require all caller material")
    docs = {key: _docs(value) for key, value in sources.items()}
    left, right = docs["shared_root"], docs["independent_roots"]
    if len(left) != 3 or len(right) != 3 or any(doc.lane != "support" for doc in (*left, *right)):
        raise ContractError("Q8.4 requires three matched supporting source documents")
    stripped = lambda rows: [{k: v for k, v in doc.data().items() if k != "root_source_id"} for doc in rows]
    if stripped(left) != stripped(right) or len({doc.root_source_id for doc in left}) != 1 or len({doc.root_source_id for doc in right}) != 3:
        raise ContractError("Q8.4 may change only shared versus distinct source provenance")
    required_text(history, "public history")
    row = dict(_map(execution, "stage execution"))
    if set(row) != {"program", "image", "input_sha256", "input_byte_count"} or type(row["input_byte_count"]) is not int or row["input_byte_count"] < 0:
        raise ContractError("stage execution declaration is incomplete")
    required_text(row["program"], "literal program"); _digest(row["input_sha256"], "input sha256")
    if "\r" in row["program"]: raise ContractError("literal program must use LF newlines")
    ExecutionRequest(task.identity, row["image"], Path("unresolved.py"), {"public_csv": Path("unresolved.csv")})
    return FrozenRecord.from_dict({"schema": "retrieval-stage-bundle-v1", "identity": task.identity.data(),
        "task_digest": task.content_hash, "query": dict(query), "budget": dict(budget),
        "sources": {key: [doc.data() for doc in rows] for key, rows in docs.items()}, "history": history, "execution": row})


def rebuild(task, body):
    return freeze_retrieval_stage_bundle(task, **{key: body.get(key) for key in ("query", "budget", "sources", "history", "execution")})


def retrieval_stage_injection(experiment, variant, *, task, evidence):
    if variant not in SCOPE.get(experiment, ()): raise ContractError("stage variant is not registered")
    public = PublicTask(DataIdentity.parse(task.data()["identity"]), FrozenRecord.from_dict(task.data()["payload"]))
    if evidence.data().get("schema") != "retrieval-stage-bundle-v1" or rebuild(public, evidence.data()).content_hash != evidence.content_hash:
        raise ContractError("stage controller requires caller-bound source and execution material")
    return {"schema": "retrieval-stage-controller-v1", "bundle": evidence.data()}


def admit_sources(session, provider, admission, authority, docs, *, provenance=False):
    pool = FrozenSourceBundle("public-train-retrieval-pool-v1", docs)
    if not callable(getattr(provider, "search", None)) or not callable(admission): raise ContractError("caller source provider and admission are required")
    receipt = admission(session.task, pool)
    expected = FrozenRecord.from_dict({"schema": "public-train-retrieval-admission-v1", "identity": session.task.identity.data(),
        "task_digest": session.task.content_hash, "source_bundle_digest": pool.content_hash,
        "public_train_safe": True, "scientific_verified": False})
    if not isinstance(receipt, FrozenRecord) or receipt.content_hash != expected.content_hash: raise ContractError("source admission binding drift")
    session._record("q8_source_admission", {"receipt": receipt.data(), "receipt_digest": receipt.content_hash})
    if provenance:
        subject = FrozenRecord.from_dict({"identity": session.task.identity.data(), "task_digest": session.task.content_hash,
            "source_bundle_digest": pool.content_hash, "sources": [doc.data() for doc in docs]})
        if not callable(getattr(authority, "verify_provenance", None)): raise ContractError("caller provenance authority is required")
        checked = authority.verify_provenance(subject)
        expected = FrozenRecord.from_dict({"schema": "source-provenance-authority-v1", "subject_digest": subject.content_hash,
            "provenance_verified": True, "scientific_verified": False})
        if not isinstance(checked, FrozenRecord) or checked.content_hash != expected.content_hash: raise ContractError("source provenance authority rejected or drifted")
        session._record("q84_provenance_admission", {"subject": subject.data(), "receipt": checked.data()})
    return pool


@dataclass(frozen=True)
class RetrievalStagePanelDriver:
    experiment_id: str
    provider: Any = None
    admission_port: Any = None
    authority: Any = None
    broker: Any = None
    input_resolver: Any = None
    slots: tuple[str, ...] = ("research", "competition", "distinguish", "review_a", "review_b", "retro_blind", "retro_reveal", "frontier", "final")
    execution_limit: int = 1
    docker_execution: str = "one fixed public CSV execution in Q81 distinguish only"
    def slots_for_variant(self, variant): return SLOTS[variant] if self.experiment_id == "Q8.1" else ("final",)
    def slots_for(self, cell): return self.slots_for_variant(cell.variant)
    def run(self, workflow, *, cell, scenario, model, package):
        from research_loop.modular.m6_public_inputs import M6PublicInputBoundary
        workflow.public_input_boundary = M6PublicInputBoundary(self.experiment_id, cell.variant)
        session = workflow.session; task = session.task; body = scenario.data()
        if set(body) != {"experiment_id", "variant", "controller_input", "base", "controls"} or body["experiment_id"] != self.experiment_id or body["variant"] != cell.variant:
            raise ContractError("stage scenario binding drift")
        ctrl = body["controller_input"]
        if not isinstance(ctrl, Mapping) or set(ctrl) != {"schema", "bundle"} or ctrl["schema"] != "retrieval-stage-controller-v1": raise ContractError("stage controller binding drift")
        bundle = FrozenRecord.from_dict(ctrl["bundle"]); data = bundle.data()
        if rebuild(task, data).content_hash != bundle.content_hash or body["base"] != {"task": task.content_hash, "evidence": bundle.content_hash, "budget": body["base"].get("budget")}:
            raise ContractError("stage task or source bundle drift")
        _digest(body["base"]["budget"], "budget digest")
        if set(body["controls"]) != {"same_task", "same_evidence", "same_budget"} or not all(strict_bool(v,k) for k,v in body["controls"].items()): raise ContractError("stage controls drift")
        if cell.identity != task.identity or cell.task_digest != task.content_hash or cell.scenario_digest != scenario.content_hash or cell.package_digest != package.digest or cell.coverage_id != self.experiment_id:
            raise ContractError("stage cell binding drift")
        if task.identity not in TrainingManifest(FrozenRecord.from_dict(package.record.data()["training_manifest"])).identities(): raise ContractError("package omits train task")
        if self.experiment_id == "Q8.4":
            detail = self._provenance(workflow, cell, data)
            stage = workflow._trace("stage_0.5", "executed", **detail)
        else:
            detail, stage = self._stage(workflow, cell, data, bundle, model)
        final = workflow.invoke_model("final", model, instruction="Report the observed public stage result under the fixed objective. Public provenance and successful execution are not scientific validation.", evidence_only=True,
            module_context=FrozenRecord.from_dict({"panel_cell": opaque_panel_cell_binding(cell), "required_objective_digest": session.objective.content_hash, "retrieval_stage_result": detail}))
        responses = tuple(FrozenRecord.from_dict(event.data()["data"]["response"]) for event in session._events if event.data()["stage"] == "model_response")
        return stage, _candidate(final, session.objective.content_hash), responses

    def _provenance(self, workflow, cell, data):
        session = workflow.session; docs = _docs(data["sources"][cell.variant]); budget = data["budget"]
        pool = admit_sources(session, self.provider, self.admission_port, self.authority, docs, provenance=True)
        port = RecordedRetrievalProvider(self.provider, session, provider_calls=3, source_cap=3)
        returned = []
        for ordinal in range(3):
            returned.extend(port.search(lane="support", query=FrozenRecord.from_dict({**data["query"], "call_ordinal": ordinal}), source_bundle=pool, source_limit=1))
        # Dedicated source-provenance ledger: admission here cannot mint session
        # scientific evidence or bypass P0. It is the real M2 ledger implementation.
        ledger = EvidenceLedger(session.task.identity, storage_path=session.sidecar / "q84-source-ledger.jsonl")
        records = []
        if "M2" in workflow.enabled:
            for doc in returned:
                records.append(ledger.append({"kind": "observation", "root_material": {"source_root": doc.root_source_id},
                    "representation": "report", "content": doc.data(), "subject_bindings": {"task": session.task.content_hash},
                    "independent_group": session.task.identity.group_id},
                    {"trusted_validator": "caller-source-provenance", "validator_verified": True, "admitted": True}))
        units = []; seen = set()
        dedup = bool({"M2", "M6"} & workflow.enabled)
        admitted_roots = {record.root_id for record in ledger.roots()} if "M2" in workflow.enabled else set()
        for index, doc in enumerate(returned):
            if "M2" in workflow.enabled and records[index].root_id not in admitted_roots: continue
            if dedup and doc.root_source_id in seen: continue
            seen.add(doc.root_source_id); units.append(doc.data())
        result = {"source_bundle_digest": pool.content_hash, "units": [], "unit_basis": "source_root" if dedup else "document",
                  "scientific_independence": "not_established", "scientific_evidence_admitted": False}
        excluded = []
        for doc in units:
            proposed = {**result, "units": result["units"] + [doc]}
            if len(FrozenRecord.from_dict(proposed).encoded.encode("utf-8")) > budget["context_bytes"]: excluded.append(doc["source_id"])
            else: result = proposed
        session._record("q84_source_accounting", {"returned_document_count": len(returned), "context_unit_count": len(result["units"]),
            "m2_admitted_records": len(records), "m2_admitted_roots": len(admitted_roots), "ledger_digest": ledger.version,
            "excluded_context_budget": excluded, "incremental_m6_given_m2": "mechanistically_redundant_expected_null", "scientific_verified": False})
        # Each EvidenceLedger append is already fsynced.  Mirror the separate
        # Q8.4 source journal before subsequent controller/model work.
        from research_loop.modular.retrieval_artifacts import append_q84_source_ledger_artifacts
        append_q84_source_ledger_artifacts(session.artifacts, ledger_path=session.sidecar/"q84-source-ledger.jsonl",
            task=session.task, m2_enabled="M2" in workflow.enabled, m6_enabled="M6" in workflow.enabled)
        session._record("q8_retrieval_budget", {"limits": budget, "provider_calls": port.calls_used, "unused_provider_calls": 3-port.calls_used,
            "sources_returned": port.sources_returned, "unused_source_slots": 3-port.sources_returned,
            "context_bytes": len(FrozenRecord.from_dict(result).encoded.encode("utf-8")), "external_cost": {"units": None, "status": "unknown"}})
        return result

    def _stage(self, workflow, cell, data, bundle, model):
        session = workflow.session; variant = cell.variant
        detail = {"scientific_verified": False}
        if variant == "research":
            docs = _docs(data["sources"]["research"])
            admit_sources(session, self.provider, self.admission_port, self.authority, docs)
            projection, usage = _select_sources(self.provider, session, docs, data["query"], data["budget"], "Q8.2", "correct", "M6" in workflow.enabled)
            response = workflow.invoke_model("research", model, instruction="Describe the public sources actually available for this question.", evidence_only=True, module_context=FrozenRecord.from_dict({"retrieval": projection}))
            detail.update(retrieval=projection, response_digest=response.content_hash)
            stage = workflow._trace("stage_0.5", "executed", **detail)
        elif variant == "competition":
            response = workflow.invoke_model("competition", model, instruction="Return question, competing operational branches and budget_units. Use the public task and fixed objective.", evidence_only=True)
            if set(response.data()) != {"question", "branches", "budget_units"}: raise ContractError("competitive plan schema mismatch")
            plan = workflow.predictions.freeze(**response.data())
            detail["plan_digest"] = plan.payload.content_hash
            stage = workflow._trace("stage_1", "executed", **detail)
        elif variant == "distinguish":
            detail.update(self._execute(session, data, bundle))
            response = workflow.invoke_model("distinguish", model, instruction="Describe the actual distinguishing execution feedback; preserve failed or unknown outcomes.", evidence_only=True,
                module_context=FrozenRecord.from_dict(detail))
            detail["response_digest"] = response.content_hash
            stage = workflow._trace("stage_3", "executed", **detail)
        elif variant == "adversarial":
            review = workflow.independent_review((("review_a", "mechanism", "What observable would refute this account?", "source-a"),
                ("review_b", "measurement", "What measurement failure could imitate the result?", "source-b")), model, evidence_snapshot=session.evidence.version)
            detail["review_result"] = review.detail.data()
            stage = workflow._trace("stage_7", "executed", **detail)
        elif variant == "retrospective":
            stage = workflow.retrospective("retro_blind", "retro_reveal", model, history_summary=FrozenRecord.from_dict({"text": data["history"]}))
            detail["review_result"] = stage.detail.data()
        else:
            stage = workflow.frontier_audit("frontier", model)
            detail["frontier"] = stage.detail.data()["result"]
        if variant != "research":
            session._record("q8_retrieval_budget", {"limits": data["budget"], "provider_calls": 0, "unused_provider_calls": 3,
                "sources_returned": 0, "unused_source_slots": 3, "context_bytes": 0,
                "reason": "retrieval outside selected protocol stage", "external_cost": {"units": None, "status": "unknown"}})
        records = {name: {"reason": "outside selected protocol coverage scenario"} for name in STAGES}
        # Bind the actual stage event, never the trailing budget event.
        records[STAGE[variant]] = {"trace_digest": next(event.content_hash for event in reversed(session._events)
            if event.data()["stage"] == "modular_workflow" and event.data()["data"].get("stage") == STAGE[variant])}
        workflow.record_stages(records)
        session._record("q81_execution_budget", {"opportunities": 1, "executed": int(variant == "distinguish"), "unused": int(variant != "distinguish")})
        return detail, stage

    def _execute(self, session, data, bundle):
        if not isinstance(self.broker, DockerExecutionBroker) or not callable(self.input_resolver) or not callable(getattr(self.authority, "verify_execution", None)):
            raise ContractError("stage execution needs actual broker, exported inputs and authority")
        spec = data["execution"]; paths = self.input_resolver(session.task, bundle)
        if not isinstance(paths, Mapping) or set(paths) != {"public_csv"}: raise ContractError("stage input set drift")
        expected = {"artifact_id": "public_csv", "sha256": spec["input_sha256"], "byte_count": spec["input_byte_count"]}
        artifacts = self.broker.validate_inputs(session.task.identity, paths)
        if len(artifacts) != 1 or artifacts[0].record.data() != expected: raise ContractError("stage exported input hash drift")
        session._record("q81_execution_reservation", {"execution_opportunities": 1, "execution_reserved": 1, "external_cost": None})
        execution = session.execute(spec["program"], broker=self.broker, image=spec["image"], inputs=paths)
        program_bytes = spec["program"].encode("utf-8").replace(b"\n", os.linesep.encode("ascii"))
        if execution.artifact is None or execution.artifact.sha256 != hashlib.sha256(program_bytes).hexdigest() or Path(execution.artifact.path).read_bytes() != program_bytes:
            raise ContractError("stage executed program differs from literal caller program")
        raw = paths["public_csv"].read_bytes()
        if hashlib.sha256(raw).hexdigest() != spec["input_sha256"] or len(raw) != spec["input_byte_count"] or execution.record.data().get("input_artifacts") != {"public_csv": expected}:
            raise ContractError("stage execution input changed")
        subject = FrozenRecord.from_dict({"identity": session.task.identity.data(), "task_digest": session.task.content_hash,
            "objective_digest": session.objective.content_hash, "execution": execution.data(), "execution_digest": execution.content_hash,
            "input_bytes_hex": raw.hex(), "declaration": spec})
        receipt = self.authority.verify_execution(subject)
        expected_receipt = FrozenRecord.from_dict({"schema": "q81-execution-authority-v1", "subject_digest": subject.content_hash,
            "execution_observed": execution.status == "succeeded", "scientific_verified": False})
        if not isinstance(receipt, FrozenRecord) or receipt.content_hash != expected_receipt.content_hash: raise ContractError("execution authority binding drift")
        session._record("q81_execution_authority", {"subject": subject.data(), "receipt": receipt.data()})
        return {"execution_digest": execution.content_hash, "execution_status": execution.status,
            "execution_authority_digest": receipt.content_hash, "scientific_verified": False}
