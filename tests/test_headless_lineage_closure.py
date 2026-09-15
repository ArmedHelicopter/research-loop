"""Native lineage closure: one signed worker cell, no account/model finalization calls."""
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import evaluation.modular.headless_evaluator_closure as closure
from evaluation.modular.lineage_combination_scoring import issue_lineage_score_input
from evaluation.modular.lineage_scorer_process import (LineageScorerProcessClient, LineageScorerProcessPool,
    LineageScorerWorker)
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.lineage_combination_driver import DESIGNS, run_lineage_combination_cell, verify_lineage_combination_cell
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError, canonical
from test_headless_lineage_evaluator import _configure_headless, _native_service
from test_lineage_combination_controller import EXECUTION, IMAGE, SCHEMAS, _model
from test_modular_train_controller import model_port


def _score_one(tmp_path, monkeypatch):
    """Drive exactly one actual synthetic OS/HTTP native evaluator opportunity."""
    compiled, sources, config_path, server = _configure_headless(tmp_path / 'headless')
    patch = pytest.MonkeyPatch()
    panel, service = _native_service(config_path, server, patch)
    cell = panel.cells[0]
    packet = next(packet for packet in compiled.packets if packet.task.content_hash == cell.task_digest)
    args = {'panel': panel, 'task': packet.task, 'scenario': compiled.scenarios[cell.key],
            'package': compiled.packages[cell.runtime_arm.content_hash], 'material': compiled.materials[cell.task_digest],
            'source_verifier': sources, 'public_inputs': {'public_csv': packet.csv_path},
            'broker': DockerExecutionBroker([tmp_path])}
    solver_calls = []
    solver = model_port(tmp_path / 'solver', monkeypatch, max_calls=4, max_tokens=1000, schemas=SCHEMAS,
                        response_factory=_model(solver_calls))
    result = run_lineage_combination_cell(cell=cell, **args, objective=FrozenRecord.from_dict({'panel_digest': panel.digest}),
        sidecar=tmp_path / 'cell', image=IMAGE, model=solver,
        audit_verifier=AuditVerifier({'a': b'a' * 32, 'b': b'b' * 32}))
    assert result.runtime.status == 'succeeded'
    verify_lineage_combination_cell(result, **args)
    score_input = issue_lineage_score_input(authority=EXECUTION, result=result, **args)
    request_id = 'lineage-closure-score'
    material = {'request_id': request_id, 'panel_digest': panel.digest, 'cell_key': list(cell.key),
                'linked_input': score_input.data()}
    request = {'schema': 'linked-scorer-process-request-v1', **material,
               'request_digest': hashlib.sha256(canonical(material).encode('utf-8')).hexdigest()}
    worker = LineageScorerWorker(service, panel, tmp_path / 'score-journal.jsonl')
    response = worker.respond(request)
    assert response['status'] == 'succeeded'
    return patch, panel, service, worker, request, response


def _final_request(service, receipt, *, nonce='lineage-closure'):
    return {'schema': 'lineage-headless-evaluator-finalize-request-v1', 'nonce': nonce,
            'receipt_digests': [FrozenRecord.from_dict(receipt).content_hash],
            'evaluator_provider': service.evaluator_provider}


def test_native_lineage_worker_closure_binds_signed_nested_primary_and_endpoint_evidence(tmp_path, monkeypatch):
    patch, panel, service, worker, score_request, scored = _score_one(tmp_path, monkeypatch)
    try:
        request = _final_request(service, scored['receipt'])
        response = worker.respond(request)
        verified = closure.verify_lineage_closure(FrozenRecord.from_dict(response['closure']),
            authority_keys={service._authority.authority_id: service._authority.key}, panel=panel, config=service.config,
            provider=service.evaluator_provider, reference_binding=service.lineage_reference_binding,
            nonce=request['nonce'], receipt_digests=request['receipt_digests']).data()
        call = verified['calls'][0]
        assert (verified['schema'] == 'headless-lineage-evaluator-closure-v1'
                and call['lineage_receipt_digest'] == request['receipt_digests'][0]
                and call['primary_receipt_digest'] and call['lineage_reference_digest']
                and verified['evaluator_usage_declaration']['evaluator_config_digest']
                and verified['evaluator_provider'] == service.evaluator_provider
                and str((Path(__file__).parents[1] / 'evaluation' / 'modular' / 'lineage_scorer_process.py').resolve()) in verified['frozen_files']
                and verified['known_main_tokens'] == service.evaluator_port.ledger['known_main_tokens']
                and verified['unknown_title_usage'] is True)
        # A replayed read has no fresh native allocation and its result must equal the original closure.
        assert worker.respond(request) == response
        assert len(service.evaluator_port.ledger['calls']) == 1
        with pytest.raises(ContractError):
            worker.respond(score_request)
    finally:
        patch.undo()


