"""Explicit native TRAIN controller envelopes and independent scorer preflight.

This module does not admit providers to legacy controller schemas. The closed
live wrapper and its original configuration must agree with a new envelope;
shape validation alone is never dispatch or scoring authorization.
"""
from collections.abc import Mapping

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.phase_provider import validate_configuration
from research_loop.modular.train_provider import GrokTrainProvider, GrokHeadlessTrainProvider
from research_loop.ontology import ContractError


NATIVE_SCHEMAS = {
    'singleton': 'train-panel-controller-v2',
    'admission': 'admission-combination-train-config-v4',
    'lineage': 'lineage-combination-train-config-v4',
    'state_prediction': 'state-prediction-combination-train-config-v3',
    'state_retrieval': 'state-retrieval-combination-train-config-v3',
    'state_exploration': 'state-exploration-combination-train-config-v3',
    'state_scheduling': 'state-scheduling-combination-train-config-v3',
    'retrieval_review': 'retrieval-review-combination-train-config-v3',
    'mechanism_exploration': 'mechanism-exploration-combination-train-config-v3',
    'mechanism_scheduling': 'mechanism-scheduling-combination-train-config-v3',
    'admission_prediction_exploration': 'admission-prediction-exploration-combination-train-config-v3',
    'exploration_scheduler': 'exploration-scheduler-train-controller-config-v3',
    'q32_execution': 'q32-prospective-source-config-v3',
}
HEADLESS_EVALUATOR_SCHEMAS = {
    'admission_prediction_exploration': 'admission-prediction-exploration-combination-train-config-v4',
}
LEGACY_TRANSPORT_FIELDS = frozenset({'model', 'effort', 'max_calls', 'max_tokens', 'schemas'})
PROGRAM_SLOTS = frozenset({'analysis_program', 'program_1', 'program_2', 'program_3'})


def native_envelope(body, family):
    if family not in NATIVE_SCHEMAS:
        raise ContractError('unregistered native controller family')
    return (body.get('schema') == NATIVE_SCHEMAS[family]
            or headless_evaluator_envelope(body, family))


def headless_evaluator_envelope(body, family):
    return family in HEADLESS_EVALUATOR_SCHEMAS and body.get('schema') == HEADLESS_EVALUATOR_SCHEMAS[family]


def native_fields(body, required, *, family, optional=()):
    """Exact new fields, with no inherited Codex context or token envelope."""
    return (native_envelope(body, family)
        and set(body)-set(optional) == (set(required)-LEGACY_TRANSPORT_FIELDS)|{'provider'})


def native_source_fields(body, required, *, family, optional=()):
    return (body.get('export_mode') == 'primary_prospective'
        and native_fields(body,set(required)|{'export_mode'},family=family,optional=optional))


def response_schemas(body, *, family):
    if not native_envelope(body,family):
        return body['schemas']
    provider=body.get('provider')
    if type(provider) is not dict or type(provider.get('native_config')) is not dict:
        raise ContractError('original native provider configuration required')
    schemas=provider['native_config'].get('schemas')
    if type(schemas) is not dict:
        raise ContractError('native response schema mapping required')
    return schemas


def validate_native_declaration(body, *, family, schemas, main_opportunities):
    if not native_envelope(body, family) or LEGACY_TRANSPORT_FIELDS & set(body):
        raise ContractError('explicit native envelope without legacy transport fields required')
    if type(body.get('provider')) is not dict:
        raise ContractError('original frozen provider declaration required')
    declared = FrozenRecord.from_dict(body['provider'])
    validate_configuration(declared, schemas=schemas, main_opportunities=main_opportunities)
    b = declared.data(); limits = b['limits']
    if (b['provider_kind'] not in {'grok-acp-public-train-v1','grok-headless-public-train-v1'}
            or limits['prompt_byte_caps'] != {s:262144 for s in schemas}
            or limits['requested_output_token_caps'] != {s:8192 if s in PROGRAM_SLOTS else 2048 for s in schemas}
            or limits['observed_main_token_cap'] != 131072
            or limits['schema_byte_caps'] is not None or limits['request_envelope_byte_caps'] is not None
            or limits['legacy_reported_token_limit'] is not None):
        raise ContractError('frozen native slot, prompt or observed MAIN policy differs')
    return declared


def native_provider_preflight(body, provider, *, family, schemas, main_opportunities):
    declared = validate_native_declaration(body, family=family, schemas=schemas,
        main_opportunities=main_opportunities)
    expected = GrokHeadlessTrainProvider if declared.data()['provider_kind']=='grok-headless-public-train-v1' else GrokTrainProvider
    if type(provider) is not expected:
        raise ContractError('independent closed Grok TRAIN provider required')
    if provider.configuration() != declared:
        raise ContractError('live original provider configuration differs from declaration')
    if provider.inspect() or provider.terminal():
        raise ContractError('fresh healthy original provider allocation required')
    return declared


def scorer_process_preflight(body, service, execution_authority, scorer_keys, *, family):
    """Require the existing process handshake and exact registered serializer."""
    from evaluation.modular.scorer_process import CombinationScorerProcessClient, serialize_combination_panel
    from evaluation.modular.lineage_scorer_process import LineageScorerProcessPool
    from evaluation.modular.scoring_service import ScorerConfig
    from evaluation.modular.linked_scoring import LinkedExecutionAuthority

    if (family not in NATIVE_SCHEMAS or family in {'singleton', 'q32_execution'}
            or type(execution_authority) is not LinkedExecutionAuthority
            or not isinstance(scorer_keys, Mapping) or not scorer_keys
            or execution_authority.authority_id in scorer_keys
            or execution_authority.key in scorer_keys.values()):
        raise ContractError('independent native family scorer authorities required')
    if family == 'lineage':
        if type(service) is not LineageScorerProcessPool:
            raise ContractError('complete independent lineage scorer process pool required')
        if service.reference_binding != body.get('lineage_reference_binding'):
            raise ContractError('lineage reference binding differs from native envelope')
        panels = tuple(client.panel for client in service.clients.values())
    else:
        if type(service) is not CombinationScorerProcessClient:
            raise ContractError('independent combination scorer process required')
        panels = (service.panel,)
    for panel in panels:
        serialize_combination_panel(panel, **{family:True})
    service.assert_configuration(config=ScorerConfig(FrozenRecord.from_dict(body['scorer'])),
        task_handle_bindings=body['scorer_handle_bindings'],
        execution_authority_keys={execution_authority.authority_id:execution_authority.key},
        scorer_authority_keys=scorer_keys)
