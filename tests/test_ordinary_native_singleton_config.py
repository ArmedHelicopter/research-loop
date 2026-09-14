"""Every existing singleton DRIVERS union reaches the new strict declaration."""
import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.panel_runner import DRIVERS
from research_loop.modular.train_controller import (FrozenTrainControllerConfig, _driver_plan,
    EXPLORATION_BUDGET, EXTENDED_EXPLORATION_BUDGET)
from research_loop.modular.train_provider_preflight import NATIVE_SCHEMAS, LEGACY_TRANSPORT_FIELDS
from research_loop.modular.p0_panel import fixed_control_design
from research_loop.ontology import ContractError
from helpers.native_ordinary_provider import native_ordinary_provider
from test_modular_train_controller import config, snapshot_and_custody


@pytest.mark.parametrize('coverage',sorted(DRIVERS))
def test_all_singleton_slot_unions_and_complete_native_call_allocation(tmp_path,monkeypatch,coverage):
    snapshot,custody=snapshot_and_custody(tmp_path)
    old=config(custody,snapshot,tmp_path).data()
    body={k:v for k,v in old.items() if k not in LEGACY_TRANSPORT_FIELDS}
    body.update(schema=NATIVE_SCHEMAS['singleton'],engineering_scope='train_only_panel_engineering',scope_ids=[coverage])
    if coverage in {'Q7.1','Q7.2'}:body['budget']=EXPLORATION_BUDGET
    elif coverage in EXTENDED_EXPLORATION_BUDGET:body['budget']=EXTENDED_EXPLORATION_BUDGET
    elif coverage=='Q5.4':body['budget']={'model_calls':3,'execution_opportunities':1,'verification_calls':1}
    elif coverage=='Q2.7':body['budget']={'docker_attempts':1,'audit_calls':1,'model_calls':1}
    if coverage in {'Q2.2','Q6.4','Q2.7'}:
        grid=fixed_control_design(body['baseline_digest'],FrozenRecord.from_dict(body['p0_control']).content_hash)
        body['evidence_by_task']={k:{**v,'p0_fixed_control':grid.data()} for k,v in body['evidence_by_task'].items()}
    if coverage=='Q2.6':body['objective_by_task']={k:{'question':'Public objective'} for k in body['evidence_by_task']}
    schemas={slot:{'type':'object','properties':{},'required':[],'additionalProperties':False} for slot in DRIVERS[coverage].slots}
    cells,calls=_driver_plan([coverage],baseline_digest=body['baseline_digest'],p0_control=FrozenRecord.from_dict(body['p0_control']),
        item_count=len(body['item_ids']),replicates=body['replicates'])
    provider,logs=native_ordinary_provider(tmp_path/'native-provider',monkeypatch,schemas=schemas,max_calls=calls,response=lambda request:{})
    body['provider']=provider.configuration().data()
    frozen=FrozenTrainControllerConfig(FrozenRecord.from_dict(body))
    assert frozen.data()['provider']['limits']['main_opportunities']==calls and cells>0
    assert set(frozen.data()['provider']['native_config']['schemas'])==set(DRIVERS[coverage].slots)
    bad=frozen.data();bad['provider']['native_config']['schemas'].pop(next(iter(schemas)))
    with pytest.raises(ContractError):FrozenTrainControllerConfig(FrozenRecord.from_dict(bad))
    assert not logs
