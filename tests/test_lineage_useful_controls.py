"""Useful-output revision of all seven existing lineage/admission designs."""
import json
from dataclasses import replace
from pathlib import Path

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.lineage_combination_controller import compile_lineage_train_panels
from research_loop.ontology import ContractError
from test_combination_prospective_train_source import prepare
from test_remaining_prospective_train_sources import prepare_controller
from test_remaining_prospective_train_sources import invoke_controller
from test_lineage_process_scoring import prepared_fixture, LineageScorerProcessClient, LineageScorerProcessPool
from test_lineage_combination_controller import _model, EXECUTION, SCORER
from test_modular_train_controller import model_port
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.lineage_combination_controller import run_lineage_train_panels
from research_loop.modular.lineage_combination_driver import verify_lineage_combination_cell
from research_loop.modular.lineage_combination_controller import _v3_admission_qualification_drift
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from test_modular_combination_benchmark_driver import _rewrite_trace
import test_admission_combination as admission


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


def run_lineage_processes(setup, monkeypatch):
    root=setup['root']; exporter=setup['exporter']; snapshot=Path(exporter.config['snapshot_root'])
    _,_,config,compiled,sources,specs=prepared_fixture(root/'scorers',snapshot,None,
        setup['packets'],setup['config'],setup['sources'])
    setup.update(config=config,compiled=compiled)
    (root/'frozen-config.json').write_text(config.record.encoded+'\n',encoding='utf-8')
    clients=[];seen=[]; ordinary=_model(seen)
    def respond(request):
        body=request.data()
        assert 'PRIVATE-REFERENCE-SENTINEL' not in request.encoded and '独立训练注释哨兵' not in request.encoded
        if body['slot']=='final_answer':
            seen.append(body)
            assert body['execution_feedback'][0]['status']=='succeeded'
            return FrozenRecord.from_dict({'objective_digest':body['module_context']['required_objective_digest'],
                'outcome':'unknown','evidence_ids':[], 'conclusion':'Actual output '+body['execution_feedback'][0]['stdout'],
                'programme_complete':False})
        return ordinary(request)
    body=config.data()
    port=model_port(root/'port',monkeypatch,max_calls=body['max_calls'],max_tokens=body['max_tokens'],
        schemas=body['schemas'],response_factory=respond)
    try:
        for spec in specs:clients.append(LineageScorerProcessClient(**spec))
        result=run_lineage_train_panels(config,custody=None,prospective_exporter=exporter,snapshot_root=snapshot,
            export_root=exporter.output_root,run_root=root/'run',model=port,
            audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),source_verifier=sources,
            execution_authority=EXECUTION,scoring_service=LineageScorerProcessPool(clients),
            scorer_authority_keys={SCORER.authority_id:SCORER.key})
    finally:
        for client in clients:client.close()
    return result,seen


