"""Engineering-only combination panel integration checks using public fixtures."""
from pathlib import Path

import pytest

from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.combination_panels import CombinationPanelVerifier, compile_combination_catalogue
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.experiments import registry
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_receipts import RuntimeReceipt
from research_loop.modular.runtime import AuditVerifier, RunSession
from research_loop.ontology import ContractError

SPLIT = "a" * 64


def _task(benchmark: str) -> PublicTask:
    identity = DataIdentity(benchmark, f"combination-{benchmark}", f"{benchmark}:combination", "fixture-v1", SPLIT, "train")
    if benchmark == "blade":
        return BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": "public",
            "research_question": "Which public mechanism is plausible?", "data_schema": [{"name": "x"}]})
    return DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id,
        "question": "Which public mechanism is plausible?", "source_kind": "synthetic",
        "dataset": [{"name": "public", "columns": [{"name": "x"}]}]})


def _inputs():
    tasks = [_task("blade"), _task("discoverybench")]
    manifest = TrainingManifest.freeze([task.identity for task in tasks])
    compatibility = default_compatibility(SPLIT)
    arms = {}
    designs = [*compatibility.all_pairs(),
               *(compatibility.conditional_factorial(triple) for triple in (("M2", "M3", "M5"), ("M4", "M5", "M6"), ("M1", "M4", "M7"), ("M3", "M6", "M9"), ("M7", "M8", "M9"))),
               compatibility.leave_one_out(compatibility.names)]
    for design in designs:
        for row in design.data()["cells"]:
            if row["status"] == "executable":
                arm = FrozenRecord.from_dict(row["arm"])
                if arm.content_hash not in arms:
                    arms[arm.content_hash] = CandidatePackage.create(parent_digest=None, manifest=manifest,
                        changes={"prompt": {"instructions": "predeclared combination arm " + arm.content_hash}}, search_cost=0)
    return tasks, arms, FrozenRecord.from_dict({"scorer": "fixture-independent-unconfigured"}), FrozenRecord.from_dict({"criterion": "engineering only"})


def _catalogue():
    tasks, packages, scorer, criteria = _inputs()
    return compile_combination_catalogue(stage="C2-C4-train", tasks=tasks, baseline_digest=SPLIT,
                                         packages_by_arm=packages, scorer=scorer, acceptance_criteria=criteria)


def _run(cell, task: PublicTask, sidecar: Path) -> RuntimeReceipt:
    objective = FrozenRecord.from_dict({"objective": "combination engineering fixture"})
    session = RunSession(task, package_digest=cell.package_digest, arm=cell.runtime_arm, objective=objective,
                         slots=("only",), execution_limit=0, sidecar=sidecar,
                         verifier=AuditVerifier({"audit-a": b"a" * 32, "audit-b": b"b" * 32}), required_audit=("audit",))
    candidate = FrozenRecord.from_dict({"objective_digest": objective.content_hash, "outcome": "unknown", "evidence_ids": [],
                                         "conclusion": "engineering fixture does not score the combination", "programme_complete": False})
    context = FrozenRecord.from_dict({"panel_cell": {"experiment_id": cell.coverage_id, "variant": cell.variant,
        "replicate": cell.replicate, "arm_id": cell.arm_id, "scenario_digest": cell.scenario_digest}})
    assert session.invoke("only", lambda _request: candidate, instruction="Use public inputs only.", module_context=context) == candidate
    terminal = session.finish(candidate)
    trace = sidecar / "trace.jsonl"
    lines = trace.read_text(encoding="utf-8").splitlines()
    output = FrozenRecord.from_dict({"responses": [candidate.data()], "terminal": terminal.data()}).content_hash
    return RuntimeReceipt(cell.key, "succeeded", trace, FrozenRecord(lines[-1]).content_hash, output)


def test_catalogue_freezes_all_obligations_without_relabeling_q_registry():
    catalogue = _catalogue()
    assert len(catalogue.panels) == 42
    assert catalogue.manifest.data()["pair_count"] == 36
    assert catalogue.manifest.data()["triple_count"] == 5
    assert catalogue.manifest.data()["full_loo_count"] == 1
    assert catalogue.manifest.data()["scientific_status"] == "not_measured"
    assert "pair:M1+M4" in catalogue.panels and "pair:M2+M3" in catalogue.panels and "full-loo" in catalogue.panels
    assert all(obligation not in registry() for obligation in catalogue.panels)


def test_legal_pair_has_complete_two_benchmark_arm_journals_and_engineering_verification(tmp_path: Path):
    panel = _catalogue().panels["pair:M1+M4"]
    tasks, *_ = _inputs()
    by_identity = {task.identity: task for task in tasks}
    assert len(panel.cells) == 8 and panel.interaction_status == "identifiable"
    rows = tuple(_run(cell, by_identity[cell.identity], tmp_path / cell.identity.benchmark / cell.arm_id) for cell in panel.cells)
    verdict = CombinationPanelVerifier().verify(panel, rows)
    assert verdict.engineering_verified and verdict.observed_cells == 8
    assert verdict.interaction_status == "not_measured" and verdict.scientific_status == "not_measured"
    with pytest.raises(ContractError, match="coverage mismatch"):
        CombinationPanelVerifier().verify(panel, rows[:-1])


def test_dependency_pair_retains_unavailable_cell_and_only_runs_feasible_grid(tmp_path: Path):
    panel = _catalogue().panels["pair:M2+M3"]
    tasks, *_ = _inputs()
    by_identity = {task.identity: task for task in tasks}
    assert panel.interaction_status == "not_identifiable"
    assert [row["id"] for row in panel.structurally_unavailable] == ["01"]
    # The 01 arm would enable M3 without its M2 prerequisite; it has no fake
    # journal.  Every actually legal arm is still run for both adapters.
    assert len(panel.cells) == 6 and {cell.arm_id for cell in panel.cells} == {"00", "10", "11"}
    rows = tuple(_run(cell, by_identity[cell.identity], tmp_path / cell.identity.benchmark / cell.arm_id) for cell in panel.cells)
    verdict = CombinationPanelVerifier().verify(panel, rows)
    assert verdict.engineering_verified and verdict.interaction_status == "not_identifiable"
    assert verdict.scientific_status == "not_measured"
