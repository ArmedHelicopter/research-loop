import hashlib
import json
from pathlib import Path

import pytest

from evaluation.modular import primary_process_qualification as qualification
from evaluation.modular.primary_prospective_exporter import PrimaryProspectiveTrainExporter, PrimaryTrainExportItem
from evaluation.modular.fresh_airs_custodian import CustodyError
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import digest
from test_primary_process_qualification import source_fixture, pin, write, SECRET


def setup_export(tmp_path, *, output_name="export"):
    config = source_fixture(tmp_path, public_projection=True)
    sealed = tmp_path / "sealed"
    receipt = qualification.seal_primary_process(sealed, config)
    split = json.loads((sealed / "prospective-split.json").read_bytes())
    audit = json.loads((sealed / "process-audit.json").read_bytes())
    policy = {"schema": "primary-train-export-eligibility-v1", "split_sha256": receipt["split_sha256"],
              "audit_sha256": receipt["audit_sha256"], "train_export_enabled": True,
              "held_group_sha256": [], "held_member_tokens": [], "review_evidence_sha256": [digest("independent-fixture-review")],
              "validation_access_enabled": False}
    eligibility = tmp_path / "eligibility.json"
    write(eligibility, policy)
    exporter = PrimaryProspectiveTrainExporter(config, sealed, expected_split_digest=receipt["split_sha256"],
        expected_audit_digest=receipt["audit_sha256"], eligibility_path=eligibility, eligibility_sha256=pin(eligibility)["sha256"],
        expected_split_sha256=pin(sealed / "prospective-split.json")["sha256"], expected_audit_sha256=pin(sealed / "process-audit.json")["sha256"],
        output_root=tmp_path / output_name, audit_root=tmp_path / "export-audit")
    sources = {row["token"]: row["source"] for row in audit["rows"]}
    items = {domain: [PrimaryTrainExportItem(sources[token], token, group["group_sha256"], digest(audit["input_bindings"]))
                      for group in split["groups"] if group["split"] == domain for token in group["member_tokens"]]
             for domain in ("train", "validation")}
    selected = [next(item for item in items["train"] if item.source == source) for source in qualification.SOURCES]
    return exporter, selected, items, split


def events(exporter):
    return [json.loads(line) for line in (exporter.audit_root / "exports.jsonl").read_bytes().splitlines()]


def test_real_public_adapters_and_standard_controller_packet_shape(tmp_path):
    exporter, selected, _, split = setup_export(tmp_path)
    before = Path(exporter.config["inputs"]["custody"]["path"]).read_bytes()
    packets = exporter.export_packets(selected)
    assert len(packets) == 2
    assert {packet.task.identity.benchmark for packet in packets} == set(qualification.SOURCES)
    for packet, item in zip(packets, selected, strict=True):
        assert packet.task.identity.split_id == digest(split)
        assert packet.task.identity.domain == "train"
        receipt = packet.receipt.data()
        assert receipt["export_token"] == item.token
        assert receipt["packet_hash"] == packet.task.content_hash
        assert receipt["csv_sha256"] == hashlib.sha256(packet.csv_path.read_bytes()).hexdigest()
        assert receipt["csv_byte_count"] == packet.csv_path.stat().st_size
        assert json.loads(packet.packet_path.read_bytes()) == {"task": packet.task.data(), "receipt": receipt}
        assert SECRET not in packet.packet_path.read_text()
    assert Path(exporter.config["inputs"]["custody"]["path"]).read_bytes() == before
    assert [row["event"] for row in events(exporter)] == ["export_reserved", "sources_verified", "exposure_reserved", "exposure_reserved", "export_completed"]


