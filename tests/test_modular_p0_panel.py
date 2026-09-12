import pytest
from research_loop.modular.p0_panel import fixed_control_design, validate_fixed_control_design
from research_loop.modular.__main__ import programme_plan
from research_loop.ontology import ContractError

def test_fixed_p0_grid_has_one_noncontrast_control_arm_and_plan_covers_three_p0_only_items():
 grid=fixed_control_design("base","a"*64)
 assert validate_fixed_control_design(grid)==grid
 body=grid.data(); assert body["arms"][0]["id"]=="p0-fixed" and body["runtime_arm"]["enabled"]==[] and body["contrast"] is None
 plan=programme_plan("base").data()
 assert set(plan["P0_fixed_control_grids"])=={"Q2.2","Q2.7","Q6.4"}
 lock=type(grid).from_dict(plan["P0_control_source_lock"])
 assert all(row["p0_control_digest"]==lock.content_hash for row in plan["P0_fixed_control_grids"].values())
 assert lock.data()["software_sources"]==plan["software_sources"]
 for row in plan["scenarios"]:
  if "P0" in row["modules"]: assert row["module_switches"]["P0"] == ["on"]
  if row["modules"] == ["P0"]: assert row["comparison_mode"] == "fixed_control"
 with pytest.raises(ContractError,match="sha256"): fixed_control_design("base","unbound-label")
 with pytest.raises(ContractError): validate_fixed_control_design(type(grid).from_dict({**body,"contrast":{"fake":1}}))