@pytest.mark.parametrize('kind',['lineage','admission'])
def test_all_58_cells_use_actual_reviews_and_independent_process_scores(tmp_path,monkeypatch,kind):
    setup=configured(tmp_path,kind)
    result,seen=run_lineage_processes(setup,monkeypatch) if kind=='lineage' else invoke_controller(setup,monkeypatch)
    n=34 if kind=='lineage' else 24
    assert len(result.scores)==len(result.attempts)==n, [a.data() for a in result.attempts if a.data()['status']!='succeeded']
    assert len(seen)==n*4
    assert all(a.data()['status']=='succeeded' for a in result.attempts)
    assert result.receipt.data()['validation_opened'] is False
    mutated=[]
    for executed in result.results:
        path=executed.runtime.trace_path
        events=[FrozenRecord(line).data() for line in path.read_text(encoding='utf-8').splitlines()]
        requests=[e['data']['request'] for e in events if e['stage']=='model_request']
        responses=[e['data']['response'] for e in events if e['stage']=='model_response']
        enabled=executed.cell.runtime_arm.data()['enabled']
        assert requests[0]['module_context']['earlier_reviews']==[]
        assert requests[1]['module_context']['earlier_reviews']==([] if 'M5' in enabled else [responses[0]])
        for r in requests[2:]: assert r['module_context']['joint_mechanism']['review_responses']==responses[:2]
        assert bool((path.parent/'reviews.jsonl').read_text(encoding='utf-8').strip())==('M5' in enabled)
        if executed.cell.identity.benchmark!='blade' or executed.cell.arm_id not in ('00','01','000','001'): continue
        panel=next(p for p in result.compiled.panels if executed.cell in p.cells)
        packet=next(p for p in result.compiled.packets if p.task.content_hash==executed.cell.task_digest)
        args=dict(panel=panel,task=packet.task,scenario=result.compiled.scenarios[executed.cell.key],
            package=result.compiled.packages[executed.cell.runtime_arm.content_hash],
            material=result.compiled.materials[executed.cell.task_digest],
            source_verifier=setup['sources'] if kind=='lineage' else setup['qualifier'],
            public_inputs={'public_csv':packet.csv_path},broker=DockerExecutionBroker([tmp_path/'export',tmp_path/'run']))
        original=path.read_bytes()
        for fault in ('discard_reviews','review_history'):
            joint=executed.joint_mechanism.data()
            def change(rows):
                if fault=='discard_reviews':
                    joint['review_responses']=[]
                    target=next(e for e in rows if e['stage']=='lineage_joint')
                    target['data']['joint']=joint
                    target['data']['public_bytes']=len(FrozenRecord.from_dict(joint).encoded.encode('utf-8'))
                else:
                    target=next(e for e in rows if e['stage']=='model_request' and e['data']['request']['slot']=='measurement_review')
                    old=target['data']['request_digest']
                    target['data']['request']['module_context']['earlier_reviews']=[{'injected':True}] if 'M5' in enabled else []
                    new=FrozenRecord.from_dict(target['data']['request']).content_hash;target['data']['request_digest']=new
                    for e in rows:
                        if e['stage']=='model_response' and e['data']['request_digest']==old:e['data']['request_digest']=new
            try:
                tail=_rewrite_trace(path,change)
                with pytest.raises(ContractError,match='joint context|review does not consume'):
                    verify_lineage_combination_cell(replace(executed,joint_mechanism=FrozenRecord.from_dict(joint),
                        runtime=replace(executed.runtime,trace_digest=tail)),**args)
                mutated.append({'obligation':panel.obligation_id,'cell':list(executed.cell.key),'fault':fault})
            finally:path.write_bytes(original)
    assert {m['obligation'] for m in mutated}=={p.obligation_id for p in result.compiled.panels}
    (tmp_path/'replay-mutations.json').write_text(json.dumps(mutated),encoding='utf-8')


def test_v3_admission_qualification_drift_keeps_all_cells_but_blocks_contrasts(tmp_path, monkeypatch):
    setup = configured(tmp_path, 'admission')
    calls = []
    # The replacement has the same frozen authority policy binding as the
    # config, while issuing valid, mutually agreeing but cell-varying results.
    setup['qualifier'] = admission.sources(calls, fault='source_cell_drift', root=tmp_path/'run')
    assert setup['qualifier'].binding().data() == setup['config'].data()['source_verifier_binding']
    result, seen = invoke_controller(setup, monkeypatch)
    assert len(result.scores) == len(result.attempts) == 24
    assert len(seen) == 24 * 4 and all(a.data()['status'] == 'succeeded' for a in result.attempts)
    contrasts = result.receipt.data()['contrasts']
    assert all(c['status'] == 'inconclusive' and c['reason'] == 'v3_admission_qualification_semantic_drift'
               for c in contrasts)
    assert all(c['qualification_drift'] for c in contrasts)
    assert result.receipt.data()['failed_cells'] == result.receipt.data()['blocked_cells'] == 0
    assert result.receipt.data()['pruned_cells'] == []


def test_v3_admission_uniform_qualification_semantics_remain_comparable(tmp_path):
    setup = configured(tmp_path, 'admission')
    panel = setup['compiled'].panels[0]
    rows = [{'cell': cell.data(), 'status': 'succeeded', 'qualification_semantics_digest': 'a' * 64}
            for cell in panel.cells]
    assert _v3_admission_qualification_drift(setup['config'], panel, rows) is None
    rows[0]['status'] = 'failed'
    rows[0].pop('qualification_semantics_digest')
    # Missing/unknown source outcomes retain the existing incomplete-cell path.
    assert _v3_admission_qualification_drift(setup['config'], panel, rows) is None
