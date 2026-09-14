"""Actual typed TRAIN journal -> C5 structural preparation, without model I/O."""
from dataclasses import FrozenInstanceError, replace

import pytest

from research_loop.modular.c5_frozen_handoff import (
    C5Arm, C5Cell, C5ValidationPanel, PreparedJointTrainHandoff,
    freeze_c5_validation_panel, prepare_joint_train_handoff,
)
from research_loop.modular.combination_panels import CombinationPanel, CombinationPanelVerifier, run_combination_cell
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_receipts import PanelCell
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError

H = "a" * 64


def record(body):
    return FrozenRecord.from_dict(body)


def source(root):
    tasks = [PublicTask.create(DataIdentity(b, "train-"+b, b+":train", "synthetic-v1", H, "train"),
              {"question": "Which observations support a bounded conclusion?"}) for b in ("blade", "discoverybench")]
    manifest = TrainingManifest.freeze([t.identity for t in tasks])
    design = default_compatibility(H).factorial(("M4", "M5"))
    packages, cells, scenarios = {}, [], {}
    for row in design.data()["cells"]:
        arm = record(row["arm"])
        packages[arm.content_hash] = CandidatePackage.create(parent_digest=None, manifest=manifest,
            changes={"prompt": {"instructions": "Predeclared arm " + row["id"]},
                     "memory": {"lesson": "Frozen synthetic source " + row["id"]}}, search_cost=0)
    for task in tasks:
        scenario = record({"schema": "combination-public-scenario-v1", "obligation_id": "pair:M4+M5",
            "design_digest": design.content_hash, "task_digest": task.content_hash, "replicate": "r1", "status": "predeclared"})
        for row in design.data()["cells"]:
            arm = record(row["arm"])
            cell = PanelCell("pair:M4+M5", task.identity, "r1", "combination", row["id"], arm,
                task.content_hash, scenario.content_hash, packages[arm.content_hash].digest, "b"*64)
            cells.append(cell); scenarios[cell.key] = scenario
    bundle = record({"schema": "combination-package-bundle-v1",
                     "packages": {key: p.record.data() for key, p in packages.items()}})
    panel = CombinationPanel("C2-train-synthetic", "train", H, "pair:M4+M5", "interaction_on_scale",
        design, bundle, record({"criterion": "engineering_only"}), tuple(cells))
    def model(request):
        # This is an in-process synthetic response, not a remote model call.
        return record({"objective_digest": request.data()["module_context"]["required_objective_digest"],
            "outcome": "unknown", "evidence_ids": [], "conclusion": "No scientific effect has been measured.",
            "programme_complete": False})
    by_id = {t.identity: t for t in tasks}
    verifier = AuditVerifier({"a": b"a"*32, "b": b"b"*32})
    receipts = tuple(run_combination_cell(panel, c, task=by_id[c.identity], scenario=scenarios[c.key],
        package=packages[c.runtime_arm.content_hash], objective=record({"objective": "Synthetic structural check"}),
        sidecar=root / str(i), model=model, audit_verifier=verifier) for i, c in enumerate(cells))
    assert CombinationPanelVerifier().verify(panel, receipts).engineering_verified
    return panel, receipts


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    panel, receipts = source(tmp_path_factory.mktemp("c5-original-train"))
    return prepare_joint_train_handoff(source_panel=panel, source_runtime_receipts=receipts, proposed_target_arm="11")


