"""Lineage scorer server and matched four-panel client pool.

Separate stdio processes, not an OS security principal: launchers must isolate
accounts/mounts and authorize the pinned train reference publisher separately.
"""
import argparse
import json
from pathlib import Path
from typing import Mapping
import uuid

from evaluation.modular.scorer_process import (LinkedScorerProcessClient, CombinationScorerProcessClient,
    ScorerWorker, serve, scorer_process_binding, serialize_combination_panel, parse_combination_panel,
    parse_server_config, _production_evaluator, _absolute, _sha)
from evaluation.modular.reference_store import FrozenTrainReferenceResolver, _plain
from evaluation.modular.lineage_rubric import FrozenLineageReferenceResolver, FrozenLineageRubricEndpoint
from evaluation.modular.lineage_combination_scoring import LineageCombinationScoringService
from evaluation.modular.scoring_service import FrozenRubricTransport
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.lineage_combination_driver import DESIGNS
from research_loop.ontology import ContractError, canonical, digest


_CODEX_USAGE_SCHEMA = 'lineage-scorer-usage-v1'
_HEADLESS_USAGE_SCHEMA = 'lineage-scorer-headless-usage-v1'
_HEADLESS_USAGE_CONTRACT = 'grok-headless-lineage-usage-v1'
_HEADLESS_PROVIDER_KIND = 'grok-headless-frozen-evaluator-v1'
_HEADLESS_USAGE_DECLARATION_SCHEMA = 'lineage-headless-evaluator-usage-declaration-v1'
_LINEAGE_FINALIZATION_SCHEMA = 'lineage-headless-evaluator-finalization-journal-v1'
_LINEAGE_FINALIZE_REQUEST_SCHEMA = 'lineage-headless-evaluator-finalize-request-v1'
_LINEAGE_FINALIZE_RESPONSE_SCHEMA = 'lineage-headless-evaluator-finalize-response-v1'


def _lineage_headless_source_pin(spec):
    """The lineage worker is a closure consumer and must be replay-pinned too."""
    if spec.get('provider_kind') != _HEADLESS_PROVIDER_KIND:
        return spec
    result = dict(spec)
    files = dict(spec.get('frozen_files', {}))
    source = Path(__file__).resolve()
    actual = _sha(source.read_bytes())
    if str(source) in files and files[str(source)] != actual:
        raise ContractError('supplied lineage scorer source pin differs')
    files[str(source)] = actual
    result['frozen_files'] = files
    return result


