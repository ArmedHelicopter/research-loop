"""Admission v4 native controller seam: 16 cells, 48 synthetic MAIN calls, real stdio closure."""
from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import sys

from evaluation.modular.scorer_process import CombinationScorerProcessClient, headless_evaluator_descriptor, serialize_combination_panel
from evaluation.modular.scoring_service import ScorerConfig
from research_loop.modular.admission_prediction_exploration_controller import (
    FrozenAdmissionPredictionExplorationTrainConfig, compile_admission_prediction_exploration_train_panels,
    run_admission_prediction_exploration_train_panels,
)
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import canonical
from test_admission_prediction_exploration_controller import EXECUTION, SCORER, IMAGE, model, prepare
from test_headless_evaluator_factory import native_spec
from tests.helpers.headless_train_provider import headless_train_provider


FAMILY = 'admission-prediction-exploration'


def _server(root, panel, setup, scorer, evaluator):
    execution_key, scorer_key = root / 'execution.key', root / 'score.key'
    execution_key.write_bytes(EXECUTION.key); scorer_key.write_bytes(SCORER.key)
    body = {'schema': 'admission-prediction-exploration-scorer-process-config-v1',
        'panel': serialize_combination_panel(panel, admission_prediction_exploration=True),
        'scorer_config': scorer.record.data(), 'scorer_config_digest': scorer.digest,
        'train_reference_store': {'root': str(setup['store'].resolve()), 'manifest_sha256': setup['manifest_sha'],
            'inventory_digest': panel.cells[0].identity.dataset_version, 'split_digest': panel.split_digest},
        'task_handles': setup['handles'],
        'execution_authority_key_files': {EXECUTION.authority_id: str(execution_key)},
        'scorer_authority': {'id': SCORER.authority_id, 'key_file': str(scorer_key)}, 'evaluator': evaluator}
    path = root / 'scorer-server.json'; path.write_text(canonical(body), encoding='utf-8')
    return path


def test_native_v4_controller_runs_16_cells_and_closes_the_declared_evaluator(tmp_path, monkeypatch):
    setup = prepare(tmp_path / 'fixture')
    body = setup['config'].data()
    seen = []
    provider, calls, gets = headless_train_provider(tmp_path / 'solver', monkeypatch, schemas=body['schemas'],
        max_calls=48, response=model(seen), wrapped=True)
    with monkeypatch.context() as evaluator_patch:
        evaluator, _, _ = native_spec(tmp_path / 'evaluator-source', evaluator_patch)
    scorer = ScorerConfig(FrozenRecord.from_dict(body['scorer']))
    evaluator_root = tmp_path / 'worker-evaluator'; evaluator_root.mkdir(); (evaluator_root / 'home').mkdir()
    evaluator.update(max_calls=16, max_tokens=1600, evaluator_id=scorer.record.data()['evaluator_id'],
        evaluator_version=scorer.record.data()['version'], work_root=str(evaluator_root / 'ledger'),
        private_home=str(evaluator_root / 'home'), private_profile=str(evaluator_root / 'profile'),
        public_cwd=str(evaluator_root / 'context'))
    descriptor = headless_evaluator_descriptor(evaluator)
    evaluator_provider = {'kind': 'grok-headless-frozen-evaluator-v1',
        'configuration_digest': descriptor['configuration_digest']}
    evaluator_usage = {'schema': f'{FAMILY}-headless-evaluator-usage-declaration-v1',
        'provider_kind': evaluator_provider['kind'], 'usage_contract': f'grok-headless-{FAMILY}-usage-v1',
        'evaluator_config_digest': evaluator_provider['configuration_digest']}
    native = dict(body)
    for name in ('model', 'effort', 'max_calls', 'max_tokens', 'schemas'):
        native.pop(name)
    native.update(schema='admission-prediction-exploration-combination-train-config-v4',
        provider=provider.configuration().data(), evaluator_usage=evaluator_usage, evaluator_provider=evaluator_provider)
    config = FrozenAdmissionPredictionExplorationTrainConfig(FrozenRecord.from_dict(native))
    compiled = compile_admission_prediction_exploration_train_panels(config, setup['packets'])
    server = _server(tmp_path, compiled.panels[0], setup, scorer, evaluator)
    helper = Path(__file__).parent / 'helpers' / 'headless_admission_evaluator_process.py'
    with ExitStack() as stack:
        client = CombinationScorerProcessClient(panel=compiled.panels[0], config=scorer,
            admission_prediction_exploration=True, evaluator_provider=evaluator_provider,
            command=[sys.executable, str(helper.resolve()), '--config', str(server.resolve()),
                '--config-sha256', hashlib.sha256(server.read_bytes()).hexdigest(),
                '--journal', str((tmp_path / 'worker.jsonl').resolve())],
            journal_path=tmp_path / 'client.jsonl',
            task_handle_bindings=native['scorer_handle_bindings'],
            execution_authority_keys={EXECUTION.authority_id: EXECUTION.key},
            scorer_authority_keys={SCORER.authority_id: SCORER.key},
            environment={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        stack.callback(client.close)
        result = run_admission_prediction_exploration_train_panels(config, custody=None,
            prospective_exporter=setup['exporter'], snapshot_root=Path(setup['exporter'].config['snapshot_root']),
            export_root=setup['exporter'].output_root, run_root=tmp_path / 'run', model=provider,
            audit_verifier=AuditVerifier({'a': b'a' * 32, 'b': b'b' * 32}),
            source_verifiers=setup['verifiers'], scoring_services={compiled.panels[0].obligation_id: client},
            execution_authority=EXECUTION, scorer_authority_keys={SCORER.authority_id: SCORER.key})
    gate = result.receipt.data()['evaluator_final_verification']
    assert len(calls) == 48 and len(gets) == 6 * 48 and len(result.scores) == 16
    assert gate['score_eligible'] is True and gate['closure'] is not None
    assert gate['ordered_receipt_digests'] == [score.receipt.content_hash for score in result.scores]
    assert gate['known_headless_main_tokens'] == 160 and gate['title_and_all_opportunity_settlement'] == 'unknown'
    assert result.receipt.data()['eligible_scored_cells'] == 16

