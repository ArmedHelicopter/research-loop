"""Synthetic P0 custody transition retention; no private state or VAL input."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from evaluation.modular.custody import CustodyStore, InventoryItem
from evaluation.modular import custody_transition_retention as retention
from evaluation.modular.custody_transition_retention import (
    CustodyTransitionRetainer, custody_transition_manifest_anchor, verify_custody_transition_retention,
)
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError
from tests.test_modular_custody_panel import PROTOCOL, issue_lease, panel


def _store(root: Path, *, retainer=None) -> tuple[CustodyStore, list[InventoryItem]]:
    store = CustodyStore(root / "custody.json", calibration_keys={"calibration": b"k" * 32},
                         signing_authority_id="custody", signing_key=b"s" * 32,
                         audit_retainer=retainer)
    items = [InventoryItem(benchmark, "g-Q1.3", "fixture-source-" + benchmark, "fixture", "fixture", (("0" if benchmark == "blade" else "1") * 64,))
             for benchmark in ("blade", "discoverybench")]
    store.inventory(items)
    for item in items:
        store.attest_independent_clean(item_ids=[f"{item.benchmark}:{item.task_id}"], custodian_id="custodian-" + item.benchmark,
                                       source_qualification_digest="2" * 64, exposure_qualification_digest="3" * 64,
                                       tested_arm_ids=["tested"])
    store.split(seed="fixture", validation_percent=100)
    return store, items


def test_opt_in_transition_retention_replays_real_custody_lifecycle_and_signed_receipt(tmp_path: Path) -> None:
    retainer = CustodyTransitionRetainer(tmp_path / "private-retention")
    store, _ = _store(tmp_path / "host", retainer=retainer)
    frozen, _ = panel(tmp_path / "runtime", store)
    issue_lease(store, frozen)
    receipt = store.issued_validation_receipt(next(iter(store.state["leases"])))
    assert receipt.data()["body"]["status"] == "consumed"
    manifest = (retainer.root / "transitions.jsonl").read_bytes()
    report = verify_custody_transition_retention(retainer.root, receipt_keys={"custody": b"s" * 32},
                                                expected_manifest_anchor=custody_transition_manifest_anchor(manifest),
                                                expected_tail_capture_digest=store.last_audit_capture.data()["capture_digest"],
                                                expected_receipt_digest=receipt.content_hash).data()
    assert report["capture_count"] == 8
    assert report["captures"][-1]["operation"] == "issued_validation_receipt"
    assert report["captures"][-1]["receipt_status"] == "retained"
    assert report["complete_transition_history"] is False and report["missing_or_failed_capture_possible"] is True
    encoded = json.dumps(report, sort_keys=True)
    assert "g-Q1.3" not in encoded and "fixture-source" not in encoded and str(store.path) not in encoded and "s" * 32 not in encoded


def test_readback_rejects_retained_receipt_mismatch(tmp_path: Path) -> None:
    retainer = CustodyTransitionRetainer(tmp_path / "private-retention")
    store, _ = _store(tmp_path / "host", retainer=retainer)
    frozen, _ = panel(tmp_path / "runtime", store)
    issue_lease(store, frozen)
    store.issued_validation_receipt(next(iter(store.state["leases"])))
    receipt_path = retainer.root / "receipt-000008.json"
    receipt_path.write_bytes(receipt_path.read_bytes() + b" ")
    with pytest.raises(ContractError, match="receipt bytes differ"):
        verify_custody_transition_retention(retainer.root, receipt_keys={"custody": b"s" * 32})


def test_capture_failure_is_observable_without_rolling_back_custody_mutation(tmp_path: Path) -> None:
    class BrokenRetainer:
        def capture(self, *args, **kwargs):
            raise OSError("synthetic retention fault")
    store, items = _store(tmp_path / "host", retainer=BrokenRetainer())
    assert store.state["inventory_digest"] is not None and len(store.state["inventory"]) == len(items)
    assert store.last_audit_capture.data() == {"schema": "custody-transition-capture-status-v1", "operation": "split",
                                               "status": "failed", "error": "retention_capture_failed"}


def test_existing_custody_cli_can_opt_into_private_retention_without_changing_state_only_contract(tmp_path: Path) -> None:
    store, _ = _store(tmp_path / "host")
    state_before = store.path.read_bytes()
    root = tmp_path / "private-retention"
    command = [sys.executable, "-m", "evaluation.modular.custody", "--state", str(store.path),
               "--audit-retention-root", str(root), "split", "--seed", "fixture", "--validation-percent", "100"]
    result = subprocess.run(command, check=True, text=True, capture_output=True)
    output = json.loads(result.stdout)
    assert output["audit_capture"]["status"] == "captured" and output["audit_capture"]["operation"] == "split"
    assert store.path.read_bytes() == state_before
    report = verify_custody_transition_retention(root).data()
    assert report["capture_count"] == 1 and report["captures"][0]["receipt_status"] == "absent"


def test_readback_rejects_status_source_and_tail_binding_tampering(tmp_path: Path) -> None:
    retainer = CustodyTransitionRetainer(tmp_path / "private-retention")
    store, _ = _store(tmp_path / "host", retainer=retainer)
    manifest = retainer.root / "transitions.jsonl"
    anchor = custody_transition_manifest_anchor(manifest.read_bytes())
    tail = store.last_audit_capture.data()["capture_digest"]
    statuses = retainer.root / "capture-status.jsonl"
    rows = statuses.read_text(encoding="utf-8").splitlines()
    body = FrozenRecord(rows[1]).data(); body["capture_digest"] = "0" * 64
    rows[1] = FrozenRecord.from_dict(body).encoded
    statuses.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")
    with pytest.raises(ContractError, match="status sequence"):
        verify_custody_transition_retention(retainer.root, expected_manifest_anchor=anchor, expected_tail_capture_digest=tail)
    retainer = CustodyTransitionRetainer(tmp_path / "private-source")
    store, _ = _store(tmp_path / "host-source", retainer=retainer)
    manifest = retainer.root / "transitions.jsonl"
    lines = manifest.read_text(encoding="utf-8").splitlines()
    row = FrozenRecord(lines[0]).data()
    row["producer_sources"] = {"retainer": {"path": "different", "sha256": "0" * 64, "bytes": 1}}
    lines[0] = FrozenRecord.from_dict(row).encoded
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    with pytest.raises(ContractError, match="source"):
        verify_custody_transition_retention(retainer.root)


def test_readback_detects_state_change_after_snapshot_replay(tmp_path: Path, monkeypatch) -> None:
    retainer = CustodyTransitionRetainer(tmp_path / "private-retention")
    _store(tmp_path / "host", retainer=retainer)
    original = retention.verify_custody_snapshot
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        Path(args[0]).write_bytes(Path(args[0]).read_bytes() + b" ")
        return result
    monkeypatch.setattr(retention, "verify_custody_snapshot", mutate)
    with pytest.raises(ContractError, match="changed during readback"):
        verify_custody_transition_retention(retainer.root)
