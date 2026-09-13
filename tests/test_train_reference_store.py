"""Synthetic source files only; no live reference or validation task is opened."""
import csv
import json
from dataclasses import replace
from pathlib import Path

import pytest

from evaluation.modular.reference_store import (
    BLADE_REFERENCE_FIELDS, FrozenTrainReferenceResolver, prepare_train_reference_store,
)
from evaluation.modular.scoring_service import (AdaptedMetricReceiptVerifier, FrozenBenchmarkRubricEndpoint,
    FrozenRubricTransport, IndependentScoringService, ScorerConfig, ScoringAuthority)
from evaluation.modular.train_io import TrainPacketExporter
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.ontology import ContractError, digest
from test_modular_train_io import fixture, sha


def material(tmp_path):
    snapshot, custody = fixture(tmp_path)
    disc = snapshot / "discovery/upstream/discoverybench/synth/train/family_1_1"
    blade = snapshot / "scienceagent/work/BLADE/blade_bench/datasets/fish"
    metadata = json.loads((disc / "metadata_1.json").read_text())
    metadata["id"] = 1; metadata["queries"][0]["qid"] = 1
    (disc / "metadata_1.json").write_text(json.dumps(metadata))
    with (blade / "annotations.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["spec_id", *BLADE_REFERENCE_FIELDS]); writer.writeheader()
        for number in range(3):
            spec = {field: json.dumps({"synthetic": field + str(number), "text": "SYNTHETIC-BLADE-REFERENCE\nline 2"}) for field in BLADE_REFERENCE_FIELDS}
            writer.writerow({"spec_id": str(number), **spec})
        writer.writerow({"spec_id": "duplicate", **spec})
        writer.writerow({"spec_id": "partial-alternative", "conceptual_spec_json": json.dumps({"x": "synthetic alternative"})})
        writer.writerow({"spec_id": "empty"})
    key_path = tmp_path / "source-answer.csv"
    with key_path.open("w", encoding="cp1252", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["dataset", "metadataid", "query_id", "gold_hypo"]); writer.writeheader()
        writer.writerow({"dataset": "family_1_1", "metadataid": "1", "query_id": "1", "gold_hypo": "SYNTHETIC-DISCOVERY-REFERENCE\ncurly ’ quote"})
        writer.writerow({"dataset": "UNALLOCATED", "metadataid": "1", "query_id": "1", "gold_hypo": "UNALLOCATED-REFERENCE-SENTINEL"})
    for row in custody.state["inventory"]:
        directory = disc if row["benchmark"] == "discoverybench" else blade
        row["content_hashes"] = sorted(sha(path) for path in directory.iterdir())
    version = digest(custody.state["inventory"])
    custody.state["inventory_digest"] = version
    custody.identities = [replace(identity, dataset_version=version) for identity in custody.identities]
    packets = TrainPacketExporter(custody, snapshot, tmp_path / "public").export(
        [f"{identity.benchmark}:{identity.task_id}" for identity in custody.identities])
    keys = {"synth": {"path": str(key_path), "sha256": sha(key_path), "encoding": "cp1252"}}
    args = dict(custody=custody, snapshot_root=snapshot, packets=packets, store_root=tmp_path / "scorer-only", discovery_answer_keys=keys)
    return args


def resolver(args, publication):
    body = publication.data()
    return FrozenTrainReferenceResolver(args["store_root"], manifest_sha256=body["manifest_sha256"],
        inventory_digest=body["inventory_digest"], split_digest=body["split_digest"])


def test_train_export_real_journal_to_frozen_reference_endpoint_and_signed_score(tmp_path):
    from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
    from research_loop.modular.panel_plan import compile_train_panel, obligation_grids, executable_arms
    from research_loop.modular.panel_runner import run_train_cell
    from research_loop.modular.runtime import AuditVerifier
    from test_modular_benchmark_cell import _model

    args = material(tmp_path)
    publication = prepare_train_reference_store(**args)
    assert publication.data()["reference_count"] == 2
    assert "REFERENCE-SENTINEL" not in publication.encoded and "SYNTHETIC-" not in publication.encoded
    resolve = resolver(args, publication)
    tasks = tuple(packet.task for packet in args["packets"])
    package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([task.identity for task in tasks]),
        changes={"prompt": {"instructions": "Synthetic reference-boundary check"}}, search_cost=0)
    control = FrozenRecord.from_dict({"always_enabled": True})
    grid = obligation_grids(("Q3.1",), baseline_digest="b" * 64, p0_control=control)
    config = ScorerConfig.create(benchmark="core_pair", evaluator_id="synthetic-resolver-check", rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest(), version="v1")
    panel = compile_train_panel(stage="synthetic-reference-store", scope_ids=("Q3.1",), tasks=tasks,
        evidence_by_task={task.content_hash: FrozenRecord.from_dict({"public": "synthetic"}) for task in tasks},
        budget=FrozenRecord.from_dict({"calls": 2}), baseline_digest="b" * 64, p0_control=control,
        packages_by_arm={arm.content_hash: package for item in grid.values() for arm in executable_arms(item).values()},
        scorer=config.record, acceptance_criteria=FrozenRecord.from_dict({"scientific_validity": "not_measured"}))
    evaluator_calls = []
    def evaluator(request):
        evaluator_calls.append(request)
        return FrozenRecord.from_dict(({"cvars": 2, "transform": 1, "model": 0} if request.data()["benchmark"] == "blade"
            else {"context": 1, "variable_f1": 0.5, "relation": 1}) | {"reason": "Synthetic response; not a measured effect"})
    endpoint = FrozenBenchmarkRubricEndpoint(resolver=resolve, evaluator=evaluator,
        evaluator_id="synthetic-resolver-check", evaluator_version="v1")
    authority = ScoringAuthority("synthetic-scorer", b"s" * 32)
    service = IndependentScoringService(config=config, authority=authority, evaluator=FrozenRubricTransport(endpoint),
        allowed_task_handles=publication.data()["task_handles"])
    for task in tasks:
        cell = next(cell for cell in panel.panel.cells if cell.task_digest == task.content_hash)
        runtime = run_train_cell(cell, task=task, scenario=panel.scenarios[cell.key], package=package,
            objective=FrozenRecord.from_dict({"objective": "synthetic reference check"}), sidecar=tmp_path / ("run-" + task.identity.benchmark),
            model=_model([]), audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32})).runtime
        assert runtime.status == "succeeded"
        score = service.score(panel=panel.panel, cell=cell, runtime=runtime)
        AdaptedMetricReceiptVerifier(authority_keys={authority.authority_id: authority.key}, config=config)(score, cell, panel.panel)
        assert score.receipt.data()["body"]["scientific_validity"] == "not_measured"
    assert len(evaluator_calls) == 2
    for request in evaluator_calls:
        assert "UNALLOCATED-REFERENCE-SENTINEL" not in request.encoded
        expected = "SYNTHETIC-BLADE-REFERENCE" if request.data()["benchmark"] == "blade" else "SYNTHETIC-DISCOVERY-REFERENCE"
        assert expected in request.data()["prompt"]
    blade_handle = publication.data()["task_handles"][digest(next(task for task in tasks if task.identity.benchmark == "blade").identity.data())]
    assert len(resolve(blade_handle, "blade").data()["references"]) == 4
    assert "\nline 2" in resolve(blade_handle, "blade").data()["references"][0][BLADE_REFERENCE_FIELDS[0]]["text"]


