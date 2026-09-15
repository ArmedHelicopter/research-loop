"""Headless lineage evaluator admission and native MAIN usage reporting."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

from evaluation.modular.evaluator_model_port import CodexEvaluatorModelPort
from evaluation.modular.lineage_scorer_process import LineageScorerProcessClient, LineageScorerWorker, load_lineage_service
from evaluation.modular.scoring_service import ScorerConfig
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.grok_acp_transport import ProcessTree
from research_loop.ontology import ContractError, canonical, digest
from test_evaluator_model_port import _probe
from test_lineage_process_scoring import fixture as legacy_fixture
from test_lineage_combination_controller import EXECUTION, IMAGE, SCHEMAS, _model
from test_modular_train_controller import model_port
from evaluation.modular.lineage_combination_scoring import issue_lineage_score_input
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.lineage_combination_driver import run_lineage_combination_cell, verify_lineage_combination_cell
from research_loop.modular.runtime import AuditVerifier
from tests.helpers.headless_authoring_fixture import install_synthetic_native


def _file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _configure_headless(root):
    """Build one frozen lineage declaration around the existing synthetic references."""
    _, _, _, compiled, sources, specs = legacy_fixture(root)
    spec = specs[0]
    config_path = Path(spec['command'][spec['command'].index('--config') + 1])
    server = json.loads(config_path.read_text(encoding='utf-8'))
    native = root / 'native'; native.mkdir()
    executable = native / 'synthetic-grok.exe'
    executable.write_bytes(b'synthetic headless lineage executable; never launched directly')
    home = native / 'approved-home'; home.mkdir()
    cells = len(compiled.panels[0].cells)
    limits = {'model': 'grok-4.6', 'effort': 'low', 'tokens_per_cell': 20, 'timeout_seconds': 60}
    server['base']['evaluator'] = {
        'provider_kind': 'grok-headless-frozen-evaluator-v1', 'executable': str(executable.resolve()),
        'work_root': str((native / 'ledger').resolve()), 'private_home': str(home.resolve()),
        'private_profile': str((native / 'profiles').resolve()), 'public_cwd': str((native / 'contexts').resolve()),
        'frozen_files': {str(executable.resolve()): _file_sha(executable)},
        'evaluator_id': 'synthetic-lineage-process', 'evaluator_version': 'v1', 'model': 'grok-4.6',
        'effort': 'low', 'max_calls': cells, 'max_tokens': cells * limits['tokens_per_cell'],
        'timeout_seconds': 60,
        'account_read_recovery': {'schema': 'headless-account-read-recovery-v1', 'max_attempts': 2},
    }
    server['lineage_references']['limits'] = limits
    server['lineage_references']['evaluator_usage'] = {
        'schema': 'lineage-headless-evaluator-usage-declaration-v1',
        'provider_kind': 'grok-headless-frozen-evaluator-v1',
        'usage_contract': 'grok-headless-lineage-usage-v1',
        'evaluator_config_digest': digest(server['base']['evaluator']),
    }
    config_path.write_bytes(canonical(server).encode('utf-8'))
    return compiled, sources, config_path, server


def _answer(schema, *, invalid=False):
    result = {}
    for name, definition in schema['properties'].items():
        if name == 'reason': result[name] = 'synthetic native lineage evaluator response'
        elif name == 'lineage_endpoints': result[name] = {endpoint: .5 for endpoint in definition['properties']}
        elif name in {'context', 'relation'}: result[name] = 1
        elif name == 'variable_f1': result[name] = .5
        else: result[name] = 1
    if invalid: result['lineage_endpoints'] = {'root_attribution': True}
    return result


def _native_service(config_path, server, patch, *, invalid=False):
    """Use the real native transport with a synthetic OS peer and account HTTP opener."""
    evaluator = server['base']['evaluator']
    import research_loop.modular.grok_headless_transport as transport

    install_synthetic_native(patch, {'native_deployment': {
        'executable': evaluator['executable'], 'slots': {'lineage': {'private_home': evaluator['private_home']}},
    }})
    peer = Path(__file__).parent / 'fixtures' / 'headless_train_peer.py'

    def spawn(command, cwd, env, stderr):
        assert env['GROK_DISABLE_API_KEY_AUTH'] == '1'
        assert not {'XAI_API_KEY', 'GROK_API_KEY'} & set(env)
        if 'inspect' in command:
            args = ['inspect']
        else:
            prompt_path = Path(command[command.index('--prompt-file') + 1])
            schema = json.loads(command[command.index('--json-schema') + 1])
            answer_path = prompt_path.parent.parent / 'synthetic-lineage-answer.json'
            answer_path.write_text(json.dumps(_answer(schema, invalid=invalid)), encoding='utf-8')
            args = [command[command.index('--session-id') + 1], str(answer_path)]
        return ProcessTree([sys.executable, str(peer), *args], cwd=cwd, env=env, stderr=stderr)

    patch.setattr(transport, 'ProcessTree', spawn)
    return load_lineage_service(config_path, _file_sha(config_path))


def _lineage_request(panel, service):
    cell = panel.cells[0]
    identity_digest = digest(cell.identity.data())
    candidate = {'answer': 'synthetic candidate'}
    context = {'schema': 'lineage-combination-public-context-v1',
        'panel_cell': {'benchmark': cell.identity.benchmark}, 'material': {'summary': 'synthetic'},
        'review_responses': [], 'candidate_context': {}}
    return FrozenRecord.from_dict({'schema': 'lineage-adapted-rubric-request-v1', 'panel_digest': panel.digest,
        'scorer_config_digest': service.config.digest, 'benchmark': cell.identity.benchmark,
        'task_handle': service._handles[identity_digest], 'identity_digest': identity_digest, 'candidate': candidate,
        'candidate_digest': digest(candidate), 'public_context': context, 'public_context_digest': digest(context),
        'lineage_endpoints': ['root_attribution', 'withdrawal_awareness', 'context_currency', 'review_responsiveness'],
        'task_digest': cell.task_digest,
        'material_digest': service.lineage_reference_binding['subjects'][identity_digest]['material_digest']})


def _validate_headless_client_view(panel, reference_binding, body):
    client = object.__new__(LineageScorerProcessClient)
    client.panel, client.reference_binding = panel, reference_binding
    client._validate_headless_usage(body)


def test_headless_lineage_resolver_endpoint_service_and_native_main_contract(tmp_path):
    _, _, config_path, server = _configure_headless(tmp_path / 'headless')
    patch = pytest.MonkeyPatch()
    try:
        panel, service = _native_service(config_path, server, patch)
        result = service._evaluator(_lineage_request(panel, service))
        assert result.data()['lineage_endpoints']['root_attribution'] == .5
        worker = LineageScorerWorker(service, panel, tmp_path / 'journal.jsonl')
        body = worker.respond({'schema': 'lineage-scorer-usage-request-v1', 'nonce': 'native-main'})['body']
        _validate_headless_client_view(panel, service.lineage_reference_binding, body)
        ledger = service.evaluator_port.ledger
        assert body['schema'] == 'lineage-scorer-headless-usage-v1'
        assert body['usage_contract'] == 'grok-headless-lineage-usage-v1'
        assert body['evaluator_config_digest'] == server['lineage_references']['evaluator_usage']['evaluator_config_digest']
        assert body['accounting_scope'] == 'native_MAIN'
        assert body['title_and_all_opportunity_settlement'] == 'unknown'
        assert body['tokens'] == ledger['tokens'] == 10
        assert body['calls'][0]['known_headless_main_usage'] == ledger['calls'][0]['known_headless_main_usage']
        assert ledger['calls'][0]['headless_binding']['usage']['main'] == body['calls'][0]['known_headless_main_usage']
    finally:
        patch.undo()


def test_headless_lineage_usage_preserves_rejected_known_native_main_usage(tmp_path):
    _, _, config_path, server = _configure_headless(tmp_path / 'headless')
    patch = pytest.MonkeyPatch()
    try:
        panel, service = _native_service(config_path, server, patch, invalid=True)
        with pytest.raises(ContractError): service._evaluator(_lineage_request(panel, service))
        worker = LineageScorerWorker(service, panel, tmp_path / 'journal.jsonl')
        body = worker.respond({'schema': 'lineage-scorer-usage-request-v1', 'nonce': 'rejected-main'})['body']
        _validate_headless_client_view(panel, service.lineage_reference_binding, body)
        ledger = service.evaluator_port.ledger
        assert body['usage_incomplete'] is True and body['tokens'] == 10
        assert body['calls'][0]['status'] == ledger['calls'][0]['status'] == 'unknown_or_failed'
        assert body['calls'][0]['known_headless_main_usage'] == ledger['calls'][0]['known_headless_main_usage']
        assert body['calls'][0]['accepted'] is False
    finally:
        patch.undo()


def test_headless_lineage_worker_consumes_one_signed_score_input(tmp_path, monkeypatch):
    """Exercise the scorer worker seam, not only the endpoint's private RPC."""
    compiled, sources, config_path, server = _configure_headless(tmp_path / 'headless')
    patch = pytest.MonkeyPatch()
    try:
        panel, service = _native_service(config_path, server, patch)
        cell = panel.cells[0]
        packet = next(packet for packet in compiled.packets if packet.task.content_hash == cell.task_digest)
        args = {'panel': panel, 'task': packet.task, 'scenario': compiled.scenarios[cell.key],
                'package': compiled.packages[cell.runtime_arm.content_hash], 'material': compiled.materials[cell.task_digest],
                'source_verifier': sources, 'public_inputs': {'public_csv': packet.csv_path},
                'broker': DockerExecutionBroker([tmp_path])}
        calls = []
        solver = model_port(tmp_path / 'solver', monkeypatch, max_calls=4, max_tokens=1000, schemas=SCHEMAS,
                            response_factory=_model(calls))
        result = run_lineage_combination_cell(cell=cell, **args, objective=FrozenRecord.from_dict({'panel_digest': panel.digest}),
            sidecar=tmp_path / 'cell', image=IMAGE, model=solver, audit_verifier=AuditVerifier({'a': b'a' * 32, 'b': b'b' * 32}))
        assert result.runtime.status == 'succeeded'
        verify_lineage_combination_cell(result, **args)
        score_input = issue_lineage_score_input(authority=EXECUTION, result=result, **args)
        request_id = 'headless-worker-score'
        material = {'request_id': request_id, 'panel_digest': panel.digest, 'cell_key': list(cell.key),
                    'linked_input': score_input.data()}
        request = {'schema': 'linked-scorer-process-request-v1', **material,
                   'request_digest': hashlib.sha256(canonical(material).encode('utf-8')).hexdigest()}
        worker = LineageScorerWorker(service, panel, tmp_path / 'score-journal.jsonl')
        response = worker.respond(request)
        assert response['status'] == 'succeeded' and 'receipt' in response
        assert service.evaluator_port.ledger['calls'][0]['status'] == 'succeeded'
    finally:
        patch.undo()