@pytest.mark.parametrize("fault", ["validation", "source", "group", "input", "schema", "hold", "held_group", "held_token"])
def test_metadata_denial_precedes_source_read_and_exposure_reservation(tmp_path, monkeypatch, fault):
    exporter, selected, items, _ = setup_export(tmp_path)
    if fault == "validation":
        selected = [items["validation"][0]]
    elif fault in {"source", "group", "input"}:
        value = selected[0].data()
        key = {"source": "source", "group": "group_sha256", "input": "input_bindings_digest"}[fault]
        value[key] = "blade" if fault == "source" else digest("foreign")
        selected = [PrimaryTrainExportItem(**value)]
    elif fault == "schema":
        exporter.config["schema"] = "unknown-schema"
    else:
        policy = json.loads(exporter.eligibility_path.read_bytes())
        if fault == "hold":
            policy["train_export_enabled"] = False
        elif fault == "held_group":
            policy["held_group_sha256"] = [selected[0].group_sha256]
        else:
            policy["held_member_tokens"] = [selected[0].token]
        write(exporter.eligibility_path, policy)
        exporter.eligibility_sha256 = pin(exporter.eligibility_path)["sha256"]
    reads = []
    monkeypatch.setattr(exporter, "_source_bindings", lambda: reads.append("read"))
    with pytest.raises(CustodyError):
        exporter.export_packets(selected)
    assert reads == [] and not exporter.output_root.exists()
    assert all(row["event"] != "exposure_reserved" for row in events(exporter))


@pytest.mark.parametrize("fault", ["input", "source", "eligibility", "split", "audit"])
def test_frozen_pins_drift_refused_before_public_materialization(tmp_path, fault):
    exporter, selected, _, _ = setup_export(tmp_path)
    path = {"input": Path(exporter.config["inputs"]["later_ledger"]["path"]),
            "source": Path(exporter.config["snapshot_root"]) / "scienceagent/work/BLADE/blade_bench/datasets/case0/data.csv",
            "eligibility": exporter.eligibility_path,
            "audit": exporter.sealed_root / "process-audit.json",
            "split": exporter.sealed_root / "prospective-split.json"}[fault]
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(CustodyError):
        exporter.export_packets(selected)
    assert not exporter.output_root.exists()
    assert not any(row["event"] == "exposure_reserved" for row in events(exporter))


def test_data_changed_after_source_check_is_not_projected_or_written(tmp_path, monkeypatch):
    exporter, selected, _, _ = setup_export(tmp_path)
    real = exporter._verify_source_receipts
    def drift(*args):
        result = real(*args)
        path = Path(exporter.config["snapshot_root"]) / "scienceagent/work/BLADE/blade_bench/datasets/case0/data.csv"
        path.write_text("PRIVATE_LABEL_DATA")
        return result
    monkeypatch.setattr(exporter, "_verify_source_receipts", drift)
    with pytest.raises(CustodyError):
        exporter.export_packets(selected)
    assert not exporter.output_root.exists()
    assert not any(row["event"] == "exposure_reserved" for row in events(exporter))


def test_same_byte_symlink_swap_is_rejected_by_concrete_reader(tmp_path):
    exporter, selected, _, _ = setup_export(tmp_path)
    path = Path(exporter.config["snapshot_root"]) / "scienceagent/work/BLADE/blade_bench/datasets/case0/data.csv"
    original = tmp_path / "same-byte-target.csv"
    original.write_bytes(path.read_bytes())
    path.unlink()
    try:
        path.symlink_to(original)
    except OSError:
        pytest.skip("host does not grant symlink creation")
    with pytest.raises(CustodyError):
        exporter.export_packets(selected)
    assert not exporter.output_root.exists()


def test_partial_failure_keeps_exposure_and_fixed_cost_receipts(tmp_path, monkeypatch):
    exporter, selected, _, _ = setup_export(tmp_path)
    def fail(*args):
        raise OSError(SECRET)
    monkeypatch.setattr("evaluation.modular.prospective_train_exporter.os.replace", fail)
    with pytest.raises(CustodyError) as error:
        exporter.export_packets(selected)
    log = events(exporter)
    assert set(log[-1]["possibly_exposed_tokens"]) == {item.token for item in selected}
    assert log[-1]["event"] == "export_failed" and log[-1]["model_calls"] == 0
    assert SECRET not in json.dumps(log) + str(error.value)
    assert len(list(exporter.audit_root.glob("attempt-*/staging/*/data.csv"))) == 2


