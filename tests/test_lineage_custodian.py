import csv
import hashlib
import io
import json
from pathlib import Path

import pytest

from evaluation.modular import extended_ingestion, lineage_custodian as c
from evaluation.modular import fresh_airs_hf_custodian as hf
from research_loop.modular.source_ingestion import ArtifactSpec, SourceSnapshot
from research_loop.ontology import digest

SECRET = "PRIVATE_DYNAMIC_TASK_GOLD_CODE"


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
    return hashlib.sha256(path.read_bytes()).hexdigest()


def csv_bytes(rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


def blob(data):
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    root = tmp_path / "snapshot"
    discovery = root / "discovery/upstream/discoverybench/synth/train/case_1"
    blade = root / "scienceagent/work/BLADE/blade_bench/datasets/case"
    data = b"a,b\n1,2\n"
    d_meta = write(discovery / "metadata_case.json", {
        "source_url": "https://doi.org/10.1234/SHARED", "datasets": [{"name": "data.csv"}],
        "queries": [{"question": SECRET, "answer": SECRET, "source_url": "https://doi.org/10.1234/not-allowed"}],
        SECRET: {"doi": "10.1234/not-allowed-either"}})
    d_data = write(discovery / "data.csv", data)
    b_meta = write(blade / "info.json", {"source_url": "10.1234/shared", "description": SECRET})
    b_data = write(blade / "data.csv", data)
    provider = discovery / "provider-prompt.txt"
    write(provider, SECRET.encode())
    inventory = [
        {"benchmark": "discoverybench", "task_id": "synth:train:case_1", "source_group": "discoverybench:synth:case", "official_split": "synth/train", "relative_path": "synth/train/case_1", "content_hashes": [d_meta, d_data], "exposure": "unknown"},
        {"benchmark": "blade", "task_id": "case", "source_group": "blade:case", "official_split": "unsplit", "relative_path": "case", "content_hashes": [b_meta, b_data], "exposure": "unknown"},
    ]
    state = tmp_path / "custody.json"
    write(state, {"schema": c.CUSTODY_SCHEMA, "inventory": inventory, "inventory_digest": digest(inventory), "attestations": {}, "split": {"private_marker": SECRET}, "leases": {}})
    extended_root = tmp_path / "extended"
    payloads = {
        "scicode": {"problems_dev.jsonl": json.dumps({"metadata": {"doi": "10.1234/shared"}, "ground_truth_code": SECRET, "sub_steps": [{"background": SECRET}]}).encode() + b"\n",
                    "problems_test.jsonl": json.dumps({"metadata": {"hf_dataset": "owner/corpus"}, "ground_truth_code": SECRET}).encode() + b"\n"},
        "scienceagentbench": {"ScienceAgentBench.csv": csv_bytes([{"github_name": "owner/repo", "citation": "10.1234/shared", "gold_program_name": SECRET}]), "data/verified-00000-of-00001.parquet": SECRET.encode()},
    }
    specs, public_sources = {}, []
    for index, (source, files) in enumerate(payloads.items()):
        pin = str(index + 1) * 40
        artifacts = tuple(ArtifactSpec(name, len(data), git_blob_sha1=blob(data)) for name, data in files.items())
        specs[source] = SourceSnapshot(source, "fixture/" + source, pin, artifacts)
        snap = extended_root / "snapshots" / source / pin
        received = []
        for name, data in files.items():
            sha = write(snap / name, data)
            received.append({"source_path": name, "size_bytes": len(data), "git_blob_sha1": blob(data),
                             "git_blob_sha1_kind": "Git blob SHA-1 verified against downloaded payload", "lfs_sha256": None,
                             "local_sha256": sha, "local_hash_kind": "SHA-256 of private downloaded bytes"})
        write(snap / "snapshot-receipt.json", {"schema": "pinned-source-snapshot-receipt-v1", "source": source,
              "repository": specs[source].repository, "revision": pin, "artifacts": received,
              "payload_returned": False, "access_isolation": "not_verified", "split_qualified": False, "task_projection_created": False})
        public_sources.append({"source": source, "revision": pin, "record_count": 2 if source == "scicode" else 1})
    monkeypatch.setattr(c, "SOURCE_SNAPSHOTS", specs)
    monkeypatch.setattr(extended_ingestion, "SOURCE_SNAPSHOTS", specs)
    monkeypatch.setattr(c, "_git_pin", lambda root: None)
    extended_public = tmp_path / "extended-public.json"
    extended_live = tmp_path / "extended-live.json"
    write(extended_public, {"schema": "extended-custodian-metadata-receipt-v1", "live_inventory_binding": {"inventory_digest": "a" * 64}, "sources": public_sources})
    write(extended_live, {"schema": "extended-source-inventory-metadata-v1", "inventory_digest": "a" * 64, "source_pins": {source: spec.revision for source, spec in specs.items()}})
    license_metadata = tmp_path / "license.json"
    write(license_metadata, {"schema": "received-dataset-public-metadata-v1", "sources": {source: {"received_snapshot_revision": spec.revision, "dataset_card_license_declaration": "fixture-terms"} for source, spec in specs.items()}})

    class HfTransport:
        def iter_bytes(self, url):
            content = csv_bytes([{"metadata.yaml": "dataset:\n  hf_dataset: owner/corpus\n", "gold": SECRET, SECRET: SECRET}])
            if url == hf.API_URL:
                yield json.dumps({"id": hf.REPO, "sha": "c" * 40, "cardData": {"license": "cc-by-nc-4.0"},
                                  "siblings": [{"rfilename": "data.csv", "size": len(content), "blobId": blob(content)}]}).encode()
            else:
                yield content
    baseline = tmp_path / "baseline.json"
    write(baseline, {"schema": "opaque-overlap-baseline-v1", "family_fingerprints": [], "artifact_fingerprints": [], "publication_fingerprints": []})
    airs_private, airs_public = tmp_path / "airs-private", tmp_path / "airs-public" / "receipt.json"
    hf.acquire(private_store=airs_private, output=airs_public, overlap_baseline=baseline, transport=HfTransport())
    config = {"schema": "canonical-lineage-input-locations-v1", "snapshot_root": str(root), "custody_state": str(state),
              "extended_private_root": str(extended_root), "extended_public_receipt": str(extended_public),
              "extended_live_metadata": str(extended_live), "airs_private_root": str(airs_private),
              "airs_public_receipt": str(airs_public), "source_license_metadata": str(license_metadata)}
    config_path = tmp_path / "config.json"
    write(config_path, config)
    return config_path, state, provider


def test_complete_file_entrypoint_keeps_all_payloads_private_and_old_split_unchanged(tmp_path, fixture, capsys, monkeypatch):
    config, state, provider = fixture
    before = state.read_bytes()
    original = Path.open
    def guarded(self, *args, **kwargs):
        if self == provider:
            raise AssertionError("provider prompt read forbidden")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, "open", guarded)
    out = tmp_path / "public" / "receipt.json"
    assert c.main(["--config", str(config), "--private-audit", str(tmp_path / "audit-private"), "--output", str(out)]) == 0
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err + out.read_text()
    receipt = c.validate_receipt(json.loads(out.read_bytes()))
    assert receipt["graph"]["total_records"] == 6
    assert receipt["graph"]["group_count"] == 2
    assert receipt["graph"]["shared_references"]["doi"][0]["source_counts"]["scienceagentbench"] == 1
    assert receipt["graph"]["shared_references"]["hf_dataset"][0]["source_counts"]["airsbench"] == 1
    assert receipt["graph"]["sources"]["scicode"]["canonical_reference_record_counts"]["data_artifact_sha256"] == 0
    assert receipt["read_files_unchanged"] is True
    assert state.read_bytes() == before


