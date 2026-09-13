"""Controller compilation tests with synthetic public records, no data acquisition."""
from dataclasses import replace

import pytest

from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.experiments import registry
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_plan import compile_train_panel, executable_arms, obligation_grids
from research_loop.ontology import ContractError

HEX = "a" * 64


def q21_bundle(task):
    rows = []
    for number, case_id in enumerate(("support", "refute", "invalid", "unknown"), 1):
        rows.append({"case_id": case_id,
            "admission_checks": {"trusted_validator": "fixture-authority-%s" % number,
                "validator_verified": True, "execution_success": True, "required_audit": ["measurement"],
                "audit": [{"name": "measurement", "executed": True, "passed": True}],
                "subject_bindings": {"task": task.identity.task_id}, "evidence_ids": ["fixture-evidence-%s" % number]},
            "review_material": {"public": "fixture-%s" % number}})
    return FrozenRecord.from_dict({"schema": "q21-pressure-material-bundle-v1", "identity": task.identity.data(),
        "task_payload_digest": task.payload.content_hash, "cases": rows})


def inputs(scope_ids=tuple(registry())):
    tasks = []
    for benchmark in ("blade", "discoverybench"):
        identity = DataIdentity(benchmark, "public-fixture", benchmark + ":fixture", "fixture-v1", HEX, "train")
        if benchmark == "blade":
            task = BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": "fixture",
                "research_question": "What do the public observations justify?", "data_schema": []})
        else:
            task = DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id,
                "question": "What do the public observations justify?", "difficulty": "fixture",
                "source_kind": "synthetic", "dataset": [{"name": "fixture", "description": "public", "columns": []}]})
        tasks.append(task)
    control = FrozenRecord.from_dict({"fixture_control": "always_enabled", "source_sha256": HEX})
    grids = obligation_grids(scope_ids, baseline_digest=HEX, p0_control=control)
    manifest = TrainingManifest.freeze([task.identity for task in tasks])
    package = CandidatePackage.create(parent_digest=None, manifest=manifest,
        changes={"prompt": {"instructions": "Use public observations; report uncertainty."}}, search_cost=0)
    packages = {arm.content_hash: package for grid in grids.values() for arm in executable_arms(grid).values()}
    return dict(stage="engineering-planning", scope_ids=scope_ids, tasks=tasks,
        evidence_by_task={task.content_hash: (q21_bundle(task) if "Q2.1" in scope_ids else FrozenRecord.from_dict({"schema": "q15-review-material-v1",
            "identity": task.identity.data(), "public_evidence": {"measurement": "synthetic public observation"},
            "historical_summary": "Synthetic historical summary for frozen planning."})) for task in tasks},
        budget=FrozenRecord.from_dict({"schema": "fixture-budget", "model_calls": 2, "execution_limit": 0}),
        baseline_digest=HEX, p0_control=control, packages_by_arm=packages,
        scorer=FrozenRecord.from_dict({"schema": "fixture-scorer", "qualification": "none"}),
        acceptance_criteria=FrozenRecord.from_dict({"fixture_only": True}))


def test_every_obligation_gets_all_variants_and_all_legal_paired_arms():
    # These scopes have distinct caller-supplied material contracts,
    # so they compile as dedicated panels instead of coercing Q1.5 material.
    caller_bound = {"Q2.1", "Q2.2", "Q2.5", "Q2.6", "Q3.2", "Q3.3", "Q3.4", "Q3.5", "Q5.3", "Q6.4"}
    values = inputs(tuple(name for name in registry() if name not in caller_bound))
    compiled = compile_train_panel(**values)
    panel = compiled.panel
    assert set(panel.scope_ids) == set(registry()) - caller_bound
    assert len(panel.combinations.pairs) == 36 and len(panel.combinations.triples) == 5
    assert set(panel.combinations.leave_one_out) == {f"M{i}" for i in range(1, 10)}
    for coverage, spec in registry().items():
        if coverage in caller_bound:
            continue
        arms = executable_arms(panel.legal_arm_grids[coverage])
        for task in values["tasks"]:
            rows = [cell for cell in panel.cells if cell.coverage_id == coverage and cell.identity == task.identity]
            assert {(row.variant, row.arm_id) for row in rows} == {(variant, arm_id) for variant in spec.variants for arm_id in arms}
            for cell in rows:
                material = compiled.scenarios[cell.key]
                assert material.content_hash == cell.scenario_digest
                assert material.data()["base"]["task"] == task.content_hash
                assert compiled.packages[cell.runtime_arm.content_hash].digest == cell.package_digest
    assert compiled.manifest.data()["status"] == "planned_only"
    assert compiled.manifest.data()["scientific_status"] == "not_measured"
    p0_grids = obligation_grids(("Q2.2", "Q2.7", "Q6.4"), baseline_digest=values["baseline_digest"], p0_control=values["p0_control"])
    assert all(len(executable_arms(grid)) == 1 for grid in p0_grids.values())
    q21 = compile_train_panel(**inputs(("Q2.1",)))
    assert set(q21.panel.scope_ids) == {"Q2.1"}
    assert len(q21.panel.cells) == 24