def _lineage_evaluator_contract(config, model, panel, limits, usage_declaration):
    """Admit exactly one frozen evaluator family and its panel allocation."""
    from evaluation.modular.evaluator_model_port import CodexEvaluatorModelPort
    from evaluation.modular.headless_evaluator_model_port import GrokHeadlessEvaluatorModelPort

    if not isinstance(limits, dict) or set(limits) != {'model', 'effort', 'tokens_per_cell', 'timeout_seconds'}:
        raise ContractError('lineage evaluator limits contract invalid')
    if (type(limits['tokens_per_cell']) is not int or limits['tokens_per_cell'] < 1
            or type(limits['timeout_seconds']) is not int or limits['timeout_seconds'] < 1):
        raise ContractError('lineage evaluator limits contract invalid')
    if isinstance(model, CodexEvaluatorModelPort):
        if config.evaluator.get('provider_kind') is not None or usage_declaration is not None:
            raise ContractError('legacy Codex evaluator declaration differs')
        usage_schema, usage_contract = _CODEX_USAGE_SCHEMA, None
    elif isinstance(model, GrokHeadlessEvaluatorModelPort):
        declaration = config.evaluator
        required = {'provider_kind', 'executable', 'work_root', 'private_home', 'private_profile', 'public_cwd',
                    'frozen_files', 'evaluator_id', 'evaluator_version', 'model', 'effort', 'max_calls',
                    'max_tokens', 'timeout_seconds', 'account_read_recovery'}
        expected_usage_declaration = {'schema': _HEADLESS_USAGE_DECLARATION_SCHEMA,
                                      'provider_kind': _HEADLESS_PROVIDER_KIND,
                                      'usage_contract': _HEADLESS_USAGE_CONTRACT,
                                      'evaluator_config_digest': digest(declaration)}
        if (usage_declaration != expected_usage_declaration
                or set(declaration) != required or declaration.get('provider_kind') != _HEADLESS_PROVIDER_KIND
                or not isinstance(declaration.get('frozen_files'), dict)
                or model.provider_kind != _HEADLESS_PROVIDER_KIND or model.rubric_mode != 'lineage_v1'
                or model.config.get('provider_kind') != _HEADLESS_PROVIDER_KIND
                or model.config.get('rubric_mode') != 'lineage_v1'
                or model.executable != str(_absolute(declaration.get('executable'), 'headless executable').resolve())
                or model.root != _absolute(declaration.get('work_root'), 'headless work root').resolve()
                or model.private_home != _absolute(declaration.get('private_home'), 'headless private home').resolve()
                or model.private_profile != _absolute(declaration.get('private_profile'), 'headless private profile').resolve()
                or model.public_cwd != _absolute(declaration.get('public_cwd'), 'headless public cwd').resolve()
                or any(model.frozen_files.get(str(_absolute(path, 'headless frozen source'))) != digest
                       for path, digest in declaration.get('frozen_files', {}).items())
                or model.evaluator_id != declaration.get('evaluator_id')
                or model.evaluator_version != declaration.get('evaluator_version')
                or model.config.get('model') != declaration.get('model')
                or model.config.get('reasoning_effort') != declaration.get('effort')
                or model.config.get('timeout_seconds') != declaration.get('timeout_seconds')
                or model.config.get('max_calls') != declaration.get('max_calls')
                or model.config.get('max_tokens') != declaration.get('max_tokens')
                or model.config.get('account_read_recovery') != declaration.get('account_read_recovery')):
            raise ContractError('lineage headless evaluator declaration differs')
        if model.frozen_files.get(str(Path(__file__).resolve())) != _sha(Path(__file__).read_bytes()):
            raise ContractError('lineage scorer source was not frozen into the evaluator port')
        usage_schema, usage_contract = _HEADLESS_USAGE_SCHEMA, _HEADLESS_USAGE_CONTRACT
    else:
        raise ContractError('lineage service requires a protected evaluator mode')
    if (model.rubric_digest != FrozenLineageRubricEndpoint.rubric_digest()
            or model.model != limits['model'] or model.effort != limits['effort']
            or model.max_tokens != len(panel.cells)*limits['tokens_per_cell']
            or model.timeout_seconds != limits['timeout_seconds']):
        raise ContractError('lineage evaluator allocation differs from frozen limits')
    if model.evaluator_id != config.scorer.record.data()['evaluator_id'] or model.evaluator_version != config.scorer.record.data()['version']:
        raise ContractError('lineage evaluator identity/version mismatch')
    if model.max_calls != len(panel.cells) or model.ledger['calls']:
        raise ContractError('lineage evaluator needs a fresh exact per-panel call allocation')
    return usage_schema, usage_contract


