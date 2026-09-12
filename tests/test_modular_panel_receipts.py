from pathlib import Path

import pytest

from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.experiments import registry
from research_loop.modular.runtime import AuditVerifier, RunSession
from research_loop.modular.contracts import PublicTask
from research_loop.modular.panel_receipts import (
    CombinationObligations, FrozenPanel, PanelCell, PanelReceiptVerifier, RuntimeReceipt,
    ScientificScorerReceipt, SignedAuthority, ValidationAcceptance,
)
from research_loop.ontology import ContractError

DIGEST = "a" * 64

def obligations() -> CombinationObligations:
    from itertools import combinations
    modules = tuple(f"M{i}" for i in range(1, 10))
    return CombinationObligations(tuple(combinations(modules, 2)),
        (("M2", "M3", "M5"), ("M4", "M5", "M6"), ("M1", "M4", "M7"), ("M3", "M6", "M9"), ("M7", "M8", "M9")), modules, modules)

def trace(sidecar: Path, *, task: PublicTask, package: str, arm: FrozenRecord, coverage: str, variant: str, replicate: str, arm_id: str):
    objective = FrozenRecord.from_dict({"question": "fixture"})
    run = RunSession(task, package_digest=package, arm=arm, objective=objective, slots=("only",), execution_limit=0,
        sidecar=sidecar, verifier=AuditVerifier({"a": b"a"*32, "b": b"b"*32}), required_audit=("measurement",))
    context = FrozenRecord.from_dict({"panel_cell": {"experiment_id": coverage, "variant": variant, "replicate": replicate, "arm_id": arm_id, "scenario_digest": DIGEST}})
    candidate = FrozenRecord.from_dict({"objective_digest": objective.content_hash, "outcome": "unknown", "evidence_ids": [], "conclusion": "engineering fixture", "programme_complete": False})
    response = run.invoke("only", lambda _: candidate, instruction="fixture", module_context=context)
    terminal = run.finish(response)
    return run._events[-1].content_hash, FrozenRecord.from_dict({"responses": [response.data()], "terminal": terminal.data()}).content_hash

def panel(tmp_path: Path, *, domain: str = "train") -> tuple[FrozenPanel, list[RuntimeReceipt]]:
    compatibility = default_compatibility(DIGEST)
    scope = {key: registry()[key] for key in ("Q1.3", "Q2.5")}
    designs = {coverage: compatibility.conditional_factorial(spec.modules) for coverage, spec in scope.items()}
    cells, runtime = [], []
    for coverage, spec in scope.items():
        arms = {row["id"]: FrozenRecord.from_dict(row["arm"]) for row in designs[coverage].data()["cells"] if row["status"] == "executable"}
        for benchmark in ("discoverybench", "blade"):
            identity = DataIdentity(benchmark, f"{coverage}-{benchmark}", f"g-{coverage}", "v1", DIGEST, domain)
            task = PublicTask.create(identity, {"question": "public fixture"})
            for variant in spec.variants:
                for arm_id, arm in arms.items():
                    cell = PanelCell(coverage, identity, "r1", variant, arm_id, arm, task.content_hash, DIGEST, DIGEST, DIGEST)
                    cells.append(cell)
                    path = tmp_path / f"{coverage}-{benchmark}-{variant}-{arm_id}"
                    trace_digest, output_digest = trace(path, task=task, package=DIGEST, arm=arm, coverage=coverage, variant=variant, replicate="r1", arm_id=arm_id)
                    runtime.append(RuntimeReceipt(cell.key, "succeeded", path / "trace.jsonl", trace_digest, output_digest))
    return FrozenPanel("C1", domain, DIGEST, DIGEST, tuple(scope), designs, FrozenRecord.from_dict({"criterion": "frozen"}), tuple(cells), obligations()), runtime

