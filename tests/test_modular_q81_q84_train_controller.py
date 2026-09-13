"""64-cell custody/controller test with real Docker and fixture model transport."""
import hashlib
import json
from pathlib import Path
import pytest
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.modules.evidence import EvidenceLedger
from research_loop.modular.panel_plan import obligation_grids, executable_arms
from research_loop.modular.retrieval_stage_panel_drivers import freeze_retrieval_stage_bundle, STAGE
from research_loop.modular.runtime import AuditVerifier, verify_trace
from research_loop.modular.train_controller import FrozenTrainControllerConfig, run_train_panel
from research_loop.ontology import ContractError
from test_modular_train_controller import snapshot_and_custody, config, model_port, FINAL, REVIEW, SCENARIO
from test_modular_retrieval_panel_drivers import admission

IMAGE = "research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349"
PROGRAM = "import csv, json\nwith open('/input/public_csv', newline='') as f:\n rows=list(csv.DictReader(f))\nprint(json.dumps({'rows': len(rows), 'sum': sum(float(r['x']) for r in rows)}))\n"
ANALYSIS = {"type": "object", "properties": {"analysis": {"type": "string"}}, "required": ["analysis"], "additionalProperties": False}
FRONTIER = {"type": "object", "properties": {"proposals": {"type": "array", "items": {"type": "object"}, "maxItems": 0}, "empty_reason": {"type": "string"}, "programme_complete": {"type": "boolean", "enum": [False]}}, "required": ["proposals", "empty_reason", "programme_complete"], "additionalProperties": False}


def sources():
    rows = [{"source_id": f"report-{i}", "root_source_id": "shared-experiment", "lane": "support", "text": f"Public report {i} records the same measurement procedure and an observation of x."} for i in range(3)]
    return {"shared_root": rows, "independent_roots": [{**doc, "root_source_id": f"experiment-{i}"} for i,doc in enumerate(rows)],
            "research": [{"source_id": lane, "root_source_id": lane, "lane": lane, "text": "Public source about " + lane} for lane in ("support", "counter", "method")]}


def bundle(packet):
    raw = packet.csv_path.read_bytes()
    return freeze_retrieval_stage_bundle(packet.task, query={"task_digest": packet.task.content_hash, "question": "fixed public task question"},
        budget={"provider_calls": 3, "source_cap": 3, "context_bytes": 4096}, sources=sources(), history="Prior public interpretation remains a hypothesis until checked.",
        execution={"program": PROGRAM, "image": IMAGE, "input_sha256": hashlib.sha256(raw).hexdigest(), "input_byte_count": len(raw)})


class Provider:
    def __init__(self): self.calls = []
    def search(self, *, lane, query, source_bundle, call_limit, source_limit):
        self.calls.append((lane, query.data(), source_bundle.content_hash, call_limit, source_limit))
        docs = [doc for doc in source_bundle.documents if doc.lane == lane]
        ordinal = query.data()["call_ordinal"] if len(docs) == 3 else 0
        return docs[ordinal:ordinal+source_limit]


class Authority:
    def __init__(self): self.executions = []; self.provenance = []
    def verify_provenance(self, subject):
        body = subject.data(); assert body["identity"]["domain"] == "train"
        expected = sources()
        normalized = lambda rows: [{**row, "text": {"text": row["text"]}} for row in rows]
        assert body["sources"] in [normalized(expected["shared_root"]), normalized(expected["independent_roots"])]
        self.provenance.append(subject)
        return FrozenRecord.from_dict({"schema": "source-provenance-authority-v1", "subject_digest": subject.content_hash,
            "provenance_verified": True, "scientific_verified": False})
    def verify_execution(self, subject):
        body = subject.data(); receipt = body["execution"]; spec = body["declaration"]
        assert receipt["identity"] == body["identity"] and body["identity"]["domain"] == "train"
        assert spec["image"] == IMAGE and spec["program"] == PROGRAM
        assert hashlib.sha256(bytes.fromhex(body["input_bytes_hex"])).hexdigest() == spec["input_sha256"]
        assert receipt["status"] == "succeeded", receipt
        assert json.loads(receipt["record"]["stdout"]) == {"rows": 1, "sum": 1.0}
        assert Path(receipt["artifact"]["path"]).is_file()
        self.executions.append(subject)
        return FrozenRecord.from_dict({"schema": "q81-execution-authority-v1", "subject_digest": subject.content_hash,
            "execution_observed": True, "scientific_verified": False})


