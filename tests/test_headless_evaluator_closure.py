import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import evaluation.modular.headless_evaluator_closure as closure
from evaluation.modular.headless_evaluator_model_port import GrokHeadlessEvaluatorModelPort
from evaluation.modular.scoring_service import FrozenBenchmarkRubricEndpoint, ScorerConfig
from evaluation.modular.scorer_process import ScorerWorker
from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError, canonical
from test_headless_evaluator_model_port import _install_native, endpoint as native_endpoint, port as native_port, request as native_request


def _sha(value): return hashlib.sha256(value).hexdigest()


def prepared(tmp_path, monkeypatch):
    exe = tmp_path / "synthetic.exe"; exe.write_bytes(b"identity")
    home = tmp_path / "home"; home.mkdir(); (home / "auth.json").write_text("{}", encoding="utf-8")
    port = GrokHeadlessEvaluatorModelPort(executable=exe, work_root=tmp_path / "ledger", private_home=home,
        private_profile=tmp_path / "profile", public_cwd=tmp_path / "cwd",
        frozen_files={str(exe.resolve()): _sha(exe.read_bytes())}, evaluator_id="fixture", evaluator_version="v1",
        max_calls=1, max_tokens=100)
    config = ScorerConfig.create(benchmark="blade", evaluator_id="fixture", version="v1",
        rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest())
    authority = LinkedExecutionAuthority("scorer", b"s" * 32)
    directory = port.calls_root / "0001-blade"; directory.mkdir()
    request = FrozenRecord.from_dict({"schema": "frozen-independent-evaluator-call-v1", "evaluator_id": "fixture",
        "evaluator_version": "v1", "benchmark": "blade", "prompt": "x", "output_schema": {},
        "prompt_digest": "a" * 64, "schema_digest": "b" * 64, "reference_digest": "c" * 64,
        "rubric_digest": port.rubric_digest})
    (directory / "request.private.json").write_text(request.encoded, encoding="utf-8")
    output = FrozenRecord.from_dict({"cvars": 1, "transform": 1, "model": 1, "reason": "ok"})
    (directory / "response.private.json").write_text(output.encoded, encoding="utf-8")
    reservation = directory / "native-reservation.json"; reservation.write_bytes(b"reservation")
    native_receipt = directory / "observer-receipt.private.json"; native_receipt.write_bytes(b"native receipt")
    row = {"id": 1, "benchmark": "blade", "status": "succeeded", "request_sha256": request.content_hash,
        "opportunity_id": "headless-evaluator-0001-blade",
        "request": {"path": str(directory / "request.private.json"), "sha256": _sha(request.encoded.encode())},
        "response_sha256": output.content_hash, "reservation_sha256": _sha(reservation.read_bytes()),
        "native_receipt_sha256": _sha(native_receipt.read_bytes()), "known_headless_main_usage": {"total_tokens": 10}}
    port.ledger = {"config": port.config, "calls": [row], "known_main_tokens": 10, "tokens": 10, "usage_incomplete": False}
    port.ledger_path.write_text(canonical(port.ledger), encoding="utf-8")
    monkeypatch.setattr("evaluation.modular.headless_evaluator_model_port.replay_headless_evaluator_ledger", lambda value: None)
    evidence = {"evaluator_id": "fixture", "evaluator_version": "v1", "rubric_digest": port.rubric_digest,
        "prompt_digest": "a" * 64, "schema_digest": "b" * 64, "reference_digest": "c" * 64,
        "output_digest": output.content_hash}
    key = ("x",) * 7
    panel = SimpleNamespace(digest="p" * 64, cells=(SimpleNamespace(key=key, scorer_digest=config.digest,
        identity=SimpleNamespace(benchmark="blade")),))
    receipt = authority.issue({"schema": "combination-adapted-scored-cell-v1", "cell_key": list(key),
        "panel_digest": panel.digest, "scorer_digest": config.digest, "scorer_config_digest": config.digest,
        "benchmark": "blade", "evaluator_evidence": evidence})
    journal = tmp_path / "journal.jsonl"
    reservation = {"schema": "linked-scorer-process-journal-v1", "cell_key": ["x"] * 7,
        "request_id": "r", "request_digest": "d" * 64, "status": "reserved"}
    journal.write_text(canonical(reservation) + "\n" + canonical(reservation | {"status": "succeeded", "receipt": receipt.data()}) + "\n", encoding="utf-8")
    service = SimpleNamespace(headless_evaluator_port=port, evaluator_provider=closure.descriptor(port),
        _authority=authority, config=config)
    return service, panel, journal, receipt, directory


