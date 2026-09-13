"""Replay actual Q3.2/Q5.3 artifacts before exposing their public projection."""
import hashlib
from pathlib import Path
from collections.abc import Mapping

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.modules.predictions import (PredictionRegistry, freeze_shared_experiment,
    deduplicate_mechanism_predictions, deduplicate_titles)
from research_loop.modular.panel_receipts import opaque_panel_cell_binding
from research_loop.modular.prediction_panel_drivers import _material, _dedup_inputs, _response_plan, _kept_response
from research_loop.ontology import ContractError, canonical


def verify_prediction_chronology(cell, events):
    """Check the original event order before flattening evidence into stages.

    Q3.2 has three ordered confirmations and one aggregate operation event.
    The aggregate and its artifacts must exist before the final model request.
    """
    slots = ['plan_1', 'plan_2', 'plan_3', 'final'] if cell.coverage_id == 'Q3.2' else ['dedup', 'final']
    requests = [(index, event['data']) for index, event in enumerate(events)
                if event['stage'] == 'model_request']
    responses = [(index, event['data']) for index, event in enumerate(events)
                 if event['stage'] == 'model_response']
    if [data['request']['slot'] for _, data in requests] != slots or len(responses) != len(slots):
        raise ContractError('prediction chronology: unexpected model schedule')
    previous_response = -1
    response_positions = []
    for position, data in requests:
        matches = [index for index, response in responses
                   if response['request_digest'] == data['request_digest']]
        if len(matches) != 1 or not previous_response < position < matches[0]:
            raise ContractError('prediction chronology: unordered or unbound response')
        previous_response = matches[0]
        response_positions.append(previous_response)
    operation = 'stage_1' if 'M4' in cell.runtime_arm.data()['enabled'] else 'operation_m4_control'
    stages = [(index, event['data']['stage']) for index, event in enumerate(events)
              if event['stage'] == 'modular_workflow'
              and event['data'].get('stage') in {'stage_1', 'operation_m4_control', 'prediction_artifacts'}]
    if [stage for _, stage in stages] != [operation, 'prediction_artifacts']:
        raise ContractError('prediction chronology: missing, extra, or reordered prediction stage')
    if not response_positions[-2] < stages[0][0] < stages[1][0] < requests[-1][0]:
        raise ContractError('prediction chronology: prediction freeze must precede final request')


def prediction_registry_observation(sidecar):
    path=Path(sidecar)/'predictions.jsonl'
    if not path.is_file() or path.is_symlink() or path.is_junction():
        raise ContractError('linked prediction requires its actual persisted registry')
    raw=path.read_bytes()
    try:
        events=[FrozenRecord(line).data() for line in raw.decode('utf-8').splitlines()]
    except (ValueError, UnicodeError) as exc:
        raise ContractError('linked prediction registry is not canonical JSONL') from exc
    if raw!=''.join(canonical(event)+'\n' for event in events).encode():
        raise ContractError('linked prediction registry has noncanonical bytes')
    return {'stage':'prediction_registry_observation','data':{'events':events,
            'sha256':hashlib.sha256(raw).hexdigest()}}