def response(request):
    body = request.data(); slot = body["slot"]
    if slot == "final":
        detail = body["module_context"]["retrieval_stage_result"]
        return FrozenRecord.from_dict({"objective_digest": body["module_context"]["required_objective_digest"], "outcome": "unknown", "evidence_ids": [],
            "conclusion": "Observed public source units: " + str(len(detail["units"])) if "units" in detail else "Observed public stage; scientific outcome unresolved.", "programme_complete": False})
    if slot == "competition":
        return FrozenRecord.from_dict({"question": "What distinguishes the public mechanisms?", "budget_units": 2,
            "branches": [{"hypothesis_id": "h"+str(i), "mechanism_key": "m"+str(i), "mechanism": "public mechanism "+str(i), "intervention": "measure x", "elimination_condition": "contrary direction",
                "predictions": [{"prediction_id": "p"+str(i), "discriminator_id": "x", "observable": "x", "direction": direction, "value_range": None, "failure_condition": "contrary result"}]} for i,direction in enumerate(("increase", "decrease"))]})
    if slot in {"research", "distinguish"}: return FrozenRecord.from_dict({"analysis": "Observed supplied public context and execution feedback."})
    if slot == "frontier": return FrozenRecord.from_dict({"proposals": [], "empty_reason": "No supported new proposal in this fixture.", "programme_complete": False})
    return FrozenRecord.from_dict({"assessment": "unknown", "evidence_refs": [], "counterexamples": [], "uncertainty": "public fixture remains scientifically unresolved"})