@pytest.mark.parametrize("fault", [None, "validation", "hold", "roots", "both_ports"])
def test_actual_controller_consumes_prospective_packets_without_custody_conversion(tmp_path, monkeypatch, fault):
    from test_modular_train_controller import model_port, SCENARIO, FINAL
    from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
    from research_loop.modular.panel_plan import executable_arms, obligation_grids
    from research_loop.modular.runtime import AuditVerifier
    from research_loop.modular.train_controller import FrozenTrainControllerConfig, run_train_panel
    exporter, selected, all_items, _ = setup_export(tmp_path / "fixture", output_name="pre-export")
    packets = exporter.export_packets(selected)
    tasks = [packet.task for packet in packets]
    package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([task.identity for task in tasks]),
        changes={"prompt": {"instructions": "Synthetic training fixture"}}, search_cost=0)
    control = FrozenRecord.from_dict({"source": "synthetic", "always_enabled": True})
    grids = obligation_grids(("Q3.1",), baseline_digest="a" * 64, p0_control=control)
    config = FrozenTrainControllerConfig(FrozenRecord.from_dict({"schema": "q31-train-controller-v1", "engineering_scope": "train_only_q3_1_engineering",
        "stage": "synthetic-primary-prospective", "scope_ids": ["Q3.1"], "item_ids": [item.token for item in selected],
        "evidence_by_task": {task.content_hash: {"observations": []} for task in tasks}, "budget": {"model_calls": 2, "execution_limit": 0},
        "baseline_digest": "a" * 64, "p0_control": control.data(), "packages_by_arm": {arm.content_hash: package.record.data() for arm in executable_arms(grids["Q3.1"]).values()},
        "scorer": {"identity": "independent-fixture-only-not-in-solver"}, "acceptance_criteria": {"scope": "engineering-only"},
        "replicates": ["r1"], "model": "gpt-5.6-luna", "effort": "low", "max_calls": 24, "max_tokens": 200,
        "schemas": {"scenario": SCENARIO, "final": FINAL}}))
    actual = PrimaryProspectiveTrainExporter(exporter.config, exporter.sealed_root,
        expected_split_digest=exporter.expected_split_digest, expected_audit_digest=exporter.expected_audit_digest,
        expected_split_sha256=exporter.seal_file_sha256["split"], expected_audit_sha256=exporter.seal_file_sha256["audit"],
        eligibility_path=exporter.eligibility_path, eligibility_sha256=exporter.eligibility_sha256,
        output_root=tmp_path / "controller-export", audit_root=tmp_path / "controller-export-audit")
    port = model_port(tmp_path / "port", monkeypatch)
    custody = None
    export_root = actual.output_root
    if fault == "validation":
        config = FrozenTrainControllerConfig(FrozenRecord.from_dict({**config.data(), "item_ids": [all_items["validation"][0].token, selected[1].token]}))
    elif fault == "hold":
        policy = json.loads(actual.eligibility_path.read_bytes())
        policy["train_export_enabled"] = False
        write(actual.eligibility_path, policy)
        actual.eligibility_sha256 = pin(actual.eligibility_path)["sha256"]
    elif fault == "roots":
        export_root = tmp_path / "foreign-export-root"
    elif fault == "both_ports":
        from evaluation.modular.custody import CustodyStore
        custody = CustodyStore(tmp_path / "other-custody.json")
    kwargs = dict(custody=custody, prospective_exporter=actual,
        snapshot_root=Path(actual.config["snapshot_root"]), export_root=export_root, run_root=tmp_path / "run", model=port,
        audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}))
    if fault:
        from research_loop.ontology import ContractError
        with pytest.raises((CustodyError, ContractError)):
            run_train_panel(config, **kwargs)
        assert port.ledger["calls"] == []
        assert not actual.output_root.exists()
        return
    result = run_train_panel(config, **kwargs)
    assert len(result.packets) == 2 and len(result.runtimes) == 12
    assert len(port.ledger["calls"]) == 24
    assert result.receipt.data()["execution_status"] == "engineering_complete"
    assert result.verdict.scientific_verified is False
    assert all(runtime.status == "succeeded" for runtime in result.runtimes)
    assert SECRET not in "".join(runtime.trace_path.read_text() for runtime in result.runtimes)
