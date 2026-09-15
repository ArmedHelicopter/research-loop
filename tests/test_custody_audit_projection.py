"""Synthetic integration for the neutral, read-only P0 custody auditor."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from evaluation.modular import custody_audit_projection as projection
from evaluation.modular.custody_audit_projection import custody_state_anchor, verify_custody_snapshot
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError
from tests.test_modular_custody_panel import PROTOCOL, custody_store, issue_lease, panel


def _consumed_fixture(tmp_path: Path):
    store, _ = custody_store(tmp_path / "state")
    frozen, _ = panel(tmp_path / "runtime", store)
    issue_lease(store, frozen)
    receipt = store.issued_validation_receipt(next(iter(store.state["leases"])))
    receipt_path = tmp_path / "independent-retention" / "lease.json"
    receipt_path.parent.mkdir()
    receipt_path.write_text(receipt.encoded + "\n", encoding="utf-8", newline="\n")
    return store.path, FrozenRecord(receipt_path.read_text(encoding="utf-8").strip())


def test_auditor_reads_pinned_state_and_independently_retained_signed_receipt_without_writing_state(tmp_path: Path) -> None:
    state_path, receipt = _consumed_fixture(tmp_path)
    before = state_path.read_bytes()
    report = verify_custody_snapshot(state_path, anchor=custody_state_anchor(before), receipt=receipt,
                                     receipt_keys={"custody": b"s" * 32}).data()
    assert state_path.read_bytes() == before
    assert report["optimizer_visible"] is False and report["scientific_validated"] is False
    assert report["receipt_observation"]["status"] == "verified"
    assert report["lease_count"] == 1 and report["leases"][0]["status"] == "consumed"
    assert report["verification_scope"]["split_allocation_replayed"] is True
    assert report["verification_scope"]["independent_custodian_authority_verified"] is False
    encoded = FrozenRecord.from_dict(report).encoded
    assert "g-Q1.3" not in encoded and str(state_path) not in encoded and "s" * 32 not in encoded


def test_cli_audits_only_absent_receipt_and_refuses_to_overwrite_output(tmp_path: Path) -> None:
    store, _ = custody_store(tmp_path / "state")
    before = store.path.read_bytes()
    anchor = custody_state_anchor(before).data()
    output = tmp_path / "auditor" / "snapshot.json"
    command = [sys.executable, "-m", "evaluation.modular.custody_audit_projection", "--state", str(store.path),
               "--state-sha256", anchor["sha256"], "--state-bytes", str(anchor["bytes"]), "--output", str(output)]
    subprocess.run(command, check=True, capture_output=True, text=True)
    report = FrozenRecord(output.read_text(encoding="utf-8").strip()).data()
    assert report["receipt_observation"] == {"status": "absent"} and store.path.read_bytes() == before
    repeated = subprocess.run(command, capture_output=True, text=True)
    assert repeated.returncode != 0 and output.read_text(encoding="utf-8").endswith("\n")


def test_auditor_rejects_anchor_drift_reanchored_receipt_mismatch_and_change_during_read(tmp_path: Path, monkeypatch) -> None:
    state_path, receipt = _consumed_fixture(tmp_path)
    original = state_path.read_bytes()
    state_path.write_bytes(original + b" ")
    with pytest.raises(ContractError, match="byte anchor"):
        verify_custody_snapshot(state_path, anchor=custody_state_anchor(original))
    changed = json.loads(state_path.read_text(encoding="utf-8"))
    lease = next(iter(changed["leases"].values()))
    lease["status"] = "active"
    state_path.write_text(json.dumps(changed, sort_keys=True, separators=(",", ":")), encoding="utf-8", newline="\n")
    with pytest.raises(ContractError, match="receipt does not exactly replay"):
        verify_custody_snapshot(state_path, anchor=custody_state_anchor(state_path.read_bytes()), receipt=receipt,
                                receipt_keys={"custody": b"s" * 32})
    state_path.write_bytes(original)
    def changed_after_replay(*args, **kwargs):
        state_path.write_bytes(original + b" ")
        return {}
    monkeypatch.setattr(projection, "_verify_leases", changed_after_replay)
    with pytest.raises(ContractError, match="byte anchor"):
        verify_custody_snapshot(state_path, anchor=custody_state_anchor(original))
