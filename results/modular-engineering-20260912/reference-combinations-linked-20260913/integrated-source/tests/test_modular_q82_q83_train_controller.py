"""Custody/controller coverage for the causal Q8.2/Q8.3 retrieval grid."""
import hashlib
import json

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.panel_plan import executable_arms, obligation_grids
from research_loop.modular.retrieval_panel_drivers import freeze_retrieval_bundle
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.train_controller import FrozenTrainControllerConfig, run_train_panel
from test_modular_retrieval_panel_drivers import Provider, _materials, admission
from test_modular_train_controller import FINAL, config, model_port, snapshot_and_custody


def test_q82_q83_custody_controller_full_grid(tmp_path, monkeypatch):
    snapshot, custody = snapshot_and_custody(tmp_path)
    base = config(custody, snapshot, tmp_path).data()
    grid = obligation_grids(("Q8.2", "Q8.3"), baseline_digest=base["baseline_digest"],
                            p0_control=FrozenRecord.from_dict(base["p0_control"]))
    package = next(iter(base["packages_by_arm"].values()))
    packets = __import__("evaluation.modular.train_io", fromlist=["TrainPacketExporter"]).TrainPacketExporter(custody, snapshot, tmp_path / "material").export(base["item_ids"])
    evidence = {packet.task.content_hash: freeze_retrieval_bundle(packet.task,
        query={"task_digest": packet.task.content_hash, "question": "fixed public train query"},
        budget={"provider_calls": 3, "source_cap": 3, "context_bytes": 4096}, materials=_materials()).data() for packet in packets}
    arms = {arm.content_hash: package for item in grid.values() for arm in executable_arms(item).values()}
    frozen = FrozenTrainControllerConfig(FrozenRecord.from_dict({**base, "schema": "train-panel-controller-v1",
        "engineering_scope": "train_only_panel_engineering", "stage": "q82-q83-controller", "scope_ids": ["Q8.2", "Q8.3"],
        "evidence_by_task": evidence, "packages_by_arm": arms, "budget": {"model_calls": 1, "retrieval_calls": 3},
        "max_calls": 48, "schemas": {"final": FINAL}}))
    seen = []
    def response(request):
        seen.append(request.data())
        docs = [doc for lane in request.data()["module_context"]["retrieval"]["by_lane"].values() for doc in lane]
        return FrozenRecord.from_dict({"objective_digest": request.data()["module_context"]["required_objective_digest"], "outcome": "unknown", "evidence_ids": [], "conclusion": "\n".join(doc["text"]["text"] for doc in docs) or "No external source was available.", "programme_complete": False})
    port = model_port(tmp_path, monkeypatch, max_calls=48, schemas=frozen.data()["schemas"], response_factory=response)
    class QueryAwareProvider(Provider):
        def search(self, **kwargs):
            rows = super().search(**kwargs)
            # Fixed public fixture index: a generic query misses the counter record;
            # explicitly seeking counterevidence retrieves it. No arm IDs are read.
            if kwargs["lane"] == "counter" and "counterevidence" not in kwargs["query"].data()["intent"]:
                return ()
            return rows
    provider = QueryAwareProvider()
    result = run_train_panel(frozen, custody=custody, snapshot_root=snapshot, export_root=tmp_path / "export", run_root=tmp_path / "run", model=port, audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}), retrieval_provider=provider, retrieval_admission_port=admission)
    assert len(result.runtimes) == len(seen) == len(port.ledger["calls"]) == 24
    assert all(runtime.status == "succeeded" for runtime in result.runtimes)
    assert len(provider.calls) == 54
    report = independent_fixture_authority(result, evidence)
    (tmp_path / "q82-q83-independent-fixture-authority.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    assert report["verified_cells"] == report["denominator"] == 24
    assert report["scientific_verified"] is False


def independent_fixture_authority(result, frozen_materials):
    """Read actual immutable requests/responses; do not call the driver selection code."""
    from research_loop.modular.runtime import verify_trace
    cells = {cell.key: cell for cell in result.compiled.panel.cells}
    observations, rows = {}, []
    assert result.receipt.data()["execution_status"] == "engineering_complete"
    assert result.receipt.data()["scientific_status"] == "not_measured"
    assert result.compiled.control.data()["always_enabled"] is True
    for runtime in result.runtimes:
        cell = cells[runtime.cell_key]
        assert cell.identity.domain == "train"
        verify_trace(runtime.trace_path)
        raw = runtime.trace_path.read_bytes()
        events = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
        request = next(event["data"]["request"] for event in events if event["stage"] == "model_request")
        response = next(event["data"]["response"] for event in events if event["stage"] == "model_response")
        budget = next(event["data"] for event in events if event["stage"] == "q8_retrieval_budget")
        queries = [event["data"] for event in events if event["stage"] == "q8_retrieval_request"]
        material = frozen_materials[cell.task_digest]["materials"][cell.coverage_id][cell.variant]
        allowed = {doc["source_id"]: doc for doc in material["sources"]}
        projection = request["module_context"]["retrieval"]
        stage = next(event['data'] for event in events if event['stage'] == 'modular_workflow'
            and event['data']['stage'] in {'stage_0.5', 'operation_m6_ordinary_baseline'})
        full_projection = {key: stage[key] for key in ('by_lane', 'source_qualification',
            'scientific_admission', 'policy_digest', 'source_bundle_digest')}
        assert projection == {key: stage[key] for key in ('by_lane', 'source_qualification', 'scientific_admission')}
        actual = [doc for lane in projection["by_lane"].values() for doc in lane]
        assert all(allowed[doc["source_id"]] == doc for doc in actual)
        assert len({doc["root_source_id"] for doc in actual}) == len(actual)
        assert projection["scientific_admission"] is False
        admitted = next(event["data"]["receipt"] for event in events if event["stage"] == "q8_source_admission")
        assert admitted["identity"] == cell.identity.data() and admitted["task_digest"] == cell.task_digest
        assert admitted["source_bundle_digest"] == stage["source_bundle_digest"]
        assert admitted["public_train_safe"] is True and admitted["scientific_verified"] is False
        assert response["objective_digest"] == request["module_context"]["required_objective_digest"]
        assert response["evidence_ids"] == []  # Public sources never become scientific evidence IDs.
        assert response["conclusion"] == ("\n".join(doc["text"]["text"] for doc in actual) or "No external source was available.")
        assert response["outcome"] == "unknown" and response["programme_complete"] is False
        assert request["module_context"]["panel_cell"]["cell_digest"] == FrozenRecord.from_dict(cell.data()).content_hash
        enabled = "M6" in cell.runtime_arm.data()["enabled"]
        assert budget["limits"] == {"provider_calls": 3, "source_cap": 3, "context_bytes": 4096}
        assert budget["provider_calls"] + budget["unused_provider_calls"] == 3
        assert budget["sources_returned"] + budget["unused_source_slots"] == 3
        assert budget["context_bytes"] == len(FrozenRecord.from_dict(full_projection).encoded.encode("utf-8")) <= 4096
        assert len(FrozenRecord.from_dict(projection).encoded.encode('utf-8')) <= budget['context_bytes']
        assert budget["external_cost"]["units"] is None
        if cell.coverage_id == "Q8.2" and not enabled:
            assert actual == [] and queries == []
        else:
            assert len(queries) == 3
            assert all(query["query"]["question"] == "fixed public train query" for query in queries)
        if cell.coverage_id == "Q8.3":
            expected = ["support"] * 3 if enabled and cell.variant == "support_only" else ["support", "counter", "method"]
            assert [query["lane"] for query in queries] == expected
        key = (cell.coverage_id, cell.identity.benchmark, cell.variant, enabled)
        assert key not in observations
        observations[key] = projection["by_lane"]
        rows.append({"cell_key": list(cell.key), "m6_enabled": enabled,
            "trace_sha256": hashlib.sha256(raw).hexdigest(), "trace_chain_digest": runtime.trace_digest,
            "source_bundle_digest": stage["source_bundle_digest"], "request_digest": FrozenRecord.from_dict(request).content_hash,
            "response_digest": FrozenRecord.from_dict(response).content_hash, "source_ids": [doc["source_id"] for doc in actual],
            "usage": budget, "scientific_admission": False})
    for benchmark in ("blade", "discoverybench"):
        for variant in ("correct", "method", "reframe"):
            assert observations[("Q8.2", benchmark, variant, True)] != observations[("Q8.2", benchmark, variant, False)]
        support, neutral, three = [observations[("Q8.3", benchmark, variant, True)] for variant in ("support_only", "neutral", "three_lane")]
        assert support["method"] == support["counter"] == []
        assert neutral["method"] and neutral["counter"] == []
        assert three["support"] and three["method"] and three["counter"]
        off = [observations[("Q8.3", benchmark, variant, False)] for variant in ("support_only", "neutral", "three_lane")]
        assert off[0] == off[1] == off[2]
    return {"schema": "q82-q83-independent-fixture-authority-v1", "denominator": 24,
            "verified_cells": len(rows), "panel_digest": result.compiled.panel.digest,
            "p0_control_digest": result.compiled.control.content_hash, "scientific_verified": False,
            "model_transport": "fixture", "paid_calls": 0, "method_execution": "not_measured",
            "rows": rows}
