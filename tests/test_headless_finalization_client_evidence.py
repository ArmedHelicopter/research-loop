"""Actual stdio observation retention; synthetic signatures, no evaluator calls.

The fixture mounts the finalization method onto a real pipe without claiming
to test the startup handshake or native evaluator. Full controller tests cover
those existing seams separately.
"""
import hashlib
from itertools import chain, count
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

import evaluation.modular.scorer_process as process
from evaluation.modular.headless_evaluator_closure import finalize
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.panel_receipts import ScientificScorerReceipt
from research_loop.ontology import ContractError, canonical
from test_headless_evaluator_closure import prepared


def client_fixture(tmp_path, monkeypatch, fault):
    service, panel, journal, receipt, _ = prepared(tmp_path, monkeypatch)
    closure = finalize(service=service, panel=panel, journal_path=journal,
        nonce="n", receipt_digests=[receipt.content_hash])
    body = closure.data()
    if fault == "signature":
        body["mac"] = "0" * 64
    response = {"schema": "headless-evaluator-finalize-response-v1",
        "nonce": "foreign" if fault == "nonce" else "n", "closure": body}
    # CRLF is intentionally translated by the existing text-mode pipe. The
    # retained UTF-8 text must match what the consumer parsed, not those bytes.
    raw = ("{broken 中文" if fault == "malformed" else canonical(response)) + "\r\n"
    reply = tmp_path / "synthetic-reply.txt"
    reply.write_bytes(raw.encode("utf-8"))
    program = ("import pathlib,sys\nraw=pathlib.Path(sys.argv[1]).read_bytes()\n"
               "for line in sys.stdin:\n sys.stdout.buffer.write(raw);sys.stdout.buffer.flush()\n")
    client = process.CombinationScorerProcessClient.__new__(process.CombinationScorerProcessClient)
    client.panel, client.cells, client.config = panel, {cell.key: cell for cell in panel.cells}, service.config
    client.evaluator_provider, client.final_closure = service.evaluator_provider, None
    client._scorer_authority_keys = {"scorer": b"s" * 32}
    client.journal_path = tmp_path / "client.jsonl"
    client.response_timeout_seconds = 10
    client.process = subprocess.Popen([sys.executable, "-u", "-c", program, str(reply)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    client.input, client.output = client.process.stdin, client.process.stdout
    identifiers = chain(("n",), (f"attempt-{index}" for index in count()))
    monkeypatch.setattr(process.uuid, "uuid4", lambda: SimpleNamespace(hex=next(identifiers)))
    return client, ScientificScorerReceipt(panel.cells[0].key, receipt), closure, raw.replace("\r\n", "\n")


def observations(client):
    path = Path(str(client.journal_path) + ".headless-evaluator-client.jsonl")
    return [row['event'] for row in process.read_headless_client_observations(path)]


@pytest.mark.parametrize("fault", ["malformed", "signature", "nonce", "success"])
def test_received_text_is_preserved_before_interpretation(tmp_path, monkeypatch, fault):
    client, receipt, expected, raw = client_fixture(tmp_path, monkeypatch, fault)
    try:
        if fault == "success":
            assert client.finalize_headless_evaluator(receipts=(receipt,)) == expected
            # A repeated read still crosses the pipe and creates a new attempt.
            assert client.finalize_headless_evaluator(receipts=(receipt,)) == expected
        else:
            with pytest.raises(ContractError):
                client.finalize_headless_evaluator(receipts=(receipt,))
            assert client.final_closure is None
    finally:
        client.close()
    assert client.process.returncode == 0
    rows = observations(client)
    terminal = "authenticated" if fault == "success" else "rejected"
    assert [row["status"] for row in rows] == ["requested", "response_received", terminal] * (2 if fault == "success" else 1)
    for offset in range(0, len(rows), 3):
        request, response, result = rows[offset:offset + 3]
        assert {row["attempt_id"] for row in (request, response, result)} == {request["attempt_id"]}
        assert response["response_text"] == raw
        assert response["response_sha256"] == hashlib.sha256(raw.encode("utf-8")).hexdigest()
        assert response["response_utf8_bytes"] == len(raw.encode("utf-8"))
        assert response["text_representation"] == "python_text_write_input_and_decoded_read_output"
        assert request["request_sha256"] == hashlib.sha256(request["request_text"].encode("utf-8")).hexdigest()
        assert request["producer_source_sha256"] == hashlib.sha256(Path(process.__file__).read_bytes()).hexdigest()
        assert result["response_sha256"] == response["response_sha256"]
        if fault != "success":
            assert result["score_eligible"] is False and result["error_type"]
    if fault == "success":
        assert rows[0]["attempt_id"] != rows[3]["attempt_id"]
        assert rows[2]["closure_digest"] == rows[5]["closure_digest"] == expected.content_hash


@pytest.mark.parametrize("failed_status", ["requested", "response_received", "authenticated"])
def test_evidence_write_failure_cannot_return_an_authenticated_closure(tmp_path, monkeypatch, failed_status):
    client, receipt, _, _ = client_fixture(tmp_path, monkeypatch, "success")
    original_append = process._append
    writes = []
    def write(path, row):
        if str(path).endswith(".headless-evaluator-client.jsonl"):
            writes.append(row['event']["status"])
            if row['event']["status"] == failed_status:
                raise OSError("synthetic evidence storage failure")
        return original_append(path, row)
    monkeypatch.setattr(process, "_append", write)
    try:
        with pytest.raises((OSError, ContractError)):
            client.finalize_headless_evaluator(receipts=(receipt,))
        assert client.final_closure is None
    finally:
        client.close()
    if failed_status == "requested":
        assert writes == ["requested"]
        assert not Path(str(client.journal_path) + ".headless-evaluator-client.jsonl").exists()
    else:
        rows = observations(client)
        assert rows[0]["status"] == "requested"
        assert all(row["status"] != "authenticated" for row in rows)
        if failed_status == "authenticated":
            assert rows[1]["status"] == "response_received"


@pytest.mark.parametrize('fault', ['text', 'reorder', 'missing_response', 'truncated_attempt'])
def test_changed_observation_history_blocks_repeated_finalize_before_dispatch(tmp_path, monkeypatch, fault):
    client, receipt, _, _ = client_fixture(tmp_path, monkeypatch, 'success')
    try:
        client.finalize_headless_evaluator(receipts=(receipt,))
        path = Path(str(client.journal_path) + '.headless-evaluator-client.jsonl')
        rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
        if fault == 'text': rows[1]['event']['response_text'] += 'changed'
        elif fault == 'reorder': rows.reverse()
        elif fault == 'missing_response': rows.pop(1)
        else: rows = []
        path.write_text(''.join(canonical(row) + '\n' for row in rows), encoding='utf-8')
        monkeypatch.setattr(client, '_readline_bounded', lambda: pytest.fail('changed log must prevent dispatch'))
        with pytest.raises(ContractError):
            client.finalize_headless_evaluator(receipts=(receipt,))
    finally:
        client.close()


def test_rejection_log_failure_preserves_original_verification_exception(tmp_path, monkeypatch):
    client, receipt, _, raw = client_fixture(tmp_path, monkeypatch, 'signature')
    original_append = process._append
    def write(path, row):
        if str(path).endswith('.headless-evaluator-client.jsonl') and row['event']['status'] == 'rejected':
            raise OSError('synthetic terminal storage failure')
        return original_append(path, row)
    monkeypatch.setattr(process, '_append', write)
    try:
        with pytest.raises(ContractError, match='rejection observation unavailable') as failure:
            client.finalize_headless_evaluator(receipts=(receipt,))
        assert isinstance(failure.value.__cause__, ContractError)
        assert 'OSError' in str(failure.value) and 'ContractError' in str(failure.value)
        assert client.final_closure is None
        rows = observations(client)
        assert [row['status'] for row in rows] == ['requested', 'response_received']
        assert rows[-1]['response_text'] == raw
        with pytest.raises(ContractError, match='unfinished observation attempt'):
            client.finalize_headless_evaluator(receipts=(receipt,))
    finally:
        client.close()