def load_lineage_service(path, expected_sha256, *, evaluator=None):
    raw = _plain(Path(path)).read_bytes()
    if _sha(raw) != expected_sha256: raise ContractError('lineage server configuration hash drift')
    b = json.loads(raw.decode('utf-8'))
    if not isinstance(b, dict) or set(b) != {'schema', 'base', 'panel', 'lineage_references'} or b['schema'] != 'lineage-scorer-process-config-v1':
        raise ContractError('lineage server configuration contract invalid')
    panel = parse_combination_panel(b['panel'], lineage=True)
    base = dict(b['base'])
    if 'panel' in base or 'schema' in base: raise ContractError('lineage base must not redefine panel')
    config = parse_server_config({**base, 'schema': 'combination-scorer-process-config-v1', 'panel': b['panel']}, lineage=True)
    if config.scorer.record.data()['rubric_digest'] != FrozenLineageRubricEndpoint.rubric_digest():
        raise ContractError('lineage scorer needs its distinct frozen rubric version')
    spec = b['lineage_references']
    if not isinstance(spec, dict) or set(spec) not in ({'root', 'manifest_sha256', 'references', 'subjects', 'limits'},
                                                        {'root', 'manifest_sha256', 'references', 'subjects', 'limits', 'evaluator_usage'}):
        raise ContractError('lineage reference configuration invalid')
    primary = FrozenTrainReferenceResolver(config.store_root, manifest_sha256=config.manifest_sha256,
        inventory_digest=config.inventory_digest, split_digest=config.split_digest)
    resolver = FrozenLineageReferenceResolver(_absolute(spec['root'], 'lineage store'),
        manifest_sha256=spec['manifest_sha256'], bindings=spec['references'], primary_resolver=primary)
    if resolver.subjects != spec['subjects']:
        raise ContractError('lineage frozen reference subjects drift')
    for cell in panel.cells:
        from research_loop.ontology import digest
        ref, _, _ = resolver.resolve(config.task_handles[digest(cell.identity.data())], cell.identity.benchmark,
            identity_digest=digest(cell.identity.data()), task_digest=cell.task_digest)
    model = evaluator if evaluator is not None else _production_evaluator(
        _lineage_headless_source_pin(config.evaluator), rubric_mode='lineage_v1')
    limits = spec['limits']
    usage_declaration = spec.get('evaluator_usage')
    usage_schema, usage_contract = _lineage_evaluator_contract(config, model, panel, limits, usage_declaration)
    endpoint = FrozenLineageRubricEndpoint(resolver=resolver, evaluator=model,
        evaluator_id=config.scorer.record.data()['evaluator_id'], evaluator_version=config.scorer.record.data()['version'])
    service = LineageCombinationScoringService(config=config.scorer, evaluator=FrozenRubricTransport(endpoint),
        execution_authority_keys=config.execution_keys, task_handles=config.task_handles, scorer_authority=config.scorer_authority)
    service.lineage_reference_binding = {**resolver.binding, 'limits': limits,
                                         **({'evaluator_usage': usage_declaration} if usage_declaration is not None else {})}
    service.evaluator_port = model
    from evaluation.modular.headless_evaluator_model_port import GrokHeadlessEvaluatorModelPort
    if isinstance(model, GrokHeadlessEvaluatorModelPort):
        from evaluation.modular.headless_evaluator_closure import descriptor
        service.headless_evaluator_port = model
        service.evaluator_provider = descriptor(model)
        service.lineage_evaluator_declaration = FrozenRecord.from_dict(config.evaluator)
    service.lineage_usage_schema = usage_schema
    service.lineage_usage_contract = usage_contract
    return panel, service


