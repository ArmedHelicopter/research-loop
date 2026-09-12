from __future__ import annotations
import pytest
from research_loop.modular.contracts import DataIdentity
from research_loop.modular.experiments import ControllerInputs, ExperimentLedger, RunReceipt, registry, scenario
from research_loop.ontology import ContractError

def receipt(benchmark:str, domain:str, group:str, scenario_hash:str, arms:tuple[str,...] = ("correct","wrong"), switches:tuple[str,...] = ("M3:on",)) -> RunReceipt:
    return RunReceipt(benchmark,DataIdentity(benchmark,"fixture",group,"v1",domain,domain),scenario_hash,arms,switches,"package","scorer","trace","run-"+benchmark)

def inputs() -> ControllerInputs:
    from research_loop.modular.contracts import FrozenRecord
    return ControllerInputs(FrozenRecord.from_dict({"task":"fixture"}), FrozenRecord.from_dict({"evidence":"fixture"}), FrozenRecord.from_dict({"budget":1}))

def test_registry_keeps_all_48_obligations_designed_and_emits_controlled_scenarios() -> None:
    specs=registry(); assert len(specs)==48
    controlled=scenario(specs["Q1.1"],"wrong",inputs=inputs())
    assert controlled.data()["controls"] == {"same_task":True,"same_evidence":True,"same_budget":True}
    ledger=ExperimentLedger.create(); assert all(row["status"]=="designed" for row in ledger.data().values())
    with pytest.raises(ContractError,match="explicit reason"):
        ledger.transition("Q1.2","blocked")
    assert ledger.transition("Q1.2","blocked",blocked_reason="blocked_endpoint_unimplemented:claim_revision_context").data()["Q1.2"]["status"] == "blocked"

def test_measurement_requires_bound_two_benchmark_receipts_and_does_not_auto_accept() -> None:
    specs=registry(); controlled=scenario(specs["Q1.1"],"correct",inputs=inputs())
    ledger=ExperimentLedger.create().transition("Q1.1","implemented",implementation_ref="module@v1").transition("Q1.1","integration_verified",implementation_ref="trace@v1")
    with pytest.raises(ContractError,match="both benchmark"):
        ledger.transition("Q1.1","train_measured",scenario_record=controlled,receipts=(receipt("discoverybench","train","g1",controlled.content_hash),))
    trained=ledger.transition("Q1.1","train_measured",scenario_record=controlled,receipts=(receipt("discoverybench","train","g1",controlled.content_hash),receipt("blade","train","g2",controlled.content_hash)))
    assert trained.data()["Q1.1"]["status"]=="train_measured"
    with pytest.raises(ContractError,match="invalid experiment state"):
        trained.transition("Q1.1","accepted")

def test_validation_binding_rejects_wrong_domain_group_or_scenario() -> None:
    spec=registry()["Q2.1"]; controlled=scenario(spec,"neutral",inputs=inputs())
    switches=("M1:on","M5:on")
    ledger=ExperimentLedger.create().transition("Q2.1","implemented",implementation_ref="m1@v1").transition("Q2.1","integration_verified",implementation_ref="trace@v1").transition("Q2.1","train_measured",scenario_record=controlled,receipts=(receipt("discoverybench","train","a",controlled.content_hash,("neutral",),switches),receipt("blade","train","b",controlled.content_hash,("neutral",),switches))).transition("Q2.1","candidate_frozen")
    with pytest.raises(ContractError,match="domain or scenario"):
        ledger.transition("Q2.1","validation_measured",scenario_record=controlled,receipts=(receipt("discoverybench","train","a",controlled.content_hash),receipt("blade","validation","b",controlled.content_hash)))
