"""Closed prospective recipe with useful reasoning in both factorial arms."""
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError


RECIPE = FrozenRecord.from_dict({
    'schema': 'm4-m5-useful-output-recipe-v1',
    'proposal': {'off': 'ordinary_three_branch', 'on': 'registered_discriminating'},
    'review': {'off': 'sequential_revision', 'on': 'sealed_independent'},
    'solver_context': 'all_three_module_responses',
    'model_slots': ['m4_plan', 'm5_mechanism', 'm5_measurement', 'analysis_program', 'final_answer'],
    'docker_attempts': 1, 'scorer_opportunities': 1,
})
PLAN_INSTRUCTION = (
    'Produce exactly a three-branch public prediction plan with budget_units=3. Each branch must use one common '
    'discriminator and at least two branches must differ on it. This is train-only reasoning, not a score or truth.')
ORDINARY_INSTRUCTION = (
    'Produce exactly three public candidate explanations and their predictions in a plan with budget_units=3. '
    'Use the supplied branch fields to develop a useful analysis proposal. This is train-only reasoning, not a score or truth.')
REVIEW_INSTRUCTION = 'Answer only the assigned public review question.'
REVISION_INSTRUCTION = (
    'Review the public proposal for the assigned question. Use any earlier review to improve your assessment; '
    'retain uncertainty and do not treat either review as validated evidence.')


def source_contract_body(body):
    """Normalize only the explicitly frozen v3 recipe for the existing source gate."""
    if body.get('schema') == 'm4-m5-train-controller-config-v4':
        normalized = dict(body)
        normalized.pop('provider', None)
        normalized['schema'] = 'm4-m5-train-controller-config-v3'
        return source_contract_body(normalized)
    if body.get('schema') != 'm4-m5-train-controller-config-v3':
        if 'execution_recipe' in body:
            raise ContractError('legacy M4/M5 configuration cannot select another execution recipe')
        return body
    if (body.get('export_mode') != 'primary_prospective'
            or not isinstance(body.get('execution_recipe'), dict)
            or FrozenRecord.from_dict(body['execution_recipe']) != RECIPE):
        raise ContractError('v3 M4/M5 requires the exact useful-output recipe and primary TRAIN source')
    normalized = dict(body)
    normalized.pop('execution_recipe')
    normalized['schema'] = 'm4-m5-train-controller-config-v2'
    return normalized


def useful_scenario(scenario):
    body = scenario.data()
    if body.get('schema') != 'combination-public-scenario-v2':
        if 'execution_recipe' in body:
            raise ContractError('legacy M4/M5 scenario cannot select another execution recipe')
        return False
    fields = {'schema', 'obligation_id', 'design_digest', 'task_digest', 'replicate', 'status', 'execution_recipe'}
    if (set(body) != fields or body['status'] != 'predeclared'
            or not isinstance(body['execution_recipe'], dict)
            or FrozenRecord.from_dict(body['execution_recipe']) != RECIPE):
        raise ContractError('M4/M5 scenario requires its exact frozen useful-output recipe')
    return True


def proposal_envelope(response):
    body = response.data()
    if (set(body) != {'question', 'branches', 'budget_units'} or type(body['budget_units']) is not int
            or body['budget_units'] != 3 or not isinstance(body['branches'], list) or len(body['branches']) != 3
            or not isinstance(body['question'], str) or not body['question'].strip()
            or any(not isinstance(branch, dict) for branch in body['branches'])):
        raise ContractError('useful proposal requires the common three-branch response envelope')
    return body


def review_context(*, binding, task, role, question, proposal, sealed, earlier):
    return {'panel_cell': binding, 'public_task': task, 'mechanism_phase': 'sealed_review' if sealed else 'sequential_revision',
            'review_role': role, 'review_question': question, 'prediction_plan': proposal,
            'sealed': sealed, 'earlier_reviews': [] if sealed else earlier}


def verify_useful_inputs(*, joint, requests, responses, enabled, roles, task, binding, sidecar):
    """Replay useful content from actual responses, not caller joint assertions."""
    proposal_envelope(responses[0])
    if (joint.get('schema') != 'm4-m5-joint-mechanism-v2'
            or joint.get('execution_recipe') != RECIPE.data()
            or joint.get('proposal') != responses[0].data()
            or joint.get('review_responses') != [r.data() for r in responses[1:]]):
        raise ContractError('useful joint context must retain every actual module response')
    sealed = 'M5' in enabled
    first_context = {k: v for k, v in requests[0]['module_context'].items() if k != 'deployment'}
    if (requests[0]['instruction'] != (PLAN_INSTRUCTION if 'M4' in enabled else ORDINARY_INSTRUCTION)
            or first_context != {'panel_cell': binding, 'public_task': task, 'mechanism_phase': 'proposal'}):
        raise ContractError('proposal instruction differs from frozen useful-output recipe')
    for i, (role, question) in enumerate(roles):
        context = review_context(binding=binding, task=task, role=role, question=question,
            proposal=responses[0].data(), sealed=sealed, earlier=[r.data() for r in responses[1:i+1]])
        actual = {k: v for k, v in requests[i+1]['module_context'].items() if k != 'deployment'}
        if actual != context or requests[i+1]['instruction'] != (REVIEW_INSTRUCTION if sealed else REVISION_INSTRUCTION):
            raise ContractError('review input differs from the frozen sealed or sequential recipe')
    for module, filename in [('M4', 'predictions.jsonl'), ('M5', 'reviews.jsonl')]:
        if module not in enabled and (sidecar/filename).read_text(encoding='utf-8').strip():
            raise ContractError('ordinary reasoning cannot create a disabled module artifact')
