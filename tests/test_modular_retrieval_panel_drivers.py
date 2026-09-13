"""Synthetic public grid checks for typed Q8.2/Q8.3 retrieval drivers."""
from pathlib import Path

import pytest

from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_receipts import PanelCell
from research_loop.modular.retrieval_panel_drivers import RetrievalPanelDriver, _SCOPE, freeze_retrieval_bundle, retrieval_panel_injection
from research_loop.modular.runtime import AuditVerifier, RunSession
from research_loop.modular.workflow import ModularWorkflow
from research_loop.ontology import ContractError


SPLIT = "8" * 64


def _task(name):
    identity = DataIdentity(name, "retrieval-" + name, name + ":retrieval", "synthetic-v1", SPLIT, "train")
    if name == "blade": return BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": "public", "research_question": "Synthetic public question", "data_schema": [{"name": "x", "dtype": "float"}]})
    return DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id, "question": "Synthetic public question", "source_kind": "synthetic", "dataset": [{"name": "public", "columns": [{"name": "x"}]}]})


def _docs(root_prefix="root", text_prefix="public"):
    return [{"source_id": "support", "root_source_id": root_prefix + "-s", "lane": "support", "text": text_prefix + " support"}, {"source_id": "counter", "root_source_id": root_prefix + "-c", "lane": "counter", "text": text_prefix + " counter"}, {"source_id": "method", "root_source_id": root_prefix + "-m", "lane": "method", "text": text_prefix + " method"}]


def _signals(**active):
    return {"new_mechanism": False, "key_conflict": False, "innovation_claim": False, "dependency_unknown": False, "stagnation": False, "cheap_distinguishing_diagnostic_locked": False, **active}


def _materials():
    data = {name: {} for name in _SCOPE}
    contributions = {
        "correct": "A calibration record shows instrument readings are offset by 2 units; subtract 2 from each recorded reading.",
        "method": "A runnable standard-library method computes the mean: import csv; rows=list(csv.DictReader(open('data.csv'))); print(sum(float(r['x']) for r in rows)/len(rows)).",
        "reframe": "Only observational measurements are available; rephrase the causal-effect question as an association question pending a randomized intervention."}
    for v in _SCOPE["Q8.2"]: data["Q8.2"][v] = {"sources": _docs("q82-" + v, contributions[v]), "signals": _signals(new_mechanism=True)}
    shared = _docs("q83", "shared public");
    for v in _SCOPE["Q8.3"]: data["Q8.3"][v] = {"sources": shared, "signals": _signals(new_mechanism=True)}
    return data


class Provider:
    def __init__(self): self.calls = []
    def search(self, *, lane, query, source_bundle, call_limit, source_limit):
        self.calls.append((lane, query.content_hash, source_bundle.content_hash, call_limit, source_limit))
        return tuple(row for row in source_bundle.documents if row.lane == lane)[:source_limit]


def admission(task, pool):
    return FrozenRecord.from_dict({"schema": "public-train-retrieval-admission-v1", "identity": task.identity.data(),
        "task_digest": task.content_hash, "source_bundle_digest": pool.content_hash,
        "public_train_safe": True, "scientific_verified": False})


