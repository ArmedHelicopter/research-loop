"""Synthetic custody-to-panel lease chain; no labels, validation data, or network."""
from pathlib import Path

import pytest

from evaluation.modular.calibration import CalibrationAuthority
from evaluation.modular.custody import CustodyStore, InventoryItem
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.experiments import registry
from research_loop.modular.panel_receipts import (
    CombinationObligations, FrozenPanel, PanelCell, PanelReceiptVerifier, RuntimeReceipt,
    ScientificScorerReceipt, SignedAuthority, ValidationAcceptance,
)
from research_loop.modular.runtime import AuditVerifier, RunSession
from research_loop.ontology import ContractError, digest


DIGEST, PROTOCOL = "a" * 64, "c" * 64
CRITERIA = {"minimum_cases_per_benchmark": 9,
            "minimum_coverage": {name: 1 for name in ("valid_positive", "valid_negative", "invalid_measurement", "uncertain", "negation_or_quoted_completion", "correct_rejection", "over_rejection", "reasonable_alternative", "empty_output")},
            "minimum_precision": .8, "minimum_recall": .8, "maximum_abstention_rate": .2, "maximum_uncertainty": .2}


def calibration(panel_digest: str) -> FrozenRecord:
    coverage = {name: 1 for name in CRITERIA["minimum_coverage"]}
    matrix = {"tp": 4, "tn": 4, "fp": 0, "fn": 0, "abstained": 1}
    return CalibrationAuthority("calibration", b"k" * 32).issue({
        "schema": "scorer-calibration-v1", "panel_digest": panel_digest, "scorer_digest": DIGEST,
        "protocol_digest": PROTOCOL, "scorer_code_digest": "d" * 64, "judge_identity": "synthetic-independent",
        "judge_parameters": {"temperature": 0}, "rubric_digest": "e" * 64, "calibration_manifest_digest": "f" * 64,
        "blind_review_protocol_digest": "1" * 64, "arbitration_protocol_digest": "2" * 64,
        "applicable_benchmarks": ["blade", "discoverybench"], "criteria": CRITERIA,
        "criteria_digest": digest(CRITERIA), "coverage": {"blade": coverage, "discoverybench": coverage},
        "confusion_matrix": {"blade": matrix, "discoverybench": matrix}, "uncertainty": {"blade": .1, "discoverybench": .1},
    })


def obligations() -> CombinationObligations:
    from itertools import combinations
    modules = tuple(f"M{i}" for i in range(1, 10))
    return CombinationObligations(tuple(combinations(modules, 2)),
        (("M2", "M3", "M5"), ("M4", "M5", "M6"), ("M1", "M4", "M7"), ("M3", "M6", "M9"), ("M7", "M8", "M9")), modules, modules)


def panel(tmp_path: Path, split_digest: str) -> tuple[FrozenPanel, tuple[RuntimeReceipt, ...]]:
    spec, design = registry()["Q1.3"], default_compatibility(DIGEST).conditional_factorial(("M2",))
    arms = {row["id"]: FrozenRecord.from_dict(row["arm"]) for row in design.data()["cells"] if row["status"] == "executable"}
    cells, rows = [], []
    for benchmark in ("blade", "discoverybench"):
        identity = DataIdentity(benchmark, f"g-Q1.3", "g-Q1.3", "v1", split_digest, "validation")
        task = PublicTask.create(identity, {"question": "synthetic public fixture"})
        for variant in spec.variants:
            for arm_id, arm in arms.items():
                cell = PanelCell("Q1.3", identity, "r1", variant, arm_id, arm, task.content_hash, DIGEST, DIGEST, DIGEST)
                sidecar = tmp_path / benchmark / variant / arm_id
                run = RunSession(task, package_digest=DIGEST, arm=arm, objective=FrozenRecord.from_dict({"q": "fixture"}),
                                 slots=("only",), execution_limit=0, sidecar=sidecar,
                                 verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}), required_audit=("audit",))
                candidate = FrozenRecord.from_dict({"objective_digest": run.objective.content_hash, "outcome": "unknown", "evidence_ids": [], "conclusion": "fixture", "programme_complete": False})
                context = FrozenRecord.from_dict({"panel_cell": {"experiment_id": "Q1.3", "variant": variant, "replicate": "r1", "arm_id": arm_id, "scenario_digest": DIGEST}})
                response = run.invoke("only", lambda _: candidate, instruction="fixture", module_context=context)
                terminal = run.finish(response)
                trace = sidecar / "trace.jsonl"
                output = FrozenRecord.from_dict({"responses": [response.data()], "terminal": terminal.data()}).content_hash
                rows.append(RuntimeReceipt(cell.key, "succeeded", trace, run._events[-1].content_hash, output)); cells.append(cell)
    return FrozenPanel("C1", "validation", split_digest, DIGEST, ("Q1.3",), {"Q1.3": design}, FrozenRecord.from_dict({"criterion": "fixture"}), tuple(cells), obligations()), tuple(rows)


