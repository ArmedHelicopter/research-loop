from copy import deepcopy

import pytest

from research_loop.modular.combinations import Compatibility, ModuleSpec, default_compatibility, freeze_panel
from research_loop.modular.contracts import ContractError, FrozenRecord
from evaluation.modular.statistics import estimate_contrast


def test_all_pairs_remain_registered_and_prerequisites_do_not_fake_interactions():
    compatibility = default_compatibility("baseline")
    pairs = {tuple(panel.data()["factors"]): panel.data() for panel in compatibility.all_pairs()}
    assert len(pairs) == 36
    assert pairs[("M3", "M9")]["background"] == ["M2"]
    assert pairs[("M3", "M9")]["interaction_status"] == "identifiable"
    dependent = pairs[("M2", "M3")]
    assert dependent["interaction_status"] == "not_identifiable"
    assert dependent["contrast"] is None
    assert dependent["cells"][1]["status"] == "structurally_unavailable"
    assert "score" not in dependent["cells"][1]
    full = compatibility.leave_one_out(compatibility.names).data()
    assert len(full["cells"]) == 10
    assert next(c for c in full["cells"] if c["id"] == "without-M2")["status"] == "structurally_unavailable"
    with pytest.raises(ContractError):
        compatibility.arm(["M3"])
    with pytest.raises(ContractError):
        compatibility.arm("M1")
    with pytest.raises(ContractError):
        Compatibility([ModuleSpec("a", ("b",)), ModuleSpec("b", ("a",))], baseline_digest="b")


def test_frozen_panel_rejects_structural_tampering_and_posthoc_packages():
    design = default_compatibility("baseline").factorial(["M1", "M4"])
    args = dict(package_digests={cell["id"]: "package-" + cell["id"] for cell in design.data()["cells"]},
                task_groups={"discoverybench": ["g1"], "blade": ["g2"]},
                schedule_digest="schedule", criteria={"endpoint": "adapted-score"}, target_arm="11")
    frozen = freeze_panel(design, **args)
    args["task_groups"]["blade"].append("g3")
    assert frozen.data()["task_groups"]["blade"] == ["g2"]
    forged = deepcopy(design.data())
    forged["cells"][0]["arm"]["enabled"] = ["M1"]
    with pytest.raises(ContractError):
        freeze_panel(FrozenRecord.from_dict(forged), **args)
    args["package_digests"]["new-winner"] = "extra"
    with pytest.raises(ContractError):
        freeze_panel(design, **args)


def score_rows(groups, values):
    return [{"benchmark": "blade", "group_id": group, "task_id": task, "replicate": "seed0", "arm": arm, "score": score}
            for group, task in groups for arm, score in values.items()]


def test_null_singletons_can_have_positive_combination_interaction():
    rows = score_rows([("g1", "t1"), ("g2", "t2")], {"00": .4, "01": .4, "10": .4, "11": .8})
    result = estimate_contrast(rows, {"00": 1, "01": -1, "10": -1, "11": 1}, resamples=100).data()
    assert result["effect"] == pytest.approx(.4)
    assert result["source_groups"] == 2
    assert result["promotes"] is False
    # Positive joint gain is not itself an interaction.
    additive = score_rows([("g1", "t1"), ("g2", "t2")], {"00": .2, "01": .4, "10": .4, "11": .6})
    assert estimate_contrast(additive, {"00": 1, "01": -1, "10": -1, "11": 1}, resamples=100).data()["effect"] == pytest.approx(0)


def test_source_group_weighting_missing_scores_and_benchmark_separation():
    rows = score_rows([("many", str(i)) for i in range(10)], {"a": 0, "b": 1})
    rows += score_rows([("one", "other")], {"a": 1, "b": 0})
    result = estimate_contrast(rows, {"a": -1, "b": 1}, resamples=100).data()
    assert result["effect"] == 0  # Each independent source receives equal weight.
    assert result["paired_units"] == 11
    one_group = estimate_contrast(rows[:20], {"a": -1, "b": 1}, resamples=100).data()
    assert one_group["interval"] is None
    assert one_group["status"] == "insufficient_independent_groups"
    with pytest.raises(ContractError):
        estimate_contrast(rows[:-1], {"a": -1, "b": 1})
    mixed = deepcopy(rows)
    mixed[0]["benchmark"] = "discoverybench"
    with pytest.raises(ContractError):
        estimate_contrast(mixed, {"a": -1, "b": 1})
