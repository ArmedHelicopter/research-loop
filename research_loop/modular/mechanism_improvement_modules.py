"""Target-only native predictions, reviews and retrieval after candidate freeze."""
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.metaprogram_training import metaprogram_schemas, _projection
from research_loop.modular.modules.predictions import PredictionRegistry
from research_loop.modular.modules.review import ReviewEngine
from research_loop.modular.modules.retrieval import FrozenSourceBundle
from research_loop.modular.panel_receipts import opaque_panel_cell_binding
from research_loop.modular.retrieval_panel_drivers import _select_sources
from research_loop.modular.retrieval_review_combination_driver import admission_receipt, BUDGET, public_retrieval, _verify_sources
from research_loop.ontology import ContractError

MEASUREMENT={'phase':'future_target_execution','observable':'target_statistic','discriminator_id':'fresh_target_execution'}
PREDICTION_INSTRUCTION=('Forecast the supplied fresh target execution measurement using the public task and frozen candidate. '
    'Return question, three competing branches, and budget_units=3. Use the declared observable and discriminator in every prediction. '
    'Historical observations are conditioning information, never prospective outcomes.')
REVIEW_INSTRUCTION='Review the frozen candidate guidance and public task for the assigned measurement question; give useful bounded checks.'
ROLES=(('mechanism','Which executable check would distinguish the candidate guidance from the public alternative?'),
       ('measurement','Which measurement or implementation error should the shared target program check?'))


def slots(pair):
    return {'pair:M4+M9':('m4_plan','analysis_program','final_answer'),
        'pair:M5+M9':('review_first','review_second','analysis_program','final_answer'),
        'pair:M6+M9':('analysis_program','final_answer')}[pair]


def model_schemas():
    result=metaprogram_schemas()
    prediction_fields={'prediction_id':{'type':'string'},'discriminator_id':{'type':'string'},
        'observable':{'type':'string'},'direction':{'type':'string'},'value_range':{'type':['string','null']},
        'failure_condition':{'type':'string'}}
    prediction={'type':'object','required':list(prediction_fields),'additionalProperties':False,'properties':prediction_fields}
    branch_fields={k:{'type':'string'} for k in ('hypothesis_id','mechanism_key','mechanism','intervention','elimination_condition')}
    branch_fields['predictions']={'type':'array','items':prediction,'minItems':1,'maxItems':3}
    branch={'type':'object','required':list(branch_fields),'additionalProperties':False,'properties':branch_fields}
    result['m4_plan']={'type':'object','required':['question','branches','budget_units'],'additionalProperties':False,
        'properties':{'question':{'type':'string'},'branches':{'type':'array','items':branch,'minItems':3,'maxItems':3},
            'budget_units':{'type':'integer','minimum':3,'maximum':3}}}
    review={'type':'object','required':['assessment','evidence_refs','counterexamples','uncertainty'],'additionalProperties':False,
        'properties':{'assessment':{'type':'string','enum':['accept','concern','unknown']},
            'evidence_refs':{'type':'array','items':{'type':'string'}},'counterexamples':{'type':'array','items':{'type':'string'}},
            'uncertainty':{'type':'string'}}}
    result.update(review_first=review,review_second=review)
    return result


def module_context(cell,task,package,transition):
    return {'panel_cell':opaque_panel_cell_binding(cell),'public_task':task.data(),
        'candidate_context':_projection(package).data(),'state_projection':transition.data()['public']}


def apply_target_module(*,cell,task,package,transition,predictions,reviews,invoke,record,retrieval=None):
    """Used for execution and deterministic replay, with independently supplied responses."""
    context=module_context(cell,task,package,transition);factor=cell.coverage_id.split(':')[1].split('+')[0]
    enabled=factor in cell.runtime_arm.data()['enabled']
    result={'prediction_proposal':None,'prediction_plan':None,'reviews':[],'retrieval':retrieval}
    if factor=='M4':
        response=invoke('m4_plan',PREDICTION_INSTRUCTION,FrozenRecord.from_dict({**context,'measurement':MEASUREMENT}))
        b=response.data()
        if (set(b)!={'question','branches','budget_units'} or b['budget_units']!=3 or len(b['branches'])!=3
                or any(p['observable']!=MEASUREMENT['observable'] or p['discriminator_id']!=MEASUREMENT['discriminator_id']
                    for branch in b['branches'] for p in branch['predictions'])):
            raise ContractError('predictions must address the declared fresh target measurement')
        # Validate operational usefulness in both arms; only on persists a registry.
        checked=PredictionRegistry(task.identity).freeze(b['question'],b['branches'],budget_units=3)
        plan=predictions.freeze(b['question'],b['branches'],budget_units=3) if enabled else None
        result.update(prediction_proposal=b,prediction_plan=plan.payload.data() if plan else None)
        record('mechanism_improvement_prediction',{'proposal_digest':response.content_hash,'measurement':MEASUREMENT,
            'registered_plan':plan.data() if plan else None})
    elif factor=='M5':
        session=reviews.open(task_binding=task.content_hash,evidence_snapshot=FrozenRecord.from_dict(context).content_hash,
            roles=[{'role_id':role,'question':question} for role,question in ROLES],budget_units=2) if enabled else None
        responses=[]
        for slot,(role,question) in zip(slots(cell.coverage_id)[:2],ROLES,strict=True):
            response=invoke(slot,REVIEW_INSTRUCTION,FrozenRecord.from_dict({**context,'question':question,
                'prior_responses':[] if session else [r.data() for r in responses]}))
            ReviewEngine._response(response.data());responses.append(response)
            if session:reviews.submit(session.review_id,role_id=role,reviewer_id=role,response=response.data(),cost_units=1)
            record('mechanism_improvement_review_submission',{'slot':slot,'response_digest':response.content_hash,
                'barrier_open':reviews.barrier_open(session.review_id) if session else None})
        revealed=reviews.reveal(session.review_id) if session else None
        record('mechanism_improvement_review_reveal',{'submissions':[r.data() for r in revealed] if revealed else None})
        result['reviews']=[r.data() for r in responses]
    return FrozenRecord.from_dict({'schema':'mechanism-improvement-public-joint-v1',**context,**result})


def execute_retrieval(session,task,material,provider,enabled):
    from research_loop.modular.retrieval_review_combination_driver import check_material
    docs=check_material(material.retrieval(),task);pool=FrozenSourceBundle('public-train-retrieval-pool-v1',docs)
    admitted=admission_receipt(task,pool)
    session._record('q8_source_admission',{'receipt':admitted.data(),'receipt_digest':admitted.content_hash})
    projection,usage=_select_sources(provider,session,docs,material.retrieval().data()['query'],BUDGET,'Q8.3','three_lane',enabled)
    session._record('retrieval_review_sources',{'projection':projection,'usage':usage})
    return public_retrieval(projection)