def test_actual_package_or_scorer_or_budget_change_changes_frozen_panel():
    values = inputs(("Q3.1",))
    first = compile_train_panel(**values)
    parent = next(iter(values["packages_by_arm"].values()))
    candidate = CandidatePackage.create(parent_digest=parent.digest,
        manifest=TrainingManifest(FrozenRecord.from_dict(parent.record.data()["training_manifest"])),
        changes={"prompt": {"instructions": "Different training package."}}, search_cost=0)
    values["packages_by_arm"] = {key: candidate for key in values["packages_by_arm"]}
    assert compile_train_panel(**values).panel.digest != first.panel.digest
    values = inputs(("Q3.1",))
    values["scorer"] = FrozenRecord.from_dict({"different_scorer": True})
    assert compile_train_panel(**values).panel.digest != first.panel.digest
    values = inputs(("Q3.1",))
    values["budget"] = FrozenRecord.from_dict({"model_calls": 3})
    assert compile_train_panel(**values).panel.digest != first.panel.digest


@pytest.mark.parametrize("fault", ["foreign_split", "foreign_task", "partial", "extra"])
def test_package_manifest_cannot_cross_or_silently_change_training_panel(fault):
    values = inputs(("Q3.1",))
    identities = [task.identity for task in values["tasks"]]
    if fault == "foreign_split":
        identities = [replace(identity, split_id="b" * 64) for identity in identities]
    elif fault == "foreign_task":
        identities[0] = replace(identities[0], task_id="different-task")
    elif fault == "partial":
        identities.pop()
    else:
        identities.append(replace(identities[0], task_id="extra-training-task"))
    package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze(identities),
        changes={"prompt": {"instructions": "Public training package."}}, search_cost=0)
    values["packages_by_arm"] = {arm: package for arm in values["packages_by_arm"]}
    with pytest.raises(ContractError, match="manifest must bind exactly"):
        compile_train_panel(**values)


@pytest.mark.parametrize("fault", ["validation", "duplicate_task", "split", "missing_benchmark", "missing_package", "wrong_package", "missing_evidence", "duplicate_replicate", "unknown_scope"])
def test_compiler_fails_before_execution_for_invalid_frozen_inputs(fault):
    values = inputs(("Q3.1",))
    if fault == "validation":
        task = values["tasks"][0]
        values["tasks"][0] = replace(task, identity=replace(task.identity, domain="validation"))
    elif fault == "duplicate_task": values["tasks"].append(values["tasks"][0])
    elif fault == "split":
        task = values["tasks"][0]
        values["tasks"][0] = replace(task, identity=replace(task.identity, split_id="b" * 64))
    elif fault == "missing_benchmark": values["tasks"].pop()
    elif fault == "missing_package": values["packages_by_arm"].pop(next(iter(values["packages_by_arm"])))
    elif fault == "wrong_package": values["packages_by_arm"][next(iter(values["packages_by_arm"]))] = FrozenRecord.from_dict({"opaque_digest": HEX})
    elif fault == "missing_evidence": values["evidence_by_task"].clear()
    elif fault == "duplicate_replicate": values["replicates"] = ("r1", "r1")
    elif fault == "unknown_scope": values["scope_ids"] = ("not_registered",)
    with pytest.raises(ContractError): compile_train_panel(**values)
