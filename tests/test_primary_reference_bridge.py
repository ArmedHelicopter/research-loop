"""Synthetic references only. No real task answer, model or network access."""
import csv
import hashlib
import json
from pathlib import Path
from dataclasses import replace
import pytest

from evaluation.modular import primary_process_qualification as qualification
from evaluation.modular.primary_prospective_exporter import PrimaryProspectiveTrainExporter, PrimaryTrainExportItem
from evaluation.modular.primary_reference_bridge import PrimaryReferenceItem, PrimaryProspectiveReferenceBridge
from evaluation.modular.reference_store import FrozenTrainReferenceResolver
from evaluation.modular.fresh_airs_custodian import CustodyError
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import digest
from test_primary_process_qualification import source_fixture, pin, write, SECRET

def material(tmp_path):
    config = source_fixture(tmp_path, public_projection=True, reference_projection=True)
    sealed = tmp_path / "sealed"
    receipt = qualification.seal_primary_process(sealed, config)
    split = json.loads((sealed / "prospective-split.json").read_bytes())
    audit = json.loads((sealed / "process-audit.json").read_bytes())
    eligibility = tmp_path / "eligibility.json"
    write(eligibility, {"schema": "primary-train-export-eligibility-v1", "split_sha256": receipt["split_sha256"],
        "audit_sha256": receipt["audit_sha256"], "train_export_enabled": True, "held_group_sha256": [],
        "held_member_tokens": [], "review_evidence_sha256": [digest("fixture-review")], "validation_access_enabled": False})
    exporter = PrimaryProspectiveTrainExporter(config, sealed, expected_split_digest=receipt["split_sha256"],
        expected_audit_digest=receipt["audit_sha256"], expected_split_sha256=pin(sealed / "prospective-split.json")["sha256"],
        expected_audit_sha256=pin(sealed / "process-audit.json")["sha256"], eligibility_path=eligibility,
        eligibility_sha256=pin(eligibility)["sha256"], output_root=tmp_path / "public", audit_root=tmp_path / "exports")
    sources = {row["token"]: row["source"] for row in audit["rows"]}
    items = {domain: [PrimaryTrainExportItem(sources[token], token, group["group_sha256"], digest(audit["input_bindings"]))
        for group in split["groups"] if group["split"] == domain for token in group["member_tokens"]] for domain in ("train", "validation")}
    selected = [next(item for item in items["train"] if item.source == source) for source in qualification.SOURCES]
    packets = exporter.export_packets(selected)
    key = tmp_path / "answer-key.csv"
    with key.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["dataset", "metadataid", "query_id", "gold_hypo"])
        writer.writeheader()
        for index in range(4):
            writer.writerow({"dataset": f"case{index}", "metadataid": index, "query_id": 0,
                "gold_hypo": "SYNTHETIC-DISCOVERY-BRIDGE-REFERENCE"})
        writer.writerow({"dataset": "UNALLOCATED", "metadataid": 99, "query_id": 0, "gold_hypo": "UNALLOCATED-REFERENCE-SENTINEL"})
    keys = {"synth": {**pin(key), "encoding": "utf-8-sig"}}
    requests = [PrimaryReferenceItem(item, packet.task.content_hash, pin(packet.packet_path)["sha256"],
        pin(packet.csv_path)["sha256"], pin(packet.packet_path.parent / "receipt.json")["sha256"])
        for item, packet in zip(selected, packets, strict=True)]
    bridge = PrimaryProspectiveReferenceBridge(exporter=exporter,
        export_receipt_sha256=pin(exporter.output_root / "export-receipt.json")["sha256"],
        store_root=tmp_path / "private-references", audit_root=tmp_path / "reference-audit", discovery_answer_keys=keys)
    return bridge, requests, packets, items

