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

def panel(tmp_path: Path, *, domain: str = "train", identities=None) -> tuple[FrozenPanel, list[RuntimeReceipt]]:
    compatibility = default_compatibility(DIGEST)
    scope = {key: registry()[key] for key in ("Q1.3", "Q2.5")}
    designs = {coverage: compatibility.conditional_factorial(spec.modules) for coverage, spec in scope.items()}
    cells, runtime = [], []
    for coverage, spec in scope.items():
        arms = {row["id"]: FrozenRecord.from_dict(row["arm"]) for row in designs[coverage].data()["cells"] if row["status"] == "executable"}
        for benchmark in ("discoverybench", "blade"):
            identity = identities[(domain, coverage, benchmark)] if identities is not None else DataIdentity(benchmark, f"{coverage}-{benchmark}", f"g-{coverage}", "v1", DIGEST, domain)
            task = PublicTask.create(identity, {"question": "public fixture"})
            for variant in spec.variants:
                for arm_id, arm in arms.items():
                    cell = PanelCell(coverage, identity, "r1", variant, arm_id, arm, task.content_hash, DIGEST, DIGEST, DIGEST)
                    cells.append(cell)
                    path = tmp_path / f"{coverage}-{benchmark}-{variant}-{arm_id}"
                    trace_digest, output_digest = trace(path, task=task, package=DIGEST, arm=arm, coverage=coverage, variant=variant, replicate="r1", arm_id=arm_id)
                    runtime.append(RuntimeReceipt(cell.key, "succeeded", path / "trace.jsonl", trace_digest, output_digest))
    return FrozenPanel("C1", domain, cells[0].identity.split_id, DIGEST, tuple(scope), designs, FrozenRecord.from_dict({"criterion": "frozen"}), tuple(cells), obligations()), runtime


def _panel_custody(tmp_path):
    """Real store transitions over authored fixtures, no dataset contents."""
    from evaluation.modular.custody import CustodyStore, InventoryItem
    from research_loop.ontology import digest
    store = CustodyStore(tmp_path / "fixture-state.json", calibration_keys={"calibration": b"k" * 32},
                         signing_authority_id="custody", signing_key=b"c" * 32)
    items, keys = [], {}
    for domain in ("train", "validation"):
        for coverage in ("Q1.3", "Q2.5"):
            for benchmark in ("discoverybench", "blade"):
                item_id = f"{domain}-{coverage}-{benchmark}"
                item = InventoryItem(benchmark, item_id, "source-" + item_id, "fixture", "fixture", (digest({"source": item_id}),), "exposed" if domain == "train" else "unknown")
                items.append(item); keys[f"{benchmark}:{item_id}"] = (domain, coverage, benchmark)
    store.inventory(items)
    for item in items:
        if item.exposure == "unknown":
            store.attest_independent_clean(item_ids=[f"{item.benchmark}:{item.task_id}"], custodian_id="fixture-custodian",
                source_qualification_digest="2" * 64, exposure_qualification_digest="3" * 64, tested_arm_ids=["fixture-tested-arm"])
    split = store.split(seed="fixture-panel", validation_percent=100)
    by_id = {f"{item.benchmark}:{item.task_id}": item for item in items}
    identities = {}
    for row in split["rows"]:
        item = by_id[row["item"]]
        identities[keys[row["item"]]] = DataIdentity(item.benchmark, item.task_id, row["group"], store.state["inventory_digest"], split["digest"], row["domain"])
    return store, identities


