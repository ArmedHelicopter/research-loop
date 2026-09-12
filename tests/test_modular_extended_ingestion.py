from __future__ import annotations

import json
import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from evaluation.modular.custody import CustodyStore, InventoryItem
from evaluation.modular.extended_ingestion import ExtendedInventoryImporter, ExtendedTrainProjectionExporter
from research_loop.modular.source_ingestion import SOURCE_SNAPSHOTS
from research_loop.ontology import ContractError, canonical


def _receipt(root: Path, source: str) -> Path:
    spec = SOURCE_SNAPSHOTS[source]
    snapshot = root / "snapshots" / source / spec.revision
    snapshot.mkdir(parents=True)
    return snapshot


def _finalize_receipt(snapshot: Path, source: str) -> None:
    spec = SOURCE_SNAPSHOTS[source]
    artifacts = []
    for artifact in spec.artifacts:
        content = (snapshot / artifact.source_path).read_bytes()
        assert len(content) == artifact.size_bytes
        artifacts.append({"source_path": artifact.source_path, "size_bytes": len(content),
                          "git_blob_sha1": artifact.git_blob_sha1, "lfs_sha256": artifact.lfs_sha256,
                          "local_sha256": hashlib.sha256(content).hexdigest()})
    value = {"schema": "pinned-source-snapshot-receipt-v1", "source": source, "repository": spec.repository,
        "revision": spec.revision, "artifacts": artifacts, "payload_returned": False,
        "access_isolation": "not_verified", "split_qualified": False, "task_projection_created": False}
    (snapshot / "snapshot-receipt.json").write_text(canonical(value), encoding="utf-8")


def _sources(tmp_path: Path) -> Path:
    root = tmp_path / "private-synthetic"
    sci = _receipt(root, "scicode")
    # The markers emulate evaluator-only fields.  Tests never use real source data.
    sci_record = {"problem_id": "synthetic-main", "required_dependencies": "numpy", "sub_steps": [{
        "step_description_prompt": "Compute a synthetic public statistic.", "function_header": "def calculate(x):",
        "return_line": "return x", "step_background": "synthetic context", "test_cases": "PRIVATE_TEST_MARKER",
        "ground_truth_code": "PRIVATE_GOLD_MARKER"}]}
    def jsonl_bytes(record: dict[str, object], size: int) -> bytes:
        record = dict(record)
        record["controller_padding"] = ""
        initial = (json.dumps(record, separators=(",", ":")) + "\n").encode()
        record["controller_padding"] = "x" * (size - len(initial))
        result = (json.dumps(record, separators=(",", ":")) + "\n").encode()
        assert len(result) == size
        return result
    (sci / "problems_dev.jsonl").write_bytes(jsonl_bytes(sci_record, SOURCE_SNAPSHOTS["scicode"].artifacts[0].size_bytes))
    test_record = {**sci_record, "problem_id": "synthetic-test-main"}
    (sci / "problems_test.jsonl").write_bytes(jsonl_bytes(test_record, SOURCE_SNAPSHOTS["scicode"].artifacts[1].size_bytes))
    _finalize_receipt(sci, "scicode")
    sab = _receipt(root, "scienceagentbench")
    sab_csv = (
        "task_inst,dataset_folder_tree,dataset_preview,output_fname,domain_knowledge,gold_program_name,eval_script_name\n"
        "Use public synthetic data,|-- shared-artifact/public.csv,feature\\n1,result.csv,synthetic context,PRIVATE_GOLD_MARKER,PRIVATE_EVAL_MARKER\n").encode()
    sab_csv += b"\n" * (SOURCE_SNAPSHOTS["scienceagentbench"].artifacts[0].size_bytes - len(sab_csv))
    (sab / "ScienceAgentBench.csv").write_bytes(sab_csv)
    # The LFS parquet is not parsed by the metadata importer, but it is part of
    # the pinned acquisition receipt and must be present for receipt validation.
    data = sab / "data"
    data.mkdir()
    (data / "verified-00000-of-00001.parquet").write_bytes(b"x" * SOURCE_SNAPSHOTS["scienceagentbench"].artifacts[1].size_bytes)
    _finalize_receipt(sab, "scienceagentbench")
    return root


def test_importer_uses_real_custody_schema_and_keeps_unknown_sources_quarantined(tmp_path: Path) -> None:
    root = _sources(tmp_path)
    custody = CustodyStore(tmp_path / "custody.json")
    imported = ExtendedInventoryImporter(root).import_into(custody)
    assert imported.receipt.data()["qualification"] == "quarantine_until_review"
    assert imported.receipt.data()["payload_returned"] is False
    assert {row["benchmark"] for row in custody.state["inventory"]} == {"scicode", "scienceagentbench"}
    sci = next(row for row in custody.state["inventory"] if row["benchmark"] == "scicode")
    assert sci["task_id"] == "synthetic-main"
    assert sci["source_group"].startswith("scicode-main-")
    sab = next(row for row in custody.state["inventory"] if row["benchmark"] == "scienceagentbench")
    assert sab["source_group"].startswith("scienceagentbench-root-")
    split = custody.split(seed="synthetic-freeze")
    assert {row["domain"] for row in split["rows"]} == {"quarantine"}
    serialized = canonical({"receipt": imported.receipt.data(), "state": custody.state})
    assert "PRIVATE_GOLD_MARKER" not in serialized and "PRIVATE_TEST_MARKER" not in serialized


def test_projection_requires_exact_train_allowlist_and_drops_private_fields(tmp_path: Path) -> None:
    root = _sources(tmp_path)
    importer = ExtendedInventoryImporter(root)
    source_custody = CustodyStore(tmp_path / "source-custody.json")
    importer.import_into(source_custody)
    # This simulates pre-existing external exposure evidence in a separate test
    # fixture.  The importer itself always writes unknown and never attests.
    eligible = [replace(InventoryItem.parse(row), exposure="exposed") for row in source_custody.state["inventory"]]
    custody = CustodyStore(tmp_path / "train-custody.json")
    custody.inventory(eligible)
    custody.split(seed="frozen-synthetic")
    allowlist = [f"{row['benchmark']}:{row['task_id']}" for row in custody.state["inventory"]]
    tasks = ExtendedTrainProjectionExporter(custody, root, tmp_path / "public").export(allowlist)
    assert {task.identity.domain for task in tasks} == {"train"}
    serialized = "\n".join(path.read_text(encoding="utf-8") for path in (tmp_path / "public").glob("**/*.json"))
    assert "PRIVATE_GOLD_MARKER" not in serialized
    assert "PRIVATE_TEST_MARKER" not in serialized
    assert "PRIVATE_EVAL_MARKER" not in serialized
    with pytest.raises(ContractError):
        ExtendedTrainProjectionExporter(custody, root, tmp_path / "other-public").export(["scicode:not-a-task"])


def test_importer_fails_closed_on_receipt_or_source_path_drift(tmp_path: Path) -> None:
    root = _sources(tmp_path)
    receipt = root / "snapshots" / "scicode" / SOURCE_SNAPSHOTS["scicode"].revision / "snapshot-receipt.json"
    value = json.loads(receipt.read_text(encoding="utf-8"))
    value["split_qualified"] = True
    receipt.write_text(canonical(value), encoding="utf-8")
    with pytest.raises(ContractError):
        ExtendedInventoryImporter(root).import_into(CustodyStore(tmp_path / "custody.json"), ("scicode",))