def test_complete_panel_requires_all_cells_and_preserves_failures(tmp_path: Path) -> None:
    frozen, rows = panel(tmp_path)
    verdict = PanelReceiptVerifier().verify(frozen, rows)
    assert verdict.decision == "engineering_verified" and verdict.observed_cells == 28
    with pytest.raises(ContractError, match="coverage mismatch"):
        PanelReceiptVerifier().verify(frozen, rows[:-1])
    failed = list(rows)
    first = failed[0]
    failed[0] = RuntimeReceipt(first.cell_key, "unscored", first.trace_path, first.trace_digest, first.output_digest, "scorer unavailable")
    verdict = PanelReceiptVerifier().verify(frozen, failed)
    assert verdict.failures == 0 and verdict.unscored == 1

def test_real_trace_binding_rejects_package_or_task_forgery(tmp_path: Path) -> None:
    frozen, rows = panel(tmp_path)
    bad = list(rows)
    first = bad[0]
    bad[0] = RuntimeReceipt(first.cell_key, first.status, first.trace_path, "b" * 64, first.output_digest)
    with pytest.raises(ContractError, match="hash-chained"):
        PanelReceiptVerifier().verify(frozen, bad)
    bad[0] = RuntimeReceipt(first.cell_key, first.status, first.trace_path, first.trace_digest, "b" * 64)
    with pytest.raises(ContractError, match="output evidence"):
        PanelReceiptVerifier().verify(frozen, bad)

def test_panel_rejects_omitted_variant_arm_and_benchmark_obligation(tmp_path: Path) -> None:
    frozen, _ = panel(tmp_path)
    with pytest.raises(ContractError, match="complete variant by legal-arm grid"):
        FrozenPanel(frozen.stage, frozen.domain, frozen.split_digest, frozen.candidate_digest,
            frozen.scope_ids, frozen.legal_arm_grids, frozen.acceptance_criteria, frozen.cells[:-1], frozen.combinations)
    q = frozen.cells[0].coverage_id
    without_blade = tuple(cell for cell in frozen.cells if not (cell.coverage_id == q and cell.identity.benchmark == "blade"))
    with pytest.raises(ContractError, match="independently cover both benchmarks"):
        FrozenPanel(frozen.stage, frozen.domain, frozen.split_digest, frozen.candidate_digest,
            frozen.scope_ids, frozen.legal_arm_grids, frozen.acceptance_criteria, without_blade, frozen.combinations)
    first = next(cell for cell in frozen.cells if cell.coverage_id == "Q1.3")
    other_arm = next(cell.runtime_arm for cell in frozen.cells if cell.coverage_id == first.coverage_id and cell.arm_id != first.arm_id)
    illegal = PanelCell(first.coverage_id, first.identity, first.replicate, first.variant, first.arm_id,
        other_arm, first.task_digest, first.scenario_digest, first.package_digest, first.scorer_digest)
    with pytest.raises(ContractError, match="compatibility-derived"):
        FrozenPanel(frozen.stage, frozen.domain, frozen.split_digest, frozen.candidate_digest,
            frozen.scope_ids, frozen.legal_arm_grids, frozen.acceptance_criteria, (illegal,) + frozen.cells[1:], frozen.combinations)

def test_validation_never_accepts_a_caller_decision_without_independent_services(tmp_path: Path) -> None:
    frozen, rows = panel(tmp_path, domain="validation")
    fake = ValidationAcceptance(FrozenRecord.from_dict({"arbitrary": "lease"}), FrozenRecord.from_dict({"decision": "accepted"}))
    assert PanelReceiptVerifier().verify(frozen, rows, validation=fake).decision == "engineering_verified"

