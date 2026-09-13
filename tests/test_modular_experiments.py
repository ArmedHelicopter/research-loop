from __future__ import annotations
import pytest
from research_loop.modular.contracts import DataIdentity
from research_loop.modular.experiments import ControllerInputs, ExperimentLedger, RunReceipt, registry, scenario
from research_loop.ontology import ContractError

def receipt(benchmark:str, domain:str, group:str, scenario_hash:str, arms:tuple[str,...] = ("correct","wrong"), switches:tuple[str,...] = ("M3:on",)) -> RunReceipt:
    return RunReceipt(benchmark,DataIdentity(benchmark,"fixture",group,"v1",domain,domain),scenario_hash,arms,switches,"package","scorer","trace","run-"+benchmark)

def inputs() -> ControllerInputs:
    from research_loop.modular.contracts import FrozenRecord
    identity = DataIdentity("discoverybench", "fixture", "group", "v1", "split", "train")
    return ControllerInputs(FrozenRecord.from_dict({"identity": identity.data(), "payload": {"question": "fixture"}}),
        FrozenRecord.from_dict({"schema": "q15-review-material-v1", "identity": identity.data(),
            "public_evidence": {"measurement": "fixture"}, "historical_summary": "fixture historical summary"}),
        FrozenRecord.from_dict({"budget":1}))

def test_registry_keeps_all_48_obligations_designed_and_emits_controlled_scenarios() -> None:
    specs=registry(); assert len(specs)==48
    controlled=scenario(specs["Q1.1"],"wrong",inputs=inputs())
    assert controlled.data()["controls"] == {"same_task":True,"same_evidence":True,"same_budget":True}
    ledger=ExperimentLedger.create(); assert all(row["status"]=="designed" for row in ledger.data().values())
    with pytest.raises(ContractError,match="explicit reason"):
        ledger.transition("Q1.2","blocked")
    assert ledger.transition("Q1.2","blocked",blocked_reason="blocked_endpoint_unimplemented:claim_revision_context").data()["Q1.2"]["status"] == "blocked"


def test_q15_requires_actual_identity_bound_review_material() -> None:
    from research_loop.modular.contracts import FrozenRecord
    seeded = inputs()
    with pytest.raises(ContractError, match="Q1.5 review material"):
        scenario(registry()["Q1.5"], "blind_first", inputs=ControllerInputs(
            seeded.task, FrozenRecord.from_dict({"evidence": "metadata is not material"}), seeded.budget))

def test_legacy_two_benchmark_hashes_cannot_claim_measurement() -> None:
    specs=registry(); controlled=scenario(specs["Q1.1"],"correct",inputs=inputs())
    ledger=ExperimentLedger.create().transition("Q1.1","implemented",implementation_ref="module@v1").transition("Q1.1","integration_verified",implementation_ref="trace@v1")
    with pytest.raises(ContractError,match="complete frozen panel"):
        ledger.transition("Q1.1","train_measured",scenario_record=controlled,receipts=(receipt("discoverybench","train","g1",controlled.content_hash),))
    with pytest.raises(ContractError, match="legacy hashes are insufficient"):
        ledger.transition("Q1.1","train_measured",scenario_record=controlled,receipts=(receipt("discoverybench","train","g1",controlled.content_hash),receipt("blade","train","g2",controlled.content_hash)))
    assert ledger.data()["Q1.1"]["status"]=="integration_verified"
    with pytest.raises(ContractError,match="invalid experiment state"):
        ledger.transition("Q1.1","accepted")

def test_blocked_status_cannot_skip_measurement_or_validation() -> None:
    ledger=ExperimentLedger.create().transition("Q2.1","implemented",implementation_ref="m1@v1").transition("Q2.1","blocked",blocked_reason="fixture unavailable")
    for target in ("train_measured", "candidate_frozen", "validation_measured", "accepted", "rejected"):
        with pytest.raises(ContractError,match="resume its recorded state"):
            ledger.transition("Q2.1",target)
    resumed=ledger.transition("Q2.1", "implemented")
    assert resumed.data()["Q2.1"]["status"] == "implemented"


@pytest.mark.parametrize("coverage", tuple(name for name in registry() if name not in {"Q2.2", "Q2.5", "Q2.6", "Q2.7", "Q3.2", "Q3.3", "Q3.4", "Q3.5", "Q5.1", "Q5.2", "Q5.3", "Q5.4", "Q6.4", "Q7.1", "Q7.2", "Q7.3", "Q7.4", "Q7.5", "Q7.6"}))
def test_added_runners_match_every_authoritative_variant(coverage):
    spec = registry()[coverage]
    for variant in spec.variants:
        result = scenario(spec, variant, inputs=inputs()).data()
        assert result["experiment_id"] == coverage and result["variant"] == variant
        controller = result["controller_input"]
        projection = controller["q21_pressure_projection"] if coverage == "Q2.1" else controller
        assert projection["fixture_only"] is True