def test_primary_new_identity_reaches_standard_frozen_reference_resolver(tmp_path):
    bridge, requests, packets, _ = material(tmp_path)
    publication = bridge.prepare(requests, packets).data()
    resolver = FrozenTrainReferenceResolver(bridge.store_root, manifest_sha256=publication["manifest_sha256"],
        inventory_digest=publication["inventory_digest"], split_digest=publication["split_digest"])
    assert publication["reference_count"] == 2
    for packet in packets:
        handle = publication["task_handles"][digest(packet.task.identity.data())]
        reference = resolver(handle, packet.task.identity.benchmark)
        assert reference.data()["task_context"] == packet.task.payload.data()
        assert reference.data()["identity_digest"] == digest(packet.task.identity.data())
        assert "UNALLOCATED-REFERENCE-SENTINEL" not in reference.encoded
        assert "SYNTHETIC-" in reference.encoded
    assert "REFERENCE" not in json.dumps(publication)


def journal(bridge):
    return [json.loads(line) for line in (bridge.audit_root / "references.jsonl").read_bytes().splitlines()]


@pytest.mark.parametrize("fault", ["validation", "held_token", "held_group", "wrong_task", "task_digest", "public_digest",
    "csv_digest", "receipt_digest", "selector", "public_file", "export_receipt", "foreign_packet_root", "unknown_schema"])
def test_complete_denial_before_source_or_reference_reads(tmp_path, monkeypatch, fault):
    bridge, requests, packets, items = material(tmp_path)
    packets = list(packets)
    if fault == "validation":
        requests[0] = replace(requests[0], item=items["validation"][0])
    elif fault.startswith("held_"):
        policy = json.loads(bridge.exporter.eligibility_path.read_bytes())
        key = "held_member_tokens" if fault == "held_token" else "held_group_sha256"
        policy[key] = [requests[0].item.token if fault == "held_token" else requests[0].item.group_sha256]
        write(bridge.exporter.eligibility_path, policy)
        bridge.exporter.eligibility_sha256 = pin(bridge.exporter.eligibility_path)["sha256"]
    elif fault in {"task_digest", "public_digest", "csv_digest", "receipt_digest"}:
        requests[0] = replace(requests[0], **{fault.replace("_digest", "_sha256"): digest("wrong")})
    elif fault == "wrong_task":
        packets[0] = replace(packets[0], task=replace(packets[0].task, identity=replace(packets[0].task.identity, task_id="foreign")))
    elif fault == "selector":
        metadata = packets[0].receipt.data()
        metadata["source_selector"]["query_index"] = 1
        packets[0] = replace(packets[0], receipt=FrozenRecord.from_dict(metadata))
    elif fault == "public_file":
        packets[0].packet_path.write_text(SECRET)
    elif fault == "export_receipt":
        bridge.export_receipt_sha256 = digest("foreign")
    elif fault == "foreign_packet_root":
        packets[0] = replace(packets[0], packet_path=tmp_path / "foreign/public.json")
    else:
        bridge.exporter.config["schema"] = "unsupported"
    calls = []
    monkeypatch.setattr(bridge.exporter, "_source_bindings", lambda: calls.append("source"))
    monkeypatch.setattr(bridge, "_reference_reader", lambda *args: calls.append("reference"))
    with pytest.raises(CustodyError) as caught:
        bridge.prepare(requests, packets)
    assert not calls and not bridge.store_root.exists()
    assert [row["event"] for row in journal(bridge)] == ["attempt_reserved", "failed"]
    assert SECRET not in str(caught.value) + json.dumps(journal(bridge))


@pytest.mark.parametrize("fault", ["csv", "source_metadata", "annotation", "history"])
def test_source_or_audit_bytes_drift_before_reference_parse(tmp_path, monkeypatch, fault):
    bridge, requests, packets, _ = material(tmp_path)
    root = Path(bridge.exporter.config["snapshot_root"])
    path = {"csv": root / "scienceagent/work/BLADE/blade_bench/datasets/case0/data.csv",
        "source_metadata": root / "scienceagent/work/BLADE/blade_bench/datasets/case0/info.json",
        "annotation": root / "scienceagent/work/BLADE/blade_bench/datasets/case0/annotations.csv",
        "history": Path(bridge.exporter.config["inputs"]["later_ledger"]["path"])}[fault]
    path.write_bytes(path.read_bytes() + b" ")
    reads = []
    monkeypatch.setattr(bridge, "_reference_reader", lambda *args: reads.append(True))
    with pytest.raises(CustodyError): bridge.prepare(requests, packets)
    assert not reads and not bridge.store_root.exists()
    assert not any(row["event"] == "reference_read_reserved" for row in journal(bridge))