@pytest.mark.parametrize("decision", ["accepted", "rejected", "inconclusive"])
def test_validation_acceptance_needs_scoring_and_signed_custody_binding(tmp_path: Path, decision: str) -> None:
    frozen, rows = panel(tmp_path, domain="validation")
    scorer = lambda receipt, cell, panel: None
    custody, accept = SignedAuthority("custody", b"c" * 32), SignedAuthority("accept", b"d" * 32)
    scores = [ScientificScorerReceipt(row.cell_key, FrozenRecord.from_dict({"schema": "independent-scored-cell-v1", "runtime_trace_digest": row.trace_digest, "scorer_digest": DIGEST, "metrics": {"score": 1}})) for row in rows]
    lease = custody.issue({"schema": "custody-panel-lease-v1", "panel_digest": frozen.digest,
        "candidate_digest": frozen.candidate_digest, "split_digest": frozen.split_digest,
        "arm_schedule": list(frozen.arm_schedule), "groups": list(frozen.validation_groups), "status": "consumed"})
    acceptance = accept.issue({"schema": "panel-acceptance-v1", "panel_digest": frozen.digest,
        "candidate_digest": frozen.candidate_digest, "lease_digest": lease.content_hash,
        "runtime_digest": FrozenRecord.from_dict({"runtime": [PanelReceiptVerifier._runtime_data(row) for row in sorted(rows, key=lambda row: row.cell_key)]}).content_hash,
        "scorer_receipts_digest": FrozenRecord.from_dict({"scorer": [
            {"cell_key": list(row.cell_key), "receipt_digest": row.receipt.content_hash}
            for row in sorted(scores, key=lambda row: row.cell_key)]}).content_hash,
        "decision": decision})
    verifier = PanelReceiptVerifier(scorer_verifier=scorer, custody_keys={"custody": b"c" * 32}, acceptance_keys={"accept": b"d" * 32})
    result = verifier.verify(frozen, rows, scorer_receipts=scores, validation=ValidationAcceptance(lease, acceptance))
    assert result.decision == decision and result.acceptance_verified == (decision == "accepted")
    unsigned_scoring = PanelReceiptVerifier(acceptance_keys={"accept": b"d"*32})
    assert unsigned_scoring.verify(frozen, rows, validation=ValidationAcceptance(lease, acceptance)).decision == "engineering_verified"

def test_real_runsession_trace_binds_scoped_q13_cells(tmp_path: Path) -> None:
    """No broker or paid model: real journal produced by invoke + finish."""
    compatibility = default_compatibility(DIGEST)
    design = compatibility.conditional_factorial(("M2",))
    arms = {row["id"]: FrozenRecord.from_dict(row["arm"]) for row in design.data()["cells"] if row["status"] == "executable"}
    objective = FrozenRecord.from_dict({"objective": "q13"})
    cells, rows = [], []
    for benchmark in ("discoverybench", "blade"):
        identity = DataIdentity(benchmark, f"q13-{benchmark}", "fresh", "v1", DIGEST, "train")
        task = PublicTask.create(identity, {"prompt": "public"})
        for variant in registry()["Q1.3"].variants:
            for arm_id, arm in arms.items():
                cell = PanelCell("Q1.3", identity, "r1", variant, arm_id, arm, task.content_hash, DIGEST, DIGEST, DIGEST)
                sidecar = tmp_path / f"{benchmark}-{variant}-{arm_id}"
                run = RunSession(task, package_digest=DIGEST, arm=arm, objective=objective, slots=("only",), execution_limit=0,
                    sidecar=sidecar, verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}), required_audit=("audit",))
                candidate = FrozenRecord.from_dict({"objective_digest": objective.content_hash, "outcome": "unknown", "evidence_ids": [], "conclusion": "bounded", "programme_complete": False})
                context = FrozenRecord.from_dict({"panel_cell": {"experiment_id": "Q1.3", "variant": variant, "replicate": "r1", "arm_id": arm_id, "scenario_digest": DIGEST}})
                assert run.invoke("only", lambda request: candidate, instruction="fixture", module_context=context) == candidate
                run.finish(candidate)
                events = [FrozenRecord(line).data() for line in (sidecar / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
                output = FrozenRecord.from_dict({"responses": [candidate.data()], "terminal": events[-1]["data"]}).content_hash
                cells.append(cell); rows.append(RuntimeReceipt(cell.key, "succeeded", sidecar / "trace.jsonl", FrozenRecord((sidecar / "trace.jsonl").read_text(encoding="utf-8").splitlines()[-1]).content_hash, output))
    frozen = FrozenPanel("C1", "train", DIGEST, DIGEST, ("Q1.3",), {"Q1.3": design}, FrozenRecord.from_dict({"criterion": "frozen"}), tuple(cells), obligations())
    assert PanelReceiptVerifier().verify(frozen, rows).decision == "engineering_verified"