def prediction_public_material(cell,task,scenario,body,calls):
    evidence,selected=_material(task,scenario,cell.coverage_id,cell.variant)
    enabled='M4' in cell.runtime_arm.data()['enabled']
    expected_slots=['plan_1','plan_2','plan_3','final'] if cell.coverage_id=='Q3.2' else ['dedup','final']
    if list(calls)!=expected_slots:
        raise ContractError('linked prediction precursor slot schedule differs')
    request_by_slot={row['slot']:row['request'] for row in body['responses']}
    stages={}
    for row in body['mechanism_stages']:
        if not isinstance(row,Mapping) or set(row)!={'stage','data'} or row['stage'] in stages:
            raise ContractError('linked prediction has duplicate or malformed stages')
        stages[row['stage']]=row['data']
    operation='stage_1' if enabled else 'operation_m4_control'
    if set(stages)!={operation,'prediction_artifacts','prediction_registry_observation'}:
        raise ContractError('linked prediction stage does not bind the frozen arm')
    registry=PredictionRegistry(task.identity); registry_events=[]
    def freeze(plan,branches=None):
        frozen=freeze_shared_experiment(registry,plan['question'],plan['branches'] if branches is None else branches,
                                       budget_units=plan['budget_units'])
        event={'event':'freeze','identity':task.identity.data(),'plan_id':frozen.plan_id,
               **frozen.payload.data()}
        # Joint planning confirms the same frozen experiment in three slots.
        if event not in registry_events: registry_events.append(event)
        return frozen.payload.data()
    def check_request(slot,context):
        if request_by_slot[slot].get('module_context')!=dict(panel_cell=opaque_panel_cell_binding(cell),**context):
            raise ContractError('linked prediction material differs from the actual precursor request')
    if cell.coverage_id=='Q3.2':
        artifacts=[];public=[]
        for index in range(3):
            plan=selected['plans'][0] if cell.variant=='joint' else selected['plans'][index]
            slot='plan_'+str(index+1)
            observations=[{key:row[key] for key in ('source_id','observation_id','public_observation','branch_ids')}
                          for row in plan['support_records']]
            plan_material={key:plan[key] for key in ('question','branches','budget_units')}
            check_request(slot,{'public_evidence':evidence,'plan_material':dict(plan_material,observations=observations)})
            response=calls[slot]
            if enabled: _response_plan(FrozenRecord.from_dict(response),plan)
            frozen=freeze(plan) if enabled else None
            artifacts.append({'plan':frozen,'support_records':plan['support_records'],'response':response,
                'planning_status':'planning_only' if enabled else 'not_applied','execution_status':'not_measured'})
            public.append({'prediction_plan':frozen,'assessment':response,'observations':observations})
        expected_artifacts={'joint_or_separate':artifacts};public_artifacts={'plans':public}
        operation_data={'stage':operation,'status':'executed','artifact_count':3,
                        'planning_status':'planning_only','execution_status':'not_measured'}
    elif cell.coverage_id=='Q5.3':
        plan,proposals=selected['plan'],selected['proposals']
        inputs=_dedup_inputs(proposals)
        mechanism_kept,mechanism_removed=deduplicate_mechanism_predictions(inputs)
        title_kept,title_removed=deduplicate_titles(inputs)
        kept,removed=(mechanism_kept,mechanism_removed) if enabled else (title_kept,title_removed)
        check_request('dedup',{'public_evidence':evidence,'proposals':proposals,'plan_material':plan,
                              'retained_proposal_ids':list(kept)})
        _kept_response(FrozenRecord.from_dict(calls['dedup']),kept)
        by_id={b['hypothesis_id']:b for b in plan['branches']};retained=[by_id[k] for k in kept]
        frozen=freeze(plan,retained) if enabled and len(retained)>=2 else None
        status=('planning_only' if len(retained)>=2 else 'not_distinguishable_after_dedup') if enabled else 'title_baseline'
        artifact={'kept':list(kept),'removed':list(removed),'title_baseline':{'kept':list(title_kept),'removed':list(title_removed)},
                  'plan':frozen,'response':calls['dedup'],'planning_status':status,'execution_status':'not_measured',
                  'retained_branches':retained}
        expected_artifacts={'deduplication':artifact}
        public_artifacts={'retained_branches':retained,'prediction_plan':frozen,'assessment':calls['dedup']}
        operation_data={'stage':operation,'status':'executed','dedup_applied':enabled,
                        'planning_status':status,'execution_status':'not_measured'}
    else:
        raise ContractError('unknown linked prediction scope')
    if stages[operation]!=operation_data or stages['prediction_artifacts']!={
            'stage':'prediction_artifacts','status':'executed','artifacts':expected_artifacts}:
        raise ContractError('linked prediction actual artifacts differ from their source replay')
    registry_bytes=''.join(canonical(event)+'\n' for event in registry_events).encode()
    if stages['prediction_registry_observation']!={'events':registry_events,'sha256':hashlib.sha256(registry_bytes).hexdigest()}:
        raise ContractError('linked prediction persisted registry differs from its source replay')
    check_request('final',{'required_objective_digest':calls['final'].get('objective_digest'),
                           'prediction_artifacts':public_artifacts})
    return {'kind':'operational_prediction_material',**public_artifacts}