def arguments(handoff):
    arms = (C5Arm("11", "target"), C5Arm("00", "baseline"), C5Arm("01", "control"), C5Arm("10", "ablation"))
    cells = tuple(C5Cell(a.arm_id, DataIdentity(b, f"validation-{b}-{g}", f"{b}:held-{g}",
                            "synthetic-v1", H, "validation"), r)
                  for b in ("blade", "discoverybench") for g in (1, 2) for r in ("r1", "r2") for a in arms)
    contrasts = record({"schema": "c5-target-relative-contrasts-v1", "estimand": "joint_bundle", "target_arm": "11",
        "rows": [{"comparison_arm": a.arm_id, "comparison_role": a.role,
            "coefficients": {name: 1 if name == "11" else -1 if name == a.arm_id else 0 for name in ("00", "01", "10", "11")}}
            for a in sorted(arms, key=lambda a: a.arm_id) if a.arm_id != "11"]})
    criteria = record({"schema": "c5-prepared-acceptance-criteria-v1",
        "benchmarks": {b: {"score_name": "synthetic_quality", "score_range": [0.0, 1.0], "direction": "higher_better",
                           "minimum_target_gain": 0.05, "maximum_safety_regression": 0,
                           "maximum_cost_ratio": 1.1, "minimum_independent_groups": 2}
                       for b in ("blade", "discoverybench")},
        "missing_policy": "any_missing_or_failed_cell_reject",
        "group_weighting": "task_replicate_mean_then_equal_group_mean",
        "decision_rule": "fixed_target_passes_every_comparison_in_each_benchmark",
        "multiple_comparisons": {"method": "bonferroni", "family_alpha": 0.05, "comparison_count": 6}})
    return dict(proposed_target_arm="11", arms=arms, cells=cells, contrast_matrix=contrasts,
                acceptance_criteria=criteria, resource_schedule=handoff.closures["11"].resource_schedule)


def test_original_typed_eight_cell_source_and_complete_c5_grid(prepared):
    assert len(prepared.source_runtime_receipts) == 8
    assert prepared.source_panel.estimand == "interaction_on_scale"
    assert set(prepared.closures) == {"00", "01", "10", "11"}
    for name, closure in prepared.closures.items():
        source_cells = [c for c in prepared.source_panel.cells if c.arm_id == name]
        assert all(c.runtime_arm == closure.runtime_arm and c.package_digest == closure.package.digest for c in source_cells)
        assert set(closure.components) == set(closure.runtime_arm.data()["enabled"])
    assert prepared.closures["00"].components == {}
    assert prepared.closures["00"].package.digest != prepared.closures["11"].package.digest
    panel = freeze_c5_validation_panel(prepared, **arguments(prepared))
    assert len(panel.cells) == 32
    body = panel.record.data()
    assert len(body["contrast_matrix"]["rows"]) == 3
    assert body["acceptance_criteria"]["multiple_comparisons"]["comparison_count"] == 6
    assert body["stage"] == "C5" and body["allocation_stage"] == "V_final"
    assert body["preparation_only"] and not body["validation_eligible"]
    assert not panel.acceptance_authorized and not panel.custody_lease_authorized
    assert not body["deployment_authorized"]
    assert prepared.admission_status == "unavailable_no_typed_joint_train_verifier"
    with pytest.raises(TypeError): prepared.closures["11"] = prepared.closures["00"]
    with pytest.raises(FrozenInstanceError): panel.proposed_target_arm = "01"
    detached = panel.record.data(); detached["proposed_target_arm"] = "01"
    assert panel.record.data()["proposed_target_arm"] == "11"


def test_direct_constructors_replay_and_bind_all_fields(prepared):
    direct = PreparedJointTrainHandoff(prepared.record, "11", dict(prepared.closures), prepared.source_panel,
                                     list(reversed(prepared.source_runtime_receipts)), prepared.original_journals)
    assert direct == prepared
    panel = freeze_c5_validation_panel(prepared, **arguments(prepared))
    assert C5ValidationPanel(panel.record, panel.handoff, panel.proposed_target_arm, list(panel.arms), list(panel.cells),
                            panel.contrast_matrix, panel.acceptance_criteria, panel.resource_schedule) == panel
    with pytest.raises(ContractError, match="original source"):
        replace(prepared, record=record({"selected": True}))
    with pytest.raises(ContractError, match="canonical preparation"):
        replace(panel, record=record({"validation_eligible": True}))
    with pytest.raises(ContractError, match="complete paired grid"):
        replace(panel, cells=panel.cells[:-1])
    with pytest.raises(ContractError, match="target"):
        replace(panel, proposed_target_arm="01")


