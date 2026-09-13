"""Explicit useful-review recipe; legacy experiments retain their old estimand."""
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError


RECIPE = FrozenRecord.from_dict({'schema':'lineage-useful-review-recipe-v1',
    'review':{'off':'sequential_revision','on':'sealed_independent'},
    'solver_context':'both_actual_reviews',
    'model_slots':['lineage_review','measurement_review','analysis_program','final_answer'],
    'docker_attempts':1,'scorer_opportunities':1})
SEALED_INSTRUCTION = 'Answer only the assigned public review question.'
REVISION_INSTRUCTION = (
    'Review the supplied public material for the assigned question. Use any earlier review to improve your assessment; '
    'retain uncertainty and do not treat either review as validated evidence.')


def source_contract_body(body, legacy_schema):
    if legacy_schema not in ('lineage-combination-train-config-v1', 'admission-combination-train-config-v1'):
        raise ContractError('useful review recipe requires a registered lineage/admission family')
    if body.get('schema') != legacy_schema.removesuffix('v1')+'v3':
        if 'execution_recipe' in body:
            raise ContractError('legacy lineage/admission configuration cannot change its review recipe')
        return body
    if (body.get('export_mode') != 'primary_prospective' or not isinstance(body.get('execution_recipe'),dict)
            or FrozenRecord.from_dict(body['execution_recipe']) != RECIPE):
        raise ContractError('v3 lineage/admission requires the exact useful-review recipe and primary TRAIN source')
    normalized = dict(body); normalized.pop('execution_recipe')
    normalized['schema'] = legacy_schema.removesuffix('v1')+'v2'
    return normalized


def useful_scenario(scenario):
    body = scenario.data()
    if body.get('schema') != 'lineage-combination-scenario-v2':
        if 'execution_recipe' in body:
            raise ContractError('legacy lineage scenario cannot change its review recipe')
        return False
    if not isinstance(body.get('execution_recipe'),dict) or FrozenRecord.from_dict(body['execution_recipe']) != RECIPE:
        raise ContractError('lineage scenario requires its exact useful-review recipe')
    return True


def review_instruction(enabled, useful):
    return REVISION_INSTRUCTION if useful and 'M5' not in enabled else SEALED_INSTRUCTION
