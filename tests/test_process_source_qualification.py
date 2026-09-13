import csv
import hashlib
import json
from pathlib import Path

import pytest

from evaluation.modular.canonical_lineage import Record, empty_references, match_records
from evaluation.modular.custody import InventoryItem, SCHEMA as CUSTODY_SCHEMA
from evaluation.modular.fresh_airs_custodian import CustodyError
from evaluation.modular.process_source_qualification import (
    BoundReads, GAPS, apply_canonical_closure, controller_metadata, metadata_groups,
    process_audit, prospective_split,
    seal_new_split,
)
from research_loop.modular.source_ingestion import SOURCE_SNAPSHOTS
from research_loop.ontology import digest


def audit():
    return {"schema": "bounded-process-access-audit-v1",
            "observation": "no_target_projection_observed_in_declared_receipt_scope",
            "legacy_independent_clean_attestation": False, "gaps": list(GAPS)}


def group(*tokens, core=False):
    tokens = sorted(tokens)
    return {"group_sha256": digest({"schema": "observed-source-family-v1", "members": tokens}),
            "member_tokens": tokens, "member_count": len(tokens), "source": "scicode",
            "independence_proven": False, "known_core_relation": core}


def test_unknown_pretraining_does_not_block_named_scope_and_seed_is_deterministic():
    groups = [group(digest(i)) for i in range(30)]
    first = prospective_split(audit(), groups, seed="frozen-synthetic")
    second = prospective_split(audit(), list(reversed(groups)), seed="frozen-synthetic")
    assert first == second
    assert sum(first["counts"].values()) == 30
    assert 0 < first["counts"]["validation"] < 30
    assert first["independence_proven"] is False
    assert first["validation_lease_issued"] is False


def test_existing_exposed_relation_never_enters_validation():
    result = prospective_split(audit(), [group(digest(i), core=True) for i in range(30)], seed="frozen-synthetic")
    assert result["counts"] == {"train": 30, "validation": 0}


def test_duplicate_tokens_and_legacy_attestation_substitution_rejected():
    with pytest.raises(CustodyError):
        prospective_split(audit(), [group(digest(1)), group(digest(1))], seed="frozen")
    invalid = audit()
    invalid["legacy_independent_clean_attestation"] = True
    with pytest.raises(CustodyError):
        prospective_split(invalid, [group(digest(1))], seed="frozen")


def test_byte_drift_is_rejected(tmp_path):
    path = tmp_path / "receipt.json"
    path.write_text('{"count":1}')
    reads = BoundReads()
    reads.read(path)
    path.write_text('{"count":2}')
    with pytest.raises(CustodyError):
        reads.finish()


def test_controller_only_metadata_does_not_output_dynamic_prompt_and_preserves_unknown_cost():
    attempt = {"schema": "train-panel-controller-attempt-v1", "packet_receipts": [
        {"identity": {"benchmark": "discoverybench", "task_id": "PRIVATE_TASK"}}],
        "compiled_manifest": {"PRIVATE_DYNAMIC_KEY": "PRIVATE_GOLD"}}
    ledger = {"config": {"schema": "codex-model-port-v1", "PRIVATE_PROMPT": "PRIVATE_CODE"},
              "calls": [{"status": "unknown", "error_text": "PRIVATE_GOLD"}], "tokens": 3, "usage_incomplete": True}
    result = controller_metadata(attempt, ledger)
    assert "PRIVATE" not in json.dumps(result)
    assert result["usage_incomplete"] is True
    assert result["call_status_counts"]["unknown"] == 1
    assert result["target_projection_observed"] is False
    attempt["packet_receipts"][0]["identity"]["benchmark"] = "scicode"
    assert controller_metadata(attempt, ledger)["target_projection_observed"] is True


@pytest.mark.parametrize("schema", ["q31-train-controller-attempt-v1", "m4-m5-train-controller-attempt-v1"])
def test_fixed_historical_controller_schemas_preserve_identity_denominator(schema):
    attempt = {"schema": schema, "packet_receipts": [{"identity": {"benchmark": "blade"}}]}
    ledger = {"config": {"schema": "codex-model-port-v1"}, "calls": [], "tokens": 0, "usage_incomplete": False}
    assert controller_metadata(attempt, ledger)["benchmark_counts"]["blade"] == 1


