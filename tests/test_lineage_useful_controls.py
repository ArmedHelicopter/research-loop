"""Useful-output revision of all seven existing lineage/admission designs."""
import json

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.lineage_combination_controller import compile_lineage_train_panels
from research_loop.ontology import ContractError
from test_combination_prospective_train_source import prepare
from test_remaining_prospective_train_sources import prepare_controller


RECIPE = {'schema':'lineage-useful-review-recipe-v1',
    'review':{'off':'sequential_revision','on':'sealed_independent'},
    'solver_context':'both_actual_reviews',
    'model_slots':['lineage_review','measurement_review','analysis_program','final_answer'],
    'docker_attempts':1,'scorer_opportunities':1}


def configured(root, kind):
    setup = prepare(root, 'lineage') if kind == 'lineage' else prepare_controller(root, 'admission')
    before = setup['compiled']
    body = setup['config'].data(); body['schema'] = body['schema'].removesuffix('v2')+'v3'
    body['execution_recipe'] = RECIPE
    setup['config'] = type(setup['config'])(FrozenRecord.from_dict(body))
    setup['compiled'] = compile_lineage_train_panels(setup['config'], setup['packets'])
    assert {p.digest for p in before.panels}.isdisjoint(p.digest for p in setup['compiled'].panels)
    (root/'frozen-config.json').write_text(setup['config'].record.encoded+'\n',encoding='utf-8')
    return setup


@pytest.mark.parametrize('kind',['lineage','admission'])
def test_recipe_frozen_across_all_seven_panels(tmp_path, kind):
    setup = configured(tmp_path,kind)
    assert sum(len(p.cells) for p in setup['compiled'].panels) == (34 if kind=='lineage' else 24)
    assert all(s.data()['execution_recipe'] == RECIPE for s in setup['compiled'].scenarios.values())


@pytest.mark.parametrize('kind',['lineage','admission'])
@pytest.mark.parametrize('fault',['legacy_flag','changed_recipe','missing_recipe','missing_source'])
def test_closed_configuration_does_not_silently_migrate_old_panels(tmp_path,kind,fault):
    setup = prepare(tmp_path,'lineage') if kind=='lineage' else prepare_controller(tmp_path,'admission')
    body = setup['config'].data(); body['schema'] = body['schema'].removesuffix('v2')+'v3'
    body['execution_recipe'] = RECIPE
    if fault=='legacy_flag': body['schema']=body['schema'].removesuffix('v3')+'v2'
    elif fault=='changed_recipe': body['execution_recipe']={**RECIPE,'solver_context':'discard_ordinary_reviews'}
    elif fault=='missing_recipe': body.pop('execution_recipe')
    else: body.pop('export_mode')
    with pytest.raises(ContractError): type(setup['config'])(FrozenRecord.from_dict(body))
    assert not setup['exporter'].output_root.exists()
