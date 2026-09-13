"""Explicit new recipe; synthetic data and transport, actual execution ports."""
from dataclasses import replace
import json

import pytest

from research_loop.modular import combination_train_controller as controller
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError
from test_combination_prospective_train_source import prepare, run
from research_loop.modular.combination_benchmark_driver import (
    run_m4_m5_combination_benchmark_cell, verify_m4_m5_combination_benchmark_cell,
)
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.runtime import AuditVerifier
from test_modular_combination_benchmark_driver import _model, _rewrite_trace, IMAGE


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
    (root/'frozen-useful-config.json').write_text(setup['config'].record.encoded+'\n', encoding='utf-8')
    (root/'frozen-useful-scenarios.json').write_text(json.dumps([
        {'cell': c.data(), 'scenario': setup['compiled'].scenarios[c.key].data()}
        for c in setup['compiled'].panel.cells]), encoding='utf-8')
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


def test_replay_rejects_useful_output_substitution_and_review_contamination(tmp_path):
    setup = configured(tmp_path)
    compiled = setup['compiled']; panel = compiled.panel
    # Two actual executions supply both the sequential and sealed replay paths.
    source = tmp_path/'synthetic.csv'; source.write_text('x\n1\n3\n', encoding='utf-8')
    for arm in ('00', '01'):
        cell = next(c for c in panel.cells if c.arm_id == arm and c.identity.benchmark == 'blade')
        task = next(p.task for p in compiled.packets if p.task.content_hash == cell.task_digest)
        args = dict(panel=panel, task=task, scenario=compiled.scenarios[cell.key],
                    package=compiled.packages[cell.runtime_arm.content_hash])
        result = run_m4_m5_combination_benchmark_cell(**args, cell=cell,
            objective=FrozenRecord.from_dict({'scope': 'synthetic replay'}), sidecar=tmp_path/('cell-'+arm),
            public_inputs={'public_csv':source}, image=IMAGE, broker=DockerExecutionBroker([tmp_path]),
            model=_model([]), audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}))
        assert result.runtime.status == 'succeeded'
        verify_m4_m5_combination_benchmark_cell(result, **args)
        path = result.runtime.trace_path; original = path.read_bytes()
        failures = []
        for fault in ('discard_proposal', 'substitute_proposal', 'discard_reviews', 'substitute_review',
                      'changed_recipe', 'downgrade_joint', 'review_history', 'proposal_task', 'proposal_instruction'):
            joint = result.joint_mechanism.data()
            def change(events):
                if fault in ('review_history', 'proposal_task', 'proposal_instruction'):
                    target_slot = 'm5_measurement' if fault == 'review_history' else 'm4_plan'
                    row = next(e for e in events if e['stage'] == 'model_request' and e['data']['request']['slot'] == target_slot)
                    old = row['data']['request_digest']; request = row['data']['request']
                    if fault == 'review_history':
                        request['module_context']['earlier_reviews'] = ([{'injected': True}] if arm == '01' else [])
                    elif fault == 'proposal_task': request['module_context']['public_task'] = {'foreign': True}
                    else: request['instruction'] = 'A different unregistered recipe.'
                    new = FrozenRecord.from_dict(request).content_hash; row['data']['request_digest'] = new
                    for e in events:
                        if e['stage'] == 'model_response' and e['data']['request_digest'] == old:
                            e['data']['request_digest'] = new
                    return
                if fault == 'discard_proposal': joint['proposal'] = None
                elif fault == 'substitute_proposal': joint['proposal']['question'] = 'Unobserved alternate proposal'
                elif fault == 'discard_reviews': joint['review_responses'] = []
                elif fault == 'substitute_review': joint['review_responses'][0]['uncertainty'] = 'Unobserved review'
                elif fault == 'changed_recipe': joint['execution_recipe']['solver_context'] = 'discard_off_responses'
                elif fault == 'downgrade_joint': joint['schema'] = 'm4-m5-joint-mechanism-v1'
                row = next(e for e in events if e['stage'] == 'combination_mechanism')
                row['data']['joint'] = joint
                row['data']['joint_digest'] = FrozenRecord.from_dict(joint).content_hash
            try:
                tail = _rewrite_trace(path, change)
                forged = replace(result, joint_mechanism=FrozenRecord.from_dict(joint),
                                 runtime=replace(result.runtime, trace_digest=tail))
                message = ('review input differs' if fault == 'review_history' else
                           'proposal instruction differs' if fault.startswith('proposal_') else 'useful joint context')
                with pytest.raises(ContractError, match=message):
                    verify_m4_m5_combination_benchmark_cell(forged, **args)
                failures.append(fault)
            finally:
                path.write_bytes(original)
        (tmp_path/('replay-faults-'+arm+'.json')).write_text(json.dumps(failures), encoding='utf-8')


@pytest.mark.parametrize('fault', ['provider_contract', 'runtime_review'])
def test_malformed_reviews_keep_full_denominator_and_stop_rule(tmp_path, monkeypatch, fault):
    setup = configured(tmp_path); ordinary = setup['module']._model
    def factory(seen):
        original = ordinary(seen)
        def respond(request):
            if request.data()['slot'] == 'm5_mechanism':
                seen.append(request.data())
                return FrozenRecord.from_dict({'invalid_review': True} if fault == 'provider_contract' else
                    {'assessment':'unknown', 'evidence_refs':[], 'counterexamples':[], 'uncertainty':''})
            return original(request)
        return respond
    monkeypatch.setattr(setup['module'], '_model', factory)
    result, port, seen, _ = run(setup, monkeypatch)
    assert len(result.attempts) == 8 and not result.scores
    assert result.receipt.data()['status'] == 'inconclusive'
    assert result.receipt.data()['pruned_cells'] == []
    blocked = fault == 'provider_contract'
    assert len(port.ledger['calls']) == len(seen) == (2 if blocked else 16)
    assert port.ledger['usage_incomplete'] is blocked
    assert result.receipt.data()['blocked_cells'] == (7 if blocked else 0)
    assert result.receipt.data()['failed_cells'] == (1 if blocked else 8)
    assert all(r is None or r.solver is None for r in result.results)
    assert all(not any(FrozenRecord(line).data()['stage'] == 'execution_request'
        for line in p.read_text(encoding='utf-8').splitlines()) for p in (tmp_path/'run').rglob('trace.jsonl'))


@pytest.mark.parametrize('fault', ['validation', 'swapped_tokens', 'export_receipt', 'completion_anchor'])
def test_new_recipe_keeps_primary_source_fail_closed(tmp_path, monkeypatch, fault):
    run(configured(tmp_path), monkeypatch, fault=fault)