def test_lineage_closure_rereads_tamper_after_restart_and_client_verifies_response(tmp_path, monkeypatch):
    patch, panel, service, worker, score_request, scored = _score_one(tmp_path, monkeypatch)
    try:
        request = _final_request(service, scored['receipt'], nonce='restart-seal')
        response = worker.respond(request)
        # Exercise the client response verifier without a second evaluator process or any model/account call.
        client = object.__new__(LineageScorerProcessClient)
        client.evaluator_provider = service.evaluator_provider
        client.input = io.StringIO()
        client._scorer_keys = {service._authority.authority_id: service._authority.key}
        client.panel, client.config = panel, service.config
        client.reference_binding = service.lineage_reference_binding
        client._readline_bounded = lambda: canonical(response)
        client._stop_unknown_worker = lambda: None
        assert client.finalize_lineage(nonce=request['nonce'], receipt_digests=request['receipt_digests']).data() == \
            FrozenRecord.from_dict(response['closure']).data()['body']
        path = Path(service.evaluator_port.ledger['calls'][0]['request']['path']).parent / 'response.private.json'
        path.write_bytes(path.read_bytes() + b'\n')
        restarted = LineageScorerWorker(service, panel, worker.journal_path)
        with pytest.raises(ContractError):
            restarted.respond(request)
        with pytest.raises(ContractError):
            restarted.respond(score_request)
        assert len(service.evaluator_port.ledger['calls']) == 1
    finally:
        patch.undo()


def test_unknown_native_usage_rejects_lineage_closure_and_durably_stops_scoring(tmp_path):
    _, _, config_path, server = _configure_headless(tmp_path / 'headless')
    patch = pytest.MonkeyPatch()
    try:
        panel, service = _native_service(config_path, server, patch, invalid=True)
        cell = panel.cells[0]
        # This reaches the real synthetic native peer but rejects its invalid endpoint response.
        from test_headless_lineage_evaluator import _lineage_request
        with pytest.raises(ContractError):
            service._evaluator(_lineage_request(panel, service))
        worker = LineageScorerWorker(service, panel, tmp_path / 'unknown-journal.jsonl')
        usage = worker.respond({'schema': 'lineage-scorer-usage-request-v1', 'nonce': 'unknown-native'})['body']
        assert usage['usage_incomplete'] is True and usage['calls'][0]['status'] == 'unknown_or_failed'
        request = {'schema': 'lineage-headless-evaluator-finalize-request-v1', 'nonce': 'unknown-seal',
                   'receipt_digests': [], 'evaluator_provider': service.evaluator_provider}
        with pytest.raises(ContractError):
            worker.respond(request)
        restarted = LineageScorerWorker(service, panel, worker.journal_path)
        with pytest.raises(ContractError):
            restarted.respond(request)
        with pytest.raises(ContractError):
            restarted.respond({'schema': 'linked-scorer-process-request-v1'})
        assert len(service.evaluator_port.ledger['calls']) == 1
    finally:
        patch.undo()


def test_headless_pool_keeps_private_declarations_and_descriptors_per_panel():
    shared = {'manifest_sha256': 'a' * 64, 'references': {'x': 'b' * 64}, 'subjects': {'x': {'task_digest': 'c' * 64,
              'material_digest': 'd' * 64}}, 'limits': {'model': 'grok-4.6', 'effort': 'low', 'tokens_per_cell': 20,
              'timeout_seconds': 60}}
    clients = []
    for index, obligation in enumerate(DESIGNS):
        client = object.__new__(LineageScorerProcessClient)
        client.panel = SimpleNamespace(obligation_id=obligation)
        client.config = SimpleNamespace(digest='config')
        client.reference_binding = {**shared, 'evaluator_usage': {'schema': 'lineage-headless-evaluator-usage-declaration-v1',
            'provider_kind': 'grok-headless-frozen-evaluator-v1', 'usage_contract': 'grok-headless-lineage-usage-v1',
            'evaluator_config_digest': f'{index:064x}'}}
        client.evaluator_provider = {'kind': 'grok-headless-frozen-evaluator-v1', 'configuration_digest': f'{index + 10:064x}'}
        clients.append(client)
    pool = LineageScorerProcessPool(clients)
    assert pool.reference_binding == shared
    assert set(pool.evaluator_usage_by_obligation) == set(DESIGNS)
    assert len({value['evaluator_config_digest'] for value in pool.evaluator_usage_by_obligation.values()}) == len(DESIGNS)
