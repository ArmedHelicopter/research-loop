"""Independent C5 consumer gate for the opt-in headless evaluator revision."""
from evaluation.modular.headless_evaluator_closure import verify_closure
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError


_GATE_SCHEMA = 'c5-common-final-headless-evaluator-v1'
_PROVIDER = 'grok-headless-frozen-evaluator-v1'
_USAGE_SCHEMA = 'c5-headless-evaluator-usage-declaration-v1'
_USAGE_CONTRACT = 'grok-headless-c5-usage-v1'


def verify_joint_headless_evaluator_gate(gate, *, authority_keys, panel, scorer_config,
                                         evaluator_provider, evaluator_usage, ordered_receipt_digests):
    """Verify the signed C5 closure before a selector can consume C5 scores."""
    fields = {'schema', 'status', 'score_eligible', 'evaluator_usage', 'evaluator_provider',
              'ordered_receipt_digests', 'closure', 'known_headless_main_tokens',
              'title_and_all_opportunity_settlement', 'failure_reason', 'error_type'}
    if (not isinstance(gate, dict) or set(gate) != fields or gate['schema'] != _GATE_SCHEMA
            or gate['status'] != 'eligible' or gate['score_eligible'] is not True
            or gate['evaluator_provider'] != evaluator_provider or gate['evaluator_usage'] != evaluator_usage
            or gate['ordered_receipt_digests'] != list(ordered_receipt_digests)
            or gate['title_and_all_opportunity_settlement'] != 'unknown'
            or gate['failure_reason'] is not None or gate['error_type'] is not None
            or type(gate['known_headless_main_tokens']) is not int or gate['known_headless_main_tokens'] < 0
            or not isinstance(gate['closure'], dict)):
        raise ContractError('C5 headless evaluator final gate is not eligible and exact')
    if (not isinstance(evaluator_provider, dict) or set(evaluator_provider) != {'kind', 'configuration_digest'}
            or evaluator_provider['kind'] != _PROVIDER or not _digest(evaluator_provider['configuration_digest'])
            or not isinstance(evaluator_usage, dict)
            or set(evaluator_usage) != {'schema', 'provider_kind', 'usage_contract', 'evaluator_config_digest'}
            or evaluator_usage['schema'] != _USAGE_SCHEMA or evaluator_usage['provider_kind'] != _PROVIDER
            or evaluator_usage['usage_contract'] != _USAGE_CONTRACT
            or not _digest(evaluator_usage['evaluator_config_digest'])
            or evaluator_usage['evaluator_config_digest'] != evaluator_provider['configuration_digest']):
        raise ContractError('C5 headless evaluator declaration or provider differs')
    expected_cells = {tuple(cell.key) for cell in panel.cells}
    if (not isinstance(ordered_receipt_digests, tuple) or len(ordered_receipt_digests) != len(panel.cells)
            or len(set(ordered_receipt_digests)) != len(ordered_receipt_digests)
            or any(not _digest(value) for value in ordered_receipt_digests)):
        raise ContractError('C5 ordered scorer receipts do not exactly cover the panel')
    envelope = FrozenRecord.from_dict(gate['closure']).data()
    nonce = envelope.get('body', {}).get('nonce') if isinstance(envelope.get('body'), dict) else None
    if not isinstance(nonce, str) or not nonce:
        raise ContractError('C5 closure nonce is malformed')
    verified = verify_closure(FrozenRecord.from_dict(gate['closure']), authority_keys=authority_keys,
        panel=panel, config=scorer_config, provider=evaluator_provider, nonce=nonce,
        receipt_digests=list(ordered_receipt_digests))
    body = verified.data(); scope = body['scope']
    if (body['known_main_tokens'] != gate['known_headless_main_tokens']
            or scope.get('unscored_cell_count') != 0
            or not isinstance(scope.get('scored_cell_keys'), list)
            or len(scope['scored_cell_keys']) != len(expected_cells)
            or {tuple(key) for key in scope['scored_cell_keys']} != expected_cells):
        raise ContractError('C5 headless evaluator closure is partial or accounting differs')
    return verified


def _digest(value):
    return isinstance(value, str) and len(value) == 64 and all(char in '0123456789abcdef' for char in value)
