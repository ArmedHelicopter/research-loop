import json
from pathlib import Path

import pytest

from evaluation.modular.fresh_airs_custodian import CustodyError
from evaluation.modular.process_source_qualification import seal_new_split
from evaluation.modular.prospective_train_exporter import ProspectiveTrainExporter, TrainExportItem
from research_loop.ontology import digest
from test_process_source_qualification import _synthetic_seal_config


def setup_export(tmp_path, monkeypatch):
    config = _synthetic_seal_config(tmp_path, monkeypatch, public_projection=True)
    sealed = tmp_path / "sealed"
    receipt = seal_new_split(sealed, config, seed="research-loop-observed-family-split-20260913-v1")
    split = json.loads((sealed / "prospective-split.json").read_bytes())
    exporter = ProspectiveTrainExporter(config, sealed,
        expected_split_digest=receipt["split_sha256"], expected_audit_digest=receipt["audit_sha256"],
        output_root=tmp_path / "public-train", audit_root=tmp_path / "export-audit")
    items = {side: [] for side in ("train", "validation")}
    for group in split["groups"]:
        for token in group["member_tokens"]:
            items[group["split"]].append(TrainExportItem(group["source"], token, group["group_sha256"],
                                                        split["source_receipt_digests"][group["source"]]))
    selected = [next(x for x in items["train"] if x.source == source) for source in ("scicode", "scienceagentbench")]
    return config, exporter, selected, items["validation"], split


def events(exporter):
    return [json.loads(line) for line in (exporter.audit_root / "exports.jsonl").read_bytes().splitlines()]


def test_pinned_source_to_seal_to_real_adapter_projection_seam(tmp_path, monkeypatch):
    config, exporter, selected, _, split = setup_export(tmp_path, monkeypatch)
    before = Path(config["extended_inventory"]).read_bytes()
    result = exporter.export(selected)
    assert len(result.tasks) == 2
    assert {task.identity.benchmark for task in result.tasks} == {"scicode", "scienceagentbench"}
    assert all(task.identity.domain == "train" for task in result.tasks)
    assert all(task.identity.split_id == digest(split) for task in result.tasks)
    assert all("PRIVATE_GOLD" not in json.dumps(task.data()) and "PRIVATE_TEST" not in json.dumps(task.data()) for task in result.tasks)
    assert Path(config["extended_inventory"]).read_bytes() == before
    assert len(list(exporter.output_root.glob("*/public.json"))) == 2
    assert events(exporter)[0]["event"] == "export_reserved"
    assert events(exporter)[-1]["event"] == "export_completed"
    assert events(exporter)[-1]["model_calls"] == 0
    assert result.receipt.data()["scientific_execution_qualified"] is False


def test_validation_rejected_before_snapshot_read_projection_or_output(tmp_path, monkeypatch):
    _, exporter, selected, validation, _ = setup_export(tmp_path, monkeypatch)
    assert validation
    calls = []
    monkeypatch.setattr(exporter, "_verify_source_receipts", lambda *args: calls.append("source_read"))
    with pytest.raises(CustodyError):
        exporter.export([selected[0], validation[0]])
    assert calls == []
    assert not exporter.output_root.exists()
    assert events(exporter)[-1]["event"] == "export_failed"
    assert events(exporter)[-1]["possibly_exposed_tokens"] == []


@pytest.mark.parametrize("changed", ["source", "group_sha256", "source_receipt_digest"])
def test_caller_identity_drift_rejected_before_source_read(tmp_path, monkeypatch, changed):
    _, exporter, selected, _, _ = setup_export(tmp_path, monkeypatch)
    value = selected[0].data()
    value[changed] = "scienceagentbench" if changed == "source" else digest("foreign")
    calls = []
    monkeypatch.setattr(exporter, "_verify_source_receipts", lambda *args: calls.append("read"))
    with pytest.raises(CustodyError):
        exporter.export([TrainExportItem(**value)])
    assert not calls and not exporter.output_root.exists()


def test_sealed_split_tamper_cannot_be_rehashed_by_caller(tmp_path, monkeypatch):
    _, exporter, selected, _, split = setup_export(tmp_path, monkeypatch)
    split["groups"][0]["split"] = "validation" if split["groups"][0]["split"] == "train" else "train"
    (exporter.sealed_root / "prospective-split.json").write_text(json.dumps(split))
    with pytest.raises(CustodyError):
        exporter.export(selected)
    assert not exporter.output_root.exists()