@pytest.mark.parametrize("fault", ["validation", "split_reallocated", "source_hash", "answer_key_hash", "foreign_question", "nested_store", "missing_selector"])
def test_rejects_mismatched_allocation_source_or_destination_before_publication(tmp_path, fault):
    args = material(tmp_path)
    if fault == "validation":
        first, *rest = args["packets"]
        args["packets"] = (replace(first, task=replace(first.task, identity=replace(first.task.identity, domain="validation"))), *rest)
    elif fault == "split_reallocated":
        args["custody"].state["split"]["rows"][0]["domain"] = "validation"
    elif fault == "source_hash":
        for row in args["custody"].state["inventory"]: row["content_hashes"] = ["0" * 64]
    elif fault == "answer_key_hash":
        args["discovery_answer_keys"]["synth"]["sha256"] = "0" * 64
    elif fault == "foreign_question":
        first, *rest = args["packets"]
        changed = replace(first.task, payload=FrozenRecord.from_dict({**first.task.payload.data(), "question": "foreign question"}))
        args["packets"] = (replace(first, task=changed), *rest)
    elif fault == "missing_selector":
        first, *rest = args["packets"]
        args["packets"] = (replace(first, receipt=FrozenRecord.from_dict({key: value for key, value in first.receipt.data().items() if key != "source_selector"})), *rest)
    else:
        args["store_root"] = args["packets"][0].packet_path.parent / "private"
    with pytest.raises(ContractError): prepare_train_reference_store(**args)
    assert not args["store_root"].exists()


