from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from evaluation.modular.custody import CustodyStore, InventoryItem, build_known_inventory
from evaluation.modular.calibration import CalibrationAuthority
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError
from research_loop.ontology import digest


def calibration(panel_digest: str, scorer_digest: str = "e" * 64, protocol_digest: str = "f" * 64) -> FrozenRecord:
    criteria = {"minimum_cases_per_benchmark": 9,
                "minimum_coverage": {"valid_positive": 1, "valid_negative": 1, "invalid_measurement": 1,
                                     "uncertain": 1, "negation_or_quoted_completion": 1, "correct_rejection": 1,
                                     "over_rejection": 1, "reasonable_alternative": 1, "empty_output": 1},
                "minimum_precision": 0.8, "minimum_recall": 0.8, "maximum_abstention_rate": 0.2, "maximum_uncertainty": 0.2}
    coverage = {name: 1 for name in criteria["minimum_coverage"]}
    matrix = {"tp": 4, "tn": 4, "fp": 0, "fn": 0, "abstained": 1}
    return CalibrationAuthority("test-calibration", b"k" * 32).issue({
        "schema": "scorer-calibration-v1", "panel_digest": panel_digest, "scorer_digest": scorer_digest,
        "protocol_digest": protocol_digest, "scorer_code_digest": "1" * 64, "judge_identity": "independent",
        "judge_parameters": {"temperature": 0}, "rubric_digest": "2" * 64,
        "calibration_manifest_digest": "3" * 64, "blind_review_protocol_digest": "4" * 64,
        "arbitration_protocol_digest": "5" * 64, "applicable_benchmarks": ["blade", "discoverybench"],
        "criteria": criteria, "criteria_digest": digest(criteria),
        "coverage": {"blade": coverage, "discoverybench": coverage},
        "confusion_matrix": {"blade": matrix, "discoverybench": matrix},
        "uncertainty": {"blade": 0.1, "discoverybench": 0.1},
    })


def calibrated_store(path: Path) -> CustodyStore:
    return CustodyStore(path, calibration_keys={"test-calibration": b"k" * 32})


