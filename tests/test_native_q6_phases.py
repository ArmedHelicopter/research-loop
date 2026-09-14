"""Separate native Q6 phases retain TRAIN-only operations and full denominators."""
import importlib
import json
from pathlib import Path

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.phase_provider import provider_configuration
from research_loop.modular.phase_provider import PhaseProviderAbort
from research_loop.modular.train_provider import GrokTrainProvider
from research_loop.modular.metaprogram_training import run_metaprogram_training,verify_metaprogram_training
from research_loop.modular.improvement_training import freeze_candidate_training,run_candidate_training
from research_loop.modular.modules.improvement import FrozenBuilderVersion
from research_loop.modular.train_operations import run_train_operations,verify_train_operations
from helpers.native_phase_provider import native_phase_provider


def prepare_native(root,patch,experiment,*,fault_at=None):
    operation=experiment in {'Q6.1','Q6.5','Q6.6'}
    module=importlib.import_module('test_modular_train_operations' if operation else 'test_modular_metaprogram_training')
    original=module.model_port;configuration=module.model_configuration
    calls={'Q6.1':48,'Q6.2':36,'Q6.3':24,'Q6.5':48,'Q6.6':60}[experiment];logs=[]
    def port(path,monkeypatch,**kwargs):
        wanted='operation-port' if operation else 'stage-port'
        if Path(path).name!=wanted:return original(path,monkeypatch,**kwargs)
        result,actual=native_phase_provider(path,monkeypatch,schemas=kwargs['schemas'],max_calls=calls,
            response=kwargs['response_factory'],fault_at=fault_at)
        logs.append(actual);return result
    patch.setattr(module,'model_port',port)
    patch.setattr(module,'model_configuration',lambda model:provider_configuration(model) if type(model) is GrokTrainProvider else configuration(model))
    if operation:
        plan,args,seen,feedback=module.operation_fixture(root,patch,experiment)
    else:
        plan,args,seen,_=module.fixture(root,patch,max_calls=calls);feedback=[]
        if experiment=='Q6.2':
            manual=FrozenBuilderVersion.freeze({'entrypoint':'emit_literal_change_v1','surface':'memory','key':'lesson','value':'Use statistic=mean'})
            body=plan.record.data()
            plan=freeze_candidate_training(targets=plan.targets,histories=plan.histories,parent=plan.parent,
                fixed_builder=plan.fixed_builder,manual_builder=manual,baseline_digest=body['baseline_digest'],
                p0_control=FrozenRecord.from_dict(body['p0_control']),image=body['image'],model_config=provider_configuration(args['model']))
    return plan,args,seen,feedback,logs[0]


@pytest.mark.parametrize('experiment',['Q6.1','Q6.2','Q6.3','Q6.5','Q6.6'])
def test_all_separate_native_q6_phases_execute_real_builders_and_successors(tmp_path,monkeypatch,experiment):
    plan,args,seen,feedback,logs=prepare_native(tmp_path,monkeypatch,experiment)
    operation=experiment in {'Q6.1','Q6.5','Q6.6'}
    fn=run_train_operations if operation else run_candidate_training if experiment=='Q6.2' else run_metaprogram_training
    run=fn(plan,**args);receipt=run.receipt.data();actual=receipt['actual']
    count={'Q6.1':16,'Q6.2':12,'Q6.3':8,'Q6.5':16,'Q6.6':20}[experiment]
    expected_calls={'Q6.1':48,'Q6.2':36,'Q6.3':24,'Q6.5':48,'Q6.6':44}[experiment]
    assert len(run.cells)==count and actual['provider_calls']==expected_calls==len(logs)
    assert actual['known_reported_tokens']==expected_calls*12
    assert actual['possible_initial_title_opportunities']==expected_calls
    assert actual['unknown_main_opportunities']==0 and actual['settled_additional_charge_usd'] is None
    assert actual['builder_attempts']==count and actual['docker_attempts']==(12 if experiment=='Q6.6' else count)
    assert receipt['schema'].endswith('-v2') and receipt['scientific_effect']=='not_measured'
    if operation:
        assert receipt['production_promotion']=='not_authorized'
        assert verify_train_operations(run,plan=plan,authority=args['authority']).data()['observed_cells']==count
        for declared,cell in zip(plan.record.data()['cells'],run.cells):
            record=json.loads((cell.root/'host-operation'/'receipt.json').read_bytes())['record']
            assert record['production_promotion']=='not_authorized'
            if experiment=='Q6.1':assert record['status']=='rejected'
            if experiment=='Q6.6' and declared['variant'] in {'drift','offline'}:
                assert record['status']=='blocked' and not (cell.root/'solver').exists()
            if experiment=='Q6.6' and declared['variant']=='rollback':
                events=[json.loads(line) for line in (cell.root/'solver'/'trace.jsonl').read_text().splitlines()]
                assert json.loads(events[-2]['data']['response']['conclusion'])['statistic']=='sum'
        if experiment=='Q6.5':assert len(feedback)==16
    else:
        assert receipt['builder_activation']=='not_performed' and receipt['scoring']=='not_configured'
        assert verify_metaprogram_training(run,plan=plan).data()['observed_cells']==count
        assert plan.experiment_id==experiment
        assert all((cell.root/'builder-receipt.json').is_file() and (cell.root/'solver'/'trace.jsonl').is_file() for cell in run.cells)
    assert len(run.provider_ledger.record.data()['scopes']['scopes'])==count


