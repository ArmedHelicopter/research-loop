from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from evaluation.modular.custody import CustodyStore, InventoryItem, build_known_inventory
from research_loop.ontology import ContractError


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
    assert CustodyStore(tmp_path / "state.json").split(seed="fixed")["digest"] == split["digest"]
    with pytest.raises(ContractError, match="reallocation"):
        store.split(seed="other")


def test_hash_union_prevents_cross_benchmark_leak_and_lease_is_one_use(tmp_path: Path) -> None:
    clean_hash = "a" * 64
    items = [
        InventoryItem("one", "a", "one:a", "test", "a", (clean_hash,), "clean"),
        InventoryItem("two", "b", "two:b", "test", "b", (clean_hash,), "clean"),
        InventoryItem("three", "c", "three:c", "test", "c", ("b" * 64,), "clean"),
    ]
    store = CustodyStore(tmp_path / "state.json")
    store.inventory(items)
    split = store.split(seed="seed", validation_percent=100)
    rows = {row["item"]: row for row in split["rows"]}
    assert rows["one:a"]["group"] == rows["two:b"]["group"]
    group = rows["one:a"]["group"]
    with pytest.raises(ContractError, match="non-validation"):
        store.qualify_stage(stage="C1", panel_digest="c" * 64, group_ids=["not-a-validation-group"])
    lease = store.lease_validation(stage="C1", panel_digest="c" * 64, group_ids=[group])
    assert store.consume_validation(lease["id"])["status"] == "consumed"
    with pytest.raises(ContractError, match="one-use"):
        store.lease_validation(stage="C1", panel_digest="c" * 64, group_ids=[group])


def test_cli_inventory_split_and_reopen(tmp_path: Path) -> None:
    root = snapshot(tmp_path / "source")
    state = tmp_path / "state.json"
    base = [sys.executable, "-m", "evaluation.modular.custody", "--state", str(state)]
    first = subprocess.run([*base, "inventory", "--snapshot", str(root)], capture_output=True, text=True, check=True)
    assert len(json.loads(first.stdout)["inventory_digest"]) == 64
    second = subprocess.run([*base, "split", "--seed", "repeatable"], capture_output=True, text=True, check=True)
    third = subprocess.run([*base, "split", "--seed", "repeatable"], capture_output=True, text=True, check=True)
    assert json.loads(second.stdout)["digest"] == json.loads(third.stdout)["digest"]
