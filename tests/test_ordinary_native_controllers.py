"""Default native entry, registered ordinary routes, Docker and process scorers.

Existing public synthetic response functions are reused below the OS spawn seam.
The wrapper around each test's entry reference only supplies the new frozen
configuration; the real production controller and its validators still execute.
"""
import importlib
import json
from pathlib import Path

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.train_provider_preflight import NATIVE_SCHEMAS, LEGACY_TRANSPORT_FIELDS
from helpers.native_ordinary_provider import native_ordinary_provider
from research_loop.ontology import ContractError


FAMILIES = ('state_prediction','state_retrieval','state_exploration','state_scheduling',
    'mechanism_exploration','mechanism_scheduling','admission_prediction_exploration',
    'lineage','admission','retrieval_review','exploration_scheduler')


def prepared(root,family):
    if family in {'lineage','admission'}:
        module=importlib.import_module('test_lineage_useful_controls')
        return module.configured(root,family)
    if family=='retrieval_review':
        return importlib.import_module('test_combination_prospective_train_source').prepare(root,'retrieval')
    if family=='exploration_scheduler':
        return importlib.import_module('test_remaining_prospective_train_sources').prepare_controller(root,'scheduler')
    module=importlib.import_module('test_'+family+('_controller' if family=='admission_prediction_exploration' else '_train_controller'))
    return module.prepare(root)


def converted(config,provider,family):
    body={k:v for k,v in config.data().items() if k not in LEGACY_TRANSPORT_FIELDS}
    body.update(schema=NATIVE_SCHEMAS[family],provider=provider.configuration().data())
    return type(config)(FrozenRecord.from_dict(body))


def invoke_native(setup,patch,family,*,fault=None):
    if family=='lineage':
        module=importlib.import_module('test_lineage_useful_controls')
        invoke=lambda:module.run_lineage_processes(setup,patch)
        owner,name=module,'run_lineage_train_panels'
    elif family in {'admission','exploration_scheduler'}:
        module=importlib.import_module('test_remaining_prospective_train_sources')
        invoke=lambda:module.invoke_controller(setup,patch)
        owner=module.adm if family=='admission' else module.es
        name='run_admission_train_panels' if family=='admission' else 'run_exploration_scheduler_train_panel'
    elif family=='retrieval_review':
        module=importlib.import_module('test_combination_prospective_train_source')
        invoke=lambda:module.run(setup,patch)
        owner,name=module.retrieval,'run_retrieval_review_panels'
    else:
        module=importlib.import_module('test_'+family+('_controller' if family=='admission_prediction_exploration' else '_train_controller'))
        invoke=lambda:module.invoke(setup,patch)
        owner,name=module,'run_'+family+'_train_panels'
    observed={};original=getattr(owner,name)
    def factory(root,monkeypatch,*,max_calls,schemas,response_factory,**kwargs):
        provider,logs=native_ordinary_provider(root,monkeypatch,schemas=schemas,max_calls=max_calls,
            response=response_factory,fault_at=2 if fault=='unknown_main' else None)
        observed.update(provider=provider,logs=logs)
        return provider
    def entry(config,**kwargs):
        native=converted(config,kwargs['model'],family)
        observed['config']=native
        (setup['root']/'native-config.json').write_bytes(native.record.encoded.encode())
        if fault in {'provenance','last_provenance'}:
            # Corrupt a successful prefix only after the first independent score
            # has returned. Subsequent accounting must abort before dispatch.
            services=kwargs.get('scoring_services',kwargs.get('scoring_service'))
            if isinstance(services,dict):service=next(iter(services.values()))
            else:service=services
            score_name='score_lineage' if family=='lineage' else 'score_combination'
            score=getattr(service,score_name)
            score_count=0
            def corrupt_after_score(**args):
                nonlocal score_count
                value=score(**args)
                score_count+=1
                if fault=='provenance' or score_count==8:
                    path=observed['provider'].backend.calls_root
                    target=next(path.glob('*/response.private.json'))
                    target.write_bytes(b'{"synthetic_original_drift":true}')
                return value
            patch.setattr(service,score_name,corrupt_after_score)
        return original(native,**kwargs)
    patch.setattr(module,'model_port',factory)
    patch.setattr(owner,name,entry)
    value=invoke()
    return value[0],observed