class LineageScorerProcessClient(CombinationScorerProcessClient):
    def __init__(self, *, panel, config, command, journal_path, task_handle_bindings, execution_authority_keys,
                 scorer_authority_keys, reference_binding, evaluator_provider=None, environment=None, response_timeout_seconds=240):
        serialize_combination_panel(panel, lineage=True)
        expected = scorer_process_binding(panel=panel, config=config, task_handle_bindings=task_handle_bindings,
            execution_authority_keys=execution_authority_keys, scorer_authority_keys=scorer_authority_keys)
        self.reference_binding = FrozenRecord.from_dict(reference_binding).data()
        expected = FrozenRecord.from_dict({**expected.data(), 'lineage_references': reference_binding})
        declaration = self.reference_binding.get('evaluator_usage')
        if declaration is not None:
            if (not isinstance(evaluator_provider, Mapping) or set(evaluator_provider) != {'kind', 'configuration_digest'}
                    or evaluator_provider.get('kind') != _HEADLESS_PROVIDER_KIND
                    or not isinstance(evaluator_provider.get('configuration_digest'), str)
                    or len(evaluator_provider['configuration_digest']) != 64):
                raise ContractError('lineage headless client requires an exact evaluator descriptor binding')
            self.evaluator_provider = dict(evaluator_provider)
            expected = FrozenRecord.from_dict({**expected.data(), 'evaluator_provider': self.evaluator_provider})
        elif evaluator_provider is not None:
            raise ContractError('legacy lineage client must not bind a headless evaluator descriptor')
        else:
            self.evaluator_provider = None
        self.config = config
        self._scorer_keys = dict(scorer_authority_keys)
        LinkedScorerProcessClient.__init__(self, panel=panel, command=command, journal_path=journal_path,
            environment=environment, response_timeout_seconds=response_timeout_seconds)
        try:
            nonce = uuid.uuid4().hex
            self.input.write(canonical({'schema':'scorer-process-binding-request-v1', 'nonce':nonce})+'\n'); self.input.flush()
            response = json.loads(self._readline_bounded())
            if response != {'schema':'scorer-process-binding-response-v1','nonce':nonce,'binding':expected.data()}:
                raise ContractError('lineage scorer startup reference/configuration binding mismatch')
            self.binding = expected
        except Exception as exc:
            self._stop_unknown_worker()
            raise ContractError('lineage scorer startup failed') from exc

    def assert_configuration(self, **kwargs):
        expected = scorer_process_binding(panel=self.panel, **kwargs)
        if (self.binding != FrozenRecord.from_dict({**expected.data(), 'lineage_references': self.reference_binding})
                or self.process.poll() is not None):
            raise ContractError('lineage scorer configuration or worker state drift')

    def usage(self):
        from evaluation.modular.combination_scoring import _signed_body
        nonce = uuid.uuid4().hex
        try:
            self.input.write(canonical({'schema':'lineage-scorer-usage-request-v1', 'nonce':nonce})+'\n'); self.input.flush()
            response = FrozenRecord.from_dict(json.loads(self._readline_bounded()))
            body = _signed_body(response, self._scorer_keys, message='lineage scorer usage')
            if (body.get('nonce') != nonce or body.get('panel_digest') != self.panel.digest
                    or body.get('scorer_digest') != self.config.digest):
                raise ContractError('lineage usage subject mismatch')
            declaration = self.reference_binding.get('evaluator_usage')
            if declaration is None and body.get('schema') == _CODEX_USAGE_SCHEMA:
                self._validate_codex_usage(body)
            elif (isinstance(declaration, dict)
                  and declaration.get('schema') == _HEADLESS_USAGE_DECLARATION_SCHEMA
                  and declaration.get('provider_kind') == _HEADLESS_PROVIDER_KIND
                  and declaration.get('usage_contract') == _HEADLESS_USAGE_CONTRACT
                  and isinstance(declaration.get('evaluator_config_digest'), str)
                  and len(declaration['evaluator_config_digest']) == 64
                  and body.get('schema') == _HEADLESS_USAGE_SCHEMA):
                self._validate_headless_usage(body)
            else:
                raise ContractError('lineage usage schema is not admitted')
            return response.data()
        except Exception:
            return {'status':'unknown', 'cost_unknown':True}

    def _validate_codex_usage(self, body):
        if (set(body) != {'schema', 'authority', 'nonce', 'panel_digest', 'scorer_digest', 'ledger_sha256',
                         'calls', 'tokens', 'usage_incomplete', 'limits', 'max_calls', 'max_tokens'}
                or body['limits'] != self.reference_binding['limits']
                or type(body['tokens']) is not int or body['tokens'] < 0
                or type(body['usage_incomplete']) is not bool or not isinstance(body['calls'], list)
                or body['max_calls'] != len(self.panel.cells)
                or body['max_tokens'] != len(self.panel.cells)*body['limits']['tokens_per_cell']):
            raise ContractError('lineage usage accounting contract mismatch')
        known = 0
        for index, call in enumerate(body['calls'], 1):
            if (not isinstance(call, dict) or set(call) != {'id', 'status', 'usage'} or call['id'] != index
                    or call['status'] not in {'reserved', 'succeeded', 'failed', 'unknown', 'over_budget'}):
                raise ContractError('lineage usage call contract mismatch')
            usage = call['usage']
            if usage is not None:
                if (not isinstance(usage, dict) or set(usage) != {'input_tokens', 'output_tokens', 'cached_input_tokens',
                        'cache_write_input_tokens', 'reasoning_output_tokens', 'total_tokens'}
                        or any(type(v) is not int or v < 0 for v in usage.values())
                        or usage['total_tokens'] != usage['input_tokens']+usage['output_tokens']):
                    raise ContractError('lineage usage token contract mismatch')
                known += usage['total_tokens']
        if known != body['tokens'] or len(body['calls']) > body['max_calls']:
            raise ContractError('lineage usage cumulative total mismatch')

    def _validate_headless_usage(self, body):
        expected = {'schema', 'authority', 'nonce', 'panel_digest', 'scorer_digest', 'ledger_sha256', 'calls',
                    'tokens', 'usage_incomplete', 'limits', 'max_calls', 'max_tokens', 'provider_kind',
                    'usage_contract', 'evaluator_config_digest', 'accounting_scope', 'title_and_all_opportunity_settlement'}
        if (set(body) != expected or body['limits'] != self.reference_binding['limits']
                or body['provider_kind'] != _HEADLESS_PROVIDER_KIND
                or body['usage_contract'] != _HEADLESS_USAGE_CONTRACT
                or body['evaluator_config_digest'] != self.reference_binding['evaluator_usage']['evaluator_config_digest']
                or body['accounting_scope'] != 'native_MAIN'
                or body['title_and_all_opportunity_settlement'] != 'unknown'
                or type(body['tokens']) is not int or body['tokens'] < 0
                or type(body['usage_incomplete']) is not bool or not isinstance(body['calls'], list)
                or body['max_calls'] != len(self.panel.cells)
                or body['max_tokens'] != len(self.panel.cells)*body['limits']['tokens_per_cell']):
            raise ContractError('headless lineage usage accounting contract mismatch')
        known = 0
        for index, call in enumerate(body['calls'], 1):
            expected_call = {'id', 'status', 'main_opportunity', 'known_headless_main_usage',
                             'main_dispatch_state', 'native_receipt_sha256', 'reservation_sha256', 'accepted'}
            if (not isinstance(call, dict) or set(call) != expected_call or call['id'] != index
                    or call['status'] not in {'reserved', 'succeeded', 'unknown_or_failed'}
                    or call['main_opportunity'] != 1
                    or call['main_dispatch_state'] not in {'unknown', 'not_dispatched', 'possibly_dispatched'}
                    or call['accepted'] not in {True, False, None}):
                raise ContractError('headless lineage usage call contract mismatch')
            for field in ('native_receipt_sha256', 'reservation_sha256'):
                if call[field] is not None and (not isinstance(call[field], str) or len(call[field]) != 64):
                    raise ContractError('headless lineage usage artifact contract mismatch')
            usage = call['known_headless_main_usage']
            if usage is not None:
                fields = {'input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens',
                          'output_tokens', 'reasoning_tokens', 'total_tokens'}
                if (not isinstance(usage, dict) or set(usage) != fields
                        or any(type(value) is not int or value < 0 for value in usage.values())
                        or usage['reasoning_tokens'] > usage['output_tokens']
                        or usage['total_tokens'] != usage['input_tokens'] + usage['cache_read_input_tokens']
                            + usage['cache_creation_input_tokens'] + usage['output_tokens']):
                    raise ContractError('headless lineage MAIN token contract mismatch')
                known += usage['total_tokens']
        if known != body['tokens'] or len(body['calls']) > body['max_calls']:
            raise ContractError('headless lineage usage cumulative total mismatch')

    def score_lineage(self, *, panel, cell, score_input):
        return self.score_combination(panel=panel, cell=cell, score_input=score_input)

    def finalize_lineage(self, *, nonce: str, receipt_digests):
        """Ask the bound private worker to replay, seal, and then stop scoring."""
        if self.evaluator_provider is None:
            raise ContractError('legacy lineage client has no headless closure contract')
        if not isinstance(nonce, str) or not nonce or not isinstance(receipt_digests, list):
            raise ContractError('lineage headless finalization request is malformed')
        request = {'schema': _LINEAGE_FINALIZE_REQUEST_SCHEMA, 'nonce': nonce,
                   'receipt_digests': receipt_digests, 'evaluator_provider': self.evaluator_provider}
        try:
            self.input.write(canonical(request)+'\n'); self.input.flush()
            response = json.loads(self._readline_bounded())
            if (not isinstance(response, dict) or set(response) != {'schema', 'nonce', 'closure'}
                    or response.get('schema') != _LINEAGE_FINALIZE_RESPONSE_SCHEMA or response.get('nonce') != nonce):
                raise ContractError('lineage headless finalization response is malformed')
            from evaluation.modular.headless_evaluator_closure import verify_lineage_closure
            closure = FrozenRecord.from_dict(response['closure'])
            # Verify the envelope before returning it, but retain the signed
            # record for the outer controller's durable final gate.
            verify_lineage_closure(closure, authority_keys=self._scorer_keys, panel=self.panel, config=self.config,
                provider=self.evaluator_provider, reference_binding=self.reference_binding, nonce=nonce,
                receipt_digests=receipt_digests)
            return closure
        except Exception as exc:
            self._stop_unknown_worker()
            raise ContractError('lineage headless finalization failed') from exc