def test_frozen_data_hash_mismatch_returns_only_safe_error_stage(tmp_path, fixture, capsys):
    config, state, provider = fixture
    (provider.parent / "data.csv").write_text(SECRET)
    out = tmp_path / "public" / "receipt.json"
    assert c.main(["--config", str(config), "--private-audit", str(tmp_path / "audit-private"), "--output", str(out)]) == 1
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err
    failure = json.loads(out.with_suffix(".failure.json").read_bytes())
    assert failure["stage"] == "primary"
    assert SECRET not in json.dumps(failure)
    assert not out.exists()


def test_untrusted_yaml_exception_does_not_export_private_text(tmp_path, fixture, capsys):
    config_path, _, _ = fixture
    config = json.loads(config_path.read_bytes())
    # Exercise an actual loader parse exception after a correctly bound receipt.
    state_path = Path(config["custody_state"])
    state = json.loads(state_path.read_bytes())
    metadata = Path(config["snapshot_root"]) / "discovery/upstream/discoverybench/synth/train/case_1/metadata_case.json"
    old = hashlib.sha256(metadata.read_bytes()).hexdigest()
    sha = write(metadata, {"metadata": "!!python/object/apply:os.system ['" + SECRET + "']", "datasets": [{"name": "data.csv"}]})
    state["inventory"][0]["content_hashes"] = [sha if value == old else value for value in state["inventory"][0]["content_hashes"]]
    state["inventory_digest"] = digest(state["inventory"])
    write(state_path, state)
    out = tmp_path / "public" / "receipt.json"
    assert c.main(["--config", str(config_path), "--private-audit", str(tmp_path / "audit-private"), "--output", str(out)]) == 1
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err + out.with_suffix(".failure.json").read_text()