@pytest.mark.parametrize('mutation', ('wrong_kind', 'wrong_rubric', 'wrong_source', 'wrong_limit'))
def test_headless_lineage_factory_rejects_unfrozen_declarations(tmp_path, mutation):
    _, _, config_path, server = _configure_headless(tmp_path / mutation)
    if mutation == 'wrong_kind':
        server['base']['evaluator']['provider_kind'] = 'grok-acp-public-train-v1'
    elif mutation == 'wrong_rubric':
        scorer = dict(server['base']['scorer_config']); scorer['rubric_digest'] = '0' * 64
        server['base']['scorer_config'] = scorer
        server['base']['scorer_config_digest'] = ScorerConfig(FrozenRecord.from_dict(scorer)).digest
    elif mutation == 'wrong_source':
        source = next(iter(server['base']['evaluator']['frozen_files']))
        server['base']['evaluator']['frozen_files'] = {source: '0' * 64}
    else:
        server['lineage_references']['limits']['tokens_per_cell'] = 21
    config_path.write_bytes(canonical(server).encode('utf-8'))
    with pytest.raises(ContractError): load_lineage_service(config_path, _file_sha(config_path))
    ledger_path = Path(server['base']['evaluator']['work_root']) / 'ledger.json'
    if ledger_path.exists(): assert json.loads(ledger_path.read_text(encoding='utf-8'))['calls'] == []


def test_legacy_codex_lineage_factory_and_usage_contract_remain_admitted(tmp_path):
    _, _, _, compiled, _, specs = legacy_fixture(tmp_path / 'legacy')
    config_path = Path(specs[0]['command'][specs[0]['command'].index('--config') + 1])
    port = CodexEvaluatorModelPort('codex', tmp_path / 'legacy-port', evaluator_id='synthetic-lineage-process',
        evaluator_version='v1', rubric_mode='lineage_v1', max_calls=len(compiled.panels[0].cells),
        max_tokens=len(compiled.panels[0].cells) * 20, process_runner=lambda *args, **kwargs: None,
        context_probe_runner=_probe, allow_mock_context=True)
    _, service = load_lineage_service(config_path, _file_sha(config_path), evaluator=port)
    assert service.lineage_usage_schema == 'lineage-scorer-usage-v1'
    assert service.lineage_usage_contract is None