def test_closure_binds_ordered_native_call_to_signed_scorer_receipt(tmp_path, monkeypatch):
    service, panel, journal, receipt, _ = prepared(tmp_path, monkeypatch)
    value = closure.finalize(service=service, panel=panel, journal_path=journal, nonce="n",
        receipt_digests=[receipt.content_hash])
    body = closure.verify_closure(value, authority_keys={"scorer": b"s" * 32}, panel=panel, config=service.config,
        provider=service.evaluator_provider, nonce="n", receipt_digests=[receipt.content_hash]).data()
    assert (body["eligible"] is True and body["known_main_tokens"] == 10
            and body["calls"][0]["output_digest"] and body["scope"]["unscored_cell_count"] == 0
            and body["title_tokens"] is None and body["settled_additional_charge_usd"] is None)


@pytest.mark.parametrize("fault", ["output", "receipt", "extra", "reservation", "usage"])
def test_closure_rejects_tampered_or_unpaired_evidence(tmp_path, monkeypatch, fault):
    service, panel, journal, receipt, directory = prepared(tmp_path, monkeypatch)
    if fault == "output":
        (directory / "response.private.json").write_text(FrozenRecord.from_dict({"cvars": 0}).encoded, encoding="utf-8")
    elif fault == "receipt":
        rows = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
        rows[-1]["receipt"]["body"]["evaluator_evidence"]["output_digest"] = "0" * 64
        journal.write_text("\n".join(canonical(row) for row in rows) + "\n", encoding="utf-8")
    elif fault == "reservation":
        (directory / "native-reservation.json").write_bytes(b"tampered reservation")
    elif fault == "usage":
        service.headless_evaluator_port.ledger["known_main_tokens"] = 9
        service.headless_evaluator_port.ledger_path.write_text(canonical(service.headless_evaluator_port.ledger), encoding="utf-8")
    else:
        journal.write_text(journal.read_text(encoding="utf-8") * 2, encoding="utf-8")
    with pytest.raises(ContractError):
        closure.finalize(service=service, panel=panel, journal_path=journal, nonce="n", receipt_digests=[receipt.content_hash])


def test_worker_finalization_is_idempotent_and_closes_scoring(tmp_path, monkeypatch):
    service, panel, journal, receipt, _ = prepared(tmp_path, monkeypatch)
    expected = service._authority.issue({"schema": closure._SCHEMA, "nonce": "n", "receipt_digests": [receipt.content_hash]})
    monkeypatch.setattr(closure, "finalize", lambda **kwargs: expected)
    worker = ScorerWorker(service=service, panel=panel, journal_path=journal)
    request = {"schema": "headless-evaluator-finalize-request-v1", "nonce": "n",
               "receipt_digests": [receipt.content_hash], "evaluator_provider": service.evaluator_provider}
    assert worker.respond(request)["closure"] == expected.data()
    assert worker.respond(request)["closure"] == expected.data()
    restarted = ScorerWorker(service=service, panel=panel, journal_path=journal)
    assert restarted.respond(request)["closure"] == expected.data()
    with pytest.raises(ContractError):
        restarted.respond({"schema": "linked-scorer-process-request-v1"})


def native_prepared(tmp_path, monkeypatch):
    """Run the real frozen endpoint through the synthetic OS/HTTP transport once."""
    port = native_port(tmp_path / "native", max_calls=2, max_tokens=1000)
    calls, gets = _install_native(monkeypatch, port)
    native_endpoint(port)(native_request())
    row = port.ledger["calls"][0]
    request_path = Path(row["request"]["path"])
    request = FrozenRecord.from_dict(json.loads(request_path.read_text(encoding="utf-8"))).data()
    output = FrozenRecord.from_dict(json.loads((request_path.parent / "response.private.json").read_text(encoding="utf-8")))
    config = ScorerConfig.create(benchmark="blade", evaluator_id="fixture", version="v1", rubric_digest=port.rubric_digest)
    authority = LinkedExecutionAuthority("scorer", b"s" * 32)
    key = ("native",) * 7
    panel = SimpleNamespace(digest="p" * 64, cells=(SimpleNamespace(key=key, scorer_digest=config.digest,
        identity=SimpleNamespace(benchmark="blade")),))
    evidence = {"evaluator_id": "fixture", "evaluator_version": "v1", "rubric_digest": port.rubric_digest,
        "prompt_digest": request["prompt_digest"], "schema_digest": request["schema_digest"],
        "reference_digest": request["reference_digest"], "output_digest": output.content_hash}
    receipt = authority.issue({"schema": "combination-adapted-scored-cell-v1", "cell_key": list(key),
        "panel_digest": panel.digest, "scorer_digest": config.digest, "scorer_config_digest": config.digest,
        "benchmark": "blade", "evaluator_evidence": evidence})
    journal = tmp_path / "worker.jsonl"
    reserve = {"schema": "linked-scorer-process-journal-v1", "cell_key": list(key), "request_id": "native",
        "request_digest": "d" * 64, "status": "reserved"}
    journal.write_text(canonical(reserve) + "\n" + canonical(reserve | {"status": "succeeded", "receipt": receipt.data()}) + "\n", encoding="utf-8")
    service = SimpleNamespace(headless_evaluator_port=port, evaluator_provider=closure.descriptor(port),
        _authority=authority, config=config)
    return service, panel, journal, receipt, calls, gets