def test_answer_key_hash_refused_before_parser_and_read_reservation_preserved(tmp_path, monkeypatch):
    bridge, requests, packets, _ = material(tmp_path)
    key = Path(bridge.discovery_answer_keys.data()["synth"]["path"])
    key.write_text(SECRET)
    with pytest.raises(CustodyError): bridge.prepare(requests, packets)
    rows = journal(bridge)
    assert rows[-1]["event"] == "failed" and rows[-1]["phase"] == "reference_read"
    assert rows[-1]["possibly_read_train_tokens"] == [requests[0].item.token]
    assert not bridge.store_root.exists() and SECRET not in json.dumps(rows)


def test_same_byte_reparse_answer_key_rejected(tmp_path):
    bridge, requests, packets, _ = material(tmp_path)
    key = Path(bridge.discovery_answer_keys.data()["synth"]["path"])
    target = tmp_path / "other-key.csv"
    target.write_bytes(key.read_bytes()); key.unlink()
    try:
        key.symlink_to(target)
    except OSError:
        pytest.skip("host does not grant symlink creation")
    with pytest.raises(CustodyError): bridge.prepare(requests, packets)
    assert not bridge.store_root.exists()


@pytest.mark.parametrize("fault", ["publish_io", "hold_after_read", "key_after_read"])
def test_partial_read_and_publication_failures_keep_hashchain_and_safe_error(tmp_path, monkeypatch, fault):
    bridge, requests, packets, _ = material(tmp_path)
    if fault == "publish_io":
        def fail(*args):
            raise OSError(SECRET)
        monkeypatch.setattr("evaluation.modular.primary_reference_bridge.os.replace", fail)
    else:
        original = bridge._finish_checks
        def changed(*args):
            path = bridge.exporter.eligibility_path if fault == "hold_after_read" else Path(bridge.discovery_answer_keys.data()["synth"]["path"])
            path.write_bytes(path.read_bytes() + b" ")
            original(*args)
        monkeypatch.setattr(bridge, "_finish_checks", changed)
    with pytest.raises(CustodyError) as caught:
        bridge.prepare(requests, packets)
    rows = journal(bridge)
    assert rows[-1]["event"] == "failed" and len(rows[-1]["possibly_read_train_tokens"]) == 2
    assert not bridge.store_root.exists()
    previous = "0" * 64
    for index, row in enumerate(rows, 1):
        core = {key: value for key, value in row.items() if key != "entry_sha256"}
        assert row["entry_sha256"] == digest(core) and row["previous_sha256"] == previous and row["sequence"] == index
        assert row["known_cost_units"] == row["model_calls"] == row["network_calls"] == 0
        previous = row["entry_sha256"]
    assert SECRET not in str(caught.value) + json.dumps(rows)
    if fault == "publish_io":
        assert len(list(bridge.audit_root.glob("attempt-*/staging/*.json"))) == 3


def test_corrupt_journal_cannot_restart_reference_reads(tmp_path, monkeypatch):
    bridge, requests, packets, _ = material(tmp_path)
    bridge.audit_root.mkdir()
    path = bridge.audit_root / "references.jsonl"
    path.write_text(SECRET)
    calls = []
    monkeypatch.setattr(bridge.exporter, "_allocation", lambda *args: calls.append(True))
    with pytest.raises(CustodyError): bridge.prepare(requests, packets)
    assert not calls and path.read_text() == SECRET


