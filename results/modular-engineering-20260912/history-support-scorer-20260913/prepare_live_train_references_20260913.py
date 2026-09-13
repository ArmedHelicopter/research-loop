"""Custodian operation: never print or export reference text to the optimizer."""
import hashlib
import json
import sys
from pathlib import Path

SOURCE = Path(r"E:\_ryanDev\AI\research-loop-modular\integration")
sys.path.insert(0, str(SOURCE))
from evaluation.modular.custody import CustodyStore
from evaluation.modular.train_io import TrainPacketExporter
from evaluation.modular.reference_store import prepare_train_reference_store, FrozenTrainReferenceResolver
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import canonical, digest

ROOT = Path(r"E:\_ryanDev\AI\research-loop-modular\work\train-reference-deployment-20260913-01")
STORE = Path(r"E:\_ryanDev\AI\research-loop-modular\custody-private\train-reference-store-20260913-01")
CUSTODY = Path(r"E:\_ryanDev\AI\research-loop-modular\benchmarks\work\custody-live-20260912.json")
SNAPSHOT = Path(r"E:\_ryanDev\AI\research-loop-benchmark-20260912")
EXPECTED = "933f158b947a0761ed297ea7cb713d816c2385e58f4d1df37dc7669071c9e96f"
ITEMS = ["discoverybench:synth:test:philosophical-debates_0_0", "blade:fish"]

if ROOT.exists() or STORE.exists():
    raise SystemExit("Existing attempt is immutable; inspect metadata instead of repeating.")
ROOT.mkdir(parents=True)
state = {"schema": "live-train-reference-preparation-v1", "source_commit": "e913ed6",
         "item_ids": ITEMS, "custody_sha256": EXPECTED, "paid_calls": 0,
         "validation_items": 0, "scientific_effect": "not_measured", "source_hashes": {}}
for name in ("evaluation/modular/reference_store.py", "evaluation/modular/train_io.py"):
    state["source_hashes"][name] = hashlib.sha256((SOURCE / name).read_bytes()).hexdigest()
try:
    assert hashlib.sha256(CUSTODY.read_bytes()).hexdigest() == EXPECTED
    custody = CustodyStore(CUSTODY)
    packets = TrainPacketExporter(custody, SNAPSHOT, ROOT / "public").export(ITEMS)
    publication = prepare_train_reference_store(custody=custody, snapshot_root=SNAPSHOT, packets=packets, store_root=STORE,
        discovery_answer_keys={"synth": {"path": str(SNAPSHOT / "discovery/upstream/eval/answer_key_synth.csv"),
            "sha256": "afd51d7053cefff6b335c209a42a1943217cb73a9fd36144a500cce49ecda675", "encoding": "cp1252"}})
    body = publication.data()
    resolver = FrozenTrainReferenceResolver(STORE, manifest_sha256=body["manifest_sha256"],
        inventory_digest=body["inventory_digest"], split_digest=body["split_digest"])
    checks = []
    for packet in packets:
        reference = resolver(body["task_handles"][digest(packet.task.identity.data())], packet.task.identity.benchmark)
        checks.append({"benchmark": packet.task.identity.benchmark, "identity_digest": digest(packet.task.identity.data()),
                       "reference_record_digest": reference.content_hash, "reference_count": len(reference.data()["references"])})
    assert hashlib.sha256(CUSTODY.read_bytes()).hexdigest() == EXPECTED
    (ROOT / "publication.json").write_text(publication.encoded, encoding="utf-8")
    state.update(status="prepared_and_lookup_verified", checks=checks, publication_sha256=hashlib.sha256(publication.encoded.encode()).hexdigest())
except Exception as exc:
    state.update(status="failed", error_type=type(exc).__name__)
    (ROOT / "status.json").write_text(canonical(state), encoding="utf-8")
    print(canonical(state))
    raise SystemExit(1)
(ROOT / "status.json").write_text(canonical(state), encoding="utf-8")
print(canonical(state))
