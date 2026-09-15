"""M7xM8 native scheduler/evaluator closure seam; synthetic peers only."""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from evaluation.modular.scorer_process import CombinationScorerProcessClient, headless_evaluator_descriptor, serialize_combination_panel
from evaluation.modular.scoring_service import ScorerConfig
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.exploration_scheduler_controller import FrozenExplorationSchedulerTrainConfig, compile_exploration_scheduler_train_panel, run_exploration_scheduler_train_panel
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.ordinary_provider import finalize_headless_evaluator_gate, verify_retained_headless_evaluator_gate
from research_loop.ontology import ContractError, canonical
from test_remaining_prospective_train_sources import prepare_controller
from test_headless_evaluator_factory import native_spec
from tests.helpers.headless_train_provider import headless_train_provider
from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from test_headless_admission_evaluator_gate import _score, _signed_closure


FAMILY = 'exploration-scheduler'


def _response(request):
    body = request.data()
    if body['slot'] == 'final_answer':
        return FrozenRecord.from_dict({'objective_digest': body['module_context']['required_objective_digest'],
            'outcome': 'unknown', 'evidence_ids': [], 'conclusion': 'Synthetic bound output.', 'programme_complete': False})
    values = [float(row['stdout']) for row in body['module_context']['joint_mechanism']['material']['observations']]
    return FrozenRecord.from_dict({'analysis': 'Use only bound public outputs.', 'program': 'print(' + repr(sum(values)) + ')'})


def _native_config(setup, provider, evaluator_provider):
    body = dict(setup['config'].data())
    for name in ('model', 'effort', 'max_calls', 'max_tokens', 'schemas'):
        body.pop(name)
    body.update(schema='exploration-scheduler-train-controller-config-v4', provider=provider.configuration().data(),
        evaluator_provider=evaluator_provider,
        evaluator_usage={'schema': f'{FAMILY}-headless-evaluator-usage-declaration-v1',
            'provider_kind': evaluator_provider['kind'], 'usage_contract': f'grok-headless-{FAMILY}-usage-v1',
            'evaluator_config_digest': evaluator_provider['configuration_digest']},
        allocation={**body['allocation'], 'scorer_token_accounting': 'signed_headless_main_unknown_title'})
    return FrozenExplorationSchedulerTrainConfig(FrozenRecord.from_dict(body))


def _server(root, panel, setup, scorer, evaluator):
    execution_key, scorer_key = root / 'execution.key', root / 'scorer.key'
    execution, scorer_authority = setup['module'].EXECUTION, setup['module'].SCORER
    execution_key.write_bytes(execution.key); scorer_key.write_bytes(scorer_authority.key)
    body = {'schema': 'exploration-scheduler-scorer-process-config-v1',
        'panel': serialize_combination_panel(panel, exploration_scheduler=True),
        'scorer_config': scorer.record.data(), 'scorer_config_digest': scorer.digest,
        'train_reference_store': {'root': str(setup['store'].resolve()), 'manifest_sha256': setup['manifest_sha'],
            'inventory_digest': panel.cells[0].identity.dataset_version, 'split_digest': panel.split_digest},
        'task_handles': setup['handles'], 'execution_authority_key_files': {execution.authority_id: str(execution_key)},
        'scorer_authority': {'id': scorer_authority.authority_id, 'key_file': str(scorer_key)}, 'evaluator': evaluator}
    path = root / 'server.json'; path.write_text(canonical(body), encoding='utf-8'); return path


