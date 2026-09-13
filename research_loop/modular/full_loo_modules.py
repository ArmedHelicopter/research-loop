"""Native C4 preparation, shared by prospective execution and original replay."""
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.mechanism_improvement_modules import (
    model_schemas as mechanism_schemas, PREDICTION_INSTRUCTION,
    ORDINARY_INSTRUCTION, REVIEW_INSTRUCTION, ROLES, execute_retrieval)
from research_loop.modular.modules.review import ReviewEngine
from research_loop.modular.modules.predictions import _prediction
from research_loop.modular.model_port import _validate_schema
from research_loop.modular.metaprogram_training import _projection, _builder
from research_loop.modular.modules.improvement import FrozenBuilderVersion
from research_loop.modular.panel_receipts import opaque_panel_cell_binding
from research_loop.ontology import ContractError

PREP_SLOTS = ('m4_plan','review_first','review_second','bounded_choice')
MEASUREMENT = {'phase':'fresh_auxiliary_execution','observable':'statistic','discriminator_id':'fresh_auxiliary_execution'}
CHOICE_INSTRUCTION = ('Choose one of the supplied alternative checks after considering the forecasts, critiques and retrieved methods. '
    'Return exactly job_id and rationale; the common measurement always runs too.')
PROPOSAL_INSTRUCTION = ('Propose a bounded emit_literal_change_v1 builder from only the supplied completed public training work. '
    'Return entrypoint, surface, key and value; use prompt/instructions or memory/lesson. Produce useful reusable guidance.')
REVISION_INSTRUCTION = ('Revise ordinary reusable analysis guidance from the supplied completed public training work. '
    'Return exactly instructions, a useful bounded instruction paragraph.')


def slots(recipe, stage):
    if stage == 'history_build':
        return PREP_SLOTS + (('builder_proposal',) if recipe['history_build_levels']['M9'] else ('ordinary_revision',))
    return (() if recipe['procedure']=='baseline_b0' else PREP_SLOTS) + ('analysis_program','final_answer')


def model_schemas():
    schemas = mechanism_schemas()
    schemas['bounded_choice'] = {'type':'object','required':['job_id','rationale'],'additionalProperties':False,
        'properties':{'job_id':{'type':'string'},'rationale':{'type':'string'}}}
    schemas['ordinary_revision'] = {'type':'object','required':['instructions'],'additionalProperties':False,
        'properties':{'instructions':{'type':'string'}}}
    return schemas


def prepare(*, cell, task, package, transition, predictions, reviews, invoke, record, retrieve, phase_material):
    enabled = set(cell.runtime_arm.data()['enabled'])
    context = {'panel_cell':opaque_panel_cell_binding(cell),'public_task':task.data(),
        'candidate_context':_projection(package).data(),'state_projection':transition.data()['public']}
    response = invoke('m4_plan', PREDICTION_INSTRUCTION if 'M4' in enabled else ORDINARY_INSTRUCTION,
        FrozenRecord.from_dict({**context,'measurement':MEASUREMENT}))
    b = response.data(); _validate_schema(model_schemas()['m4_plan'],b)
    for branch in b['branches']:
        if any(not branch[k].strip() for k in ('hypothesis_id','mechanism_key','mechanism','intervention','elimination_condition')):
            raise ContractError('empty forecast alternative')
        for p in branch['predictions']:
            _prediction(p)
            if p['observable']!=MEASUREMENT['observable'] or p['discriminator_id']!=MEASUREMENT['discriminator_id']:
                raise ContractError('prediction must precede and address the fresh measurement')
    plan = predictions.freeze(b['question'],b['branches'],budget_units=3) if 'M4' in enabled else None
    record('c4_prediction_frozen', {'proposal':b,'registered':plan.data() if plan else None})
    context.update(prediction_proposal=b,prediction_plan=plan.payload.data() if plan else None)
    review = reviews.open(task_binding=task.content_hash,evidence_snapshot=FrozenRecord.from_dict(context).content_hash,
        roles=[{'role_id':r,'question':q} for r,q in ROLES],budget_units=2) if 'M5' in enabled else None
    responses=[]
    for slot,(role,question) in zip(PREP_SLOTS[1:3],ROLES,strict=True):
        response=invoke(slot,REVIEW_INSTRUCTION,FrozenRecord.from_dict({**context,'question':question,
            'prior_responses':[] if review else [r.data() for r in responses]}))
        ReviewEngine._response(response.data());responses.append(response)
        if review: reviews.submit(review.review_id,role_id=role,reviewer_id=role,response=response.data(),cost_units=1)
        record('c4_review_sealed',{'slot':slot,'response_digest':response.content_hash,
            'barrier_open':reviews.barrier_open(review.review_id) if review else None})
    revealed=reviews.reveal(review.review_id) if review else None
    record('c4_review_reveal',{'submissions':[r.data() for r in revealed] if revealed else None})
    context['reviews']=[r.data() for r in responses]
    context['retrieval']=retrieve()
    choice=invoke('bounded_choice',CHOICE_INSTRUCTION,FrozenRecord.from_dict({**context,
        'alternative_checks':phase_material.data()['jobs'][1:]}))
    _validate_schema(model_schemas()['bounded_choice'],choice.data())
    if choice.data()['job_id'] not in {j['id'] for j in phase_material.data()['jobs'][1:]} or not choice.data()['rationale'].strip():
        raise ContractError('bounded choice must select a useful frozen alternative')
    record('c4_choice_frozen',{'choice':choice.data()})
    return FrozenRecord.from_dict({**context,'choice':choice.data()})


def joint(prepared, phase, cell, task, package):
    if prepared is None:
        return FrozenRecord.from_dict({'schema':'c4-public-joint-v1','panel_cell':opaque_panel_cell_binding(cell),
            'public_task':task.data(),'candidate_context':_projection(package).data()})
    if phase.data()['status']!='succeeded': raise ContractError('failed auxiliary work cannot reach common solve')
    return FrozenRecord.from_dict({'schema':'c4-public-joint-v1',**prepared.data(),
        'execution_observations':phase.data()['public']['observations']})


def select_builder(response, recipe, fixed_builder):
    if recipe['history_build_levels']['M9']:
        return _builder(FrozenBuilderVersion(response))
    _validate_schema(model_schemas()['ordinary_revision'],response.data())
    # Ordinary revision supplies text to one fixed literal writer; it does not
    # propose a builder program, surface, key, or metaprogram search policy.
    source=fixed_builder.record.data(); source['value']=response.data()['instructions']
    return _builder(FrozenBuilderVersion(FrozenRecord.from_dict(source)))