@pytest.mark.parametrize("swap", ["swap_arms", "b0_package", "drop_arm", "extra_arm", "wrong_activation", "background"])
def test_exact_source_closures_reject_realistic_substitutions(prepared, swap):
    closures = dict(prepared.closures)
    if swap == "swap_arms": closures["01"], closures["10"] = closures["10"], closures["01"]
    elif swap == "b0_package": closures["00"] = replace(closures["00"], package=closures["11"].package)
    elif swap == "drop_arm": del closures["01"]
    elif swap == "extra_arm": closures["new"] = closures["00"]
    elif swap == "wrong_activation": closures["11"] = closures["01"]
    else:
        body = closures["11"].background.data(); body["objective"] = {"objective": "Substituted after TRAIN"}
        closures["11"] = replace(closures["11"], background=record(body))
    with pytest.raises(ContractError, match="every closure"):
        replace(prepared, closures=closures)


def test_component_and_p0_projections_cannot_claim_unobserved_state(prepared):
    c = prepared.closures["11"]
    with pytest.raises(ContractError, match="projections"):
        replace(c.components["M4"], config=record({"claimed_module_version": "new"}))
    with pytest.raises(ContractError, match="whole-arm package"):
        replace(c, package=prepared.closures["01"].package)
    with pytest.raises(ContractError, match="always-enabled P0"):
        replace(c, p0_control=record({"control_plane": "optional"}))
    with pytest.raises(ContractError, match="schedule"):
        replace(c, resource_schedule=record({"slots": ["more-calls"]}))


@pytest.mark.parametrize("fault", ["missing", "duplicate", "relabeled", "output", "trace", "failed", "wrong_cell"])
def test_original_runtime_receipts_must_replay_exactly(prepared, fault):
    rows = list(prepared.source_runtime_receipts)
    if fault == "missing": rows.pop()
    elif fault == "duplicate": rows[-1] = rows[0]
    elif fault == "relabeled": rows[0] = replace(rows[0], cell_key=rows[1].cell_key)
    elif fault == "output": rows[0] = replace(rows[0], output_digest="c"*64)
    elif fault == "trace": rows[0] = replace(rows[0], trace_digest="c"*64)
    elif fault == "failed": rows[0] = replace(rows[0], status="failed", output_digest=None, failure_reason="synthetic source failure")
    else: rows[0] = replace(rows[0], trace_path=rows[1].trace_path)
    with pytest.raises(ContractError): replace(prepared, source_runtime_receipts=tuple(rows))