@pytest.mark.parametrize('family',FAMILIES)
def test_each_registered_family_native_configuration_preserves_compiled_cells(tmp_path,monkeypatch,family):
    setup=prepared(tmp_path,family);old=setup['config'];body=old.data()
    provider,logs=native_ordinary_provider(tmp_path/'native-provider',monkeypatch,schemas=body['schemas'],
        max_calls=body['max_calls'],response=lambda request:{})
    config=converted(old,provider,family)
    assert not LEGACY_TRANSPORT_FIELDS & set(config.data())
    # The provider envelope changes; scientific designs and source materials do not.
    for key in ('allocation','task_bindings','packages_by_arm','scorer'):
        assert config.data()[key]==body[key]
    changed=config.data();changed['provider']['limits']['main_opportunities']-=1
    with pytest.raises(ContractError):type(old)(FrozenRecord.from_dict(changed))
    changed=config.data();changed['schemas']=body['schemas']
    with pytest.raises(ContractError):type(old)(FrozenRecord.from_dict(changed))
    assert logs==[]


@pytest.mark.parametrize('family',FAMILIES)
def test_full_registered_family_default_native_docker_and_process_scores(tmp_path,monkeypatch,family):
    setup=prepared(tmp_path,family)
    expected_calls=setup['config'].data()['max_calls']
    compiled=setup['compiled'];panels=compiled.panels if hasattr(compiled,'panels') else (compiled.panel,)
    expected_cells=sum(len(p.cells) for p in panels)
    result,observed=invoke_native(setup,monkeypatch,family)
    rows=[a.data() for a in result.attempts]
    assert len(rows)==len(result.results)==len(result.scores)==expected_cells,[r for r in rows if r['status']!='succeeded']
    assert all(row['status']=='succeeded' and row['provider_seal_digest'] for row in rows)
    assert len(observed['logs'])==expected_calls
    assert result.receipt.data()['actual_model_usage']['main_opportunities']==expected_calls
    assert result.receipt.data()['actual_model_usage']['known_usage_scope']=='native_main'
    assert result.receipt.data()['actual_model_usage']['possible_initial_title_opportunities']==expected_calls
    assert result.receipt.data()['actual_model_usage']['all_opportunity_tokens'] is None
    assert result.receipt.data()['scientific_effectiveness_proven'] is False
    assert result.receipt.data()['validation_opened'] is False
    assert set(p.obligation_id for p in panels)==set(p.obligation_id for p in (result.compiled.panels if hasattr(result.compiled,'panels') else (result.compiled.panel,)))
    assert all(r['docker_attempts']>=1 and r['scorer_calls']==1 for r in rows)
    assert result.receipt.data()['provider_final_gate']['provider_evidence_eligible'] is True
    assert result.receipt.data()['eligible_scored_cells']==expected_cells


def test_last_score_original_fault_keeps_historical_scores_but_no_eligible_contrast(tmp_path,monkeypatch):
    setup=prepared(tmp_path,'exploration_scheduler')
    result,observed=invoke_native(setup,monkeypatch,'exploration_scheduler',fault='last_provenance')
    receipt=result.receipt.data();rows=[r.data() for r in result.attempts]
    assert len(rows)==len(result.scores)==8 and len(observed['logs'])==16
    assert receipt['status']=='inconclusive' and receipt['pruned_cells']==[]
    assert receipt['provider_final_gate']['provider_evidence_eligible'] is False
    assert receipt['eligible_scored_cells']==0 and len(receipt['historical_score_receipt_digests'])==8
    assert result.contrast.data()['reason']=='provider_final_provenance_unavailable'
    assert result.contrast.data()['status']=='inconclusive'
    assert receipt['actual_model_usage']['known_reported_tokens_lower_bound']==192
    assert receipt['actual_model_usage']['current_originals_verified'] is False
    assert rows[-1]['status']=='failed'


@pytest.mark.parametrize('fault',['unknown_main','provenance'])
def test_native_failure_preserves_full_planned_rows_and_known_main_lower_bound(tmp_path,monkeypatch,fault):
    setup=prepared(tmp_path,'state_prediction')
    result,observed=invoke_native(setup,monkeypatch,'state_prediction',fault=fault)
    rows=[r.data() for r in result.attempts]
    assert len(rows)==len(result.results)==24
    assert result.receipt.data()['expected_cells']==24 and result.receipt.data()['status']=='inconclusive'
    assert any(r['status']=='blocked' for r in rows) and result.receipt.data()['pruned_cells']==[]
    assert len(observed['logs'])==(2 if fault=='unknown_main' else 3)
    usage=result.receipt.data()['actual_model_usage']
    if fault=='provenance':
        assert usage['schema']=='public-train-provider-terminal-snapshot-v1'
        assert usage['known_reported_tokens_lower_bound']==36
        assert usage['current_originals_verified'] is False
        assert result.receipt.data()['unused_model_opportunities'] is None
    else:
        assert usage['known_reported_tokens']==24 and usage['unknown_main_opportunities']==1
        assert result.receipt.data()['unused_model_opportunities']==70