@pytest.mark.parametrize("fault", ["task", "selector", "csv"])
def test_repinning_forged_public_material_does_not_replace_source_proof(tmp_path, monkeypatch, fault):
    bridge, requests, packets, _ = material(tmp_path)
    packets = list(packets)
    packet = packets[0]
    metadata = packet.receipt.data()
    if fault == "task":
        packet = replace(packet, task=replace(packet.task, payload=FrozenRecord.from_dict({**packet.task.payload.data(), "question": "Forged"})))
        metadata["packet_hash"] = packet.task.content_hash
    elif fault == "selector":
        metadata["source_selector"]["metadata_file"] = "metadata_other.json"
    else:
        packet.csv_path.write_bytes(b"x\n9999\n")
        metadata["csv_sha256"] = pin(packet.csv_path)["sha256"]
        metadata["csv_byte_count"] = packet.csv_path.stat().st_size
    packet = replace(packet, receipt=FrozenRecord.from_dict(metadata))
    packets[0] = packet
    write(packet.packet_path, {"task": packet.task.data(), "receipt": metadata})
    write(packet.packet_path.parent / "receipt.json", metadata)
    export_path = bridge.exporter.output_root / "export-receipt.json"
    receipt = json.loads(export_path.read_bytes())
    receipt["packets"] = [metadata if row["export_token"] == requests[0].item.token else row for row in receipt["packets"]]
    write(export_path, receipt)
    bridge.export_receipt_sha256 = pin(export_path)["sha256"]
    requests[0] = PrimaryReferenceItem(requests[0].item, packet.task.content_hash, pin(packet.packet_path)["sha256"],
        pin(packet.csv_path)["sha256"], pin(packet.packet_path.parent / "receipt.json")["sha256"])
    reads = []
    monkeypatch.setattr(bridge, "_reference_reader", lambda *args: reads.append(True))
    with pytest.raises(CustodyError): bridge.prepare(requests, packets)
    assert not reads and not bridge.store_root.exists()
    assert journal(bridge)[-1]["phase"] == "source_verification"


def test_staged_reference_drift_cannot_publish(tmp_path, monkeypatch):
    import evaluation.modular.primary_reference_bridge as module
    bridge, requests, packets, _ = material(tmp_path)
    original = module.publish_train_reference_records
    def drift(destination, *args, **kwargs):
        publication = original(destination, *args, **kwargs)
        handle = next(iter(publication.data()["task_handles"].values()))
        (destination / (handle + ".json")).write_text(SECRET)
        return publication
    monkeypatch.setattr(module, "publish_train_reference_records", drift)
    with pytest.raises(CustodyError): bridge.prepare(requests, packets)
    assert not bridge.store_root.exists() and journal(bridge)[-1]["event"] == "failed"


