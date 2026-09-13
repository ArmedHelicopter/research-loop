import hashlib
import json
from pathlib import Path

import pytest

from evaluation.modular import primary_process_qualification as p
from evaluation.modular import lineage_custodian as c
from evaluation.modular.sab_history_eligibility import supplement_sab_eligibility
from research_loop.ontology import digest

SECRET = "PRIVATE_TASK_ANSWER_DYNAMIC_KEY_MUST_NOT_ESCAPE"


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
    return str(path)


def pin(path):
    return {"path": str(path), "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}


def source_fixture(tmp_path, nested_duplicate=False, public_projection=False, reference_projection=False):
    root = tmp_path / "snapshot"
    inventory = []
    for source in p.SOURCES:
        for index in range(4):
            relative = f"synth/test/case{index}" if source == "discoverybench" else f"case{index}"
            parent = root / ("discovery/upstream/discoverybench" if source == "discoverybench" else "scienceagent/work/BLADE/blade_bench/datasets") / relative
            text = {"source_url": f"10.1234/{'shared' if index == 0 else source + str(index)}",
                    "datasets": [{"name": "data.csv"}], "question": SECRET, SECRET: {SECRET: SECRET}}
            if public_projection:
                text.update(queries=[{"question": "Compute the mean of x.", "gold": SECRET}],
                            research_questions=["Compute the mean of x."], data_desc={"dataset_description": "Report the public x mean."})
            if reference_projection:
                text["id"] = index
                text["queries"][0]["qid"] = 0
            metadata = parent / ("metadata_0.json" if source == "discoverybench" else "info.json")
            write(metadata, text)
            value = (0 if index == 0 else index + (10 if source == "blade" else 20)) if public_projection else ('shared' if index == 0 else source + str(index))
            write(parent / "data.csv", f"x\n{value}\n".encode())
            if reference_projection and source == "blade":
                import csv, io
                from evaluation.modular.reference_store import BLADE_REFERENCE_FIELDS
                stream = io.StringIO(newline="")
                writer = csv.DictWriter(stream, fieldnames=["spec_id", *BLADE_REFERENCE_FIELDS])
                writer.writeheader()
                writer.writerow({"spec_id": "fixture", "conceptual_spec_json": json.dumps({"synthetic": "SYNTHETIC-BLADE-BRIDGE-REFERENCE"})})
                write(parent / "annotations.csv", stream.getvalue().encode())
            if nested_duplicate and source == "discoverybench" and index == 3:
                write(parent / "nested" / "metadata_0.json", metadata.read_bytes())
            task_id = relative.replace("/", ":")
            inventory.append(p.InventoryItem(source, task_id, f"{source}-family{index}", "synth/test" if source == "discoverybench" else "unsplit",
                                            relative, tuple(pin(path)["sha256"] for path in parent.rglob("*") if path.is_file()),
                                            "exposed" if source == "discoverybench" and index == 0 else "unknown").data())
    split = {"inventory_digest": digest(inventory), "rows": [{"item": f"{row['benchmark']}:{row['task_id']}",
              "domain": "train" if row["task_id"].endswith("case0") else "quarantine"} for row in inventory]}
    state = {"schema": p.CUSTODY_SCHEMA, "inventory": inventory, "inventory_digest": digest(inventory),
             "split": {**split, "digest": digest(split)}, "attestations": {}, "leases": {}}
    state_path = tmp_path / "custody.json"
    write(state_path, state)
    collector = c.Audit()
    records, inventory_sha = c.primary_records({"custody_state": str(state_path), "snapshot_root": str(root)}, collector)
    manifest = collector.finish()
    receipt = {"schema": c.SCHEMA, "inventory_digest": inventory_sha, "config_sha256": digest("fixture"),
               "field_rules_sha256": digest("fixture"), "implementation_sha256": [], "runtime_metadata_sha256": digest("fixture"),
               "read_manifest_sha256": digest(manifest), "read_file_count": len(manifest), "read_files_unchanged": True,
               "source_bindings": collector.bindings, "graph": c.match_records(records), "raw_private_payload_returned": False,
               "current_process_payload_exported": False, "historical_exposure_status": "unknown_not_changed",
               "os_access_isolation_verified": False, "old_split_mutated": False, "validation_lease_issued": False}
    metadata = root / "discovery/upstream/discoverybench/synth/test/case0/metadata_0.json"
    objects = {"custody": state, "canonical_receipt": receipt, "canonical_manifest": manifest,
               "discovery_manifest": {"tasks": [{"metadata_path": str(metadata), "data_path": str(metadata.with_name("data.csv")),
                                                   "metadata_sha256": pin(metadata)["sha256"], "data_sha256": pin(metadata.with_name("data.csv"))["sha256"],
                                                   "question": SECRET, SECRET: SECRET}]},
               "blade_v2_manifest": {"benchmark": "BLADE", "tasks": ["case0"]},
               "blade_manifest": {SECRET: SECRET}, "final_verification": {SECRET: SECRET},
               "blade_runner": b"TASKS=['case0']\n", "blade_v2_runner": b"TASKS=['case0']\n",
               "discovery_runner": b"def selected_tasks(): return []\n", "prepare_runner": b"# fixture\n",
               "blade_call": {"exit": 1, "usage": []},
               "later_ledger": {"config": {"schema": "codex-model-port-v1"}, "calls": [{"status": "succeeded"}], "tokens": 8, "usage_incomplete": False},
               "later_attempt": {"schema": "train-panel-controller-attempt-v1", "model_root": str(tmp_path),
                                 "packet_receipts": [{"identity": {"benchmark": "blade", "task_id": "case0", "domain": "train"}}]}}
    inputs = {}
    for key, value in objects.items():
        file = state_path if key == "custody" else tmp_path / (key + ".json")
        write(file, value)
        inputs[key] = pin(file)
    return {"schema": "primary-process-qualification-inputs-v1", "inputs": inputs, "snapshot_root": str(root), "expected_counts": {s: 4 for s in p.SOURCES},
            "runs": [{"attempt": "later_attempt", "ledger": "later_ledger"}],
            "blade_call_receipts": [{"task_id": "case0", "input": "blade_call"}]}


def test_synthetic_source_history_audit_seal_real_seam_and_no_payload_parse(tmp_path, monkeypatch, capsys):
    config = source_fixture(tmp_path)
    original = Path(config["inputs"]["custody"]["path"]).read_bytes()
    real_json = json.loads
    def guarded(value, *args, **kwargs):
        # New auditor may parse fixed history metadata containing a hidden task
        # field, but never decodes an upstream metadata/CSV payload.
        if isinstance(value, bytes) and b'"datasets"' in value:
            raise AssertionError("upstream metadata decode forbidden")
        return real_json(value, *args, **kwargs)
    monkeypatch.setattr(json, "loads", guarded)
    receipt = p.seal_primary_process(tmp_path / "sealed", config)
    assert receipt["counts"] == {"train": 6, "validation": 2}
    split = real_json((tmp_path / "sealed/prospective-split.json").read_bytes())
    assert all(row["split"] == "train" for row in split["groups"] if row["known_train_member_count"])
    assert any(row["source_counts"] == {"discoverybench": 1, "blade": 1} for row in split["groups"])
    assert Path(config["inputs"]["custody"]["path"]).read_bytes() == original
    assert SECRET not in "".join(path.read_text() for path in (tmp_path / "sealed").iterdir())
    assert capsys.readouterr().out == ""


def test_missing_complete_read_manifest_preserves_primary_aggregate_binding_and_gap(tmp_path):
    config = source_fixture(tmp_path)
    del config["inputs"]["canonical_manifest"]
    audit, _ = p.audit_primary_process(config)
    assert audit["canonical_read_manifest_available"] is False
    assert audit["primary_aggregate_source_hashes_reverified"] is True


def test_aggregate_classification_matches_original_direct_child_metadata_contract(tmp_path):
    config = source_fixture(tmp_path, nested_duplicate=True)
    del config["inputs"]["canonical_manifest"]
    audit, _ = p.audit_primary_process(config)
    assert audit["source_verified_file_counts"]["discoverybench"] == 8


@pytest.mark.parametrize("change", ["source", "history", "graph", "inventory", "aggregate"])
def test_byte_or_metadata_contract_drift_fails_without_split_and_safe_error(tmp_path, change, capsys):
    config = source_fixture(tmp_path)
    if change == "source":
        file = Path(config["snapshot_root"]) / "scienceagent/work/BLADE/blade_bench/datasets/case3/data.csv"
        file.write_text(SECRET)
    elif change == "history":
        Path(config["inputs"]["discovery_manifest"]["path"]).write_text(SECRET)
    else:
        key = "custody" if change == "inventory" else "canonical_receipt"
        file = Path(config["inputs"][key]["path"])
        value = json.loads(file.read_bytes())
        if change == "inventory":
            value["inventory"][0]["exposure"] = "unknown"
        elif change == "aggregate":
            value["source_bindings"]["blade"]["data_artifact_hashes"] = []
        else:
            value["graph"]["groups"][0]["member_tokens"].append(digest("foreign"))
        write(file, value)
        config["inputs"][key] = pin(file)
    with pytest.raises(p.CustodyError) as error:
        p.seal_primary_process(tmp_path / "sealed", config)
    assert str(error.value) == ""
    assert not (tmp_path / "sealed/prospective-split.json").exists()
    assert SECRET not in (tmp_path / "sealed/failure.json").read_text() + capsys.readouterr().out


def test_stratified_exact_ceil_is_order_invariant_and_never_splits_cross_benchmark_group(tmp_path):
    config = source_fixture(tmp_path)
    audit, groups = p.audit_primary_process(config)
    left = p.partition_primary(audit, groups)
    right = p.partition_primary(audit, list(reversed(groups)))
    assert left == right
    assert all(row["validation_groups"] == (3 * row["candidate_groups"] + 9) // 10 for row in left["strata"])
    assert left["seed"] == p.SEED


def sab_fixture(tmp_path):
    audit = {"schema": "bounded-process-access-audit-v1"}
    groups = [{"source": "scienceagentbench", "split": "validation", "group_sha256": digest("family"),
               "member_tokens": [digest("task-a"), digest("task-b")]}]
    values = {"sab_audit": audit,
              "sab_split": {"schema": "prospective-observed-family-split-v1", "audit_sha256": digest(audit), "groups": groups,
                            "validation_lease_issued": False},
              "sab_initial_manifest": {"task_ids": [2, 9], SECRET: SECRET}, "sab_runner": b"TASK_IDS=[2,9]\n",
              "call": {"exit_code": 1, "usage": [], SECRET: SECRET}}
    inputs = {}
    for key, value in values.items():
        file = tmp_path / (key + ".json")
        write(file, value)
        inputs[key] = pin(file)
    return {"inputs": inputs, "call_receipts": [{"instance_id": 2, "input": "call"}]}


def test_sab_unknown_revision_identity_bridge_holds_all_without_ordinal_guess(tmp_path):
    config = sab_fixture(tmp_path)
    before = Path(config["inputs"]["sab_split"]["path"]).read_bytes()
    result = supplement_sab_eligibility(tmp_path / "hold", config)
    assert result["selected_identity_count"] == 2
    assert result["call_observed_identity_count"] == 1
    assert result["potential_only_identity_count"] == 1
    assert result["historical_call_cost"]["unknown_usage_count"] == 1
    assert result["validation_eligible_count"] == 0
    assert result["same_ordinal_assumed"] is False
    assert Path(config["inputs"]["sab_split"]["path"]).read_bytes() == before
    assert SECRET not in "".join(path.read_text() for path in (tmp_path / "hold").iterdir())


def test_sab_malformed_history_keeps_persistent_hold_and_failure(tmp_path):
    config = sab_fixture(tmp_path)
    Path(config["inputs"]["sab_runner"]["path"]).write_text(SECRET)
    with pytest.raises(p.CustodyError):
        supplement_sab_eligibility(tmp_path / "hold", config)
    assert (tmp_path / "hold/eligibility-hold.json").exists()
    assert (tmp_path / "hold/failure.json").exists()


def test_source_mutation_after_first_audit_is_rejected_at_final_seal_boundary(tmp_path, monkeypatch):
    config = source_fixture(tmp_path)
    real_audit = p.audit_primary_process
    def mutate_after(*args):
        result = real_audit(*args)
        (Path(config["snapshot_root"]) / "scienceagent/work/BLADE/blade_bench/datasets/case3/data.csv").write_text(SECRET)
        return result
    monkeypatch.setattr(p, "audit_primary_process", mutate_after)
    with pytest.raises(p.CustodyError):
        p.seal_primary_process(tmp_path / "sealed", config)
    assert not (tmp_path / "sealed/prospective-split.json").exists()


def test_sab_public_hold_cannot_leak_dynamic_token_strings(tmp_path):
    config = sab_fixture(tmp_path)
    path = Path(config["inputs"]["sab_split"]["path"])
    value = json.loads(path.read_bytes())
    value["groups"][0]["member_tokens"] = [SECRET]
    write(path, value)
    config["inputs"]["sab_split"] = pin(path)
    with pytest.raises(p.CustodyError):
        supplement_sab_eligibility(tmp_path / "hold", config)
    assert not (tmp_path / "hold").exists()


def test_initial_budget_preserves_unknown_usage_instead_of_zero(tmp_path):
    config = source_fixture(tmp_path)
    path = tmp_path / "budget.json"
    write(path, {"calls": 4, "tokens": 17, "usage_incomplete": True})
    config["inputs"]["initial_budget"] = pin(path)
    config["initial_budgets"] = [{"source": "blade", "input": "initial_budget"}]
    audit, _ = p.audit_primary_process(config)
    assert audit["initial_budget_observations"] == [{"source": "blade", "call_count": 4, "known_tokens": 17,
                                                    "usage_incomplete": True, "call_status_breakdown_available": False}]


@pytest.mark.parametrize("raw", [b"TASKS=get_private_data()", b"TASKS=['x']; TASKS=['y']", b"TASKS=['x','x']"])
def test_runner_selection_must_be_literal_unique(raw):
    with pytest.raises((p.CustodyError, ValueError)):
        p.literal_selection(raw, "TASKS")