@pytest.mark.parametrize("changed", ["original_receipt", "snapshot", "audit_ledger"])
def test_original_receipt_input_or_actual_snapshot_drift_blocks_before_payload_write(tmp_path, monkeypatch, changed):
    config, exporter, selected, _, _ = setup_export(tmp_path, monkeypatch)
    if changed == "original_receipt":
        acquisition = Path(config["acquisition_receipts"]["scicode"])
    elif changed == "audit_ledger":
        acquisition = Path(config["runs"][0]["ledger"])
    else:
        from research_loop.modular import source_ingestion
        acquisition = (Path(config["extended_private_root"]) / "snapshots/scicode" /
                       source_ingestion.SOURCE_SNAPSHOTS["scicode"].revision / "problems_dev.jsonl")
    acquisition.write_text(acquisition.read_text() + " ")
    with pytest.raises(CustodyError):
        exporter.export(selected)
    assert not exporter.output_root.exists()
    assert events(exporter)[-1]["possibly_exposed_tokens"] == []


def test_bytes_changed_after_first_source_check_are_rejected_before_projection(tmp_path, monkeypatch):
    config, exporter, selected, _, _ = setup_export(tmp_path, monkeypatch)
    from research_loop.modular import source_ingestion
    path = (Path(config["extended_private_root"]) / "snapshots/scicode" /
            source_ingestion.SOURCE_SNAPSHOTS["scicode"].revision / "problems_dev.jsonl")
    real = exporter._verify_source_receipts
    projected = []
    def change_after_check(*args):
        receipt = real(*args)
        path.write_bytes(path.read_bytes() + b" ")
        return receipt
    monkeypatch.setattr(exporter, "_verify_source_receipts", change_after_check)
    monkeypatch.setattr("evaluation.modular.prospective_train_exporter.project_extended_public_record",
                        lambda *args: projected.append("projection"))
    with pytest.raises(CustodyError):
        exporter.export(selected)
    assert projected == [] and not exporter.output_root.exists()


def test_failure_retains_reserved_partial_exposure_without_raw_exception(tmp_path, monkeypatch):
    _, exporter, selected, _, _ = setup_export(tmp_path, monkeypatch)
    def fail(*args):
        raise OSError("PRIVATE_DYNAMIC_ERROR_GOLD")
    monkeypatch.setattr("evaluation.modular.prospective_train_exporter.os.replace", fail)
    with pytest.raises(CustodyError) as error:
        exporter.export(selected)
    assert "PRIVATE" not in str(error.value)
    log = events(exporter)
    assert log[-1]["event"] == "export_failed"
    assert set(log[-1]["possibly_exposed_tokens"]) == {x.token for x in selected}
    assert "PRIVATE" not in json.dumps(log)
    assert len(list(exporter.audit_root.glob("attempt-*/staging/*/public.json"))) == 2


def test_failure_ledger_is_append_only_and_tamper_is_not_reset(tmp_path, monkeypatch):
    _, exporter, _, validation, _ = setup_export(tmp_path, monkeypatch)
    for _ in range(2):
        with pytest.raises(CustodyError):
            exporter.export([validation[0]])
    assert len(events(exporter)) == 4
    path = exporter.audit_root / "exports.jsonl"
    path.write_bytes(path.read_bytes().replace(b'export_failed', b'export_forged'))
    before = path.read_bytes()
    with pytest.raises(CustodyError):
        exporter.export([validation[0]])
    assert path.read_bytes() == before


def test_output_cannot_overlap_private_snapshot_or_sealed_validation(tmp_path, monkeypatch):
    config, exporter, _, _, _ = setup_export(tmp_path, monkeypatch)
    for forbidden in (Path(config["extended_private_root"]) / "public", exporter.sealed_root / "public"):
        with pytest.raises(CustodyError):
            ProspectiveTrainExporter(config, exporter.sealed_root,
                expected_split_digest=exporter.expected_split_digest, expected_audit_digest=exporter.expected_audit_digest,
                output_root=forbidden, audit_root=tmp_path / "other-audit")