def test_native_q63_failure_retains_eight_allocated_cells_and_known_main(tmp_path,monkeypatch):
    plan,args,_,_,logs=prepare_native(tmp_path,monkeypatch,'Q6.3',fault_at=1)
    run=run_metaprogram_training(plan,**args);b=run.receipt.data()
    assert len(run.cells)==8 and len(logs)==1 and b['status']=='engineering_incomplete'
    assert b['actual']['known_reported_tokens']==12 and b['actual']['unknown_main_opportunities']==1
    assert b['actual']['provider_calls']==1 and b['actual']['builder_attempts']==b['actual']['docker_attempts']==0
    assert b['builder_activation']=='not_performed'
    assert verify_metaprogram_training(run,plan=plan).data()['observed_cells']==8


@pytest.mark.parametrize('experiment',['Q6.3','Q6.5'])
def test_native_q6_original_drift_stops_with_all_planned_rows_and_unresolved_scope(tmp_path,monkeypatch,experiment):
    from research_loop.modular import metaprogram_training as phase
    plan,args,_,feedback,logs=prepare_native(tmp_path,monkeypatch,experiment)
    original=phase._run_cell
    def corrupt(*a,**k):
        result=original(*a,**k)
        path=args['model'].backend.calls_root/'0001-builder_proposal'/'response.private.json'
        path.write_bytes(path.read_bytes()+b' ')
        return result
    monkeypatch.setattr(phase,'_run_cell',corrupt)
    run=(run_train_operations if experiment=='Q6.5' else run_metaprogram_training)(plan,**args)
    b=run.receipt.data();count=16 if experiment=='Q6.5' else 8
    assert type(run.provider_ledger) is PhaseProviderAbort and b['status']=='engineering_incomplete'
    assert b['expected_cells']==len(b['attempts'])==count and b['observed_cell_receipts']==1
    assert b['attempts'][0]['status']=='executed_unverified'
    assert all(row['status']=='blocked' for row in b['attempts'][1:])
    assert len(logs)==3 and b['provider_snapshot']['observed_main_opportunities_lower_bound']==3
    assert b['provider_snapshot']['known_reported_tokens_lower_bound']==36
    assert b['exact_unused_main_opportunities'] is None and not b['current_originals_verified']
    assert run.provider_ledger.record.data()['unresolved_scope']['scope_id']==plan.record.data()['cells'][0]['cell_id']
    checked=(verify_train_operations(run,plan=plan,authority=args['authority']) if experiment=='Q6.5'
        else verify_metaprogram_training(run,plan=plan)).data()
    assert checked['status']=='terminal_accounting_only' and not checked['engineering_verified']
    assert len(feedback)==(1 if experiment=='Q6.5' else 0)
