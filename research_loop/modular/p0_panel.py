"""Fixed P0 control-plane grid; P0 is not an M1--M9 contrast factor."""
from __future__ import annotations
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import FrozenRecord, required_text
from research_loop.ontology import ContractError

def fixed_control_design(baseline_digest: str, p0_control_digest: str) -> FrozenRecord:
    required_text(p0_control_digest, "P0 control digest")
    if len(p0_control_digest) != 64 or any(ch not in "0123456789abcdef" for ch in p0_control_digest):
        raise ContractError("P0 control digest must be a sha256 digest")
    arm=default_compatibility(required_text(baseline_digest,"baseline digest")).arm(())
    return FrozenRecord.from_dict({"schema":"p0-fixed-control-grid-v1","baseline_digest":baseline_digest,
        "p0_control_digest":required_text(p0_control_digest,"P0 control digest"),"runtime_arm":arm.data(),
        "arms":[{"id":"p0-fixed","runtime_arm":arm.data()}],"contrast":None,
        "status":"fixed-control; no module-effect estimand"})

def validate_fixed_control_design(record: FrozenRecord) -> FrozenRecord:
    body=record.data()
    if set(body)!={"schema","baseline_digest","p0_control_digest","runtime_arm","arms","contrast","status"} or body["schema"]!="p0-fixed-control-grid-v1" or body["contrast"] is not None or body["status"]!="fixed-control; no module-effect estimand": raise ContractError("invalid P0 fixed-control grid")
    expected=fixed_control_design(body["baseline_digest"],body["p0_control_digest"])
    if expected!=record: raise ContractError("P0 fixed-control grid was modified")
    return expected
