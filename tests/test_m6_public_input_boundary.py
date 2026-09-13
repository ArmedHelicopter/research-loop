"""Scoped structural projection of the preserved real M6 model requests."""
import json
from pathlib import Path
import pytest
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.m6_public_inputs import M6PublicInputBoundary
from research_loop.ontology import ContractError

ROOT=Path(__file__).resolve().parents[1]/'results/modular-engineering-20260913/m6-public-input/original-finding'

def test_all_original_retrieval_projections_drop_controller_digests():
    rows=json.loads((ROOT/'actual-requests.json').read_text(encoding='utf-8'))
    assert len(rows)==156 and sum(len(r['requests']) for r in rows)==364
    for row in rows:
        boundary=M6PublicInputBoundary(row['cell']['coverage_id'],row['cell']['variant'])
        for request in row['requests']:
            public=boundary.project(request['slot'],FrozenRecord.from_dict(request['module_context'])).data()
            def walk(v):
                if isinstance(v,dict):
                    assert not {'policy_digest','source_bundle_digest','review_mode','caller_authorized'} & set(v)
                    for x in v.values():walk(x)
                elif isinstance(v,list):
                    for x in v:walk(x)
            walk(public)

def test_observation_words_are_not_filtered():
    boundary=M6PublicInputBoundary('Q8.7','anomaly')
    observation={'policy_digest':'measured variable','review_mode':'observed instrument setting'}
    raw={'kind':'anomaly','identity':{},'task_digest':'t','execution':{'status':'succeeded','record':{'stdout':'review_mode policy_digest','stderr':'','exit_code':0}},'expected_observation':observation}
    public=boundary.project('frontier_review_a',FrozenRecord.from_dict(raw)).data()
    assert public['expected_observation']==observation
    assert public['execution']['record']['stdout']=='review_mode policy_digest'


def verify_actual_public_requests(events):
    """Read-only independent key/value and source-binding checks on real I/O."""
    records=[e['data'] for e in events if e['stage']=='q8_public_model_context']
    requests=[e['data']['request'] for e in events if e['stage']=='model_request']
    assert len(records)==len(requests)
    forbidden_digests=set()
    def digests(row):
        if isinstance(row,dict):
            for key,value in row.items():
                if key in {'policy_digest','source_bundle_digest'}:forbidden_digests.add(value)
                digests(value)
        elif isinstance(row,list):
            for value in row:digests(value)
    for record in records:digests(record['controller_context'])
    for record,request in zip(records,requests):
        raw=record['controller_context'];public=request['module_context']
        assert record['slot']==request['slot']
        assert {k:v for k,v in public.items() if k!='deployment'}==record['public_context']
        assert FrozenRecord.from_dict(record['public_context']).content_hash==record['public_digest']
        encoded=FrozenRecord.from_dict(request).encoded
        assert all(digest not in encoded for digest in forbidden_digests)
        slot=request['slot']
        if 'retrieval' in raw:
            assert public['retrieval']=={k:raw['retrieval'][k] for k in ('by_lane','source_qualification','scientific_admission')}
        if slot=='review':
            assert 'goal_lock' not in public
            assert public['typed_request']==({k:raw['typed_request'][k] for k in ('operation','source_id','proposed_objective')} if raw['typed_request'] else None)
        if slot in {'review_a','review_b'}:
            assert set(public)=={'question','role'}
        if slot.startswith('retro_'):
            assert set(public)<={'history_summary','sealed_first_review'}
            assert public=={k:raw[k] for k in public}
        if slot=='final':
            key=next(k for k in raw if k in {'retrieval_stage_result','retrieval_final_result'})
            original,detail=raw[key],public[key]
            assert not {'unit_basis','source_bundle_digest','review_mode','execution_authority_digest'} & set(detail)
            if 'retrieval' in original:
                assert detail['retrieval']=={k:original['retrieval'][k] for k in ('by_lane','source_qualification','scientific_admission')}
            if 'units' in original:assert detail['units']==original['units']
            if 'research_version' in original:
                a,b=original['research_version'],detail['research_version']
                assert set(b)=={'state','objective_digest','child'} and b['state']==a['state']
                assert b['child']==({k:a['child'][k] for k in ('new_objective','state')} if a['child'] else None)
            if 'review_result' in detail:assert set(detail['review_result'])<={'status','correctness'}
        if slot in {'frontier_review_a','frontier_review_b'}:
            assert not {'sealed','review_id','control'} & set(public)
            a=raw.get('origin',raw);b=public.get('origin',public)
            assert not {'plan_trace','declaration','input_bytes_hex','execution_digest'} & set(b)
            if 'plan' in a or 'plan_trace' in a:
                plan=a['plan'] if 'plan' in a else a['plan_trace']['data']['plan']
                assert b['plan']=={k:plan[k] for k in ('question','branches','budget_units')}
            if 'execution' in a:
                assert b['execution']=={'status':a['execution']['status'],'record':{k:a['execution']['record'][k] for k in ('stdout','stderr','exit_code','status') if k in a['execution']['record']}}
                assert b['expected_observation']==a['expected_observation']
        if slot=='frontier':
            assert 'catalog_digest' not in public
            assert list(public['frontier_catalog'])==['origin-'+str(i) for i in range(len(raw['frontier_catalog']))]
            if 'review_context' in raw:assert public['review_context']=={'responses':raw['review_context']['responses']}
            for a,b in zip(raw['frontier_catalog'].values(),public['frontier_catalog'].values()):
                assert a['kind']==b['kind'] and not {'trace','registered','observation'} & set(b)
                if 'plan' in a or a['kind']=='untested':
                    plan=a.get('plan',a.get('trace',{}).get('data',{}).get('plan'))
                    assert b['plan']=={k:plan[k] for k in ('question','branches','budget_units')}
                if a['kind']=='anomaly':
                    content=a['observation']['payload']['content']
                    assert b['expected_observation']==content['expected_observation']
                    assert b['execution']['record']['stdout']==content['execution']['record']['stdout']
                if a['kind']=='failed_check' and a['trace']['stage']=='execution_result':
                    assert b['execution']['status']=='failed'
                    assert b['execution']['record']['stderr']==a['trace']['data']['receipt']['record']['stderr']
    for event in events:
        if event['stage']!='q8_public_frontier_binding':continue
        binding=event['data'];mapping=binding['references']
        assert len(set(mapping.values()))==len(mapping)
        for public,original in zip(binding['public_response']['proposals'],binding['controller_response']['proposals']):
            assert original=={**public,'origin_ref':mapping[public['origin_ref']]}
    return len(requests)


def test_frontier_aliases_cannot_add_origins_or_change_proposal_content():
    boundary=M6PublicInputBoundary('Q8.7','untested')
    raw={'frontier_catalog':{'candidate-plan:secret':{'kind':'untested','trace':{'data':{'plan':{'question':'q','branches':[],'budget_units':1}}}}},'catalog_digest':'hidden'}
    public=boundary.project('frontier',FrozenRecord.from_dict(raw)).data()
    assert set(public['frontier_catalog'])=={'origin-0'}
    body={'proposals':[{'origin_ref':'origin-0','question':'same actual question'}],'programme_complete':False,'empty_reason':None}
    result=boundary.restore_frontier_response(FrozenRecord.from_dict(body)).data()
    assert result=={**body,'proposals':[{**body['proposals'][0],'origin_ref':'candidate-plan:secret'}]}
    body['proposals'][0]['origin_ref']='origin-1'
    with pytest.raises(ContractError,match='unknown public origin'):
        boundary.restore_frontier_response(FrozenRecord.from_dict(body))