def test_actual_scorer_subprocess_uses_bridge_store_for_both_benchmarks(tmp_path):
    import sys
    from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
    from research_loop.modular.panel_plan import compile_train_panel, obligation_grids, executable_arms
    from evaluation.modular.scoring_service import ScorerConfig, FrozenBenchmarkRubricEndpoint
    from evaluation.modular.scorer_process import LinkedScorerProcessClient, serialize_frozen_panel
    from evaluation.modular.linked_scoring import LinkedExecutionAuthority, verify_linked_adapted_receipt
    bridge, requests, packets, _ = material(tmp_path)
    publication = bridge.prepare(requests, packets).data()
    tasks = [packet.task for packet in packets]
    package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze(task.identity for task in tasks),
        changes={"prompt": {"instructions": "synthetic bridge fixture"}}, search_cost=0)
    control = FrozenRecord.from_dict({"synthetic": True})
    grid = obligation_grids(("Q3.1",), baseline_digest="b" * 64, p0_control=control)
    config = ScorerConfig.create(benchmark="core_pair", evaluator_id="synthetic-bridge-verifier", version="v1",
        rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest())
    panel = compile_train_panel(stage="synthetic-reference-bridge", scope_ids=("Q3.1",), tasks=tasks,
        evidence_by_task={task.content_hash: control for task in tasks}, budget=control, baseline_digest="b" * 64,
        p0_control=control, packages_by_arm={arm.content_hash: package for arm in executable_arms(grid["Q3.1"]).values()},
        scorer=config.record, acceptance_criteria=FrozenRecord.from_dict({"scientific_validity": "not_measured"})).panel
    executor = LinkedExecutionAuthority("fixture-executor", b"e" * 32)
    scorer = LinkedExecutionAuthority("fixture-scorer", b"s" * 32)
    (tmp_path / "executor.key").write_bytes(executor.key)
    (tmp_path / "scorer.key").write_bytes(scorer.key)
    server = {"schema": "linked-scorer-process-config-v1", "panel": serialize_frozen_panel(panel),
        "scorer_config": config.record.data(), "scorer_config_digest": config.digest,
        "train_reference_store": {"root": str(bridge.store_root), "manifest_sha256": publication["manifest_sha256"],
            "inventory_digest": publication["inventory_digest"], "split_digest": publication["split_digest"]},
        "task_handles": publication["task_handles"], "execution_authority_key_files": {executor.authority_id: str(tmp_path / "executor.key")},
        "scorer_authority": {"id": scorer.authority_id, "key_file": str(tmp_path / "scorer.key")}, "evaluator": {}}
    server_path = tmp_path / "worker-config.json"
    write(server_path, server)
    helper = Path(__file__).parent / "helpers/primary_reference_scorer_helper.py"
    worker_journal = tmp_path / "worker.jsonl"
    client = LinkedScorerProcessClient(panel=panel, command=[sys.executable, str(helper.resolve()),
        "--config", str(server_path), "--config-sha256", pin(server_path)["sha256"], "--journal", str(worker_journal)],
        journal_path=tmp_path / "client.jsonl")
    receipts = []
    try:
        for benchmark in qualification.SOURCES:
            cell = next(cell for cell in panel.cells if cell.identity.benchmark == benchmark)
            candidate = {"analysis": "Synthetic fixture candidate", "program": "print(1)", "answer": "fixture answer",
                "execution_feedback": {"status": "succeeded", "exit_code": 0, "stdout": "1", "stderr": ""}}
            # Explicit fixture authority, not a claim that a real solver ran.
            body = {"schema": "linked-benchmark-score-input-v1", "panel_digest": panel.digest, "cell_key": list(cell.key),
                "identity": cell.identity.data(), "panel_cell_digest": digest({"cell_key": list(cell.key),
                    "scenario_digest": cell.scenario_digest, "package_digest": cell.package_digest, "arm": cell.runtime_arm.data()}),
                "task_digest": cell.task_digest, "scenario_digest": cell.scenario_digest, "package_digest": cell.package_digest,
                "arm_digest": cell.runtime_arm.content_hash, "candidate": candidate, "candidate_digest": digest(candidate),
                "status": "linked_execution_succeeded", "scientific_validity": "not_measured"}
            for field in ("objective_digest", "mechanism_trace_digest", "mechanism_output_digest", "solver_trace_digest",
                          "linked_receipt_digest", "analysis_digest", "answer_digest", "execution_digest", "executed_program_sha256"):
                body[field] = digest("synthetic-fixture-" + field)
            linked = executor.issue(body)
            receipt = client.submit(cell_key=cell.key, linked_input=linked)
            verify_linked_adapted_receipt(receipt, authority_keys={scorer.authority_id: scorer.key}, config=config,
                panel=panel, cell=cell, linked_input=linked, execution_authority_keys={executor.authority_id: executor.key})
            receipts.append(receipt)
    finally:
        client.close()
    rows = [json.loads(line) for line in worker_journal.read_bytes().splitlines()]
    assert [row["status"] for row in rows] == ["reserved", "succeeded", "reserved", "succeeded"]
    assert len(receipts) == 2
    for path in (worker_journal, tmp_path / "client.jsonl", bridge.audit_root / "references.jsonl"):
        text = path.read_text(encoding="utf-8")
        assert "BRIDGE-REFERENCE" not in text and "UNALLOCATED-REFERENCE-SENTINEL" not in text
    write(tmp_path / "fixture-call-counts.json", {"schema": "primary-reference-fixture-counts-v1",
        "scorer_processes": 1, "scorer_requests": 2, "fixture_evaluator_calls": 2, "failed_calls": 0,
        "model_calls": 0, "network_calls": 0, "docker_calls": 0, "scientific_validity": "not_measured"})
