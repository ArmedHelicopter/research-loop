import hashlib
import json
from pathlib import Path

import pytest

from evaluation.modular.train_io import TrainPacketExporter
from research_loop.modular.contracts import DataIdentity
from research_loop.ontology import ContractError, digest


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Custody:
    def __init__(self, identities, state): self.identities, self.state = identities, state
    def export_train(self): return list(self.identities)


def fixture(tmp_path: Path):
    root = tmp_path / "snapshot"
    disc = root / "discovery" / "upstream" / "discoverybench" / "synth" / "train" / "family_1_1"
    blade = root / "scienceagent" / "work" / "BLADE" / "blade_bench" / "datasets" / "fish"
    disc.mkdir(parents=True); blade.mkdir(parents=True)
    (disc / "metadata_1.json").write_text(json.dumps({"queries": [{"question": "public q", "difficulty": 1}], "datasets": [{"name": "data.csv", "description": "d", "columns": [{"name": "x", "description": "x"}]}]}), encoding="utf-8")
    (disc / "data.csv").write_text("x\n1\n", encoding="utf-8")
    (blade / "info.json").write_text(json.dumps({"research_questions": ["public blade q"], "data_desc": {"dataset_description": "public instructions", "fields": ["x", "y"]}}), encoding="utf-8")
    (blade / "data.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    rows = []
    for benchmark, task_id, group, official, relative, files in [
        ("discoverybench", "synth:train:family_1_1", "disc-group", "synth/train", "synth/train/family_1_1", [disc / "metadata_1.json", disc / "data.csv"]),
        ("blade", "fish", "blade-group", "unsplit", "fish", [blade / "info.json", blade / "data.csv"]),
    ]:
        rows.append({"benchmark": benchmark, "task_id": task_id, "source_group": group, "official_split": official, "relative_path": relative, "content_hashes": [sha(p) for p in files], "exposure": "exposed"})
    inv = digest(sorted(rows, key=lambda r: (r["benchmark"], r["task_id"])))
    split_rows = [{"item": f"{r['benchmark']}:{r['task_id']}", "group": r["source_group"], "domain": "train", "official_split": r["official_split"]} for r in rows]
    split = {"digest": digest(split_rows), "rows": split_rows}
    ids = [DataIdentity(r["benchmark"], r["task_id"], r["source_group"], inv, split["digest"], "train") for r in rows]
    return root, Custody(ids, {"inventory": rows, "inventory_digest": inv, "split": split})


def test_exports_only_allowlisted_public_packets(tmp_path: Path):
    root, custody = fixture(tmp_path)
    packets = TrainPacketExporter(custody, root, tmp_path / "out").export(["discoverybench:synth:train:family_1_1", "blade:fish"])
    assert {packet.task.identity.benchmark for packet in packets} == {"discoverybench", "blade"}
    assert all(packet.packet_path.name == "public.json" and packet.csv_path.exists() for packet in packets)
    assert all("annotation" not in packet.packet_path.read_text(encoding="utf-8").lower() for packet in packets)


def test_rejects_validation_identity_and_hash_drift_before_parse(tmp_path: Path):
    root, custody = fixture(tmp_path)
    bad = DataIdentity("discoverybench", "synth:train:family_1_1", "disc-group", custody.state["inventory_digest"], custody.state["split"]["digest"], "validation")
    custody.identities = [bad]
    with pytest.raises(ContractError):
        TrainPacketExporter(custody, root, tmp_path / "out").export(["discoverybench:synth:train:family_1_1"])
    root, custody = fixture(tmp_path / "hash")
    data = root / "discovery" / "upstream" / "discoverybench" / "synth" / "train" / "family_1_1" / "metadata_1.json"
    data.write_text("{}", encoding="utf-8")
    with pytest.raises(ContractError, match="hash"):
        TrainPacketExporter(custody, root, tmp_path / "out2").export(["discoverybench:synth:train:family_1_1"])
