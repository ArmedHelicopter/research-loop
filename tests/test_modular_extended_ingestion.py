from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

import evaluation.modular.extended_ingestion as ingestion
from evaluation.modular.custody import CustodyStore, InventoryItem
from evaluation.modular.extended_ingestion import ExtendedInventoryImporter, ExtendedTrainProjectionExporter
from research_loop.modular.source_ingestion import ArtifactSpec, SourceSnapshot
from research_loop.ontology import ContractError, canonical


def _git_blob_sha1(content: bytes) -> str:
    return hashlib.sha1(f"blob {len(content)}\0".encode("ascii") + content).hexdigest()


@pytest.fixture
def synthetic_snapshots(monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, SourceSnapshot], dict[str, dict[str, bytes]]]:
    scicode_dev = (json.dumps({"problem_id": "synthetic-main", "required_dependencies": "numpy", "sub_steps": [{
        "step_description_prompt": "Compute a synthetic public statistic.", "function_header": "def calculate(x):",
        "return_line": "return x", "step_background": "synthetic context", "test_cases": "PRIVATE_TEST_MARKER",
        "ground_truth_code": "PRIVATE_GOLD_MARKER"}]}) + "\n").encode()
    scicode_test = (json.dumps({"problem_id": "synthetic-test-main", "required_dependencies": "numpy", "sub_steps": [{
        "step_description_prompt": "Compute a second synthetic statistic.", "function_header": "def calculate(y):",
        "return_line": "return y", "step_background": "synthetic context", "test_cases": "PRIVATE_TEST_MARKER",
        "ground_truth_code": "PRIVATE_GOLD_MARKER"}]}) + "\n").encode()
    sab_csv = ("task_inst,dataset_folder_tree,dataset_preview,output_fname,domain_knowledge,gold_program_name,eval_script_name\n"
        "Use public synthetic data,|-- shared-artifact/public.csv,feature\\n1,result.csv,synthetic context,PRIVATE_GOLD_MARKER,PRIVATE_EVAL_MARKER\n").encode()
    sab_lfs = b"synthetic-lfs-container"
    data = {"scicode": {"problems_dev.jsonl": scicode_dev, "problems_test.jsonl": scicode_test},
            "scienceagentbench": {"ScienceAgentBench.csv": sab_csv, "data/verified-00000-of-00001.parquet": sab_lfs}}
    snapshots = {
        "scicode": SourceSnapshot("scicode", "synthetic/SciCode", "a" * 40, (
            ArtifactSpec("problems_dev.jsonl", len(scodecidev := scicode_dev), git_blob_sha1=_git_blob_sha1(scodecidev)),
            ArtifactSpec("problems_test.jsonl", len(scicode_test), git_blob_sha1=_git_blob_sha1(scicode_test)),
        )),
        "scienceagentbench": SourceSnapshot("scienceagentbench", "synthetic/ScienceAgentBench", "b" * 40, (
            ArtifactSpec("ScienceAgentBench.csv", len(sab_csv), git_blob_sha1=_git_blob_sha1(sab_csv)),
            ArtifactSpec("data/verified-00000-of-00001.parquet", len(sab_lfs), git_blob_sha1=_git_blob_sha1(b"synthetic-lfs-pointer"), lfs_sha256=hashlib.sha256(sab_lfs).hexdigest()),
        )),
    }
    monkeypatch.setattr(ingestion, "SOURCE_SNAPSHOTS", MappingProxyType(snapshots))
    return snapshots, data