def file(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def snapshot(root: Path) -> Path:
    for split, names in {"train": ["old"], "dev": ["dev"], "test": ["a", "b", "c"]}.items():
        for name in names:
            file(root / "discovery/upstream/discoverybench/synth" / split / name / "metadata.json", name)
    for name, complete in {"fish": True, "panda_nuts": True, "toy": False}.items():
        base = root / "scienceagent/work/BLADE/blade_bench/datasets" / name
        file(base / "data.csv", name)
        file(base / "info.json", name)
        if complete:
            file(base / "annotations.csv", name)
    return root


def test_inventory_split_exposure_and_train_export(tmp_path: Path) -> None:
    store = CustodyStore(tmp_path / "state.json")
    items = build_known_inventory(snapshot(tmp_path / "source"))
    assert {item.official_split for item in items if item.benchmark == "discoverybench"} == {"synth/train", "synth/dev", "synth/test"}
    store.inventory(items)
    split = store.split(seed="fixed")
    # All available synthetic test groups are historical selection in this tiny fixture.
    assert {row["domain"] for row in split["rows"] if row["official_split"] == "synth/test"} == {"train"}
    assert all(identity.domain == "train" for identity in store.export_train())
    assert all(identity.split_id == split["digest"] for identity in store.export_train())
    assert CustodyStore(tmp_path / "state.json").split(seed="fixed")["digest"] == split["digest"]
    with pytest.raises(ContractError, match="reallocation"):
        store.split(seed="other")
    altered = [
        InventoryItem(**{**item.data(), "content_hashes": tuple(item.content_hashes),
                         "exposure": "exposed" if item.benchmark == "blade" and item.task_id == "toy" else item.exposure})
        for item in items
    ]
    with pytest.raises(ContractError, match="inventory drift"):
        store.inventory(altered)
    with pytest.raises(ContractError, match="invalid exposure"):
        InventoryItem("invalid", "clean", "invalid:clean", "test", "clean", ("a" * 64,), "clean")


def test_historical_discovery_selection_is_one_first_variant_per_domain(tmp_path: Path) -> None:
    root = snapshot(tmp_path / "source")
    test_root = root / "discovery/upstream/discoverybench/synth/test"
    for name in ("alpha_0_0", "alpha_0_1", "beta_0_0", "beta_1_0", "gamma_0_0"):
        file(test_root / name / "metadata.json", name)
    items = build_known_inventory(root)
    exposed = {item.relative_path.rsplit("/", 1)[-1] for item in items
               if item.benchmark == "discoverybench" and item.official_split == "synth/test" and item.exposure == "exposed"}
    assert {"alpha_0_0", "beta_0_0", "gamma_0_0"} <= exposed
    assert "alpha_0_1" not in exposed
    assert "beta_1_0" not in exposed


def test_partial_source_group_attestation_cannot_admit_unreviewed_members(tmp_path: Path) -> None:
    store = CustodyStore(tmp_path / "partial.json")
    store.inventory([InventoryItem("blade", name, "shared", "unsplit", name, ("a" * 64,)) for name in ["a", "b"]])
    store.attest_independent_clean(item_ids=["blade:b"], custodian_id="custodian",
        source_qualification_digest="b" * 64, exposure_qualification_digest="c" * 64, tested_arm_ids=["tested"])
    assert {row["domain"] for row in store.split(seed="frozen", validation_percent=100)["rows"]} == {"quarantine"}


def test_stale_controller_cannot_overwrite_another_validation_lease(tmp_path: Path) -> None:
    path = tmp_path / "concurrent.json"
    first = calibrated_store(path)
    first.inventory([InventoryItem("blade", "a", "a", "unsplit", "a", ("a" * 64,))])
    first.attest_independent_clean(item_ids=["blade:a"], custodian_id="custodian",
        source_qualification_digest="b" * 64, exposure_qualification_digest="c" * 64, tested_arm_ids=["tested"])
    group = first.split(seed="s", validation_percent=100)["rows"][0]["group"]
    second = calibrated_store(path)
    lease = first.lease_validation(stage="stage-a", panel_digest="d" * 64, group_ids=[group], arm_schedule=["control", "candidate"], candidate_digest="7" * 64, scorer_digest="e" * 64, protocol_digest="f" * 64, calibration_receipt=calibration("d" * 64))
    with pytest.raises(ContractError, match="stale write"):
        second.lease_validation(stage="stage-b", panel_digest="e" * 64, group_ids=[group], arm_schedule=["control", "candidate"], candidate_digest="7" * 64, scorer_digest="e" * 64, protocol_digest="f" * 64, calibration_receipt=calibration("e" * 64))
    assert set(CustodyStore(path).state["leases"]) == {lease["id"]}


def test_hash_union_and_validation_lease_are_bound_and_one_use(tmp_path: Path) -> None:
    clean_hash = "a" * 64
    items = [
        InventoryItem("one", "a", "one:a", "test", "a", (clean_hash,)),
        InventoryItem("two", "b", "two:b", "test", "b", (clean_hash,)),
        InventoryItem("three", "c", "three:c", "test", "c", ("b" * 64,)),
    ]
    store = calibrated_store(tmp_path / "state.json")
    store.inventory(items)
    store.attest_independent_clean(item_ids=["one:a", "two:b", "three:c"], custodian_id="custody-service",
                                   source_qualification_digest="a" * 64,
                                   exposure_qualification_digest="b" * 64,
                                   tested_arm_ids=["arm-a", "arm-b"])
    split = store.split(seed="seed", validation_percent=100)
    rows = {row["item"]: row for row in split["rows"]}
    assert rows["one:a"]["group"] == rows["two:b"]["group"]
    group = rows["one:a"]["group"]
    with pytest.raises(ContractError, match="non-validation"):
        store.qualify_stage(stage="C1", panel_digest="c" * 64, group_ids=["not-a-validation-group"], arm_schedule=["arm-a", "arm-b"])
    lease = store.lease_validation(stage="C1", panel_digest="c" * 64, group_ids=[group], arm_schedule=["arm-a", "arm-b"], candidate_digest="7" * 64, scorer_digest="e" * 64, protocol_digest="f" * 64, calibration_receipt=calibration("c" * 64))
    with pytest.raises(ContractError, match="panel or arm"):
        store.consume_validation(lease["id"], panel_digest="d" * 64, arm_schedule=["arm-a", "arm-b"])
    with pytest.raises(ContractError, match="allocated or consumed"):
        store.lease_validation(stage="C2", panel_digest="d" * 64, group_ids=[group], arm_schedule=["arm-a", "arm-b"], candidate_digest="7" * 64, scorer_digest="e" * 64, protocol_digest="f" * 64, calibration_receipt=calibration("d" * 64))
    assert store.consume_validation(lease["id"], panel_digest="c" * 64, arm_schedule=["arm-a", "arm-b"])["status"] == "consumed"
    with pytest.raises(ContractError, match="allocated or consumed"):
        store.qualify_stage(stage="C3", panel_digest="e" * 64, group_ids=[group], arm_schedule=["arm-a", "arm-b"])


def test_unverified_blade_folder_stays_quarantined_until_external_attestation(tmp_path: Path) -> None:
    root = snapshot(tmp_path / "source")
    for name in ("data.csv", "info.json", "annotations.csv"):
        file(root / "scienceagent/work/BLADE/blade_bench/datasets/soccer" / name, "soccer")
    items = build_known_inventory(root)
    store = CustodyStore(tmp_path / "unqualified.json")
    store.inventory(items)
    split = store.split(seed="fixed", validation_percent=100)
    soccer = next(row for row in split["rows"] if row["item"] == "blade:soccer")
    assert soccer["domain"] == "quarantine"
    with pytest.raises(ContractError, match="after split"):
        store.attest_independent_clean(item_ids=["blade:soccer"], custodian_id="custody-service",
                                       source_qualification_digest="a" * 64,
                                       exposure_qualification_digest="b" * 64,
                                       tested_arm_ids=["arm-a"])

    qualified = CustodyStore(tmp_path / "qualified.json")
    qualified.inventory(items)
    with pytest.raises(ContractError, match="independent"):
        qualified.attest_independent_clean(item_ids=["blade:soccer"], custodian_id="arm-a",
                                           source_qualification_digest="a" * 64,
                                           exposure_qualification_digest="b" * 64,
                                           tested_arm_ids=["arm-a"])
    qualified.attest_independent_clean(item_ids=["blade:soccer"], custodian_id="custody-service",
                                       source_qualification_digest="a" * 64,
                                       exposure_qualification_digest="b" * 64,
                                       tested_arm_ids=["arm-a", "arm-b"])
    qualified_split = qualified.split(seed="fixed", validation_percent=100)
    soccer = next(row for row in qualified_split["rows"] if row["item"] == "blade:soccer")
    assert soccer["domain"] == "validation"
    assert soccer["custodian_qualified"] is True


def test_cli_inventory_attest_split_export_qualify_lease_consume(tmp_path: Path) -> None:
    root = snapshot(tmp_path / "source")
    for name in ("data.csv", "info.json", "annotations.csv"):
        file(root / "scienceagent/work/BLADE/blade_bench/datasets/soccer" / name, "soccer")
    state = tmp_path / "state.json"
    base = [sys.executable, "-m", "evaluation.modular.custody", "--state", str(state)]
    first = subprocess.run([*base, "inventory", "--snapshot", str(root)], capture_output=True, text=True, check=True)
    assert len(json.loads(first.stdout)["inventory_digest"]) == 64
    subprocess.run([*base, "attest", "--item", "blade:soccer", "--custodian", "custody-service",
                    "--source-proof", "a" * 64, "--exposure-proof", "b" * 64,
                    "--tested-arm", "arm-a", "--tested-arm", "arm-b"], capture_output=True, text=True, check=True)
    second = subprocess.run([*base, "split", "--seed", "repeatable", "--validation-percent", "100"], capture_output=True, text=True, check=True)
    third = subprocess.run([*base, "split", "--seed", "repeatable", "--validation-percent", "100"], capture_output=True, text=True, check=True)
    assert json.loads(second.stdout)["digest"] == json.loads(third.stdout)["digest"]
    exported = subprocess.run([*base, "export"], capture_output=True, text=True, check=True)
    assert all(row["domain"] == "train" for row in json.loads(exported.stdout))
    qualified = subprocess.run([*base, "qualify", "--stage", "C1", "--panel-digest", "c" * 64,
                                "--group", "blade:soccer", "--arm", "arm-a", "--arm", "arm-b"], capture_output=True, text=True, check=True)
    assert json.loads(qualified.stdout)["qualification"] == "metadata_only"
    leased = subprocess.run([*base, "lease", "--stage", "C1", "--panel-digest", "c" * 64,
                              "--group", "blade:soccer", "--arm", "arm-a", "--arm", "arm-b"], capture_output=True, text=True)
    assert leased.returncode != 0 and "signed scorer calibration" in leased.stderr
