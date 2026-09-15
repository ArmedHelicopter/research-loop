"""Full v6 factorial through solver, Docker, private scorer process and final closure."""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

from evaluation.modular.scorer_process import CombinationScorerProcessClient, _production_evaluator, serialize_combination_panel
from evaluation.modular.scoring_service import ScorerConfig
from research_loop.modular import combination_train_controller as controller
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError, canonical
from test_headless_m4_m5_controller import setup_headless
from test_headless_evaluator_factory import native_spec


def test_v6_preflight_rejects_undeclared_legacy_scorer_before_solver_calls(tmp_path, monkeypatch):
    from test_combination_prospective_train_source import processes
    setup, solver, calls, gets = setup_headless(tmp_path, monkeypatch)
    body = setup['config'].data()
    body.update(schema='m4-m5-train-controller-config-v6', evaluator_provider={
        'kind': 'grok-headless-frozen-evaluator-v1', 'configuration_digest': 'a' * 64})
    body['allocation']['scorer_token_accounting'] = 'signed_headless_main_unknown_title'
    setup['config'] = controller.FrozenM4M5TrainConfig(FrozenRecord.from_dict(body))
    setup['compiled'] = controller.compile_m4_m5_train_panel(setup['config'], setup['packets'])
    with ExitStack() as stack:
        service = processes(setup, stack)
        with pytest.raises(ContractError, match='frozen headless evaluator process descriptor'):
            controller._service_preflight(setup['config'], solver, service, setup['module'].EXECUTION,
                {setup['module'].SCORER.authority_id: setup['module'].SCORER.key})
    assert not calls and not gets and not (tmp_path / 'worker-0.jsonl').exists()


def prepare(root, patch, stack):
    setup, solver, calls, gets = setup_headless(root, patch)
    body = setup['config'].data()
    with pytest.MonkeyPatch.context() as evaluator_patch:
        spec, _, _ = native_spec(root / 'evaluator', evaluator_patch)
    spec.update(max_calls=8, max_tokens=8 * 131072,
        evaluator_id=body['scorer']['evaluator_id'], evaluator_version=body['scorer']['version'])
    port = _production_evaluator(spec)
    provider = {'kind': 'grok-headless-frozen-evaluator-v1', 'configuration_digest': port._config_record.content_hash}
    body.update(schema='m4-m5-train-controller-config-v6', evaluator_provider=provider)
    body['allocation']['scorer_token_accounting'] = 'signed_headless_main_unknown_title'
    setup['config'] = controller.FrozenM4M5TrainConfig(FrozenRecord.from_dict(body))
    setup['compiled'] = controller.compile_m4_m5_train_panel(setup['config'], setup['packets'])
    panel = setup['compiled'].panel
    rubric = ScorerConfig(FrozenRecord.from_dict(body['scorer']))
    executor, scorer = setup['module'].EXECUTION, setup['module'].SCORER
    (root / 'executor.key').write_bytes(executor.key)
    (root / 'scorer.key').write_bytes(scorer.key)
    server = {'schema': 'combination-scorer-process-config-v1', 'panel': serialize_combination_panel(panel),
        'scorer_config': rubric.record.data(), 'scorer_config_digest': rubric.digest,
        'train_reference_store': {'root': str(setup['store'].resolve()), 'manifest_sha256': setup['manifest_sha'],
            'inventory_digest': panel.cells[0].identity.dataset_version, 'split_digest': panel.split_digest},
        'task_handles': setup['handles'], 'execution_authority_key_files': {executor.authority_id: str(root / 'executor.key')},
        'scorer_authority': {'id': scorer.authority_id, 'key_file': str(root / 'scorer.key')}, 'evaluator': spec}
    path = root / 'scorer-server.json'; path.write_text(canonical(server), encoding='utf-8')
    helper = Path(__file__).parent / 'helpers/headless_evaluator_process.py'
    service = CombinationScorerProcessClient(panel=panel, config=rubric,
        command=[sys.executable, str(helper), '--config', str(path), '--config-sha256', hashlib.sha256(path.read_bytes()).hexdigest(),
                 '--journal', str(root / 'worker.jsonl')], journal_path=root / 'client.jsonl',
        task_handle_bindings=body['scorer_handle_bindings'], execution_authority_keys={executor.authority_id: executor.key},
        scorer_authority_keys={scorer.authority_id: scorer.key}, evaluator_provider=provider,
        environment={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    stack.callback(service.close)
    return setup, solver, calls, gets, service, port


@pytest.mark.parametrize('late_tamper', [False, True])
def test_full_v6_factorial_closes_private_evaluator_or_retains_failed_history(tmp_path, monkeypatch, late_tamper):
    with ExitStack() as stack:
        setup, solver, calls, gets, service, evaluator = prepare(tmp_path, monkeypatch, stack)
        scored = []; original = service.score_combination
        def score(**kwargs):
            result = original(**kwargs); scored.append(result)
            if late_tamper and len(scored) == 8:
                first = next(evaluator.calls_root.glob('0001-*/response.private.json'))
                first.write_bytes(first.read_bytes() + b'\n')
            return result
        monkeypatch.setattr(service, 'score_combination', score)
        result = controller.run_m4_m5_train_panel(setup['config'], custody=None, prospective_exporter=setup['exporter'],
            snapshot_root=Path(setup['exporter'].config['snapshot_root']), export_root=setup['exporter'].output_root,
            run_root=tmp_path / 'run', model=solver, audit_verifier=AuditVerifier({'a': b'a' * 32, 'b': b'b' * 32}),
            execution_authority=setup['module'].EXECUTION, scoring_service=service,
            scorer_authority_keys={setup['module'].SCORER.authority_id: setup['module'].SCORER.key})
        receipt = result.receipt.data()
        assert len(calls) == 40 and len(gets) == 240 and len(result.scores) == len(scored) == 8
        assert receipt['schema'] == 'm4-m5-train-controller-receipt-v3'
        assert receipt['native_final_verification']['score_eligible'] is True
        assert receipt['evaluator_final_verification']['score_eligible'] is (not late_tamper)
        assert receipt['eligible_scored_cells'] == (0 if late_tamper else 8)
        assert receipt['status'] == ('inconclusive' if late_tamper else 'estimated')
        assert not receipt['validation_opened'] and receipt['pruned_cells'] == []
        assert 'PRIVATE-REFERENCE-SENTINEL' not in (tmp_path / 'client.jsonl').read_text(encoding='utf-8')
        if not late_tamper:
            body = receipt['evaluator_final_verification']['receipt']['body']
            assert body['known_main_tokens'] == 80 and body['scope']['unscored_cell_count'] == 0
            assert len(body['calls']) == 8
            with pytest.raises(ContractError):
                service.score_combination(panel=setup['compiled'].panel, cell=setup['compiled'].panel.cells[0],
                    score_input=FrozenRecord.from_dict(result.attempts[0].data()['score_input']))
    ledger = json.loads(evaluator.ledger_path.read_bytes())
    assert len(ledger['calls']) == 8 and ledger['known_main_tokens'] == 80