def test_q81_q84_full_custody_controller_grid_real_docker(tmp_path, monkeypatch):
    snapshot, custody = snapshot_and_custody(tmp_path)
    base = config(custody, snapshot, tmp_path).data()
    from evaluation.modular.train_io import TrainPacketExporter
    packets = TrainPacketExporter(custody, snapshot, tmp_path / "material").export(base["item_ids"])
    evidence = {packet.task.content_hash: bundle(packet).data() for packet in packets}
    grids = obligation_grids(("Q8.1", "Q8.4"), baseline_digest=base["baseline_digest"], p0_control=FrozenRecord.from_dict(base["p0_control"]))
    package = next(iter(base["packages_by_arm"].values()))
    schemas = {"final": FINAL, "research": ANALYSIS, "competition": SCENARIO, "distinguish": ANALYSIS,
        "review_a": REVIEW, "review_b": REVIEW, "retro_blind": REVIEW, "retro_reveal": REVIEW, "frontier": FRONTIER}
    frozen = FrozenTrainControllerConfig(FrozenRecord.from_dict({**base, "schema": "train-panel-controller-v1", "engineering_scope": "train_only_panel_engineering",
        "stage": "q81-q84-controller", "scope_ids": ["Q8.1", "Q8.4"], "evidence_by_task": evidence,
        "packages_by_arm": {arm.content_hash: package for grid in grids.values() for arm in executable_arms(grid).values()},
        "budget": {"model_calls": 3, "retrieval_calls": 3, "execution_limit": 1}, "max_calls": 128, "max_tokens": 512, "schemas": schemas}))
    port = model_port(tmp_path, monkeypatch, max_calls=128, max_tokens=512, schemas=schemas, response_factory=response)
    provider, authority = Provider(), Authority()
    result = run_train_panel(frozen, custody=custody, snapshot_root=snapshot, export_root=tmp_path / "export", run_root=tmp_path / "run",
        model=port, audit_verifier=AuditVerifier({"a": b"a"*32, "b": b"b"*32}), retrieval_provider=provider,
        retrieval_admission_port=admission, retrieval_stage_authority=authority)
    assert len(result.runtimes) == 64
    assert all(row.status == "succeeded" for row in result.runtimes), [(row.cell_key, row.failure_reason) for row in result.runtimes if row.status != "succeeded"]
    assert len(port.ledger["calls"]) == 128 and len(provider.calls) == 60
    assert len(authority.executions) == 8 and len(authority.provenance) == 16
    report = verify_grid(result)
    (tmp_path / "independent-authority.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


def verify_grid(result):
    from test_m6_public_input_boundary import verify_actual_public_requests
    cells = {cell.key: cell for cell in result.compiled.panel.cells}; rows = []; q84 = {}
    assert result.receipt.data()["execution_status"] == "engineering_complete"
    assert result.compiled.control.data()["always_enabled"] is True
    assert result.verdict.scientific_verified is False
    for runtime in result.runtimes:
        verify_trace(runtime.trace_path)
        cell = cells[runtime.cell_key]; enabled = set(cell.runtime_arm.data()["enabled"])
        events = [json.loads(line) for line in runtime.trace_path.read_text(encoding="utf-8").splitlines()]
        verify_actual_public_requests(events)
        requests = [event["data"]["request"] for event in events if event["stage"] == "model_request"]
        final = requests[-1]; assert final["slot"] == "final"
        assert final["module_context"]["panel_cell"]["cell_digest"] == FrozenRecord.from_dict(cell.data()).content_hash
        outcome = [event["data"]["response"] for event in events if event["stage"] == "model_response"][-1]
        assert outcome["objective_digest"] == final["module_context"]["required_objective_digest"]
        assert outcome["outcome"] == "unknown" and outcome["evidence_ids"] == []
        assert cell.identity.domain == "train"
        budget = next(event["data"] for event in events if event["stage"] == "q8_retrieval_budget")
        assert budget["limits"] == {"provider_calls": 3, "source_cap": 3, "context_bytes": 4096}
        assert budget["provider_calls"] + budget["unused_provider_calls"] == 3
        assert budget["sources_returned"] + budget["unused_source_slots"] == 3
        if cell.coverage_id == "Q8.1":
            coverage = [event["data"] for event in events if event["stage"] == "modular_workflow" and event["data"]["stage"].startswith("coverage_")]
            assert len(coverage) == 6
            assert {row["stage"] for row in coverage if row["status"] == "executed"} == {"coverage_" + STAGE[cell.variant]}
            assert all(row.get("reason") for row in coverage if row["status"] == "blocked")
            if cell.variant == "distinguish":
                execution = next(event["data"] for event in events if event["stage"] == "execution_result")
                assert execution["status"] == "succeeded" and json.loads(execution["record"]["stdout"]) == {"rows": 1, "sum": 1.0}
                checked = next(event["data"] for event in events if event["stage"] == "q81_execution_authority")
                assert checked["receipt"]["subject_digest"] == FrozenRecord.from_dict(checked["subject"]).content_hash
            elif cell.variant == "competition": assert (runtime.trace_path.parent / "predictions.jsonl").stat().st_size > 0
            elif cell.variant == "research":
                actual = requests[0]["module_context"]["retrieval"]["by_lane"]
                assert sum(map(len,actual.values())) == (3 if "M6" in enabled else 0)
            elif cell.variant == "retrospective":
                assert ("history_summary" in requests[0]["module_context"]) == ("M5" not in enabled)
                assert "history_summary" in requests[1]["module_context"]
            elif cell.variant == "adversarial":
                assert len(requests) == 3
                assert requests[0]["module_context"]["role"] != requests[1]["module_context"]["role"]
                original = next(row['data']['controller_context'] for row in events if row['stage']=='q8_public_model_context')
                assert ("sealed" in original) == ("M5" in enabled)
            else: assert final["module_context"]["retrieval_stage_result"]["frontier"]["programme_complete"] is False
        else:
            detail = final["module_context"]["retrieval_stage_result"]
            accounting = next(event["data"] for event in events if event["stage"] == "q84_source_accounting")
            expected = 1 if cell.variant == "shared_root" and enabled else 3
            assert len(detail["units"]) == expected
            assert outcome["conclusion"] == "Observed public source units: " + str(expected)
            assert len(FrozenRecord.from_dict(detail).encoded.encode("utf-8")) <= budget["context_bytes"] <= 4096
            assert accounting["m2_admitted_records"] == (3 if "M2" in enabled else 0)
            ledger = EvidenceLedger(cell.identity, storage_path=runtime.trace_path.parent / "q84-source-ledger.jsonl")
            assert len(ledger.roots()) == ((1 if cell.variant == "shared_root" else 3) if "M2" in enabled else 0)
            assert final["context"]["records"] == []  # provenance never becomes scientific evidence
            q84[(cell.identity.benchmark, cell.variant, tuple(sorted(enabled)))] = detail["units"]
        rows.append({"cell_key": list(cell.key), "enabled": sorted(enabled), "trace_digest": runtime.trace_digest,
            "trace_sha256": hashlib.sha256(runtime.trace_path.read_bytes()).hexdigest(), "final_request_digest": FrozenRecord.from_dict(final).content_hash,
            "model_calls": len(requests), "budget": budget, "scientific_verified": False})
    for benchmark in ("blade", "discoverybench"):
        assert q84[(benchmark,"shared_root",())] != q84[(benchmark,"shared_root",("M6",))]
        assert q84[(benchmark,"shared_root",("M2",))] == q84[(benchmark,"shared_root",("M2","M6"))]
    return {"schema": "q81-q84-independent-fixture-grid-v1", "denominator": 64, "verified_cells": len(rows), "q81_cells": 48, "q84_cells": 16,
        "model_transport": "fixture", "docker_execution": "real", "docker_executions": 8, "paid_calls": 0,
        "m6_increment_given_m2": "mechanistically_redundant_expected_null", "scientific_verified": False,
        "panel_digest": result.compiled.panel.digest, "p0_control_digest": result.compiled.control.content_hash, "rows": rows}


@pytest.mark.parametrize("fault", ["text", "count", "root", "budget"])
def test_q84_material_must_keep_actual_document_and_budget_controls(tmp_path, fault):
    snapshot, custody = snapshot_and_custody(tmp_path)
    from evaluation.modular.train_io import TrainPacketExporter
    packet = TrainPacketExporter(custody, snapshot, tmp_path/"material").export(["blade:fish"])[0]
    material = bundle(packet).data()
    if fault == "text": material["sources"]["independent_roots"][0]["text"] = {"text": "different intervention"}
    elif fault == "count": material["sources"]["independent_roots"].pop()
    elif fault == "root": material["sources"]["independent_roots"][0]["root_source_id"] = "experiment-1"
    else: material["budget"]["provider_calls"] = 9
    with pytest.raises(ContractError):
        freeze_retrieval_stage_bundle(packet.task, **{key: material[key] for key in ("query", "budget", "sources", "history", "execution")})


@pytest.mark.parametrize("field,value", [("subject_digest", "f"*64), ("provenance_verified", False), ("provenance_verified", 1), ("scientific_verified", True)])
def test_provenance_authority_must_bind_subject_without_claiming_science(tmp_path, field, value):
    from research_loop.modular.retrieval_stage_panel_drivers import admit_sources, _docs
    from test_modular_retrieval_panel_drivers import _task
    from types import SimpleNamespace
    task = _task("blade"); events = []; provider = Provider()
    session = SimpleNamespace(task=task, _record=lambda stage,data: events.append((stage,data)))
    class BadAuthority:
        def verify_provenance(self, subject):
            return FrozenRecord.from_dict({"schema": "source-provenance-authority-v1", "subject_digest": subject.content_hash,
                "provenance_verified": True, "scientific_verified": False, field: value})
    with pytest.raises(ContractError, match="provenance authority rejected"):
        admit_sources(session, provider, admission, BadAuthority(), _docs(sources()["shared_root"]), provenance=True)
    assert provider.calls == [] and all(stage != "q84_provenance_admission" for stage,_ in events)


def test_actual_m2_source_admission_cannot_bypass_p0_scientific_evidence(tmp_path):
    from research_loop.modular.retrieval_stage_panel_drivers import RetrievalStagePanelDriver
    from research_loop.modular.runtime import RunSession
    from research_loop.modular.workflow import ModularWorkflow
    from research_loop.modular.combinations import default_compatibility
    from test_modular_retrieval_panel_drivers import _task
    from types import SimpleNamespace
    task = _task("blade")
    session = RunSession(task, package_digest="public", arm=default_compatibility("a"*64).arm(("M2","M6")),
        objective=FrozenRecord.from_dict({"question": "fixed"}), slots=("final",), execution_limit=0,
        sidecar=tmp_path, verifier=AuditVerifier({"a": b"a"*32,"b": b"b"*32}), required_audit=("measurement",))
    driver = RetrievalStagePanelDriver("Q8.4", Provider(), admission, Authority())
    result = driver._provenance(ModularWorkflow(session), SimpleNamespace(variant="shared_root"),
        {"sources": sources(), "query": {"question": "public", "task_digest": task.content_hash},
         "budget": {"provider_calls": 3, "source_cap": 3, "context_bytes": 4096}})
    ledger = EvidenceLedger(task.identity, storage_path=tmp_path/"q84-source-ledger.jsonl")
    assert len(ledger.roots()) == len(result["units"]) == 1
    candidate = session.invoke("final", lambda _: FrozenRecord.from_dict({"objective_digest": session.objective.content_hash,
        "outcome": "positive", "evidence_ids": [ledger.roots()[0].root_id], "conclusion": "unsupported scientific leap", "programme_complete": False}),
        instruction="Report the fixed objective.", evidence_only=True)
    terminal = session.finish(candidate).data()
    assert terminal["decision"] == "blocked" and terminal["scientific_validated"] is False
    assert {"missing_validated_evidence", "unbound_evidence"} <= set(terminal["reasons"])


def test_complete_q84_factorial_retains_estimable_expected_null(tmp_path):
    from research_loop.modular.retrieval_stage_panel_drivers import RetrievalStagePanelDriver
    from research_loop.modular.runtime import RunSession
    from research_loop.modular.workflow import ModularWorkflow
    from research_loop.modular.combinations import default_compatibility
    from test_modular_retrieval_panel_drivers import _task
    from types import SimpleNamespace
    task = _task("blade"); rows = []
    for variant in ("shared_root", "independent_roots"):
        counts = {}
        for enabled in ((), ("M6",), ("M2",), ("M2","M6")):
            session = RunSession(task, package_digest="public", arm=default_compatibility("a"*64).arm(enabled),
                objective=FrozenRecord.from_dict({"question": "fixed"}), slots=("final",), execution_limit=0,
                sidecar=tmp_path/variant/("-".join(enabled) or "off"), verifier=AuditVerifier({"a":b"a"*32,"b":b"b"*32}), required_audit=("measurement",))
            provider = Provider()
            result = RetrievalStagePanelDriver("Q8.4", provider, admission, Authority())._provenance(
                ModularWorkflow(session), SimpleNamespace(variant=variant), {"sources": sources(),
                "query": {"question": "fixed", "task_digest": task.content_hash},
                "budget": {"provider_calls": 3, "source_cap": 3, "context_bytes": 4096}})
            counts[enabled] = len(result["units"])
            accounting = next(event.data()["data"] for event in session._events if event.data()["stage"] == "q84_source_accounting")
            assert accounting["incremental_m6_given_m2"] == "mechanistically_redundant_expected_null"
            assert len(provider.calls) == 3
            rows.append({"variant": variant, "enabled": list(enabled), "context_units": counts[enabled],
                "provider_calls": len(provider.calls), "annotation": accounting["incremental_m6_given_m2"]})
        assert len(counts) == 4
        assert counts[("M2","M6")] - counts[("M2",)] == 0
        assert counts[("M6",)] - counts[()] == (-2 if variant == "shared_root" else 0)
    (tmp_path/"expected-null-contrasts.json").write_text(json.dumps({"denominator": 8, "verified_cells": len(rows),
        "conditional_increment_estimable": True, "excluded_contrasts": [], "rows": rows}, indent=2), encoding="utf-8")
