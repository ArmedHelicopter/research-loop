"""Synthetic public train process checks; no validation or scientific claims."""
import json
import pytest
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.modules.improvement import FrozenBuilderVersion
from research_loop.modular.improvement_training import freeze_candidate_training,run_candidate_training
from research_loop.modular.metaprogram_training import model_configuration,verify_metaprogram_training
from test_modular_metaprogram_training import fixture


@pytest.mark.parametrize('fault',[None,'analysis_schema','answer_schema'])
def test_q62_complete_twelve_cells_consume_selected_changes_and_retain_failures(tmp_path,monkeypatch,fault):
    original,args,seen,_=fixture(tmp_path,monkeypatch,fault=fault,max_calls=36)
    manual=FrozenBuilderVersion.freeze({'entrypoint':'emit_literal_change_v1','surface':'memory',
        'key':'lesson','value':'Use statistic=mean'})
    data=original.record.data()
    plan=freeze_candidate_training(targets=original.targets,histories=original.histories,parent=original.parent,
        fixed_builder=original.fixed_builder,manual_builder=manual,baseline_digest=data['baseline_digest'],
        p0_control=FrozenRecord.from_dict(data['p0_control']),image=data['image'],model_config=model_configuration(args['model']))
    run=run_candidate_training(plan,**args)
    assert len(run.cells)==12 and verify_metaprogram_training(run,plan=plan).data()['observed_cells']==12
    actual=run.receipt.data()['actual']
    assert actual['provider_calls']==actual['model_requests']==(24 if fault=='analysis_schema' else 36)
    assert actual['builder_attempts']==12 and actual['docker_attempts']==(0 if fault=='analysis_schema' else 12)
    declared={c['cell_id']:c for c in plan.record.data()['cells']}
    for result in run.cells:
        row=result.record.data();cell=declared[row['cell_id']]
        assert row['status']==('failed' if fault else 'succeeded')
        rows=[json.loads(line) for line in (result.root/'solver'/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
        if fault:
            assert rows[-1]['stage']=='driver_failure'
        else:
            answer=rows[-2]['data']['response']['conclusion']
            adapted='M9' in cell['arm']['enabled'] and cell['variant']!='fixed'
            assert json.loads(answer)['statistic']==('mean' if adapted else 'sum')
            context=rows[1]['data']['request']['module_context']['predecessor_context']
            assert bool(context['memory_lesson'])==('M9' in cell['arm']['enabled'] and cell['variant']=='manual_train')
