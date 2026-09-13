"""Scoped structural projection of the preserved real M6 model requests."""
import json
from pathlib import Path
import pytest
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.m6_public_inputs import M6PublicInputBoundary

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