def test_native_scheduler_closes_eight_evaluator_receipts(tmp_path, monkeypatch):
    setup = prepare_controller(tmp_path / 'fixture', 'scheduler'); original = setup['config'].data()
    provider, calls, _ = headless_train_provider(tmp_path / 'solver', monkeypatch, schemas=original['schemas'],
        max_calls=16, response=_response)
    with monkeypatch.context() as patch:
        evaluator, _, _ = native_spec(tmp_path / 'evaluator-source', patch)
    scorer = ScorerConfig(FrozenRecord.from_dict(original['scorer'])); root = tmp_path / 'evaluator'; root.mkdir(); (root/'home').mkdir()
    evaluator.update(max_calls=8, max_tokens=800, evaluator_id=scorer.record.data()['evaluator_id'],
        evaluator_version=scorer.record.data()['version'], work_root=str(root/'ledger'), private_home=str(root/'home'),
        private_profile=str(root/'profile'), public_cwd=str(root/'context'))
    descriptor = headless_evaluator_descriptor(evaluator); evaluator_provider = {'kind': 'grok-headless-frozen-evaluator-v1', 'configuration_digest': descriptor['configuration_digest']}
    config = _native_config(setup, provider, evaluator_provider); compiled = compile_exploration_scheduler_train_panel(config, setup['packets'])
    server = _server(tmp_path, compiled.panel, setup, scorer, evaluator); helper = Path(__file__).parent/'helpers'/'headless_scheduler_evaluator_process.py'
    execution, scorer_authority = setup['module'].EXECUTION, setup['module'].SCORER
    with ExitStack() as stack:
        client = CombinationScorerProcessClient(panel=compiled.panel, config=scorer, exploration_scheduler=True,
            evaluator_provider=evaluator_provider, command=[sys.executable, str(helper), '--config', str(server),
                '--config-sha256', hashlib.sha256(server.read_bytes()).hexdigest(), '--journal', str(tmp_path/'worker.jsonl')],
            journal_path=tmp_path/'client.jsonl', task_handle_bindings=config.data()['scorer_handle_bindings'],
            execution_authority_keys={execution.authority_id: execution.key}, scorer_authority_keys={scorer_authority.authority_id: scorer_authority.key},
            environment={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        stack.callback(client.close)
        result = run_exploration_scheduler_train_panel(config, custody=None, prospective_exporter=setup['exporter'],
            snapshot_root=Path(setup['exporter'].config['snapshot_root']), export_root=setup['exporter'].output_root,
            run_root=tmp_path/'run', model=provider, audit_verifier=AuditVerifier({'a': b'a'*32, 'b': b'b'*32}),
            execution_authority=execution, scoring_service=client, scorer_authority_keys={scorer_authority.authority_id: scorer_authority.key})
    gate = result.receipt.data()['evaluator_final_verification']
    assert len(calls) == 16 and len(result.scores) == 8 and gate['score_eligible'] is True
    assert result.receipt.data()['eligible_scored_cells'] == 8 and result.receipt.data()['status'] == 'estimated'
    assert all(row.data()['status'] == 'succeeded' for row in result.attempts)
    assert gate['ordered_receipt_digests'] == [score.receipt.content_hash for score in result.scores]
    assert gate['closure']['body']['scope']['unscored_cell_count'] == 0
    assert gate['closure']['body']['evaluator_provider'] == evaluator_provider
    assert gate['closure']['body']['scorer_config_digest'] == scorer.digest
    assert gate['known_headless_main_tokens'] == 80
    assert gate['title_and_all_opportunity_settlement'] == 'unknown'
    assert len(__import__('json').loads((root / 'ledger.json').read_text(encoding='utf-8'))['calls']) == 8


def test_evaluator_descriptor_mismatch_rejects_before_export_or_model(tmp_path, monkeypatch):
    setup = prepare_controller(tmp_path / 'fixture', 'scheduler'); original = setup['config'].data()
    provider, calls, _ = headless_train_provider(tmp_path / 'solver', monkeypatch, schemas=original['schemas'], max_calls=16, response=_response)
    provider_descriptor = {'kind': 'grok-headless-frozen-evaluator-v1', 'configuration_digest': 'a' * 64}
    config = _native_config(setup, provider, provider_descriptor)
    execution, scorer_authority = setup['module'].EXECUTION, setup['module'].SCORER
    class Service:
        panel = compile_exploration_scheduler_train_panel(config, setup['packets']).panel
        evaluator_provider = {'kind': 'grok-headless-frozen-evaluator-v1', 'configuration_digest': 'b' * 64}
    with pytest.raises(ContractError, match='declaration disagree'):
        run_exploration_scheduler_train_panel(config, custody=None, prospective_exporter=setup['exporter'],
            snapshot_root=Path(setup['exporter'].config['snapshot_root']), export_root=setup['exporter'].output_root,
            run_root=tmp_path/'run', model=provider, audit_verifier=AuditVerifier({'a': b'a'*32, 'b': b'b'*32}),
            execution_authority=execution, scoring_service=Service(), scorer_authority_keys={scorer_authority.authority_id: scorer_authority.key})
    assert calls == [] and not setup['exporter'].output_root.exists()


def test_signed_tampered_final_closure_keeps_all_eight_historical_scores_ineligible():
    """Adapter-only final-gate check; the full controller path is covered above.

    This consumes a genuinely signed but provider-mismatched closure.  It does
    not start a solver, evaluator worker, export, or controller grid.
    """
    authority = LinkedExecutionAuthority('scheduler-scorer', b's' * 32)
    cells = tuple(SimpleNamespace(key=('bench' + str(index), 'cell' + str(index))) for index in range(8))
    panel = SimpleNamespace(digest='e' * 64, cells=cells)
    scores = tuple(_score(cell.key, format(index + 1, 'x')) for index, cell in enumerate(cells))
    config = ScorerConfig.create(benchmark='core_pair', evaluator_id='synthetic', version='v1', rubric_digest='c' * 64)
    provider = {'kind': 'grok-headless-frozen-evaluator-v1', 'configuration_digest': 'b' * 64}
    closure = _signed_closure(authority=authority, panel=panel, config=config, scores=scores,
        provider={**provider, 'configuration_digest': 'a' * 64})
    class Service:
        def __init__(self): self.config = config; self.calls = 0
        def finalize_headless_evaluator(self, *, receipts):
            self.calls += 1; assert tuple(receipts) == scores; return closure
    captured = []; service = Service()
    gate = finalize_headless_evaluator_gate(binding={'evaluator_usage': {
        'schema': f'{FAMILY}-headless-evaluator-usage-declaration-v1', 'provider_kind': provider['kind'],
        'usage_contract': f'grok-headless-{FAMILY}-usage-v1', 'evaluator_config_digest': provider['configuration_digest']},
        'evaluator_provider': provider}, family=FAMILY, service=service, panel=panel, scores=scores,
        scorer_authority_keys={authority.authority_id: authority.key}, scorer_config=config,
        capture=lambda value: captured.append(dict(value)))
    assert service.calls == 1 and len(scores) == 8 and gate['score_eligible'] is False
    assert gate['closure'] == closure.data() and gate['failure_reason'] == 'closure_verification_failed'
    assert captured[0]['closure'] == closure.data() and captured[-1]['score_eligible'] is False


def test_return_readback_rejects_changed_retained_signed_gate(tmp_path):
    """Focused return-boundary readback; no controller or provider is started."""
    authority = LinkedExecutionAuthority('scheduler-scorer', b's' * 32)
    cells = tuple(SimpleNamespace(key=('bench' + str(index), 'cell' + str(index))) for index in range(8))
    panel = SimpleNamespace(digest='e' * 64, cells=cells)
    scores = tuple(_score(cell.key, format(index + 1, 'x')) for index, cell in enumerate(cells))
    config = ScorerConfig.create(benchmark='core_pair', evaluator_id='synthetic', version='v1', rubric_digest='c' * 64)
    provider = {'kind': 'grok-headless-frozen-evaluator-v1', 'configuration_digest': 'b' * 64}
    closure = _signed_closure(authority=authority, panel=panel, config=config, scores=scores, provider=provider)
    gate = {'score_eligible': True, 'closure': closure.data()}
    path = tmp_path / 'controller-attempt.json'
    path.write_text(json.dumps({'evaluator_final_verification': {**gate, 'score_eligible': False}}), encoding='utf-8')
    with pytest.raises(ContractError, match='retained evaluator final gate differs'):
        verify_retained_headless_evaluator_gate(path, gate=gate, binding={'evaluator_provider': provider}, panel=panel,
            scores=scores, scorer_authority_keys={authority.authority_id: authority.key}, scorer_config=config)