def _consumed_panel_lease(store, frozen):
    from test_modular_custody_panel import calibration, PROTOCOL
    receipt = calibration(frozen.digest)
    leased = store.lease_panel(frozen, calibration_receipt=receipt, protocol_digest=PROTOCOL)
    store.consume_validation(leased["id"], panel_digest=frozen.digest, arm_schedule=list(frozen.arm_schedule))
    return store.issued_validation_receipt(leased["id"]), receipt, PROTOCOL

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
    with pytest.raises(ContractError, match="independently cover every required benchmark"):
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
    custody, identities = _panel_custody(tmp_path / "custody")
    frozen, rows = panel(tmp_path / "runtime", domain="validation", identities=identities)
    scorer = lambda receipt, cell, panel: None
    accept = SignedAuthority("accept", b"d" * 32)
    scores = [ScientificScorerReceipt(row.cell_key, FrozenRecord.from_dict({"schema": "independent-scored-cell-v1", "runtime_trace_digest": row.trace_digest, "scorer_digest": DIGEST, "metrics": {"score": 1}})) for row in rows]
    lease, calibration, protocol = _consumed_panel_lease(custody, frozen)
    acceptance = accept.issue({"schema": "panel-acceptance-v1", "panel_digest": frozen.digest,
        "candidate_digest": frozen.candidate_digest, "lease_digest": lease.content_hash,
        "runtime_digest": FrozenRecord.from_dict({"runtime": [PanelReceiptVerifier._runtime_data(row) for row in sorted(rows, key=lambda row: row.cell_key)]}).content_hash,
        "scorer_receipts_digest": FrozenRecord.from_dict({"scorer": [
            {"cell_key": list(row.cell_key), "receipt_digest": row.receipt.content_hash}
            for row in sorted(scores, key=lambda row: row.cell_key)]}).content_hash,
        "decision": decision})
    verifier = PanelReceiptVerifier(scorer_verifier=scorer, custody_keys={"custody": b"c" * 32}, acceptance_keys={"accept": b"d" * 32}, calibration_keys={"calibration": b"k" * 32})
    result = verifier.verify(frozen, rows, scorer_receipts=scores, validation=ValidationAcceptance(lease, acceptance, calibration, protocol))
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


def _fixture_scoring(rows):
    """Trusted test authority, not a scientific scorer/calibration claim."""
    from research_loop.modular.panel_receipts import verify_signed
    authority = SignedAuthority("fixture-scorer", b"s" * 32)
    scores = []
    for row in rows:
        body = {"schema": "independent-scored-cell-v1", "runtime_trace_digest": row.trace_digest,
                "scorer_digest": DIGEST, "cell_key": list(row.cell_key), "fixture_only": True}
        scores.append(ScientificScorerReceipt(row.cell_key, FrozenRecord.from_dict({
            **body, "attestation": authority.issue(body).data()})))
    def verify(receipt, cell, frozen):
        body = receipt.receipt.data()
        signed = verify_signed(FrozenRecord.from_dict(body["attestation"]),
                               {"fixture-scorer": b"s" * 32}, schema="independent-scored-cell-v1")
        assert signed == {key: value for key, value in body.items() if key != "attestation"} | {"authority": "fixture-scorer"}
        assert signed["cell_key"] == list(cell.key)
    return tuple(scores), verify


def _ledger_ready():
    from research_loop.modular.experiments import ExperimentLedger
    return ExperimentLedger.create().transition("Q1.3", "implemented", implementation_ref="fixture") .transition(
        "Q1.3", "integration_verified", implementation_ref="fixture-trace")


def test_ledger_rechecks_actual_panel_and_rejects_missing_cells_unscored_and_tampering(tmp_path):
    frozen, rows = panel(tmp_path)
    ledger = _ledger_ready()
    with pytest.raises(ContractError, match="insufficient for scientific measurement"):
        ledger.transition("Q1.3", "train_measured", panel=frozen, runtime_receipts=tuple(rows), panel_verifier=PanelReceiptVerifier())
    scores, verify = _fixture_scoring(rows)
    verifier = PanelReceiptVerifier(scorer_verifier=verify)
    with pytest.raises(ContractError, match="coverage mismatch"):
        ledger.transition("Q1.3", "train_measured", panel=frozen, runtime_receipts=tuple(rows[:-1]), scorer_receipts=scores, panel_verifier=verifier)
    forged = RuntimeReceipt(rows[0].cell_key, "succeeded", rows[0].trace_path, "b" * 64, rows[0].output_digest)
    with pytest.raises(ContractError, match="hash-chained"):
        ledger.transition("Q1.3", "train_measured", panel=frozen, runtime_receipts=(forged, *rows[1:]), scorer_receipts=scores, panel_verifier=verifier)
    trained = ledger.transition("Q1.3", "train_measured", panel=frozen, runtime_receipts=tuple(rows), scorer_receipts=scores, panel_verifier=verifier)
    assert trained.data()["Q1.3"]["train_measurement"]["observed_cells"] == len(rows)
    assert trained.data()["Q2.5"]["status"] == "designed"
    with pytest.raises(ContractError, match="explicit immutable train selection"):
        trained.transition("Q1.3", "candidate_frozen")


