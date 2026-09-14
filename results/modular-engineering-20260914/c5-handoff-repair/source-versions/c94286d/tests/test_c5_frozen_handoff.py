import pytest

from research_loop.modular.c5_frozen_handoff import JointClosure, prepare_joint_train_handoff
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError

H = "a" * 64


def records(*, p0=True):
    baseline = FrozenRecord.from_dict({"baseline_digest": H})
    background = FrozenRecord.from_dict({"baseline_digest": H, "fixed": []})
    control = FrozenRecord.from_dict({"control_plane": "always_enabled"} if p0 else {"control_plane": "optional"})
    schedule = FrozenRecord.from_dict({"order": ["r1"], "resource": "fixed"})
    arm = FrozenRecord.from_dict({"schema": "module-arm-v1", "baseline_digest": H,
        "compatibility_digest": FrozenRecord.from_dict({"schema": "module-compatibility-v1", "baseline_digest": H,
        "modules": [{"id": f"M{i}", "requires": (["M2"] if i in (3, 9) else []), "conflicts": []} for i in range(1, 10)]}).content_hash,
        "enabled": []})
    return baseline, background, control, schedule, arm


def test_legal_b0_closure_retains_p0_and_is_immutable():
    closure = JointClosure({}, *records())
    assert closure.runtime_arm.data()["enabled"] == []
    assert closure.p0_control.data()["control_plane"] == "always_enabled"
    with pytest.raises(TypeError):
        closure.components["M1"] = object()


def test_p0_is_not_optional_and_arbitrary_panel_cannot_claim_train_source():
    with pytest.raises(ContractError, match="always-enabled P0"):
        JointClosure({}, *records(p0=False))
    closure = JointClosure({}, *records())
    with pytest.raises(ContractError, match="typed complete joint TRAIN panel"):
        prepare_joint_train_handoff(source_panel=FrozenRecord.from_dict({"selected": True}), source_runtime_receipts=(),
                                   proposed_target_arm="b0", closures={"b0": closure})
