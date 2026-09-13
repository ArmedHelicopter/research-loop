import csv
import json
from pathlib import Path

import pytest

from evaluation.modular.canonical_lineage import Record, empty_references, match_records
from evaluation.modular.fresh_airs_custodian import CustodyError
from evaluation.modular.process_source_qualification import (
    BoundReads, GAPS, apply_canonical_closure, controller_metadata, metadata_groups,
    process_audit, prospective_split,
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
