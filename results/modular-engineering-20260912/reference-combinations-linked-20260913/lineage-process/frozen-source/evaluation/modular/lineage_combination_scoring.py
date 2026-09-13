"""One independent frozen rubric opportunity for primary and lineage endpoints."""
import hashlib
import math

from evaluation.modular.combination_scoring import (CombinationAdaptedScoringService, _signed_body, _score_input_payload,
    verify_combination_score_input, verify_combination_adapted_receipt)
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.lineage_combination_driver import verify_lineage_combination_cell
from research_loop.modular.panel_receipts import ScientificScorerReceipt
from research_loop.ontology import ContractError

ENDPOINTS = ('root_attribution', 'withdrawal_awareness', 'context_currency', 'review_responsiveness')


def issue_lineage_score_input(*, authority, result, **verification_args):
    verify_lineage_combination_cell(result, **verification_args)
    primary = authority.issue(_score_input_payload(verification_args['panel'], result).data())
    context = result.joint_mechanism
    return authority.issue({'schema': 'lineage-combination-score-input-v1', 'primary': primary.data(),
        'public_context': context.data(), 'public_context_digest': context.content_hash,
        'material_digest': verification_args['material'].record.content_hash})


def _source(source, keys, panel, cell):
    body = _signed_body(source, keys, message='lineage score input')
    if set(body) != {'schema', 'authority', 'primary', 'public_context', 'public_context_digest', 'material_digest'} or body['schema'] != 'lineage-combination-score-input-v1':
        raise ContractError('lineage score input envelope drift')
    primary = FrozenRecord.from_dict(body['primary'])
    bound = verify_combination_score_input(primary, authority_keys=keys, panel=panel, cell=cell).data()
    context = FrozenRecord.from_dict(body['public_context'])
    if context.content_hash != body['public_context_digest'] or context.content_hash != bound['joint_mechanism_digest']:
        raise ContractError('independent scorer context differs from actual solver joint')
    return body, primary, bound


def _endpoints(values):
    if (not isinstance(values, dict) or set(values) != set(ENDPOINTS)
            or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in values.values())):
        raise ContractError('independent lineage endpoints require frozen finite dimensions')


class LineageCombinationScoringService(CombinationAdaptedScoringService):
    def score_lineage(self, *, panel, cell, score_input):
        source, primary_input, _ = _source(score_input, self._execution_keys, panel, cell)
        from evaluation.modular.lineage_rubric import FrozenLineageRubricEndpoint
        v2 = self.config.record.data()['rubric_digest'] == FrozenLineageRubricEndpoint.rubric_digest()
        endpoint_result = {}
        def combined_transport(request):
            prompt = request.data()
            prompt.update(schema='lineage-adapted-rubric-request-v1', public_context=source['public_context'],
                public_context_digest=source['public_context_digest'], lineage_endpoints=list(ENDPOINTS))
            if v2:
                prompt.update(task_digest=cell.task_digest, material_digest=source['material_digest'])
            response = self._evaluator(FrozenRecord.from_dict(prompt))
            if not isinstance(response, FrozenRecord):
                raise ContractError('independent lineage scorer returned no immutable response')
            data = response.data()
            if data.pop('public_context_digest', None) != source['public_context_digest']:
                raise ContractError('independent rubric did not bind the public lineage context')
            values = data.pop('lineage_endpoints', None); _endpoints(values)
            if v2:
                ref_digest = data.pop('lineage_reference_digest', None)
                if not isinstance(ref_digest, str) or len(ref_digest) != 64:
                    raise ContractError('lineage rubric must bind qualified reference')
            endpoint_result.update(values=values, response_digest=response.content_hash, response=response.data())
            return FrozenRecord.from_dict(data)
        # Reuse exact adapted-score calculation and evidence validation without a
        # second rubric call. The configured transport sees primary + endpoints together.
        primary_service = CombinationAdaptedScoringService(config=self.config, evaluator=combined_transport,
            execution_authority_keys=self._execution_keys, task_handles=self._handles, scorer_authority=self._authority)
        primary = primary_service.score_combination(panel=panel, cell=cell, score_input=primary_input)
        return ScientificScorerReceipt(cell.key, self._authority.issue({'schema': 'lineage-combination-scored-cell-v1',
            'primary': primary.receipt.data(), 'source_digest': score_input.content_hash,
            'public_context_digest': source['public_context_digest'], 'endpoints': endpoint_result['values'],
            'rubric_response_digest': endpoint_result['response_digest'],
            'rubric_response': endpoint_result['response'], 'scorer_digest': self.config.digest,
            'metric': primary.receipt.data()['body']['metric'],
            'runtime_trace_digest': primary.receipt.data()['body']['runtime_trace_digest']}))


def verify_lineage_score(receipt, *, authority_keys, config, panel, cell, score_input, execution_authority_keys, expected_reference_digest=None):
    source, primary_input, _ = _source(score_input, execution_authority_keys, panel, cell)
    if not isinstance(receipt, ScientificScorerReceipt) or receipt.cell_key != cell.key:
        raise ContractError('lineage scorer cell drift')
    body = _signed_body(receipt.receipt, authority_keys, message='lineage scored cell')
    if (set(body) != {'schema', 'authority', 'primary', 'source_digest', 'public_context_digest', 'endpoints',
                    'rubric_response_digest', 'rubric_response', 'scorer_digest', 'metric', 'runtime_trace_digest'}
            or body['schema'] != 'lineage-combination-scored-cell-v1' or body['source_digest'] != score_input.content_hash
            or body['public_context_digest'] != source['public_context_digest']):
        raise ContractError('lineage scorer response subject drift')
    _endpoints(body['endpoints'])
    response = FrozenRecord.from_dict(body['rubric_response'])
    if (body['scorer_digest'] != config.digest or response.content_hash != body['rubric_response_digest']
            or response.data().get('lineage_endpoints') != body['endpoints']
            or response.data().get('public_context_digest') != source['public_context_digest']):
        raise ContractError('lineage endpoints differ from the original independent response')
    from evaluation.modular.lineage_rubric import FrozenLineageRubricEndpoint
    if config.record.data()['rubric_digest'] == FrozenLineageRubricEndpoint.rubric_digest():
        if expected_reference_digest is None or response.data().get('lineage_reference_digest') != expected_reference_digest:
            raise ContractError('lineage score did not bind the predeclared independent reference')
        if any(value not in (0, .5, 1) for value in body['endpoints'].values()):
            raise ContractError('lineage endpoint is outside its fixed discrete rubric')
        schema = FrozenRecord.from_dict(FrozenLineageRubricEndpoint._output_schema(cell.identity.benchmark))
        if response.data().get('evidence', {}).get('schema_digest') != schema.content_hash:
            raise ContractError('lineage response did not bind the frozen evaluator output schema')
    elif expected_reference_digest is not None:
        raise ContractError('legacy lineage scoring cannot claim source-reference binding')
    primary = ScientificScorerReceipt(cell.key, FrozenRecord.from_dict(body['primary']))
    verified = verify_combination_adapted_receipt(primary, authority_keys=authority_keys, config=config,
        panel=panel, cell=cell, score_input=primary_input, execution_authority_keys=execution_authority_keys)
    if body['metric'] != verified.data()['metric'] or body['runtime_trace_digest'] != verified.data()['runtime_trace_digest']:
        raise ContractError('lineage metric does not bind the independent primary score')
    if response.data().get('dimensions') != verified.data()['dimensions'] or response.data().get('evidence') != verified.data()['evaluator_evidence']:
        raise ContractError('primary score and lineage endpoints were not returned by the same rubric opportunity')
    return FrozenRecord.from_dict(body)