class LineageScorerProcessPool(CombinationScorerProcessClient):
    """Prestarted, exact four-panel workers; no reference contents enter controller."""
    def __init__(self, clients):
        if len(clients) != len(DESIGNS) or any(not isinstance(c, LineageScorerProcessClient) for c in clients):
            raise ContractError('lineage process pool needs all four typed clients')
        self.clients = {c.panel.obligation_id: c for c in clients}
        if set(self.clients) != set(DESIGNS) or len({c.config.digest for c in clients}) != 1:
            raise ContractError('lineage process pool design/configuration drift')
        self.config = clients[0].config
        bindings = [c.reference_binding for c in clients]
        declarations = [binding.get('evaluator_usage') for binding in bindings]
        if any(value is not None for value in declarations):
            if any(not isinstance(value, Mapping) for value in declarations):
                raise ContractError('lineage process headless declarations differ across panels')
            shared = [{key: value for key, value in binding.items() if key != 'evaluator_usage'} for binding in bindings]
            if any(value != shared[0] for value in shared):
                raise ContractError('lineage process references differ across panels')
            if any(client.evaluator_provider is None for client in clients):
                raise ContractError('lineage process headless descriptor is missing')
            self.reference_binding = shared[0]
            self.evaluator_usage_by_obligation = {client.panel.obligation_id: client.reference_binding['evaluator_usage']
                                                  for client in clients}
            self.evaluator_providers_by_obligation = {client.panel.obligation_id: client.evaluator_provider
                                                       for client in clients}
        else:
            self.reference_binding = bindings[0]
            if any(binding != self.reference_binding for binding in bindings):
                raise ContractError('lineage process references differ across panels')

    def assert_configuration(self, **kwargs):
        for client in self.clients.values(): client.assert_configuration(**kwargs)

    def score_lineage(self, *, panel, cell, score_input):
        return self.clients[panel.obligation_id].score_lineage(panel=panel, cell=cell, score_input=score_input)

    def close(self):
        for client in self.clients.values(): client.close()