def test_resolver_rejects_foreign_handles_and_changed_reference_or_manifest(tmp_path):
    args = material(tmp_path); publication = prepare_train_reference_store(**args); resolve = resolver(args, publication)
    handle = next(iter(publication.data()["task_handles"].values()))
    manifest_path = args["store_root"] / "manifest.json"
    manifest = FrozenRecord(manifest_path.read_text()).data()
    benchmark = next(row["identity"]["benchmark"] for row in manifest["rows"] if row["task_handle"] == handle)
    with pytest.raises(ContractError): resolve("foreign", benchmark)
    with pytest.raises(ContractError): resolve(handle, "blade" if benchmark == "discoverybench" else "discoverybench")
    reference = args["store_root"] / (handle + ".json")
    original = reference.read_bytes(); reference.write_bytes(b"{}")
    with pytest.raises(ContractError, match="hash"): resolve(handle, benchmark)
    reference.write_bytes(original)
    manifest_path.write_bytes(b"{}")
    with pytest.raises(ContractError, match="hash"): resolve(handle, benchmark)


def test_exact_discovery_source_selector_and_task_context_binding(tmp_path):
    args = material(tmp_path)
    directory = args["snapshot_root"] / "discovery/upstream/discoverybench/synth/train/family_1_1"
    # A new lexically first metadata record cannot redirect the exported task.
    alternate = json.loads((directory / "metadata_1.json").read_text()); alternate["id"] = 99
    (directory / "metadata_0.json").write_text(json.dumps(alternate))
    publication = prepare_train_reference_store(**args)
    resolve = resolver(args, publication)
    packet = args["packets"][0]; handle = publication.data()["task_handles"][digest(packet.task.identity.data())]
    assert "SYNTHETIC-DISCOVERY-REFERENCE" in resolve(handle, "discoverybench").encoded
    manifest_path = args["store_root"] / "manifest.json"
    manifest = FrozenRecord(manifest_path.read_text()).data()
    reference_path = args["store_root"] / (handle + ".json")
    body = FrozenRecord(reference_path.read_text(encoding="utf-8")).data(); body["task_context"]["question"] = "wrong task"
    reference_path.write_text(FrozenRecord.from_dict(body).encoded, encoding="utf-8")
    for row in manifest["rows"]:
        if row["task_handle"] == handle: row["reference_sha256"] = sha(reference_path)
    manifest_path.write_text(FrozenRecord.from_dict(manifest).encoded)
    changed = FrozenRecord.from_dict({**publication.data(), "manifest_sha256": sha(manifest_path)})
    with pytest.raises(ContractError, match="identity mismatch"):
        resolver(args, changed)(handle, "discoverybench")
