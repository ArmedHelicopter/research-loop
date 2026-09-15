"""Bounded native-v4 lineage controller with four synthetic headless workers."""
import hashlib
import json
import os
from pathlib import Path
import sys

from evaluation.modular.headless_lineage_worker_composition import compose_headless_lineage_server_configs
from evaluation.modular.lineage_scorer_process import LineageScorerProcessClient, LineageScorerProcessPool
from evaluation.modular.scoring_service import ScorerConfig
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.lineage_combination_controller import FrozenLineageTrainConfig, compile_lineage_train_panels, run_lineage_train_panels
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.train_provider_preflight import LEGACY_TRANSPORT_FIELDS
from research_loop.ontology import canonical
from test_headless_lineage_evaluator import _configure_headless
from test_lineage_process_scoring import prepared_fixture
from test_lineage_useful_controls import configured
from test_lineage_combination_controller import EXECUTION, SCORER, _model
from helpers.headless_train_provider import headless_train_provider


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _setup(root, monkeypatch):
    setup = configured(root, 'lineage')
    # Generate the isolated reference store from the prospective source first.
    _, _, legacy_config, compiled, sources, legacy_specs = prepared_fixture(root/'scorers', Path(setup['exporter'].config['snapshot_root']),
        None, setup['packets'], setup['config'], setup['sources'])
    seen = []; ordinary = _model(seen)
    def answer(request):
        if request.data()['slot'] == 'final_answer':
            return {'objective_digest': request.data()['module_context']['required_objective_digest'], 'outcome': 'unknown',
                    'evidence_ids': [], 'conclusion': 'synthetic native controller output', 'programme_complete': False}
        return ordinary(request)
    provider, calls, gets = headless_train_provider(root/'solver', monkeypatch, schemas=legacy_config.data()['schemas'],
        max_calls=136, response=answer)
    body = {key: value for key, value in legacy_config.data().items() if key not in LEGACY_TRANSPORT_FIELDS}
    body.update(schema='lineage-combination-train-config-v4', provider=provider.configuration().data())
    reference = dict(body['lineage_reference_binding'])
    reference['limits'] = {'model': 'grok-4.6', 'effort': 'low', 'tokens_per_cell': 20, 'timeout_seconds': 60}
    body['lineage_reference_binding'] = reference
    server_path = Path(legacy_specs[0]['command'][legacy_specs[0]['command'].index('--config') + 1])
    server = json.loads(server_path.read_text(encoding='utf-8'))
    _, _, _, template_server = _configure_headless(root/'headless-template')
    template = template_server['base']['evaluator']; specs = {}
    for index, panel in enumerate(compiled.panels):
        worker_root = root/'workers'/f'worker-{index}'
        specs[panel.obligation_id] = {**template, 'work_root': str((worker_root/'ledger').resolve()),
            'private_profile': str((worker_root/'profile').resolve()), 'public_cwd': str((worker_root/'context').resolve()),
            'max_calls': len(panel.cells), 'max_tokens': len(panel.cells)*20}
    base = {key: value for key, value in server['base'].items() if key != 'evaluator'}
    configs, bindings = compose_headless_lineage_server_configs(panels=compiled.panels, base=base,
        lineage_reference_root=server['lineage_references']['root'], lineage_reference_binding=reference,
        evaluator_specs=specs, tokens_per_cell=20)
    body['lineage_evaluator_bindings'] = bindings
    config = FrozenLineageTrainConfig(FrozenRecord.from_dict(body)); compiled = compile_lineage_train_panels(config, setup['packets'])
    clients = []
    for index, panel in enumerate(compiled.panels):
        worker = root/'workers'/f'worker-{index}'; worker.mkdir(parents=True, exist_ok=True); path = worker/'server.json'
        path.write_text(canonical(configs[panel.obligation_id]), encoding='utf-8')
        clients.append(LineageScorerProcessClient(panel=panel, config=ScorerConfig(FrozenRecord.from_dict(base['scorer_config'])),
            command=[sys.executable, str(Path(__file__).parent/'helpers'/'lineage_scorer_helper.py'), '--config', str(path),
                '--config-sha256', _sha(path), '--journal', str(worker/'server.jsonl')], journal_path=worker/'client.jsonl',
            task_handle_bindings={key: hashlib.sha256(value.encode()).hexdigest() for key, value in base['task_handles'].items()},
            execution_authority_keys={EXECUTION.authority_id: EXECUTION.key}, scorer_authority_keys={SCORER.authority_id: SCORER.key},
            reference_binding={**reference, 'evaluator_usage': bindings[panel.obligation_id]['evaluator_usage']},
            evaluator_provider=bindings[panel.obligation_id]['evaluator_provider'], environment={**os.environ, 'PYTHONIOENCODING':'utf-8'}))
    return setup, config, provider, calls, gets, LineageScorerProcessPool(clients), clients


def test_native_v4_headless_lineage_controller_closes_all_four_34_cell_workers(tmp_path, monkeypatch):
    setup, config, provider, calls, gets, pool, clients = _setup(tmp_path, monkeypatch)
    try:
        result = run_lineage_train_panels(config, custody=None, prospective_exporter=setup['exporter'],
            snapshot_root=Path(setup['exporter'].config['snapshot_root']), export_root=setup['exporter'].output_root,
            run_root=tmp_path/'run', model=provider, audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),
            source_verifier=setup['sources'], execution_authority=EXECUTION, scoring_service=pool,
            scorer_authority_keys={SCORER.authority_id:SCORER.key})
    finally:
        for client in clients: client.close()
    gate = result.receipt.data()['lineage_evaluator_final_gate']
    assert len(result.scores) == 34 and gate['status'] == 'eligible' and len(gate['panels']) == 4
    assert len(calls) == 136 and len(gets) == 6 * len(calls)
    assert all(row['status'] == 'eligible' and row['native_MAIN'] == len(row['receipt_digests']) * 10
               and row['closure']['body']['scope']['unscored_cell_count'] == 0 for row in gate['panels'])
