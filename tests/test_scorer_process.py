"""Subprocess boundary checks for the train-only linked adapted scorer."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

from evaluation.modular.linked_scoring import verify_linked_adapted_receipt
from evaluation.modular.scorer_process import (LinkedScorerProcessClient, _JOURNAL_SCHEMA, _load, _sha,
    build_service, parse_server_config, serialize_frozen_panel)
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError, canonical, digest
from test_train_adapted_selection import EXEC, SCORER, material


def _material(tmp_path: Path):
    root = tmp_path / "compiled"; root.mkdir()
    return material(root)


def _store(tmp_path: Path, args: dict) -> tuple[Path, dict[str, str], str]:
    """Build a synthetic frozen store without reading any source benchmark data."""
    root = tmp_path / "private-scorer-store"; root.mkdir()
    tasks = {task.identity: task for task in args["tasks"].values()}
    rows, handles = [], {}
    for index, identity in enumerate(sorted(tasks, key=lambda item: item.benchmark)):
        handle = f"{index + 1:064x}"; identity_digest = digest(identity.data()); task = tasks[identity]
        reference = FrozenRecord.from_dict({"schema": "train-only-rubric-reference-v1", "split": "train",
            "benchmark": identity.benchmark, "task_handle_digest": hashlib.sha256(handle.encode()).hexdigest(),
            "identity_digest": identity_digest, "task_context": task.payload.data(),
            "references": [{"synthetic": "PRIVATE-REFERENCE-SENTINEL"}]})
        path = root / (handle + ".json"); path.write_text(reference.encoded, encoding="utf-8")
        rows.append({"identity": identity.data(), "identity_digest": identity_digest, "task_digest": task.content_hash,
            "task_handle": handle, "file": path.name, "reference_sha256": hashlib.sha256(reference.encoded.encode()).hexdigest(),
            "sources": [{"role": "synthetic-test-only", "sha256": "a" * 64}]})
        handles[identity_digest] = handle
    inventory = next(iter(tasks)).dataset_version; split = next(iter(tasks)).split_id
    manifest = FrozenRecord.from_dict({"schema": "frozen-train-reference-store-v1", "inventory_digest": inventory,
        "split_digest": split, "rows": rows, "scope": "train_only", "scientific_validity": "not_measured"})
    (root / "manifest.json").write_text(manifest.encoded, encoding="utf-8")
    return root, handles, hashlib.sha256(manifest.encoded.encode()).hexdigest()


def _config(tmp_path: Path, args: dict) -> dict:
    root, handles, manifest_sha = _store(tmp_path, args)
    executor, scorer = tmp_path / "executor.key", tmp_path / "scorer.key"
    executor.write_bytes(EXEC.key); scorer.write_bytes(SCORER.key)
    panel, config = args["panel"], args["config"]
    return {"schema": "linked-scorer-process-config-v1", "panel": serialize_frozen_panel(panel),
        "scorer_config": config.record.data(), "scorer_config_digest": config.digest,
        "train_reference_store": {"root": str(root.resolve()), "manifest_sha256": manifest_sha,
            "inventory_digest": panel.cells[0].identity.dataset_version, "split_digest": panel.split_digest},
        "task_handles": handles, "execution_authority_key_files": {EXEC.authority_id: str(executor.resolve())},
        "scorer_authority": {"id": SCORER.authority_id, "key_file": str(scorer.resolve())},
        # Test helper never consumes this. Production main requires the full reviewed form.
        "evaluator": {}}


def _command(config: Path, journal: Path) -> list[str]:
    helper = Path(__file__).parent / "helpers" / "scorer_process_helper.py"
    return [sys.executable, str(helper.resolve()), "--config", str(config.resolve()),
            "--config-sha256", hashlib.sha256(config.read_bytes()).hexdigest(), "--journal", str(journal.resolve())]


def test_actual_stdio_worker_scores_two_benchmark_cells_without_exposing_private_reference(tmp_path):
    args, _ = _material(tmp_path)
    config = _config(tmp_path, args); path = tmp_path / "worker.json"; path.write_text(canonical(config), encoding="utf-8")
    client_journal, worker_journal = tmp_path / "client.jsonl", tmp_path / "worker.jsonl"
    client = LinkedScorerProcessClient(panel=args["panel"], command=_command(path, worker_journal), journal_path=client_journal)
    try:
        chosen = [next(cell for cell in args["panel"].cells if cell.identity.benchmark == benchmark)
                  for benchmark in ("discoverybench", "blade")]
        receipts = [client.submit(cell_key=cell.key, linked_input=args["linked_inputs"][cell.key]) for cell in chosen]
        # Exact completed calls are replayed locally without another model request.
        assert client.submit(cell_key=chosen[0].key, linked_input=args["linked_inputs"][chosen[0].key]) == receipts[0]
        changed = args["linked_inputs"][chosen[0].key].data()
        changed["body"]["candidate"]["answer"] = "different candidate after successful score"
        with pytest.raises(ContractError, match="differs"):
            client.submit(cell_key=chosen[0].key, linked_input=FrozenRecord.from_dict(changed))
    finally:
        client.close()
    for cell, receipt in zip(chosen, receipts, strict=True):
        verify_linked_adapted_receipt(receipt, authority_keys={SCORER.authority_id: SCORER.key}, config=args["config"],
            panel=args["panel"], cell=cell, linked_input=args["linked_inputs"][cell.key], execution_authority_keys={EXEC.authority_id: EXEC.key})
    assert "PRIVATE-REFERENCE-SENTINEL" not in client_journal.read_text(encoding="utf-8")
    assert "PRIVATE-REFERENCE-SENTINEL" not in worker_journal.read_text(encoding="utf-8")
    journal_rows = [json.loads(line) for line in worker_journal.read_text(encoding="utf-8").splitlines()]
    assert {row["status"] for row in journal_rows} == {"reserved", "succeeded"}
    assert len(journal_rows) == 4
    with pytest.raises(ContractError, match="hash mismatch"):
        _load(path, "0" * 64)


def test_first_submit_rejects_deleted_exchange_sidecars_before_return(tmp_path, monkeypatch):
    import evaluation.modular.scorer_process as process
    args, _ = _material(tmp_path)
    path = tmp_path / 'worker.json'
    path.write_text(canonical(_config(tmp_path, args)), encoding='utf-8')
    client = LinkedScorerProcessClient(panel=args['panel'], command=_command(path, tmp_path/'worker.jsonl'),
        journal_path=tmp_path/'client.jsonl')
    original = process._exchange_catalogue_anchor
    def remove_after_append(owner, row):
        appended = original(owner, row)
        if row['event']['phase'] == 'authenticated':
            process._exchange_path(owner).write_bytes(b'')
            Path(str(owner.journal_path)+'.exchange-catalogue-anchors.jsonl').write_bytes(b'')
        return appended
    monkeypatch.setattr(process, '_exchange_catalogue_anchor', remove_after_append)
    cell = args['panel'].cells[0]
    try:
        with pytest.raises(ContractError, match='originals differ'):
            client.submit(cell_key=cell.key, linked_input=args['linked_inputs'][cell.key])
        # The scorer succeeded; failed audit custody prevents consumer return
        # without rewriting or retrying that already completed transaction.
        assert client.states[canonical(list(cell.key))]['status'] == 'succeeded'
        with pytest.raises(ContractError):
            client.submit(cell_key=cell.key, linked_input=args['linked_inputs'][cell.key])
    finally:
        client.close()
    assert len((tmp_path/'worker.jsonl').read_text(encoding='utf-8').splitlines()) == 2


def test_success_journal_failure_cannot_emit_authenticated_exchange(tmp_path, monkeypatch):
    import evaluation.modular.scorer_process as process
    args, _ = _material(tmp_path)
    path = tmp_path / 'worker.json'
    path.write_text(canonical(_config(tmp_path, args)), encoding='utf-8')
    journal = tmp_path/'client.jsonl'
    client = LinkedScorerProcessClient(panel=args['panel'], command=_command(path, tmp_path/'worker.jsonl'), journal_path=journal)
    original = process._append
    def fail_success(destination, value):
        if destination == journal and value.get('status') == 'succeeded':
            raise OSError('synthetic durable write failure')
        return original(destination, value)
    monkeypatch.setattr(process, '_append', fail_success)
    cell = args['panel'].cells[0]
    try:
        with pytest.raises(OSError, match='durable write failure'):
            client.submit(cell_key=cell.key, linked_input=args['linked_inputs'][cell.key])
        assert client.states[canonical(list(cell.key))]['status'] == 'reserved'
        observations = process.read_scorer_exchange_observations(process._exchange_path(client))
        assert [row['event']['phase'] for row in observations] == ['reserved', 'received']
    finally:
        client.close()


def test_utf8_signed_candidate_survives_a_gbk_worker_locale(tmp_path):
    args, _ = _material(tmp_path)
    value = _config(tmp_path, args)
    path = tmp_path / "worker.json"
    path.write_text(canonical(value), encoding="utf-8")
    cell = args["panel"].cells[0]
    # This fixture exercises the signed transport contract, not a claim about
    # the scientific quality or provenance of generated benchmark answers.
    body = args["linked_inputs"][cell.key].data()["body"]
    body["candidate"]["answer"] = "中文观测：均值 α = 1；保留阴性结果 🔬"
    body["candidate_digest"] = digest(body["candidate"])
    linked = EXEC.issue(body)
    worker = tmp_path / "worker.jsonl"
    client = LinkedScorerProcessClient(panel=args["panel"], command=_command(path, worker),
        journal_path=tmp_path / "client.jsonl", environment={**os.environ, "PYTHONIOENCODING":"gbk"})
    try:
        receipt = client.submit(cell_key=cell.key, linked_input=linked)
    finally:
        client.close()
    verify_linked_adapted_receipt(receipt, authority_keys={SCORER.authority_id:SCORER.key}, config=args["config"],
        panel=args["panel"], cell=cell, linked_input=linked, execution_authority_keys={EXEC.authority_id:EXEC.key})
    assert [json.loads(line)["status"] for line in worker.read_text(encoding="utf-8").splitlines()] == ["reserved","succeeded"]


@pytest.mark.parametrize("fault", ["validation", "scorer", "handles", "store_row"])
def test_rejects_validation_or_mismatched_frozen_dependencies_before_evaluator(tmp_path, fault):
    args, _ = _material(tmp_path)
    value = _config(tmp_path, args)
    if fault == "validation":
        panel = args["panel"]
        validation = replace(panel, domain="validation", cells=tuple(replace(cell, identity=replace(cell.identity, domain="validation")) for cell in panel.cells))
        value["panel"] = serialize_frozen_panel(validation)
    elif fault == "scorer":
        value["scorer_config_digest"] = "0" * 64
    elif fault == "handles":
        items = list(value["task_handles"].items())
        value["task_handles"] = dict((key, items[(index + 1) % len(items)][1]) for index, (key, _) in enumerate(items))
    else:
        handle = next(iter(value["task_handles"].values())); ref = Path(value["train_reference_store"]["root"]) / (handle + ".json")
        body = FrozenRecord(ref.read_text(encoding="utf-8")).data(); body["identity_digest"] = "f" * 64
        ref.write_text(FrozenRecord.from_dict(body).encoded, encoding="utf-8")
        manifest = Path(value["train_reference_store"]["root"]) / "manifest.json"
        rows = FrozenRecord(manifest.read_text(encoding="utf-8")).data();
        for row in rows["rows"]:
            if row["task_handle"] == handle: row["reference_sha256"] = hashlib.sha256(ref.read_bytes()).hexdigest()
        updated = FrozenRecord.from_dict(rows); manifest.write_text(updated.encoded, encoding="utf-8")
        value["train_reference_store"]["manifest_sha256"] = hashlib.sha256(updated.encoded.encode()).hexdigest()
    calls = []
    def forbidden(request):
        calls.append(request); raise AssertionError("evaluator must not be called")
    with pytest.raises(ContractError):
        build_service(parse_server_config(value), evaluator=forbidden)
    assert calls == []


def test_unknown_server_reservation_is_not_retried_or_double_scored(tmp_path):
    args, _ = _material(tmp_path)
    value = _config(tmp_path, args); config_path = tmp_path / "worker.json"; config_path.write_text(canonical(value), encoding="utf-8")
    cell = args["panel"].cells[0]; linked = args["linked_inputs"][cell.key]
    request_id = "interrupted-request"; material_value = {"request_id": request_id, "panel_digest": args["panel"].digest,
        "cell_key": list(cell.key), "linked_input": linked.data()}; request_digest = _sha(canonical(material_value))
    worker_journal = tmp_path / "worker.jsonl"
    worker_journal.write_text(canonical({"schema": _JOURNAL_SCHEMA, "cell_key": list(cell.key), "request_id": request_id,
        "request_digest": request_digest, "status": "reserved"}) + "\n", encoding="utf-8")
    client = LinkedScorerProcessClient(panel=args["panel"], command=_command(config_path, worker_journal), journal_path=tmp_path / "client.jsonl")
    try:
        with pytest.raises(ContractError, match="bound receipt"):
            client.submit(cell_key=cell.key, linked_input=linked)
        with pytest.raises(ContractError, match="unresolved"):
            client.submit(cell_key=cell.key, linked_input=linked)
    finally:
        client.close()
    # A stalled preflight/provider process cannot block the controller forever:
    # it is reaped and its cell remains unknown rather than being retried.
    timeout_client = LinkedScorerProcessClient(panel=args["panel"], command=[sys.executable, "-c", "import time; time.sleep(30)"],
        journal_path=tmp_path / "timeout-client.jsonl", response_timeout_seconds=1)
    try:
        with pytest.raises(ContractError, match="timed out"):
            timeout_client.submit(cell_key=args["panel"].cells[1].key, linked_input=args["linked_inputs"][args["panel"].cells[1].key])
        assert timeout_client.process.poll() is not None
        with pytest.raises(ContractError, match="unresolved"):
            timeout_client.submit(cell_key=args["panel"].cells[1].key, linked_input=args["linked_inputs"][args["panel"].cells[1].key])
    finally:
        timeout_client.close()


def test_malformed_client_journal_refuses_before_spawning_worker(tmp_path, monkeypatch):
    args, _ = _material(tmp_path)
    journal = tmp_path / "bad-client.jsonl"; journal.write_text("not json\n", encoding="utf-8")
    spawned = []
    def forbidden(*args, **kwargs):
        spawned.append(True); raise AssertionError("worker must not spawn")
    monkeypatch.setattr("evaluation.modular.scorer_process.subprocess.Popen", forbidden)
    with pytest.raises(ContractError, match="journal"):
        LinkedScorerProcessClient(panel=args["panel"], command=[sys.executable, "-c", "pass"], journal_path=journal)
    assert spawned == []