def custody_store(tmp_path: Path) -> tuple[CustodyStore, str]:
    store = CustodyStore(tmp_path / "custody.json", calibration_keys={"calibration": b"k" * 32},
                         signing_authority_id="custody", signing_key=b"s" * 32)
    items = [InventoryItem(benchmark, "g-Q1.3", "fixture-source-" + benchmark, "fixture", "fixture", (("0" if benchmark == "blade" else "1") * 64,))
             for benchmark in ("blade", "discoverybench")]
    store.inventory(items)
    for item in items:
        store.attest_independent_clean(item_ids=[f"{item.benchmark}:{item.task_id}"], custodian_id="custodian-" + item.benchmark,
                                       source_qualification_digest="2" * 64, exposure_qualification_digest="3" * 64, tested_arm_ids=["tested"])
    split = store.split(seed="fixture", validation_percent=100)
    return store, split["digest"]


def issue_lease(store: CustodyStore, frozen: FrozenPanel, *, candidate: str = DIGEST) -> FrozenRecord:
    groups = list(frozen.validation_groups)
    calibration_receipt = calibration(frozen.digest)
    lease = store.lease_validation(stage="C1", panel_digest=frozen.digest, candidate_digest=candidate, group_ids=groups,
                                   arm_schedule=list(frozen.arm_schedule), scorer_digest=DIGEST, protocol_digest=PROTOCOL,
                                   calibration_receipt=calibration_receipt)
    with pytest.raises(ContractError, match="only a consumed"):
        store.issued_validation_receipt(lease["id"])
    store.consume_validation(lease["id"], panel_digest=frozen.digest, arm_schedule=list(frozen.arm_schedule))
    return calibration_receipt


def acceptance(frozen: FrozenPanel, rows: tuple[RuntimeReceipt, ...], scores: tuple[ScientificScorerReceipt, ...], lease: FrozenRecord) -> FrozenRecord:
    runtime_digest = FrozenRecord.from_dict({"runtime": [PanelReceiptVerifier._runtime_data(row) for row in sorted(rows, key=lambda row: row.cell_key)]}).content_hash
    scorer_digest = FrozenRecord.from_dict({"scorer": [{"cell_key": list(row.cell_key), "receipt_digest": row.receipt.content_hash} for row in sorted(scores, key=lambda row: row.cell_key)]}).content_hash
    return SignedAuthority("accept", b"t" * 32).issue({"schema": "panel-acceptance-v1", "panel_digest": frozen.digest,
        "candidate_digest": frozen.candidate_digest, "lease_digest": lease.content_hash, "runtime_digest": runtime_digest,
        "scorer_receipts_digest": scorer_digest, "decision": "inconclusive"})


def test_consumed_custody_lease_is_required_for_panel_validation(tmp_path: Path) -> None:
    store, split = custody_store(tmp_path / "state")
    frozen, rows = panel(tmp_path / "runtime", split)
    calibration_receipt = issue_lease(store, frozen)
    lease = store.issued_validation_receipt(next(iter(store.state["leases"])))
    scores = tuple(ScientificScorerReceipt(row.cell_key, FrozenRecord.from_dict({"schema": "independent-scored-cell-v1", "runtime_trace_digest": row.trace_digest, "scorer_digest": DIGEST})) for row in rows)
    verifier = PanelReceiptVerifier(scorer_verifier=lambda *_: None, custody_keys={"custody": b"s" * 32}, acceptance_keys={"accept": b"t" * 32}, calibration_keys={"calibration": b"k" * 32})
    result = verifier.verify(frozen, rows, scorer_receipts=scores,
        validation=ValidationAcceptance(lease, acceptance(frozen, rows, scores, lease), calibration_receipt, PROTOCOL))
    assert result.decision == "inconclusive" and result.scientific_verified
    with pytest.raises(ContractError, match="allocated or consumed"):
        store.lease_validation(stage="C2", panel_digest=frozen.digest, candidate_digest=DIGEST, group_ids=list(frozen.validation_groups), arm_schedule=list(frozen.arm_schedule), scorer_digest=DIGEST, protocol_digest=PROTOCOL, calibration_receipt=calibration_receipt)


def test_wrong_candidate_or_missing_calibration_cannot_pass_panel(tmp_path: Path) -> None:
    store, split = custody_store(tmp_path / "state")
    frozen, rows = panel(tmp_path / "runtime", split)
    calibration_receipt = issue_lease(store, frozen, candidate="9" * 64)
    lease = store.issued_validation_receipt(next(iter(store.state["leases"])))
    scores = tuple(ScientificScorerReceipt(row.cell_key, FrozenRecord.from_dict({"schema": "independent-scored-cell-v1", "runtime_trace_digest": row.trace_digest, "scorer_digest": DIGEST})) for row in rows)
    verifier = PanelReceiptVerifier(scorer_verifier=lambda *_: None, custody_keys={"custody": b"s" * 32}, acceptance_keys={"accept": b"t" * 32}, calibration_keys={"calibration": b"k" * 32})
    with pytest.raises(ContractError, match="custody lease"):
        verifier.verify(frozen, rows, scorer_receipts=scores, validation=ValidationAcceptance(lease, acceptance(frozen, rows, scores, lease), calibration_receipt, PROTOCOL))
    with pytest.raises(ContractError, match="calibration receipt"):
        verifier.verify(frozen, rows, scorer_receipts=scores, validation=ValidationAcceptance(lease, acceptance(frozen, rows, scores, lease)))
