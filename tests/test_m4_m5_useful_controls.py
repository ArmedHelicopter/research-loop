"""Explicit new recipe; synthetic data and transport, actual execution ports."""
from dataclasses import replace
import json

import pytest

from research_loop.modular import combination_train_controller as controller
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError
from test_combination_prospective_train_source import prepare, run


RECIPE = {
    'schema': 'm4-m5-useful-output-recipe-v1',
    'proposal': {'off': 'ordinary_three_branch', 'on': 'registered_discriminating'},
    'review': {'off': 'sequential_revision', 'on': 'sealed_independent'},
    'solver_context': 'all_three_module_responses',
    'model_slots': ['m4_plan', 'm5_mechanism', 'm5_measurement', 'analysis_program', 'final_answer'],
    'docker_attempts': 1, 'scorer_opportunities': 1,
}


def configured(root):
    setup = prepare(root, 'm4')
    old_panel = setup['compiled'].panel
    body = setup['config'].data()
    body.update(schema='m4-m5-train-controller-config-v3', execution_recipe=RECIPE)
    setup['config'] = controller.FrozenM4M5TrainConfig(FrozenRecord.from_dict(body))
    setup['compiled'] = controller.compile_m4_m5_train_panel(setup['config'], setup['packets'])
    assert setup['compiled'].panel.digest != old_panel.digest
    return setup


def test_explicit_recipe_frozen_into_every_cell(tmp_path):
    setup = configured(tmp_path)
    assert len(setup['compiled'].panel.cells) == 8
    for cell in setup['compiled'].panel.cells:
        scenario = setup['compiled'].scenarios[cell.key]
        assert scenario.data()['execution_recipe'] == RECIPE
        assert cell.scenario_digest == scenario.content_hash


@pytest.mark.parametrize('fault', ['legacy_flag', 'missing_recipe', 'changed_recipe', 'legacy_source'])
def test_recipe_rejects_silent_migration_and_mutation(tmp_path, fault):
    setup = prepare(tmp_path, 'm4'); body = setup['config'].data()
    body.update(schema='m4-m5-train-controller-config-v3', execution_recipe=RECIPE)
    if fault == 'legacy_flag': body['schema'] = 'm4-m5-train-controller-config-v2'
    elif fault == 'missing_recipe': body.pop('execution_recipe')
    elif fault == 'changed_recipe': body['execution_recipe'] = {**RECIPE, 'solver_context': 'discard_off_responses'}
    elif fault == 'legacy_source': body.pop('export_mode')
    with pytest.raises(ContractError): controller.FrozenM4M5TrainConfig(FrozenRecord.from_dict(body))
    assert not setup['exporter'].output_root.exists()


def test_eight_cell_useful_output_grid(tmp_path, monkeypatch):
    setup = configured(tmp_path)
    result, port, seen, _ = run(setup, monkeypatch)
    assert len(result.scores) == 8
    assert len(result.results) == 8 and all(r.runtime.status == 'succeeded' for r in result.results)
    assert len(seen) == 40 and len(port.ledger['calls']) == 40
    assert result.receipt.data()['validation_opened'] is False
    for executed in result.results:
        events = [FrozenRecord(line).data() for line in executed.runtime.trace_path.read_text(encoding='utf-8').splitlines()]
        requests = [e['data']['request'] for e in events if e['stage'] == 'model_request']
        responses = [e['data']['response'] for e in events if e['stage'] == 'model_response']
        enabled = executed.cell.runtime_arm.data()['enabled']
        for request in requests[3:]:
            joint = request['module_context']['joint_mechanism']
            assert joint['proposal'] == responses[0]
            assert joint['review_responses'] == responses[1:3]
        assert requests[1]['module_context']['prediction_plan'] == responses[0]
        assert requests[2]['module_context']['prediction_plan'] == responses[0]
        expected_prior = [] if 'M5' in enabled else [responses[1]]
        assert requests[2]['module_context']['earlier_reviews'] == expected_prior
        assert requests[1]['module_context']['earlier_reviews'] == []
        assert requests[1]['module_context']['sealed'] == ('M5' in enabled)
        logs = executed.runtime.trace_path.parent
        assert bool((logs/'predictions.jsonl').read_text(encoding='utf-8').strip()) == ('M4' in enabled)
        assert bool((logs/'reviews.jsonl').read_text(encoding='utf-8').strip()) == ('M5' in enabled)
