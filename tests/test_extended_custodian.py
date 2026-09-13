from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import MappingProxyType

import pytest

import evaluation.modular.extended_custodian as custodian
import evaluation.modular.extended_ingestion as ingestion
from evaluation.modular.extended_custodian import extract_extended_custody_metadata
from research_loop.modular.source_ingestion import ArtifactSpec, SourceSnapshot
from research_loop.ontology import ContractError, canonical


def _git_blob(content: bytes) -> str:
    return hashlib.sha1(f"blob {len(content)}\0".encode("ascii") + content).hexdigest()


@pytest.fixture
def private_snapshots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    scicode = (json.dumps({"problem_id": "one", "sub_steps": [{"prompt": "PRIVATE_PROMPT_MARKER"}],
                           "private_solution": "PRIVATE_SOLUTION_MARKER"}) + "\n" +
               json.dumps({"problem_id": "two", "sub_steps": [{"prompt": "PRIVATE_PROMPT_MARKER"}]}) + "\n").encode()
    scicode_test = (json.dumps({"problem_id": "three", "sub_steps": [{"prompt": "PRIVATE_PROMPT_MARKER"}]}) + "\n").encode()
    sab = ("task_inst,dataset_folder_tree,github_name,src_file_or_path,private_gold\n"
           "public,shared/data.csv,same-repo,first.py,PRIVATE_GOLD_MARKER\n"
           "public-2,other/data.csv,same-repo,second.py,PRIVATE_GOLD_MARKER\n").encode()
    snapshots = MappingProxyType({
        "scicode": SourceSnapshot("scicode", "fixture/SciCode", "a" * 40,
                                  (ArtifactSpec("problems_dev.jsonl", len(scicode), git_blob_sha1=_git_blob(scicode)),
                                   ArtifactSpec("problems_test.jsonl", len(scicode_test), git_blob_sha1=_git_blob(scicode_test)))),
        "scienceagentbench": SourceSnapshot("scienceagentbench", "fixture/ScienceAgentBench", "b" * 40,
                                             (ArtifactSpec("ScienceAgentBench.csv", len(sab), git_blob_sha1=_git_blob(sab)),)),
    })
    monkeypatch.setattr(custodian, "SOURCE_SNAPSHOTS", snapshots)
    monkeypatch.setattr(ingestion, "SOURCE_SNAPSHOTS", snapshots)
    root = tmp_path / "private"
    payloads = {"scicode": {"problems_dev.jsonl": scicode, "problems_test.jsonl": scicode_test},
                "scienceagentbench": {"ScienceAgentBench.csv": sab}}
    for source, spec in snapshots.items():
        snapshot = root / "snapshots" / source / spec.revision
        snapshot.mkdir(parents=True)
        artifacts = []
        for artifact in spec.artifacts:
            content = payloads[source][artifact.source_path]
            target = snapshot / artifact.source_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            artifacts.append({"source_path": artifact.source_path, "size_bytes": len(content),
                              "git_blob_sha1": artifact.git_blob_sha1,
                              "git_blob_sha1_kind": "Git blob SHA-1 verified against downloaded payload",
                              "lfs_sha256": None, "local_sha256": hashlib.sha256(content).hexdigest(),
                              "local_hash_kind": "SHA-256 of private downloaded bytes"})
        (snapshot / "snapshot-receipt.json").write_text(canonical({
            "schema": "pinned-source-snapshot-receipt-v1", "source": source, "repository": spec.repository,
            "revision": spec.revision, "artifacts": artifacts, "payload_returned": False,
            "access_isolation": "not_verified", "split_qualified": False, "task_projection_created": False}), encoding="utf-8")
    return root, snapshots


def _live(snapshots):
    return {"schema": "extended-source-inventory-metadata-v1", "inventory_digest": "a" * 64,
            "custody_state_sha256": "b" * 64,
            "source_pins": {name: spec.revision for name, spec in snapshots.items()},
            "split_assigned": False, "exposure_counts": {"unknown": 182}}


def test_restricted_extractor_returns_only_opaque_family_metadata(private_snapshots) -> None:
    root, snapshots = private_snapshots
    receipt = extract_extended_custody_metadata(private_store=root, live_metadata=_live(snapshots))
    encoded = canonical(receipt)
    assert receipt["raw_private_payload_returned"] is False
    assert receipt["optimizer_access"] == "none"
    assert receipt["mutated_private_store"] is False and receipt["mutated_custody_state"] is False
    assert {row["source"]: row["record_count"] for row in receipt["sources"]} == {"scicode": 3, "scienceagentbench": 2}
    assert all(sum(component["member_count"] for component in row["components"]) == row["record_count"]
               for row in receipt["sources"])
    assert {row["source"]: len(row["components"]) for row in receipt["sources"]} == {"scicode": 2, "scienceagentbench": 1}
    assert "PRIVATE_PROMPT_MARKER" not in encoded
    assert "PRIVATE_SOLUTION_MARKER" not in encoded
    assert "PRIVATE_GOLD_MARKER" not in encoded
    assert "shared/data.csv" not in encoded


def test_extractor_refuses_snapshot_pin_or_inventory_state_drift(private_snapshots) -> None:
    root, snapshots = private_snapshots
    live = _live(snapshots)
    live["source_pins"] = {**live["source_pins"], "scicode": "c" * 40}
    with pytest.raises(ContractError, match="does not bind"):
        extract_extended_custody_metadata(private_store=root, live_metadata=live)
    live = _live(snapshots)
    live["split_assigned"] = True
    with pytest.raises(ContractError, match="unchanged unsplit"):
        extract_extended_custody_metadata(private_store=root, live_metadata=live)