def _lineage_finalization_path(journal_path: Path) -> Path:
    return Path(str(journal_path) + '.headless-lineage-evaluator-finalization.jsonl')


def _lineage_finalization_request(value: object) -> dict[str, object]:
    required = {'schema', 'nonce', 'receipt_digests', 'evaluator_provider'}
    if (not isinstance(value, Mapping) or set(value) != required or value.get('schema') != _LINEAGE_FINALIZE_REQUEST_SCHEMA
            or not isinstance(value.get('nonce'), str) or not value['nonce'] or not isinstance(value.get('receipt_digests'), list)
            or not isinstance(value.get('evaluator_provider'), Mapping)):
        raise ContractError('lineage headless finalization request is malformed')
    provider = value['evaluator_provider']
    if (set(provider) != {'kind', 'configuration_digest'} or provider.get('kind') != _HEADLESS_PROVIDER_KIND
            or not isinstance(provider.get('configuration_digest'), str) or len(provider['configuration_digest']) != 64):
        raise ContractError('lineage headless finalization provider is malformed')
    for receipt in value['receipt_digests']:
        if not isinstance(receipt, str) or len(receipt) != 64:
            raise ContractError('lineage headless closure receipt is malformed')
    return {'schema': value['schema'], 'nonce': value['nonce'], 'receipt_digests': list(value['receipt_digests']),
            'evaluator_provider': dict(provider)}


