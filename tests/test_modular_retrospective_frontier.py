import pytest

from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.runtime import AuditVerifier, RunSession, verify_trace
from research_loop.modular.workflow import ModularWorkflow, STAGES
from research_loop.ontology import ContractError


def make(path, benchmark, *, enabled=("M2", "M3", "M5"), domain="train", slots=("blind", "reveal", "frontier")):
    identity = DataIdentity(benchmark, "fixture", "source", "v1", "split", domain)
    if benchmark == "blade":
        task = BladeAdapter().prepare(identity, {"task_id": "fixture", "dataset_id": "d", "research_question": "q", "data_schema": [{"name": "x"}]})
    else:
        task = DiscoveryBenchAdapter().prepare(identity, {"task_id": "fixture", "question": "q", "source_kind": "synthetic", "dataset": [{"name": "d", "columns": [{"name": "x"}]}]})
    return ModularWorkflow(RunSession(task, package_digest="pkg", arm=default_compatibility("base").arm(enabled),
        objective=FrozenRecord.from_dict({"question": "q"}), slots=slots, execution_limit=1, sidecar=path,
        verifier=AuditVerifier({"a": b"a"*32, "b": b"b"*32}), required_audit=("measurement",)))


def review(assessment="unknown"):
    return FrozenRecord.from_dict({"assessment": assessment, "evidence_refs": [], "counterexamples": [], "uncertainty": "fixture only"})


def proposal():
    return {"origin_ref": "boundary:objective", "kind": "boundary", "question": "Does effect reverse beyond the observed range?",
            "observable": "out-of-range effect sign", "opposing_predictions": ["positive", "negative"]}


@pytest.mark.parametrize("benchmark", ["blade", "discoverybench"])
def test_actual_blind_seal_reveal_frontier_and_train_export(tmp_path, benchmark):
    workflow = make(tmp_path / benchmark, benchmark)
    workflow.session.claims.create("HIDDEN_CLAIM_SUMMARY", subject_bindings={"task": "fixture"})
    seen = []
    def model(request):
        seen.append(request)
        if request.data()["slot"] == "frontier":
            return FrozenRecord.from_dict({"proposals": [proposal()], "empty_reason": None, "programme_complete": False})
        return review("concern" if request.data()["slot"] == "reveal" else "unknown")
    result = workflow.retrospective("blind", "reveal", model, history_summary=FrozenRecord.from_dict({"text": "HIDDEN_HISTORY"}))
    assert len(seen) == 2 and result.detail.data()["before_digest"] != result.detail.data()["after_digest"]
    assert "HIDDEN_HISTORY" not in seen[0].encoded and "HIDDEN_CLAIM_SUMMARY" not in seen[0].encoded
    assert "HIDDEN_HISTORY" in seen[1].encoded and "sealed_first_review" in seen[1].encoded
    assert workflow.frontier_audit("frontier", model).status == "executed"
    exported = workflow.training_followups().data()
    assert exported["proposals"][0]["origin_ref"] == "boundary:objective"
    assert exported["benchmark_admission"] is False and exported["programme_complete"] is False
    assert verify_trace(workflow.session.sidecar / "trace.jsonl").data()["stages"].count("model_request") == 3
    stages = {stage: {"reason": "outside this fixture"} for stage in STAGES}
    for event in workflow.session._events:
        row = event.data()
        if row["stage"] == "modular_workflow" and row["data"]["stage"] in {"stage_9", "frontier"}:
            stages[row["data"]["stage"]] = {"trace_digest": event.content_hash}
    assert [result.status for result in workflow.record_stages(stages)][-2:] == ["executed", "executed"]


def test_control_uses_same_two_calls_with_summary_first(tmp_path):
    workflow = make(tmp_path / "control", "blade", enabled=(), slots=("blind", "reveal"))
    seen = []
    def model(request):
        seen.append(request)
        return review()
    result = workflow.retrospective("blind", "reveal", model, history_summary=FrozenRecord.from_dict({"text": "VISIBLE_FIRST"}))
    assert len(seen) == 2 and all("VISIBLE_FIRST" in item.encoded for item in seen)
    assert result.detail.data()["method"] == "summary_first_control"


@pytest.mark.parametrize("change", ["invented_origin", "same_prediction", "completion", "evaluation_authority"])
def test_frontier_rejects_unbound_or_unearned_outputs(tmp_path, change):
    workflow = make(tmp_path / change, "blade", slots=("frontier",))
    body = {"proposals": [proposal()], "empty_reason": None, "programme_complete": False}
    if change == "invented_origin": body["proposals"][0]["origin_ref"] = "missing"
    if change == "same_prediction": body["proposals"][0]["opposing_predictions"] = ["same", "same"]
    if change == "completion": body["programme_complete"] = True
    if change == "evaluation_authority": body["benchmark_admission"] = True
    with pytest.raises(ContractError):
        workflow.frontier_audit("frontier", lambda _: FrozenRecord.from_dict(body))
    assert workflow.frontier_result is None
    assert workflow.session._next_call == 1


def test_validation_empty_frontier_never_exports_into_optimization(tmp_path):
    workflow = make(tmp_path / "validation", "discoverybench", domain="validation", slots=("frontier",))
    result = workflow.frontier_audit("frontier", lambda _: FrozenRecord.from_dict({"proposals": [], "empty_reason": "No new discriminating proposal in this fixture", "programme_complete": False}))
    assert result.detail.data()["result"]["programme_complete"] is False
    with pytest.raises(ContractError, match="training provenance"):
        workflow.training_followups()


def test_stage_coverage_cannot_relabel_lock_as_executed_frontier(tmp_path):
    workflow = make(tmp_path / "coverage", "blade")
    records = {stage: {"reason": "outside fixture"} for stage in STAGES}
    records["frontier"] = {"trace_digest": workflow.session._events[0].content_hash}
    with pytest.raises(ContractError, match="this executed stage"):
        workflow.record_stages(records)