def test_source_drift_after_preparation_is_rejected_at_c5_freeze(tmp_path):
    panel, rows = source(tmp_path / "source")
    handoff = prepare_joint_train_handoff(source_panel=panel, source_runtime_receipts=rows, proposed_target_arm="11")
    rows[0].trace_path.write_text(rows[0].trace_path.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
    with pytest.raises(ContractError): freeze_c5_validation_panel(handoff, **arguments(handoff))


def test_unsupported_panel_family_and_validation_source_are_explicitly_refused(prepared):
    class UncontractedPanel(CombinationPanel): pass
    p = prepared.source_panel
    subclass = UncontractedPanel(p.stage, p.domain, p.split_digest, p.obligation_id, p.estimand, p.design,
                                p.package_bundle, p.acceptance_criteria, p.cells, p.required_benchmarks)
    with pytest.raises(ContractError, match="only the typed"):
        replace(prepared, source_panel=subclass)
    with pytest.raises(ContractError, match="only the typed"):
        prepare_joint_train_handoff(source_panel=record({"stage": "C4", "selected": True}),
                                   source_runtime_receipts=(), proposed_target_arm="11")
    with pytest.raises(ContractError, match="validation panels"):
        replace(p, domain="validation")


@pytest.mark.parametrize("fault", ["two_targets", "two_baselines", "missing_control", "duplicate_id", "wrong_b0"])
def test_c5_roles_are_not_overwritten_or_silently_reassigned(prepared, fault):
    args = arguments(prepared); arms = list(args["arms"])
    if fault == "two_targets": arms[2] = C5Arm("01", "target")
    elif fault == "two_baselines": arms[2] = C5Arm("01", "baseline")
    elif fault == "missing_control": arms[2] = C5Arm("01", "ablation")
    elif fault == "duplicate_id": arms[2] = C5Arm("00", "control")
    else: arms[1], arms[2] = C5Arm("00", "control"), C5Arm("01", "baseline")
    args["arms"] = arms
    with pytest.raises(ContractError): freeze_c5_validation_panel(prepared, **args)


@pytest.mark.parametrize("fault", ["version", "split", "group", "missing", "duplicate", "train_group", "extra_arm"])
def test_c5_pairs_full_identity_and_every_source_group(prepared, fault):
    args = arguments(prepared); cells = list(args["cells"]); first = cells[0]
    if fault == "version": cells[0] = replace(first, identity=replace(first.identity, dataset_version="different-data"))
    elif fault == "split": cells[0] = replace(first, identity=replace(first.identity, split_id="d"*64))
    elif fault == "group": cells[0] = replace(first, identity=replace(first.identity, group_id="unpaired-group"))
    elif fault == "missing": cells.pop()
    elif fault == "duplicate": cells.append(first)
    elif fault == "train_group": cells[0] = replace(first, identity=replace(first.identity, group_id="blade:train"))
    else: cells[0] = replace(first, arm_id="unexpected")
    args["cells"] = cells
    with pytest.raises(ContractError): freeze_c5_validation_panel(prepared, **args)


@pytest.mark.parametrize("fault", ["positive", "wrong_weight", "boolean", "omit_comparison", "wrong_role", "interaction"])
def test_each_contrast_is_target_minus_exactly_one_comparator(prepared, fault):
    args = arguments(prepared); body = args["contrast_matrix"].data()
    if fault == "positive": body["rows"][0]["coefficients"] = {a: 1 for a in ("00", "01", "10", "11")}
    elif fault == "wrong_weight": body["rows"][0]["coefficients"]["01"] = -0.5
    elif fault == "boolean": body["rows"][0]["coefficients"]["11"] = True
    elif fault == "omit_comparison": body["rows"].pop()
    elif fault == "wrong_role": body["rows"][0]["comparison_role"] = "ablation"
    else: body["estimand"] = "interaction_on_scale"
    args["contrast_matrix"] = record(body)
    with pytest.raises(ContractError, match="target-minus-comparator"):
        freeze_c5_validation_panel(prepared, **args)


@pytest.mark.parametrize("fault", ["empty", "missing_benchmark", "safety", "range", "zero_cost", "multiplicity", "missing_policy"])
def test_c5_criteria_and_schedule_are_concrete_and_frozen(prepared, fault):
    args = arguments(prepared); body = args["acceptance_criteria"].data()
    if fault == "empty": body = {}
    elif fault == "missing_benchmark": del body["benchmarks"]["blade"]
    elif fault == "safety": body["benchmarks"]["blade"]["maximum_safety_regression"] = 0.1
    elif fault == "range": body["benchmarks"]["blade"]["score_range"] = [1, 0]
    elif fault == "zero_cost": body["benchmarks"]["blade"]["maximum_cost_ratio"] = 0
    elif fault == "multiplicity": body["multiple_comparisons"]["comparison_count"] = 1
    else: body["missing_policy"] = "drop_failed_arms"
    args["acceptance_criteria"] = record(body)
    with pytest.raises(ContractError): freeze_c5_validation_panel(prepared, **args)


def test_c5_schedule_direct_constructor_and_freeze_cannot_drift(prepared):
    args = arguments(prepared)
    args["resource_schedule"] = record({"slots": ["extra-model"]})
    with pytest.raises(ContractError, match="every frozen source closure"):
        freeze_c5_validation_panel(prepared, **args)
    panel = freeze_c5_validation_panel(prepared, **arguments(prepared))
    with pytest.raises(ContractError, match="every frozen source closure"):
        replace(panel, resource_schedule=args["resource_schedule"])