@pytest.mark.parametrize("decision", ["accepted", "rejected", "inconclusive"])
def test_ledger_validation_binds_frozen_training_selection_and_independent_decision(tmp_path, decision):
    custody, identities = _panel_custody(tmp_path / "custody")
    train, train_rows = panel(tmp_path / "train", identities=identities)
    train_scores, verify = _fixture_scoring(train_rows)
    verifier = PanelReceiptVerifier(scorer_verifier=verify, custody_keys={"custody": b"c" * 32}, acceptance_keys={"accept": b"d" * 32}, calibration_keys={"calibration": b"k" * 32})
    trained = _ledger_ready().transition("Q1.3", "train_measured", panel=train, runtime_receipts=tuple(train_rows), scorer_receipts=train_scores, panel_verifier=verifier)
    selection = FrozenRecord.from_dict({"training_panel_digest": train.digest, "candidate_digest": train.candidate_digest,
        "split_digest": train.split_digest, "scorer_digest": DIGEST, "acceptance_criteria_digest": train.acceptance_criteria.content_hash,
        "required_benchmarks": list(train.required_benchmarks)})
    selected = trained.transition("Q1.3", "candidate_frozen", frozen_candidate=selection)
    frozen, rows = panel(tmp_path / "validation", domain="validation", identities=identities)
    scores, _ = _fixture_scoring(rows)
    with pytest.raises(ContractError, match="custody and acceptance"):
        selected.transition("Q1.3", "validation_measured", panel=frozen, runtime_receipts=tuple(rows), scorer_receipts=scores, panel_verifier=verifier)
    accept = SignedAuthority("accept", b"d" * 32)
    lease, calibration, protocol = _consumed_panel_lease(custody, frozen)
    acceptance = accept.issue({"schema": "panel-acceptance-v1", "panel_digest": frozen.digest,
        "candidate_digest": frozen.candidate_digest, "lease_digest": lease.content_hash,
        "runtime_digest": FrozenRecord.from_dict({"runtime": [PanelReceiptVerifier._runtime_data(row) for row in sorted(rows, key=lambda row: row.cell_key)]}).content_hash,
        "scorer_receipts_digest": FrozenRecord.from_dict({"scorer": [
            {"cell_key": list(row.cell_key), "receipt_digest": row.receipt.content_hash}
            for row in sorted(scores, key=lambda row: row.cell_key)]}).content_hash, "decision": decision})
    validation = ValidationAcceptance(lease, acceptance, calibration, protocol)
    with pytest.raises(ContractError, match="independently verified acceptance"):
        selected.transition("Q1.3", "validation_measured", panel=frozen, runtime_receipts=tuple(rows), scorer_receipts=scores,
                            panel_verifier=PanelReceiptVerifier(scorer_verifier=verify), validation_acceptance=validation)
    measured = selected.transition("Q1.3", "validation_measured", panel=frozen, runtime_receipts=tuple(rows), scorer_receipts=scores,
                                   panel_verifier=verifier, validation_acceptance=validation)
    other = "rejected" if decision == "accepted" else "accepted"
    with pytest.raises(ContractError, match="independent validation verdict"):
        measured.transition("Q1.3", other)
    assert measured.transition("Q1.3", decision).data()["Q1.3"]["status"] == decision
