"""Actual complete C5 common TRAIN controller integration, synthetic-only model peer."""
import hashlib
import os
from pathlib import Path

from evaluation.modular.scorer_process import CombinationScorerProcessClient, serialize_combination_panel
from evaluation.modular.scoring_service import ScorerConfig
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.joint_train_controller import run_joint_common_train, verify_joint_common_train_run
from research_loop.ontology import canonical
from test_joint_train_runtime import executor, prepare
from test_scorer_process import _command, _store
from test_train_adapted_selection import EXEC, SCORER


def _factory(tmp_path, plan):
    """Return a real subprocess scorer factory over the normal synthetic worker."""
    store, handles, manifest = _store(tmp_path, {'tasks': {packet.task.content_hash: packet.task for packet in plan.packets}})
    expected = {key: hashlib.sha256(value.encode()).hexdigest() for key, value in handles.items()}
    assert expected == plan.data()['scorer_handle_bindings']
    execution_key = tmp_path / 'execution.key'; scorer_key = tmp_path / 'scorer.key'
    execution_key.write_bytes(EXEC.key); scorer_key.write_bytes(SCORER.key)

    def create(panel):
        config = {'schema': 'c5-common-train-scorer-process-config-v1',
                  'panel': serialize_combination_panel(panel, joint_train=True),
                  'scorer_config': plan.protocol.record.data()['scorer'],
                  'scorer_config_digest': panel.cells[0].scorer_digest,
                  'train_reference_store': {'root': str(store.resolve()), 'manifest_sha256': manifest,
                                            'inventory_digest': panel.cells[0].identity.dataset_version,
                                            'split_digest': panel.split_digest},
                  'task_handles': handles,
                  'execution_authority_key_files': {EXEC.authority_id: str(execution_key)},
                  'scorer_authority': {'id': SCORER.authority_id, 'key_file': str(scorer_key)},
                  'evaluator': {'synthetic_mode': 'normal'}}
        path = tmp_path / 'common-scorer-config.json'; path.write_text(canonical(config), encoding='utf-8')
        worker = tmp_path / 'common-scorer-worker.jsonl'; client_log = tmp_path / 'common-scorer-client.jsonl'
        command = _command(path, worker)
        command[1] = str(Path(__file__).parent / 'helpers' / 'joint_train_scorer_process_helper.py')
        return CombinationScorerProcessClient(panel=panel, config=ScorerConfig(FrozenRecord.from_dict(plan.protocol.record.data()['scorer'])),
            joint_train=True, command=command, journal_path=client_log, task_handle_bindings=expected,
            execution_authority_keys={EXEC.authority_id: EXEC.key}, scorer_authority_keys={SCORER.authority_id: SCORER.key},
            environment={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    return create


def test_complete_common_train_controller_uses_real_barrier_docker_and_independent_scorer(tmp_path, monkeypatch):
    setup = prepare(tmp_path, monkeypatch)
    runner = executor(setup)
    create = _factory(tmp_path, runner.plan)
    run = run_joint_common_train(runner, scorer_factory=create, execution_authority=EXEC,
                                 scorer_authority_keys={SCORER.authority_id: SCORER.key})
    receipt = run.receipt.data()
    assert len(run.builds) == 46 and len(run.targets) == len(run.panel.cells) == 118
    assert len(run.score_inputs) == len(run.scores) == 118
    assert receipt['status'] == 'complete_train_engineering' and receipt['final_provider_eligible'] is True
    assert receipt['actual']['model_calls'] == 930 and receipt['actual']['scorer_calls'] == 118
    assert all(row['status'] == 'scored' for row in receipt['targets'])
    assert run.targets[0].inner.solver.execution.record.data()['argv'][:4] == ['docker', 'run', '--pull', 'never']
    assert verify_joint_common_train_run(run, execution_authority_keys={EXEC.authority_id: EXEC.key},
                                         scorer_authority_keys={SCORER.authority_id: SCORER.key}) == run.receipt
    assert len(setup['common_logs']) == 930