def _lineage_finalization_state(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
        if len(rows) not in {1, 2}:
            raise ValueError('unexpected lineage finalization history')
        attempted = rows[0]
        if (not isinstance(attempted, Mapping) or set(attempted) != {'schema', 'status', 'request'}
                or attempted.get('schema') != _LINEAGE_FINALIZATION_SCHEMA or attempted.get('status') != 'attempted'):
            raise ValueError('invalid lineage finalization attempt')
        request = _lineage_finalization_request(attempted['request'])
        if len(rows) == 1:
            return {'status': 'attempted', 'request': request}
        terminal = rows[1]
        if (not isinstance(terminal, Mapping) or terminal.get('schema') != _LINEAGE_FINALIZATION_SCHEMA
                or terminal.get('request') != request or terminal.get('status') not in {'eligible', 'rejected'}):
            raise ValueError('invalid lineage finalization terminal')
        if terminal['status'] == 'eligible':
            if set(terminal) != {'schema', 'status', 'request', 'closure'}:
                raise ValueError('invalid eligible lineage finalization')
            FrozenRecord.from_dict(terminal['closure'])
        elif set(terminal) != {'schema', 'status', 'request', 'reason'} or not isinstance(terminal['reason'], str):
            raise ValueError('invalid rejected lineage finalization')
        return dict(terminal)
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise ContractError('lineage headless finalization history is not safely recoverable') from exc


class LineageScorerWorker(ScorerWorker):
    def __init__(self, service, panel, journal_path):
        super().__init__(service, panel, journal_path)
        self.lineage_finalization_path = _lineage_finalization_path(journal_path)
        self.lineage_finalization_state = _lineage_finalization_state(self.lineage_finalization_path)
        self.lineage_final_closure = (FrozenRecord.from_dict(self.lineage_finalization_state['closure'])
                                      if self.lineage_finalization_state and self.lineage_finalization_state['status'] == 'eligible'
                                      else None)

    def _respond_lineage_finalization(self, value):
        request = _lineage_finalization_request(value)
        if (not hasattr(self.service, 'headless_evaluator_port') or request['evaluator_provider'] != self.service.evaluator_provider
                or not hasattr(self.service, 'lineage_reference_binding')):
            raise ContractError('lineage headless finalization provider differs')
        if _lineage_finalization_state(self.lineage_finalization_path) != self.lineage_finalization_state:
            raise ContractError('lineage headless finalization history changed')
        from evaluation.modular.headless_evaluator_closure import finalize_lineage
        if self.lineage_finalization_state is not None:
            if self.lineage_finalization_state['request'] != request:
                raise ContractError('lineage headless finalization already differs')
            if self.lineage_finalization_state['status'] != 'eligible' or self.lineage_final_closure is None:
                raise ContractError('lineage headless finalization is terminally rejected')
            current = finalize_lineage(service=self.service, panel=self.panel, journal_path=self.journal_path,
                nonce=request['nonce'], receipt_digests=request['receipt_digests'])
            if current != self.lineage_final_closure:
                raise ContractError('lineage headless finalization differs from the sealed original')
            return {'schema': _LINEAGE_FINALIZE_RESPONSE_SCHEMA, 'nonce': request['nonce'], 'closure': current.data()}
        attempted = {'schema': _LINEAGE_FINALIZATION_SCHEMA, 'status': 'attempted', 'request': request}
        from evaluation.modular.scorer_process import _append
        _append(self.lineage_finalization_path, attempted)
        self.lineage_finalization_state = attempted
        try:
            self.lineage_final_closure = finalize_lineage(service=self.service, panel=self.panel, journal_path=self.journal_path,
                nonce=request['nonce'], receipt_digests=request['receipt_digests'])
        except Exception as exc:
            terminal = {'schema': _LINEAGE_FINALIZATION_SCHEMA, 'status': 'rejected', 'request': request,
                        'reason': 'provenance_replay_failed'}
            _append(self.lineage_finalization_path, terminal)
            self.lineage_finalization_state = terminal
            raise ContractError('lineage headless finalization is terminally rejected') from exc
        terminal = {'schema': _LINEAGE_FINALIZATION_SCHEMA, 'status': 'eligible', 'request': request,
                    'closure': self.lineage_final_closure.data()}
        _append(self.lineage_finalization_path, terminal)
        self.lineage_finalization_state = terminal
        return {'schema': _LINEAGE_FINALIZE_RESPONSE_SCHEMA, 'nonce': request['nonce'], 'closure': self.lineage_final_closure.data()}

    def respond(self, value):
        if isinstance(value, Mapping) and value.get('schema') == _LINEAGE_FINALIZE_REQUEST_SCHEMA:
            return self._respond_lineage_finalization(value)
        if isinstance(value, Mapping) and value.get('schema') == 'headless-evaluator-finalize-request-v1':
            raise ContractError('lineage scorer requires the lineage headless closure contract')
        if isinstance(value, dict) and value.get('schema') == 'lineage-scorer-usage-request-v1':
            if set(value) != {'schema', 'nonce'} or not isinstance(value['nonce'], str) or not value['nonce']:
                raise ContractError('invalid lineage usage query')
            model = self.service.evaluator_port
            ledger = model.ledger
            if json.loads(model.ledger_path.read_text(encoding='utf-8')) != ledger:
                raise ContractError('lineage evaluator ledger bytes changed externally')
            common = {'nonce':value['nonce'], 'panel_digest':self.panel.digest, 'scorer_digest':self.service.config.digest,
                      'ledger_sha256':_sha(model.ledger_path.read_bytes()), 'tokens':ledger['tokens'],
                      'usage_incomplete':ledger['usage_incomplete'], 'limits':self.service.lineage_reference_binding['limits'],
                      'max_calls':model.max_calls, 'max_tokens':model.max_tokens}
            if self.service.lineage_usage_schema == _CODEX_USAGE_SCHEMA:
                body = {'schema':_CODEX_USAGE_SCHEMA, **common,
                        'calls':[{'id':c['id'], 'status':c['status'], 'usage':c.get('usage')} for c in ledger['calls']]}
            elif self.service.lineage_usage_schema == _HEADLESS_USAGE_SCHEMA:
                body = {'schema':_HEADLESS_USAGE_SCHEMA, **common, 'provider_kind':_HEADLESS_PROVIDER_KIND,
                        'usage_contract':self.service.lineage_usage_contract,
                        'evaluator_config_digest':self.service.lineage_reference_binding['evaluator_usage']['evaluator_config_digest'],
                        'accounting_scope':'native_MAIN',
                        'title_and_all_opportunity_settlement':'unknown',
                        'calls':[{'id':c['id'], 'status':c['status'], 'main_opportunity':c.get('main_opportunity'),
                                  'known_headless_main_usage':c.get('known_headless_main_usage'),
                                  'main_dispatch_state':c.get('main_dispatch_state'),
                                  'native_receipt_sha256':c.get('native_receipt_sha256'),
                                  'reservation_sha256':c.get('reservation_sha256'), 'accepted':c.get('accepted')}
                                 for c in ledger['calls']]}
            else:
                raise ContractError('lineage usage contract was not admitted')
            return self.service._authority.issue(body).data()
        if self.lineage_finalization_state is not None and not (isinstance(value, Mapping)
                                                                and value.get('schema') == 'scorer-process-binding-request-v1'):
            raise ContractError('lineage headless evaluator scorer is finalized')
        return super().respond(value)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--config', required=True)
    parser.add_argument('--config-sha256', required=True); parser.add_argument('--journal', required=True)
    args = parser.parse_args()
    panel, service = load_lineage_service(args.config, args.config_sha256)
    return serve(LineageScorerWorker(service, panel, _absolute(args.journal, 'journal')))


if __name__ == '__main__': raise SystemExit(main())
