"""Lineage scorer server and matched four-panel client pool.

Separate stdio processes, not an OS security principal: launchers must isolate
accounts/mounts and authorize the pinned train reference publisher separately.
"""
import argparse
import json
from pathlib import Path
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
from research_loop.ontology import ContractError, canonical


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
    if not isinstance(spec, dict) or set(spec) != {'root', 'manifest_sha256', 'references', 'subjects', 'limits'}:
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
    model = evaluator if evaluator is not None else _production_evaluator(config.evaluator, rubric_mode='lineage_v1')
    from evaluation.modular.evaluator_model_port import CodexEvaluatorModelPort
    if not isinstance(model, CodexEvaluatorModelPort) or model.rubric_digest != FrozenLineageRubricEndpoint.rubric_digest():
        raise ContractError('lineage service requires protected Codex evaluator mode')
    limits = spec['limits']
    if (not isinstance(limits, dict) or set(limits) != {'model', 'effort', 'tokens_per_cell', 'timeout_seconds'}
            or type(limits['tokens_per_cell']) is not int or limits['tokens_per_cell'] < 1
            or type(limits['timeout_seconds']) is not int or limits['timeout_seconds'] < 1
            or model.model != limits['model'] or model.effort != limits['effort']
            or model.max_tokens != len(panel.cells)*limits['tokens_per_cell']
            or model.timeout_seconds != limits['timeout_seconds']):
        raise ContractError('lineage evaluator allocation differs from frozen limits')
    if model.evaluator_id != config.scorer.record.data()['evaluator_id'] or model.evaluator_version != config.scorer.record.data()['version']:
        raise ContractError('lineage evaluator identity/version mismatch')
    if model.max_calls != len(panel.cells) or model.ledger['calls']:
        raise ContractError('lineage evaluator needs a fresh exact per-panel call allocation')
    endpoint = FrozenLineageRubricEndpoint(resolver=resolver, evaluator=model,
        evaluator_id=config.scorer.record.data()['evaluator_id'], evaluator_version=config.scorer.record.data()['version'])
    service = LineageCombinationScoringService(config=config.scorer, evaluator=FrozenRubricTransport(endpoint),
        execution_authority_keys=config.execution_keys, task_handles=config.task_handles, scorer_authority=config.scorer_authority)
    service.lineage_reference_binding = {**resolver.binding, 'limits': limits}
    service.evaluator_port = model
    return panel, service


class LineageScorerProcessClient(CombinationScorerProcessClient):
    def __init__(self, *, panel, config, command, journal_path, task_handle_bindings, execution_authority_keys,
                 scorer_authority_keys, reference_binding, environment=None, response_timeout_seconds=240):
        serialize_combination_panel(panel, lineage=True)
        expected = scorer_process_binding(panel=panel, config=config, task_handle_bindings=task_handle_bindings,
            execution_authority_keys=execution_authority_keys, scorer_authority_keys=scorer_authority_keys)
        self.reference_binding = FrozenRecord.from_dict(reference_binding).data()
        expected = FrozenRecord.from_dict({**expected.data(), 'lineage_references': reference_binding})
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
            if (body.get('schema') != 'lineage-scorer-usage-v1' or body.get('nonce') != nonce
                    or body.get('panel_digest') != self.panel.digest or body.get('scorer_digest') != self.config.digest):
                raise ContractError('lineage usage subject mismatch')
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
            return response.data()
        except Exception:
            return {'status':'unknown', 'cost_unknown':True}

    def score_lineage(self, *, panel, cell, score_input):
        return self.score_combination(panel=panel, cell=cell, score_input=score_input)


class LineageScorerProcessPool(CombinationScorerProcessClient):
    """Prestarted, exact four-panel workers; no reference contents enter controller."""
    def __init__(self, clients):
        if len(clients) != len(DESIGNS) or any(not isinstance(c, LineageScorerProcessClient) for c in clients):
            raise ContractError('lineage process pool needs all four typed clients')
        self.clients = {c.panel.obligation_id: c for c in clients}
        if set(self.clients) != set(DESIGNS) or len({c.config.digest for c in clients}) != 1:
            raise ContractError('lineage process pool design/configuration drift')
        self.config = clients[0].config
        self.reference_binding = clients[0].reference_binding
        if any(c.reference_binding != self.reference_binding for c in clients):
            raise ContractError('lineage process references differ across panels')

    def assert_configuration(self, **kwargs):
        for client in self.clients.values(): client.assert_configuration(**kwargs)

    def score_lineage(self, *, panel, cell, score_input):
        return self.clients[panel.obligation_id].score_lineage(panel=panel, cell=cell, score_input=score_input)

    def close(self):
        for client in self.clients.values(): client.close()


class LineageScorerWorker(ScorerWorker):
    def respond(self, value):
        if isinstance(value, dict) and value.get('schema') == 'lineage-scorer-usage-request-v1':
            if set(value) != {'schema', 'nonce'} or not isinstance(value['nonce'], str) or not value['nonce']:
                raise ContractError('invalid lineage usage query')
            model = self.service.evaluator_port
            ledger = model.ledger
            if json.loads(model.ledger_path.read_text(encoding='utf-8')) != ledger:
                raise ContractError('lineage evaluator ledger bytes changed externally')
            return self.service._authority.issue({'schema':'lineage-scorer-usage-v1', 'nonce':value['nonce'],
                'panel_digest':self.panel.digest, 'scorer_digest':self.service.config.digest,
                'ledger_sha256':_sha(model.ledger_path.read_bytes()),
                'calls':[{'id':c['id'], 'status':c['status'], 'usage':c.get('usage')} for c in ledger['calls']],
                'tokens':ledger['tokens'], 'usage_incomplete':ledger['usage_incomplete'],
                'limits':self.service.lineage_reference_binding['limits'],
                'max_calls':model.max_calls, 'max_tokens':model.max_tokens}).data()
        return super().respond(value)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--config', required=True)
    parser.add_argument('--config-sha256', required=True); parser.add_argument('--journal', required=True)
    args = parser.parse_args()
    panel, service = load_lineage_service(args.config, args.config_sha256)
    return serve(LineageScorerWorker(service, panel, _absolute(args.journal, 'journal')))


if __name__ == '__main__': raise SystemExit(main())