def test_storage_container_does_not_merge_sab_but_missing_fallback_and_actual_tree_equality_do(tmp_path, monkeypatch):
    monkeypatch.setattr("evaluation.modular.process_source_qualification._receipt", lambda *args: {"verified_fixture": True})
    for source, spec in SOURCE_SNAPSHOTS.items():
        directory = tmp_path / "snapshots" / source / spec.revision
        directory.mkdir(parents=True)
        if source == "scicode":
            for name, count in (("problems_dev.jsonl", 15), ("problems_test.jsonl", 65)):
                (directory / name).write_text("\n".join(json.dumps({"PRIVATE_GOLD": i}) for i in range(count)))
        else:
            with (directory / "ScienceAgentBench.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["github_name", "dataset_folder_tree", "src_file_or_path", "PRIVATE_GOLD"])
                writer.writeheader()
                for i in range(102):
                    writer.writerow({"github_name": f"fixture/repo{i // 33}" if i < 99 else "n/a",
                                     "dataset_folder_tree": "shared-fixture-tree" if i in {0, 99} else "",
                                     "src_file_or_path": "", "PRIVATE_GOLD": f"secret{i}"})
    groups, _ = metadata_groups(tmp_path)
    assert sorted(row["member_count"] for row in groups) == [33, 33, 36, 80]
    assert "PRIVATE" not in json.dumps(groups)
    assert sum(row["member_count"] for row in groups) == 182


def test_canonical_artifact_link_joins_fallback_to_known_primary_and_forces_train():
    token_a, token_b, primary = digest("a"), digest("b"), digest("primary")
    references = empty_references()
    references["data_artifact_sha256"].add(digest("shared-scientific-bytes"))
    records = [Record("scicode", token_a, references), Record("scicode", token_b, references),
               Record("discoverybench", primary, references)]
    graph = match_records(records)
    groups = apply_canonical_closure([group(token_a), group(token_b)], graph)
    assert len(groups) == 1 and groups[0]["known_core_relation"] is True
    assert prospective_split(audit(), groups, seed="frozen")["counts"] == {"train": 2, "validation": 0}


def _synthetic_seal_config(tmp_path, monkeypatch):
    import io
    from research_loop.modular.source_ingestion import ArtifactSpec, SourceSnapshot, SourceAcquirer
    blobs, specs = {}, {}
    for source, real in SOURCE_SNAPSHOTS.items():
        if source == "scicode":
            content = {name: ("\n".join(json.dumps({"PRIVATE_GOLD": index}) for index in range(count)) + "\n").encode()
                       for name, count in (("problems_dev.jsonl", 15), ("problems_test.jsonl", 65))}
        else:
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=["github_name", "dataset_folder_tree", "src_file_or_path", "PRIVATE_GOLD"])
            writer.writeheader()
            for index in range(102):
                writer.writerow({"github_name": f"fixture/repo{index // 3}" if index < 99 else "n/a",
                                 "dataset_folder_tree": "", "src_file_or_path": "", "PRIVATE_GOLD": "fixture-only"})
            content = {"ScienceAgentBench.csv": stream.getvalue().encode()}
        artifacts = tuple(ArtifactSpec(name, len(raw), git_blob_sha1=hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest())
                          for name, raw in content.items())
        specs[source] = SourceSnapshot(source, real.repository, real.revision, artifacts)
        blobs.update({f"https://huggingface.co/datasets/{real.repository}/resolve/{real.revision}/{name}?download=true": raw
                      for name, raw in content.items()})
    for module in ("research_loop.modular.source_ingestion", "evaluation.modular.extended_ingestion", "evaluation.modular.process_source_qualification"):
        monkeypatch.setattr(module + ".SOURCE_SNAPSHOTS", specs)

    class FakeTransport:
        def iter_bytes(self, url):
            yield blobs[url]

    def write(name, value):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        return str(path)

    private = tmp_path / "private"
    acquired = {source: SourceAcquirer(FakeTransport()).acquire(source, private).data() for source in specs}
    items = [InventoryItem(source, f"fixture-{index}", f"fixture-group-{index}", "test", "fixture-path", (digest(index),)).data()
             for source, count in (("scicode", 80), ("scienceagentbench", 102)) for index in range(count)]
    inventory_sha = digest(items)
    state = {"schema": CUSTODY_SCHEMA, "inventory": items, "inventory_digest": inventory_sha, "split": None, "leases": {}, "attestations": {}}
    state_path = write("state.json", state)
    state_sha = hashlib.sha256(Path(state_path).read_bytes()).hexdigest()
    metadata = {"schema": "extended-custodian-metadata-receipt-v1", "optimizer_access": "none",
                "read_scope": "private_schema_provenance_paths_and_content_hashes_only",
                "raw_private_payload_returned": False, "mutated_private_store": False, "mutated_custody_state": False,
                "live_inventory_binding": {"inventory_digest": inventory_sha, "custody_state_sha256": state_sha}}
    ledger_path = write("model/ledger.json", {"config": {"schema": "codex-model-port-v1"},
                                             "calls": [{"status": "succeeded"}], "tokens": 2, "usage_incomplete": False})
    attempt_path = write("run/controller-attempt.json", {"schema": "train-panel-controller-attempt-v1",
        "model_root": str(Path(ledger_path).parent), "packet_receipts": [{"identity": {"benchmark": "blade"}}]})
    groups, _ = metadata_groups(private)
    records = [Record(row["source"], token, empty_references()) for row in groups for token in row["member_tokens"]]
    review = {"schema": "process-access-scope-review-v1", "decision": "observed_process_scope_and_conservative_grouping",
              "run_locator_sha256": [digest(str(Path(attempt_path).resolve()))],
              "ledger_locator_sha256": [digest(str(Path(ledger_path).resolve()))], "gaps": list(GAPS)}
    return {"extended_private_root": str(private), "extended_inventory": state_path,
            "import_metadata": write("import.json", {"custody_state_sha256": state_sha, "inventory_digest": inventory_sha}),
            "metadata_receipt": write("metadata.json", metadata),
            "acquisition_receipts": {source: write(source + "-acquired.json", value) for source, value in acquired.items()},
            "canonical_receipt": write("canonical.json", {"graph": match_records(records)}),
            "scope_review": write("review.json", review),
            "runs": [{"attempt": attempt_path, "ledger": ledger_path}]}