def _run(root, task, bundle, experiment, variant, enabled, admission_port=admission):
    injection = retrieval_panel_injection(experiment, variant, task=FrozenRecord.from_dict(task.data()), evidence=bundle)
    budget = FrozenRecord.from_dict({"calls": 1})
    scenario = FrozenRecord.from_dict({"experiment_id": experiment, "variant": variant, "controller_input": injection, "base": {"task": task.content_hash, "evidence": bundle.content_hash, "budget": budget.content_hash}, "controls": {"same_task": True, "same_evidence": True, "same_budget": True}})
    package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([task.identity]), changes={"prompt": {"instructions": "synthetic"}}, search_cost=0)
    arm = default_compatibility("b" * 64).arm(enabled); cell = PanelCell(experiment, task.identity, "r1", variant, "a", arm, task.content_hash, scenario.content_hash, package.digest, "a" * 64)
    session = RunSession(task, package_digest=package.digest, arm=arm, objective=FrozenRecord.from_dict({"objective": "fixed"}), slots=("final",), execution_limit=0, sidecar=root, verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}), required_audit=("measurement",))
    provider, seen = Provider(), []
    def model(request):
        seen.append(request.data()); encoded = request.encoded
        for marker in ('"arm_id"', '"variant"', '"controller_input"', '"signals"'): assert marker not in encoded
        return FrozenRecord.from_dict({"objective_digest": request.data()["module_context"]["required_objective_digest"], "outcome": "unknown", "evidence_ids": [], "conclusion": "public retrieval remains unresolved", "programme_complete": False})
    driver = RetrievalPanelDriver(experiment, provider, admission_port); stage, candidate, _ = driver.run(ModularWorkflow(session), cell=cell, scenario=scenario, model=model, package=package); terminal = session.finish(candidate)
    return stage, terminal, provider, seen


def test_full_two_benchmark_grid_uses_actual_sources_in_both_m6_arms(tmp_path):
    for benchmark in ("blade", "discoverybench"):
        task = _task(benchmark); bundle = freeze_retrieval_bundle(task, query={"task_digest": task.content_hash, "question": "fixed train query"}, budget={"provider_calls": 3, "source_cap": 3, "context_bytes": 4096}, materials=_materials())
        for experiment, variants in _SCOPE.items():
            module_sets = [(), ("M6",)]
            for variant in variants:
                for enabled in module_sets:
                    stage, terminal, provider, seen = _run(tmp_path / benchmark / experiment / variant / ("-".join(enabled) or "off"), task, bundle, experiment, variant, enabled)
                    # Q8.2 off records its retrieval allowance unused.
                    expected_calls = 0 if experiment == "Q8.2" and "M6" not in enabled else 3
                    assert terminal.data()["decision"] == "unknown" and len(seen) == 1 and len(provider.calls) == expected_calls
                    retrieval = seen[0]["module_context"]["retrieval"]
                    assert set(retrieval["by_lane"]) == {"support", "counter", "method"}
                    if experiment == "Q8.3" and "M6" in enabled and variant == "support_only": assert retrieval["by_lane"]["counter"] == [] and retrieval["by_lane"]["method"] == []


def test_closed_bundle_rejects_query_source_and_boolean_budget_drift_before_model_call():
    task = _task("blade"); materials = _materials()
    with pytest.raises(ContractError, match="strict integers"):
        freeze_retrieval_bundle(task, query={"task_digest": task.content_hash, "question": "q"}, budget={"provider_calls": True, "source_cap": 3, "context_bytes": 4096}, materials=materials)
    materials["Q8.3"]["neutral"] = {"sources": _docs("different", "drift"), "signals": _signals(new_mechanism=True)}
    with pytest.raises(ContractError, match="share one frozen source pool"):
        freeze_retrieval_bundle(task, query={"task_digest": task.content_hash, "question": "q"}, budget={"provider_calls": 3, "source_cap": 3, "context_bytes": 4096}, materials=materials)


@pytest.mark.parametrize("field,value", [("task_digest", "f" * 64), ("source_bundle_digest", "f" * 64), ("public_train_safe", False), ("public_train_safe", 1), ("scientific_verified", True)])
def test_wrong_source_admission_blocks_before_any_retrieval(tmp_path, field, value):
    task = _task("blade")
    bundle = freeze_retrieval_bundle(task, query={"task_digest": task.content_hash, "question": "q"},
        budget={"provider_calls": 3, "source_cap": 3, "context_bytes": 4096}, materials=_materials())
    def bad_admission(task, pool):
        return FrozenRecord.from_dict({**admission(task, pool).data(), field: value})
    with pytest.raises(ContractError, match="source admission does not bind"):
        _run(tmp_path, task, bundle, "Q8.2", "correct", ("M6",), admission_port=bad_admission)
    import json
    events = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert not any(event["stage"] in {"q8_retrieval_request", "model_request"} for event in events)
