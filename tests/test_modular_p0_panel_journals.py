"""P0 fixed-control panels use real runtime journals, never labels or models."""
from itertools import combinations
from pathlib import Path
import pytest
from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.experiments import registry
from research_loop.modular.p0_panel import fixed_control_design
from research_loop.modular.panel_receipts import CombinationObligations, FrozenPanel, PanelCell, PanelReceiptVerifier, RuntimeReceipt
from research_loop.modular.runtime import AuditVerifier, RunSession
from research_loop.ontology import ContractError

HEX="a"*64
P0_IDS=("Q2.2","Q2.7","Q6.4")

def obligations():
 m=tuple(f"M{i}" for i in range(1,10))
 return CombinationObligations(tuple(combinations(m,2)),(("M2","M3","M5"),("M4","M5","M6"),("M1","M4","M7"),("M3","M6","M9"),("M7","M8","M9")),m,m)

def public_task(benchmark, coverage, domain="train"):
 i=DataIdentity(benchmark,f"{coverage}-{benchmark}",f"g-{coverage}","v1",HEX,domain)
 if benchmark=="blade": return BladeAdapter().prepare(i,{"task_id":i.task_id,"dataset_id":"fixture","research_question":"public fixture?","data_schema":[]})
 return DiscoveryBenchAdapter().prepare(i,{"task_id":i.task_id,"question":"public fixture?","difficulty":"fixture","source_kind":"synthetic","dataset":[{"name":"fixture","description":"public","columns":[]}]})

def build(tmp_path: Path, *, wrong_control=False):
 controls={coverage:FrozenRecord.from_dict({"fixture_control":coverage}).content_hash for coverage in P0_IDS}
 grids={coverage:fixed_control_design(HEX,controls[coverage]) for coverage in P0_IDS}
 arm=default_compatibility(HEX).arm(())
 cells=[]; rows=[]
 for coverage in P0_IDS:
  for benchmark in ("discoverybench","blade"):
   task=public_task(benchmark,coverage)
   for variant in registry()[coverage].variants:
    cell=PanelCell(coverage,task.identity,"r1",variant,"p0-fixed",arm,task.content_hash,HEX,HEX,HEX); cells.append(cell)
    sidecar=tmp_path/f"{coverage}-{benchmark}-{variant}"
    objective=FrozenRecord.from_dict({"question":"P0 fixture"})
    run=RunSession(task,package_digest=HEX,arm=arm,objective=objective,slots=("only",),execution_limit=0,sidecar=sidecar,verifier=AuditVerifier({"a":b"a"*32,"b":b"b"*32}),required_audit=("audit",))
    candidate=FrozenRecord.from_dict({"objective_digest":objective.content_hash,"outcome":"unknown","evidence_ids":[],"conclusion":"engineering P0 fixture","programme_complete":False})
    context=FrozenRecord.from_dict({"panel_cell":{"experiment_id":coverage,"variant":variant,"replicate":"r1","arm_id":"p0-fixed","scenario_digest":HEX},"p0_control_digest":HEX if wrong_control else controls[coverage]})
    assert run.invoke("only",lambda _:candidate,instruction="P0 fixture",module_context=context)==candidate
    terminal=run.finish(candidate)
    trace=(sidecar/"trace.jsonl"); lines=trace.read_text(encoding="utf-8").splitlines()
    out=FrozenRecord.from_dict({"responses":[candidate.data()],"terminal":terminal.data()}).content_hash
    rows.append(RuntimeReceipt(cell.key,"succeeded",trace,FrozenRecord(lines[-1]).content_hash,out))
 panel=FrozenPanel("P0", "train",HEX,HEX,P0_IDS,grids,FrozenRecord.from_dict({"criterion":"engineering only"}),tuple(cells),obligations())
 return panel,rows

def test_every_p0_only_variant_and_adapter_has_actual_bound_journal(tmp_path):
 panel,rows=build(tmp_path)
 verdict=PanelReceiptVerifier().verify(panel,rows)
 assert verdict.decision=="engineering_verified" and verdict.scientific_verified is False
 assert len(rows)==2*sum(len(registry()[x].variants) for x in P0_IDS)

def test_p0_panel_rejects_missing_cell_missing_control_digest_and_extra_arm(tmp_path):
 panel,rows=build(tmp_path)
 with pytest.raises(ContractError,match="coverage mismatch"): PanelReceiptVerifier().verify(panel,rows[:-1])
 with pytest.raises(ContractError): fixed_control_design(HEX,"")
 bad=panel.legal_arm_grids["Q2.2"].data(); bad["arms"].append({"id":"extra","runtime_arm":bad["runtime_arm"]})
 with pytest.raises(ContractError): FrozenPanel(panel.stage,panel.domain,panel.split_digest,panel.candidate_digest,panel.scope_ids,{**panel.legal_arm_grids,"Q2.2":FrozenRecord.from_dict(bad)},panel.acceptance_criteria,panel.cells,panel.combinations)

def test_p0_control_binding_must_match_actual_journal_request(tmp_path):
 panel,rows=build(tmp_path,wrong_control=True)
 with pytest.raises(ContractError,match="frozen P0 control binding"):
  PanelReceiptVerifier().verify(panel,rows)