def test_native_endpoint_worker_finalization_replays_raw_and_survives_restart(tmp_path, monkeypatch):
    service, panel, journal, receipt, calls, gets = native_prepared(tmp_path, monkeypatch)
    worker = ScorerWorker(service=service, panel=panel, journal_path=journal)
    request = {"schema": "headless-evaluator-finalize-request-v1", "nonce": "native-final",
        "receipt_digests": [receipt.content_hash], "evaluator_provider": service.evaluator_provider}
    response = worker.respond(request)
    assert len(calls) == 1 and len(gets) == 6
    verified = closure.verify_closure(FrozenRecord.from_dict(response["closure"]), authority_keys={"scorer": b"s" * 32},
        panel=panel, config=service.config, provider=service.evaluator_provider, nonce="native-final",
        receipt_digests=[receipt.content_hash]).data()
    assert verified["ledger_sha256"] and verified["calls"][0]["reservation_sha256"]
    restarted = ScorerWorker(service=service, panel=panel, journal_path=journal)
    assert restarted.respond(request) == response
    with pytest.raises(ContractError):
        restarted.respond({"schema": "linked-scorer-process-request-v1"})
    assert len(calls) == 1 and len(gets) == 6


@pytest.mark.parametrize("restart", [False, True])
@pytest.mark.parametrize("fault", ["response", "reservation", "journal"])
def test_successful_closure_rereads_originals_on_every_later_read(tmp_path, monkeypatch, restart, fault):
    service, panel, journal, receipt, calls, gets = native_prepared(tmp_path, monkeypatch)
    worker = ScorerWorker(service=service, panel=panel, journal_path=journal)
    request = {"schema": "headless-evaluator-finalize-request-v1", "nonce": "sealed-final",
        "receipt_digests": [receipt.content_hash], "evaluator_provider": service.evaluator_provider}
    worker.respond(request)
    if restart:
        worker = ScorerWorker(service=service, panel=panel, journal_path=journal)
    directory = Path(service.headless_evaluator_port.ledger['calls'][0]['request']['path']).parent
    if fault == "journal":
        lines = journal.read_text(encoding="utf-8").splitlines()
        journal.write_text("\n".join([*lines, lines[-1]]) + "\n", encoding="utf-8")
    else:
        path = directory / ("response.private.json" if fault == "response" else "native-reservation.json")
        path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ContractError):
        worker.respond(request)
    with pytest.raises(ContractError):
        worker.respond({"schema": "linked-scorer-process-request-v1"})
    assert len(calls) == 1 and len(gets) == 6


def test_successful_closure_rejects_deleted_finalization_history(tmp_path, monkeypatch):
    service, panel, journal, receipt, calls, gets = native_prepared(tmp_path, monkeypatch)
    worker = ScorerWorker(service=service, panel=panel, journal_path=journal)
    request = {"schema": "headless-evaluator-finalize-request-v1", "nonce": "sealed-final",
        "receipt_digests": [receipt.content_hash], "evaluator_provider": service.evaluator_provider}
    worker.respond(request)
    worker.finalization_path.unlink()
    with pytest.raises(ContractError, match="history changed"):
        worker.respond(request)
    assert len(calls) == 1 and len(gets) == 6


@pytest.mark.parametrize("fault", ["response", "reservation", "ledger"])
def test_native_finalization_rejects_tamper_and_durably_closes_worker(tmp_path, monkeypatch, fault):
    service, panel, journal, receipt, calls, gets = native_prepared(tmp_path, monkeypatch)
    row = service.headless_evaluator_port.ledger["calls"][0]
    directory = Path(row["request"]["path"]).parent
    if fault == "response":
        path = directory / "response.private.json"; path.write_bytes(path.read_bytes() + b"\n")
    elif fault == "reservation":
        path = directory / "native-reservation.json"; path.write_bytes(path.read_bytes() + b"tamper")
    else:
        service.headless_evaluator_port.ledger["known_main_tokens"] += 1
        service.headless_evaluator_port.ledger_path.write_text(canonical(service.headless_evaluator_port.ledger), encoding="utf-8")
    worker = ScorerWorker(service=service, panel=panel, journal_path=journal)
    request = {"schema": "headless-evaluator-finalize-request-v1", "nonce": "native-final",
        "receipt_digests": [receipt.content_hash], "evaluator_provider": service.evaluator_provider}
    with pytest.raises(ContractError):
        worker.respond(request)
    restarted = ScorerWorker(service=service, panel=panel, journal_path=journal)
    with pytest.raises(ContractError):
        restarted.respond(request)
    with pytest.raises(ContractError):
        restarted.respond({"schema": "linked-scorer-process-request-v1"})
    assert len(calls) == 1 and len(gets) == 6
