"""Two synthetic custody tasks, real CodexModelPort, real Docker, independent rubric RPC."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from evaluation.modular.combination_scoring import CombinationAdaptedScoringService
from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from evaluation.modular.scoring_service import ScorerConfig, FrozenBenchmarkRubricEndpoint, FrozenRubricTransport
from evaluation.modular.train_io import TrainPacketExporter
from research_loop.modular import combination_train_controller as controller
from research_loop.modular.combination_train_controller import FrozenM4M5TrainConfig, SLOTS, run_m4_m5_train_panel
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError
from test_modular_train_controller import snapshot_and_custody, model_port, SCENARIO, REVIEW, FINAL
from test_modular_combination_benchmark_driver import _plan


IMAGE = "research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349"
EXECUTION = LinkedExecutionAuthority("m4m5-execution", b"e" * 32)
SCORER = LinkedExecutionAuthority("m4m5-scorer", b"s" * 32)
ANALYSIS = {"type": "object", "properties": {"analysis": {"type": "string"}, "program": {"type": "string"}},
            "required": ["analysis", "program"], "additionalProperties": False}
SCHEMAS = {"m4_plan": SCENARIO, "m5_mechanism": REVIEW, "m5_measurement": REVIEW,
           "analysis_program": ANALYSIS, "final_answer": FINAL}


def _fixture(root):
    snapshot, custody = snapshot_and_custody(root)
    items = ["discoverybench:synth:train:family_1_1", "blade:fish"]
    packets = TrainPacketExporter(custody, snapshot, root / "material").export(items)
    identities = [p.task.identity for p in packets]
    package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze(identities),
        changes={"prompt": {"instructions": "frozen public train package"}}, search_cost=0)
    arms = default_compatibility("a" * 64).conditional_factorial(("M4", "M5")).data()["cells"]
    scorer = ScorerConfig.create(benchmark="core_pair", evaluator_id="synthetic-independent-evaluator",
        version="v1", rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest())
    handles = {FrozenRecord.from_dict(i.data()).content_hash: "synthetic-handle-" + i.benchmark for i in identities}
    config = FrozenM4M5TrainConfig(FrozenRecord.from_dict({"schema": "m4-m5-train-controller-config-v1", "domain": "train",
        "stage": "synthetic-custody-m4-m5", "item_ids": items, "task_bindings": {
            f"{p.task.identity.benchmark}:{p.task.identity.task_id}": {"identity": p.task.identity.data(),
                "task_digest": p.task.content_hash, "csv_sha256": hashlib.sha256(p.csv_path.read_bytes()).hexdigest()} for p in packets},
        "baseline_digest": "a" * 64, "packages_by_arm": {row["arm_digest"]: package.record.data() for row in arms},
        "scorer": scorer.record.data(), "scorer_handle_bindings": {key: hashlib.sha256(value.encode()).hexdigest() for key, value in handles.items()},
        "acceptance_criteria": {"criterion": "synthetic adapted engineering contrast", "contrast_analysis": controller._ANALYSIS},
        "replicates": ["r1"], "model": "gpt-5.6-luna", "effort": "low", "max_calls": 40, "max_tokens": 200,
        "schemas": SCHEMAS, "allocation": {"model_slots_per_cell": list(SLOTS), "docker_attempts_per_cell": 1,
            "scorer_calls_per_cell": 1, "scorer_call_limit": 8, "scorer_token_accounting": "transport_not_provided"},
        "image": IMAGE, "timeout_seconds": 20}))
    return snapshot, custody, packets, config, scorer, handles


def _service(scorer, handles, calls, *, fail=False):
    def resolver(handle, benchmark):
        return FrozenRecord.from_dict({"schema": "train-only-rubric-reference-v1", "split": "train", "benchmark": benchmark,
            "task_handle_digest": hashlib.sha256(handle.encode()).hexdigest(),
            "identity_digest": next(key for key, value in handles.items() if value == handle),
            "task_context": "synthetic public CSV task", "references": [{"synthetic": True, "mean": 1.0}]})
    def evaluator(request):
        body = request.data(); calls.append(body)
        assert all(token not in body["prompt"] for token in ('"arm_id"', '"enabled"', "pair:M4+M5", "package_digest", "joint_mechanism", "contrast"))
        if fail and len(calls) == 1:
            raise RuntimeError("synthetic independent scorer failure")
        dimensions = {"cvars": 2, "transform": 2, "model": 2} if body["benchmark"] == "blade" else {"context": 1, "variable_f1": 1, "relation": 1}
        return FrozenRecord.from_dict({**dimensions, "reason": "synthetic engineering dimensions"})
    endpoint = FrozenBenchmarkRubricEndpoint(resolver=resolver, evaluator=evaluator,
        evaluator_id="synthetic-independent-evaluator", evaluator_version="v1")
    return CombinationAdaptedScoringService(config=scorer, evaluator=FrozenRubricTransport(endpoint),
        execution_authority_keys={EXECUTION.authority_id: EXECUTION.key}, task_handles=handles, scorer_authority=SCORER)


def _model(seen, *, fail=False):
    def respond(request):
        body = request.data(); seen.append(body)
        assert all(token not in request.encoded for token in ('"arm_id"', '"enabled"', '"contrast"', '"packages_by_arm"', '"scorer_handle_bindings"'))
        if body["slot"] == "m4_plan":
            return FrozenRecord.from_dict(_plan())
        if body["slot"] in ("m5_mechanism", "m5_measurement"):
            return FrozenRecord.from_dict({"assessment": "concern", "evidence_refs": [], "counterexamples": [], "uncertainty": "synthetic"})
        if body["slot"] == "analysis_program":
            if fail:
                raise RuntimeError("synthetic solver transport failure")
            return FrozenRecord.from_dict({"analysis": "mean public x", "program":
                "import csv\nwith open('/input/public_csv', newline='') as f:\n rows=list(csv.DictReader(f))\nprint(sum(float(r['x']) for r in rows)/len(rows))"})
        assert body["slot"] == "final_answer" and body["execution_feedback"][0]["stdout"].strip() == "1.0"
        return FrozenRecord.from_dict({"objective_digest": body["module_context"]["required_objective_digest"],
            "outcome": "unknown", "evidence_ids": [], "conclusion": "The synthetic public mean is 1.0.", "programme_complete": False})
    return respond


def _run(root, monkeypatch, *, fail_model=False, fail_scorer=False, fixture=None, mutate_service=None):
    snapshot, custody, packets, config, scorer, handles = fixture or _fixture(root)
    model_calls, scorer_calls = [], []
    model = model_port(root / "port", monkeypatch, max_calls=40, schemas=SCHEMAS,
        response_factory=_model(model_calls, fail=fail_model))
    service = _service(scorer, handles, scorer_calls, fail=fail_scorer)
    if mutate_service:
        mutate_service(service)
    result = run_m4_m5_train_panel(config, custody=custody, snapshot_root=snapshot, export_root=root / "export", run_root=root / "run",
        model=model, audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}),
        execution_authority=EXECUTION, scoring_service=service, scorer_authority_keys={SCORER.authority_id: SCORER.key})
    return result, model, model_calls, scorer_calls


def test_real_custody_complete_eight_cells_port_docker_signed_scorer_and_contrast(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    result, model, model_calls, scorer_calls = _run(tmp_path, monkeypatch, fixture=fixture)
    receipt = result.receipt.data()
    assert len(result.compiled.panel.cells) == len(result.results) == len(result.attempts) == len(result.scores) == 8
    assert receipt["status"] == "estimated" and receipt["expected_cells"] == receipt["successful_cells"] == 8
    assert receipt["failed_cells"] == receipt["blocked_cells"] == 0 and receipt["pruned_cells"] == []
    assert receipt["scientific_effectiveness_proven"] is receipt["validation_opened"] is False
    assert len(model_calls) == len(model.ledger["calls"]) == 40 and len(scorer_calls) == receipt["actual_scorer_calls"] == 8
    assert {call["slot"] for call in model_calls} == set(SLOTS)
    assert receipt["actual_model_usage"] == {"model_calls": 40, "known_model_tokens": 80, "model_usage_incomplete": False}
    assert all(value["mean"] == 0.0 for value in result.contrast.data()["benchmark_estimates"].values())
    for row, execution in zip(result.attempts, result.results):
        body = row.data()
        assert body["status"] == "succeeded" and body["phase"] == "verified" and body["scorer_calls"] == 1
        assert execution.solver.execution.status == "succeeded"
        assert body["execution_receipt"]["record"]["stdout"].strip() == "1.0"
        assert body["score_input"]["body"]["runtime_trace_digest"] == execution.runtime.trace_digest
        assert body["scorer_receipt"]["body"]["scorer_digest"] == execution.cell.scorer_digest
        assert body["model_usage_after"]["model_calls"] - body["model_usage_before"]["model_calls"] == 5
    for benchmark in ("blade", "discoverybench"):
        assert {cell.arm_id for cell in result.compiled.panel.cells if cell.identity.benchmark == benchmark} == {"00", "01", "10", "11"}
    before = (tmp_path / "run" / "controller-attempt.json").read_bytes()
    # Reusing a partially/fully used ledger never restarts the panel.
    with pytest.raises(ContractError):
        run_m4_m5_train_panel(fixture[3], custody=fixture[1],
            snapshot_root=tmp_path / "public-snapshot", export_root=tmp_path / "export", run_root=tmp_path / "run", model=model,
            audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}), execution_authority=EXECUTION,
            scoring_service=_service(fixture[4], fixture[5], []),
            scorer_authority_keys={SCORER.authority_id: SCORER.key})
    assert (tmp_path / "run" / "controller-attempt.json").read_bytes() == before


@pytest.mark.parametrize("fault", ["solver", "scorer", "source_verification", "foreign_cell", "score_verification"])
def test_failed_stage_keeps_complete_denominator_calls_and_inconclusive(tmp_path, monkeypatch, fault):
    if fault == "source_verification":
        original = controller.verify_m4_m5_combination_benchmark_cell
        called = []
        def reject_first(*args, **kwargs):
            called.append(1)
            if len(called) == 1:
                raise ContractError("synthetic source verification failure")
            return original(*args, **kwargs)
        monkeypatch.setattr(controller, "verify_m4_m5_combination_benchmark_cell", reject_first)
    if fault == "foreign_cell":
        original = controller.run_m4_m5_combination_benchmark_cell
        called = []
        def foreign(**kwargs):
            result = original(**kwargs); called.append(1)
            return replace(result, cell=kwargs["panel"].cells[1]) if len(called) == 1 else result
        monkeypatch.setattr(controller, "run_m4_m5_combination_benchmark_cell", foreign)
    def mutate(service):
        if fault == "score_verification":
            original = service.score_combination
            called = []
            def forged(**kwargs):
                score = original(**kwargs); called.append(1)
                if len(called) == 1:
                    envelope = score.receipt.data(); envelope["body"]["candidate_digest"] = "0" * 64
                    return replace(score, receipt=FrozenRecord.from_dict(envelope))
                return score
            service.score_combination = forged
    result, model, model_calls, scorer_calls = _run(tmp_path, monkeypatch, fail_model=fault == "solver",
        fail_scorer=fault == "scorer", mutate_service=mutate)
    body = result.receipt.data()
    assert body["status"] == result.contrast.data()["status"] == "inconclusive"
    assert body["expected_cells"] == body["observed_cells"] == len(result.attempts) == 8
    assert body["pruned_cells"] == [] and body["failed_cells"] >= 1
    first = result.attempts[0].data()
    assert first["model_usage_after"]["model_calls"] > 0
    if fault == "solver":
        assert len(model_calls) == 4 and len(scorer_calls) == 0
        assert body["blocked_cells"] == 7 and body["scored_cells"] == 0
        assert body["actual_model_usage"]["model_usage_incomplete"] is True
    else:
        assert len(model_calls) == 40 and body["scored_cells"] == 7
        assert len(scorer_calls) == (7 if fault in ("source_verification", "foreign_cell") else 8)
        assert first["model_usage_after"]["known_model_tokens"] == 10
        assert first["phase"] == {"source_verification": "source_verification", "foreign_cell": "source_verification",
                                  "scorer": "scoring", "score_verification": "score_verification"}[fault]
        assert first["scorer_calls"] == (0 if fault in ("source_verification", "foreign_cell") else 1)


@pytest.mark.parametrize("mutation", ["validation", "missing_arm", "extra_arm", "calls", "tokens_bool", "docker_bool",
    "scorer_budget", "schema_missing", "schema_bad", "csv_hash", "task_identity", "scorer_config", "missing_handle", "criteria"])
def test_bad_frozen_configuration_rejected_without_execution(tmp_path, mutation):
    body = _fixture(tmp_path)[3].data()
    if mutation == "validation": body["domain"] = "validation"
    elif mutation == "missing_arm": body["packages_by_arm"].pop(next(iter(body["packages_by_arm"])))
    elif mutation == "extra_arm": body["packages_by_arm"]["0" * 64] = next(iter(body["packages_by_arm"].values()))
    elif mutation == "calls": body["max_calls"] -= 1
    elif mutation == "tokens_bool": body["max_tokens"] = True
    elif mutation == "docker_bool": body["allocation"]["docker_attempts_per_cell"] = True
    elif mutation == "scorer_budget": body["allocation"]["scorer_call_limit"] = 7
    elif mutation == "schema_missing": del body["schemas"]["m4_plan"]
    elif mutation == "schema_bad": body["schemas"]["m4_plan"] = {"type": "string"}
    elif mutation == "csv_hash": next(iter(body["task_bindings"].values()))["csv_sha256"] = "name"
    elif mutation == "task_identity": next(iter(body["task_bindings"].values()))["identity"]["domain"] = "validation"
    elif mutation == "scorer_config": body["scorer"]["reference_access"] = "caller_material"
    elif mutation == "missing_handle": body["scorer_handle_bindings"].pop(next(iter(body["scorer_handle_bindings"])))
    elif mutation == "criteria": body["acceptance_criteria"]["contrast_analysis"]["missing_policy"] = "drop_failed"
    with pytest.raises(ContractError):
        FrozenM4M5TrainConfig(FrozenRecord.from_dict(body))
    assert not (tmp_path / "run").exists() and not (tmp_path / "export").exists()


@pytest.mark.parametrize("drift", ["same_key", "foreign_execution", "foreign_scorer", "schema", "source", "handles"])
def test_live_provenance_drift_is_rejected_before_provider_calls(tmp_path, monkeypatch, drift):
    fixture = _fixture(tmp_path)
    snapshot, custody, packets, config, scorer, handles = fixture
    seen, scored = [], []
    model = model_port(tmp_path / "port", monkeypatch, max_calls=40, schemas=SCHEMAS, response_factory=_model(seen))
    service = _service(scorer, handles, scored)
    authority, keys = EXECUTION, {SCORER.authority_id: SCORER.key}
    if drift == "same_key": authority = LinkedExecutionAuthority("another-execution", SCORER.key)
    elif drift == "foreign_execution": authority = LinkedExecutionAuthority("foreign", b"f" * 32)
    elif drift == "foreign_scorer": keys = {"foreign": b"f" * 32}
    elif drift == "schema": model.schemas = {**model.schemas, "unexpected": ANALYSIS}
    elif drift == "handles": service._handles[next(iter(service._handles))] = "different-reference"
    elif drift == "source":
        body = config.data(); next(iter(body["task_bindings"].values()))["csv_sha256"] = "0" * 64
        config = FrozenM4M5TrainConfig(FrozenRecord.from_dict(body))
    with pytest.raises(ContractError):
        run_m4_m5_train_panel(config, custody=custody, snapshot_root=snapshot, export_root=tmp_path / "export", run_root=tmp_path / "run",
            model=model, audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}),
            execution_authority=authority, scoring_service=service, scorer_authority_keys=keys)
    assert seen == scored == model.ledger["calls"] == []
    if drift == "source":
        receipt = json.loads((tmp_path / "run" / "controller-attempt.json").read_text())
        assert receipt["status"] == "blocked_before_execution" and receipt["actual_model_usage"]["model_calls"] == 0
    else:
        assert not (tmp_path / "run").exists() and not (tmp_path / "export").exists()


def test_execution_allocation_failure_keeps_all_cells_without_retry_or_provider_calls(tmp_path, monkeypatch):
    attempts = []
    def unavailable(*args, **kwargs):
        attempts.append(1)
        raise ContractError("synthetic broker preflight failure")
    monkeypatch.setattr(controller, "DockerExecutionBroker", unavailable)
    result, model, model_calls, scorer_calls = _run(tmp_path, monkeypatch)
    assert attempts == [1] and model_calls == scorer_calls == model.ledger["calls"] == []
    receipt = result.receipt.data()
    assert receipt["status"] == "inconclusive" and receipt["expected_cells"] == receipt["blocked_cells"] == 8
    assert receipt["actual_scorer_calls"] == 0 and receipt["pruned_cells"] == []
    assert all(row.data()["phase"] == "execution_allocation" for row in result.attempts)