def _sources(tmp_path: Path, snapshots: dict[str, SourceSnapshot], source_data: dict[str, dict[str, bytes]]) -> Path:
    root = tmp_path / "private-synthetic"
    for source, spec in snapshots.items():
        snapshot = root / "snapshots" / source / spec.revision
        snapshot.mkdir(parents=True)
        artifacts = []
        for artifact in spec.artifacts:
            content = source_data[source][artifact.source_path]
            target = snapshot.joinpath(*artifact.source_path.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            artifacts.append({"source_path": artifact.source_path, "size_bytes": len(content),
                "git_blob_sha1": artifact.git_blob_sha1,
                "git_blob_sha1_kind": ("Git LFS pointer blob SHA-1 metadata; not verified against downloaded payload" if artifact.lfs_sha256 else "Git blob SHA-1 verified against downloaded payload"),
                "lfs_sha256": artifact.lfs_sha256, "local_sha256": hashlib.sha256(content).hexdigest()})
        receipt = {"schema": "pinned-source-snapshot-receipt-v1", "source": source, "repository": spec.repository,
            "revision": spec.revision, "artifacts": artifacts, "payload_returned": False,
            "access_isolation": "not_verified", "split_qualified": False, "task_projection_created": False}
        (snapshot / "snapshot-receipt.json").write_text(canonical(receipt), encoding="utf-8")
    return root


def test_importer_uses_real_custody_schema_and_keeps_unknown_sources_quarantined(tmp_path: Path, synthetic_snapshots) -> None:
    snapshots, source_data = synthetic_snapshots
    root = _sources(tmp_path, snapshots, source_data)
    custody = CustodyStore(tmp_path / "custody.json")
    imported = ExtendedInventoryImporter(root).import_into(custody)
    assert imported.receipt.data()["qualification"] == "quarantine_until_review"
    assert imported.receipt.data()["raw_private_payload_returned"] is False
    assert imported.receipt.data()["parent_inventory_digest"] is None
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


def test_projection_requires_exact_train_allowlist_and_drops_private_fields(tmp_path: Path, synthetic_snapshots) -> None:
    snapshots, source_data = synthetic_snapshots
    root = _sources(tmp_path, snapshots, source_data)
    source_custody = CustodyStore(tmp_path / "source-custody.json")
    ExtendedInventoryImporter(root).import_into(source_custody)
    # Test-only stand-in for separately established exposure evidence; importer never sets it.
    eligible = [replace(InventoryItem.parse(row), exposure="exposed") for row in source_custody.state["inventory"]]
    custody = CustodyStore(tmp_path / "train-custody.json")
    custody.inventory(eligible)
    custody.split(seed="frozen-synthetic")
    allowlist = [f"{row['benchmark']}:{row['task_id']}" for row in custody.state["inventory"]]
    tasks = ExtendedTrainProjectionExporter(custody, root, tmp_path / "public").export(allowlist)
    assert {task.identity.domain for task in tasks} == {"train"}
    serialized = "\n".join(path.read_text(encoding="utf-8") for path in (tmp_path / "public").glob("**/*.json"))
    assert "PRIVATE_GOLD_MARKER" not in serialized and "PRIVATE_TEST_MARKER" not in serialized and "PRIVATE_EVAL_MARKER" not in serialized
    assert '"public_projection_written":true' in serialized
    assert '"public_projection_returned":true' in serialized
    assert '"raw_private_payload_returned":false' in serialized
    with pytest.raises(ContractError):
        ExtendedTrainProjectionExporter(custody, root, tmp_path / "other-public").export(["scicode:not-a-task"])


def test_real_pin_cannot_be_mimicked_by_synthetic_bytes(tmp_path: Path, synthetic_snapshots) -> None:
    snapshots, source_data = synthetic_snapshots
    root = _sources(tmp_path, snapshots, source_data)
    # Present synthetic bytes under the real source/revision and metadata.  A
    # receipt with matching local hashes still cannot substitute for the fixed
    # Git blob metadata.
    from research_loop.modular.source_ingestion import SOURCE_SNAPSHOTS as production
    real = production["scicode"]
    snapshot = root / "snapshots" / "scicode" / real.revision
    snapshot.mkdir(parents=True)
    artifacts = []
    for artifact in real.artifacts:
        content = b"synthetic-not-real-pin" * (artifact.size_bytes // len(b"synthetic-not-real-pin"))
        content += b"x" * (artifact.size_bytes - len(content))
        (snapshot / artifact.source_path).write_bytes(content)
        artifacts.append({"source_path": artifact.source_path, "size_bytes": artifact.size_bytes,
            "git_blob_sha1": artifact.git_blob_sha1,
            "git_blob_sha1_kind": "Git blob SHA-1 verified against downloaded payload",
            "lfs_sha256": None, "local_sha256": hashlib.sha256(content).hexdigest()})
    (snapshot / "snapshot-receipt.json").write_text(canonical({"schema": "pinned-source-snapshot-receipt-v1",
        "source": "scicode", "repository": real.repository, "revision": real.revision, "artifacts": artifacts,
        "payload_returned": False, "access_isolation": "not_verified", "split_qualified": False,
        "task_projection_created": False}), encoding="utf-8")
    ingestion.SOURCE_SNAPSHOTS = production
    with pytest.raises(ContractError, match="fixed metadata"):
        ExtendedInventoryImporter(root).import_into(CustodyStore(tmp_path / "custody.json"), ("scicode",))


def test_import_refuses_existing_inventory_and_receipt_schema_drift(tmp_path: Path, synthetic_snapshots) -> None:
    snapshots, source_data = synthetic_snapshots
    root = _sources(tmp_path, snapshots, source_data)
    custody = CustodyStore(tmp_path / "custody.json")
    custody.inventory([InventoryItem("scicode", "old", "old-group", "old", "old", ("0" * 64,), "unknown")])
    with pytest.raises(ContractError, match="new empty custody"):
        ExtendedInventoryImporter(root).import_into(custody, ("scicode",))
    receipt = root / "snapshots" / "scicode" / snapshots["scicode"].revision / "snapshot-receipt.json"
    value = json.loads(receipt.read_text(encoding="utf-8"))
    value["artifacts"].append(value["artifacts"][0])
    receipt.write_text(canonical(value), encoding="utf-8")
    with pytest.raises(ContractError):
        ExtendedInventoryImporter(root).import_into(CustodyStore(tmp_path / "fresh.json"), ("scicode",))


def test_artifact_paths_fail_closed_when_a_reparse_segment_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "snapshot"
    source.mkdir()
    (source / "artifact.jsonl").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(ingestion, "_reparse", lambda path: path.name == "artifact.jsonl")
    with pytest.raises(ContractError, match="symlink or reparse"):
        ingestion._inside(source, "artifact.jsonl")
