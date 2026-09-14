"""Four complete native M9 routes with actual builders, Docker and scorers."""
import importlib
from pathlib import Path

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.phase_provider import PhaseProviderLedger, provider_configuration
from research_loop.modular.train_provider import GrokTrainProvider
from research_loop.ontology import ContractError
from helpers.native_phase_provider import native_phase_provider

FAMILIES={
    'state':('FrozenStateImprovementPlan',55,11,22,22),
    'mechanism':('FrozenMechanismImprovementPlan',78,6,24,24),
    'execution':('FrozenExecutionImprovementPlan',70,6,32,96),
    'lineage_retrieval':('FrozenLineageRetrievalImprovementPlan',34,2,16,16),
}


def prepare_native(root,patch,family,*,fault_at=None):
    module=importlib.import_module('test_'+family+'_improvement_train_controller')
    original_port=module.model_port;old_config=module.model_configuration
    cls=getattr(module,FAMILIES[family][0]);logs=[]
    def port(path,monkeypatch,**kwargs):
        if Path(path).name!='port':return original_port(path,monkeypatch,**kwargs)
        result,actual=native_phase_provider(path,monkeypatch,schemas=kwargs['schemas'],max_calls=kwargs['max_calls'],
            response=kwargs['response_factory'],fault_at=fault_at)
        logs.append(actual);return result
    def plan(record,*args):
        body=record.data();body['schema']=body['schema'].removesuffix('v1')+'v2'
        return cls(FrozenRecord.from_dict(body),*args)
    patch.setattr(module,'model_port',port)
    patch.setattr(module,'model_configuration',lambda model:provider_configuration(model) if type(model) is GrokTrainProvider else old_config(model))
    patch.setattr(module,FAMILIES[family][0],plan)
    setup=module.prepare(root,patch);setup['native_logs']=logs[0]
    return module,setup


@pytest.mark.parametrize('family',FAMILIES)
def test_complete_native_build_barrier_target_and_score(family,tmp_path,monkeypatch):
    module,setup=prepare_native(tmp_path,monkeypatch,family)
    run=module.invoke(setup,monkeypatch);b=run.receipt.data()
    _,calls,builds,targets,docker=FAMILIES[family]
    assert b['status']=='complete_train_engineering', {'family':family,'receipt':b}
    assert b['schema'].endswith('-v2') and run.barrier.record.data()['schema'].endswith('-v2')
    assert b['scored_cells']==b['actual_scorer_calls']==targets
    assert b['actual_builder_executions']==builds and b['actual_docker_attempts']==docker
    assert b['actual_model_usage']['main_opportunities']==calls
    assert b['actual_model_usage']['known_reported_tokens']==calls*12
    assert b['actual_model_usage']['possible_initial_title_opportunities']==calls
    assert b['actual_model_usage']['settled_additional_charge_usd'] is None
    assert not b['validation_opened'] and not b['scientific_effectiveness_proven']
    assert len(setup['native_logs'])==calls and type(run.ledger) is PhaseProviderLedger
    run.barrier.verify();run.ledger.verify()
    scopes=run.ledger.record.data()['scopes']['scopes']
    assert len(scopes)==builds+targets
    assert [n for row in scopes for n in row['call_ids']]==list(range(1,calls+1))
    assert [len(s['call_ids']) for s in scopes[:builds]]==[1]*builds
    assert all(r.record.data()['schema']=='state-improvement-build-receipt-v2' for r in run.builds)
    assert b['unused_model_opportunities']==0 and b['pruned_cells']==[]


@pytest.mark.parametrize('fault_at',[1,12])
def test_unknown_native_history_or_target_retains_complete_state_denominator(tmp_path,monkeypatch,fault_at):
    module,setup=prepare_native(tmp_path,monkeypatch,'state',fault_at=fault_at)
    run=module.invoke(setup,monkeypatch);b=run.receipt.data()
    assert b['expected_builds']==11 and b['expected_cells']==22 and len(b['structural_exclusions'])==2
    assert b['actual_model_usage']['main_opportunities']==fault_at
    assert b['actual_model_usage']['known_reported_tokens']==fault_at*12
    assert b['actual_model_usage']['unknown_main_opportunities']==1
    assert b['scored_cells']==b['actual_scorer_calls']==0 and b['status']=='inconclusive'
    assert b['blocked_cells']==(22 if fault_at==1 else 21)
    assert b['actual_docker_attempts']==0 and len(setup['native_logs'])==fault_at
    assert b['pruned_cells']==[] and not b['validation_opened']
    assert run.ledger.verify().data()['originals_verified']
    if fault_at==12:
        run.barrier.verify()
        assert run.barrier.ledger.verify().data()['successful_prefix']
        assert not run.ledger.verify().data()['score_eligible']