def test_real_seal_entry_uses_verified_synthetic_source_receipts_and_never_projects_payload(tmp_path, monkeypatch):
    config = _synthetic_seal_config(tmp_path, monkeypatch)
    before = Path(config["extended_inventory"]).read_bytes()
    receipt = seal_new_split(tmp_path / "sealed", config, seed="frozen-synthetic")
    assert sum(receipt["counts"].values()) == 182
    assert receipt["counts"]["validation"] > 0
    assert Path(config["extended_inventory"]).read_bytes() == before
    assert {p.name for p in (tmp_path / "sealed").iterdir()} == {"process-audit.json", "prospective-split.json"}
    assert all("PRIVATE_GOLD" not in p.read_text() for p in (tmp_path / "sealed").iterdir())
    with pytest.raises(FileExistsError):
        seal_new_split(tmp_path / "sealed", config, seed="frozen-synthetic")


def test_real_seal_entry_rejects_target_projection_before_creating_output(tmp_path, monkeypatch):
    config = _synthetic_seal_config(tmp_path, monkeypatch)
    path = Path(config["runs"][0]["attempt"])
    value = json.loads(path.read_bytes())
    value["packet_receipts"][0]["identity"]["benchmark"] = "scienceagentbench"
    path.write_text(json.dumps(value))
    with pytest.raises(CustodyError):
        seal_new_split(tmp_path / "sealed", config, seed="frozen-synthetic")
    assert not (tmp_path / "sealed").exists()


def test_real_seal_entry_rejects_received_byte_drift_and_scope_review_pair_drift(tmp_path, monkeypatch):
    config = _synthetic_seal_config(tmp_path, monkeypatch)
    path = Path(config["scope_review"])
    value = json.loads(path.read_bytes())
    value["ledger_locator_sha256"] = [digest("different-ledger")]
    path.write_text(json.dumps(value))
    with pytest.raises(CustodyError):
        seal_new_split(tmp_path / "sealed", config, seed="frozen-synthetic")
    value["ledger_locator_sha256"] = [digest(str(Path(config["runs"][0]["ledger"]).resolve()))]
    path.write_text(json.dumps(value))
    snapshot = Path(config["extended_private_root"]) / "snapshots/scicode" / SOURCE_SNAPSHOTS["scicode"].revision / "problems_dev.jsonl"
    snapshot.write_bytes(snapshot.read_bytes() + b" ")
    with pytest.raises(Exception):
        seal_new_split(tmp_path / "sealed", config, seed="frozen-synthetic")
    assert not (tmp_path / "sealed").exists()
