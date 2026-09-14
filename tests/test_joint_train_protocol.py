"""Common TRAIN precommit; no model, scoring, validation or Docker calls."""
import hashlib

import pytest

from evaluation.modular.scoring_service import ScorerConfig, FrozenBenchmarkRubricEndpoint
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.experiments import registry
from research_loop.modular.full_loo_composition import MODULES, candidate_build_key, derive_allocation
from research_loop.modular.full_loo_modules import model_schemas, slots
from research_loop.modular.joint_deployment import JointComponentVersion
from research_loop.modular.joint_train_protocol import FrozenJointTrainProtocol, OBLIGATION, common_recipes
from research_loop.modular.modules.improvement import TrainingManifest
from research_loop.modular.phase_provider import provider_configuration
from research_loop.modular.train_selection import FrozenTrainSelectionRule
from research_loop.ontology import ContractError
from helpers.native_phase_provider import native_phase_provider

R = FrozenRecord.from_dict
H = 'a' * 64


def catalogue():
    return common_recipes(baseline_digest=H, history_binding_digest='b'*64,
                          builder_digest='c'*64, context_bytes=4096)


def fixture(root, patch, *, validation=False, same_group=False):
    source = root/'source'; source.mkdir()
    (source/'runtime.py').write_bytes(b'# Synthetic common runtime source\n')
    history = PublicTask.create(DataIdentity('blade','history','history-group','fixture-v1',H,'train'),
                                {'question':'Synthetic history'})
    targets = tuple(PublicTask.create(DataIdentity(benchmark, 'target-'+str(i),
                    'history-group' if same_group and i == 0 else 'target-group-'+str(i),
                    'fixture-v1', H, 'validation' if validation else 'train'), {'question':'Synthetic TRAIN target'})
                    for i, benchmark in enumerate(('blade','discoverybench','discoverybench')))
    csv = {}
    for i, task in enumerate((history, *targets)):
        path = root/(str(i)+'.csv'); path.write_bytes(b'x,y\n1,2\n3,4\n'); csv[task.content_hash] = path
    manifest = TrainingManifest.freeze([history.identity]); components = {}
    for name in MODULES:
        path = source/(name+'.py'); path.write_bytes(('# Synthetic '+name+'\n').encode())
        components[name] = JointComponentVersion.capture(name, source_root=source, source_files=[path.name],
            config=R({'instruction':name}), state=R({'history':'synthetic'}), training_manifest=manifest)
    recipes = [r['recipe'] for r in catalogue().data()['recipes']]
    provider, logs = native_phase_provider(root/'provider',patch,schemas=model_schemas(),
        max_calls=derive_allocation(recipes,target_count=len(targets))['model_calls'], response=lambda request:{})
    kwargs = dict(baseline_digest=H,p0_digest='d'*64,
        runtime_sources={'runtime.py':hashlib.sha256((source/'runtime.py').read_bytes()).hexdigest()},
        history=history,targets=targets,public_csv=csv,builder_digest='c'*64,history_binding_digest='b'*64,
        component_templates=components,context_bytes=4096,provider_config=provider_configuration(provider),
        scorer=ScorerConfig.create(benchmark='core_pair',evaluator_id='synthetic',
            rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest(),version='fixture-v1'),
        selection_rule=FrozenTrainSelectionRule.create(coverage_id=OBLIGATION,baseline_arm='ordinary-control',
            tie_break_order=[r['id'] for r in recipes if r['id']!='B0']))
    originals = dict(tasks={t.content_hash:t for t in (history,*targets)},public_csv=csv,
                     component_roots={name:source for name in MODULES},runtime_root=source)
    return kwargs, originals, logs


def test_common_catalogue_retains_every_source_setting_and_real_stage_schedules():
    body = catalogue().data(); rows = body['recipes']
    origins = [a for r in rows for a in r['origins']] + [r['origin'] for r in body['structural_origins']]
    assert len(origins) == len(set(origins))
    for prefix, count in (('C1:',9),('C2:',36),('C3:',5)):
        assert len({a.split('/')[0] for a in origins if a.startswith(prefix)}) == count
    assert 'C4/without-M2' in {r['origin'] for r in body['structural_origins']}
    assert len({r['recipe']['id'] for r in rows}) == len(rows)
    assert all(r['source_identity']=='new_common_procedure_projection_requires_execution' for r in rows)
    assert body['source_scores_reusable'] is body['score_based_pruning'] is False
    full = next(r['recipe'] for r in rows if all(r['recipe']['arm_bits'].values()))
    minus8 = next(r['recipe'] for r in rows if 'C4/without-M8' in r['origins'])
    assert candidate_build_key(full) == candidate_build_key(minus8)
    assert full['target_levels']['M9'] == full['history_build_levels']['M8'] == 0
    for row in rows:
        recipe = row['recipe']
        assert len(slots(recipe,'history_build')) == 5
        assert len(slots(recipe,'target')) == (2 if recipe['id']=='B0' else 6)
    # An ordinary no-module recipe does not prune the combinations containing it.
    ordinary = next(r for r in rows if r['recipe']['id']=='ordinary-control')
    assert 'C1:M4/0' in ordinary['origins']
    assert any('C2:M4+M5/11' in r['origins'] for r in rows)


def test_real_precommit_checks_original_sources_and_writes_exclusively(tmp_path,monkeypatch):
    args, originals, logs = fixture(tmp_path,monkeypatch)
    protocol = FrozenJointTrainProtocol.freeze(**args)
    lock = tmp_path/'lock.json'; protocol.write_lock(lock,**originals)
    assert FrozenJointTrainProtocol(FrozenRecord(lock.read_text())).digest == protocol.digest
    protocol.verify_original_inputs(**originals)
    assert protocol.record.data()['issue_contracts'] == {k:v.record.data() for k,v in registry().items()}
    assert len(protocol.record.data()['targets']) == 3
    assert not logs
    assert protocol.record.data()['execution_authorized'] is protocol.record.data()['acceptance_authorized'] is False
    with pytest.raises(FileExistsError): protocol.write_lock(lock,**originals)


@pytest.mark.parametrize('kind',['validation','same_group'])
def test_train_domain_and_whole_history_group_isolation(tmp_path,monkeypatch,kind):
    args, _, logs = fixture(tmp_path,monkeypatch,**{kind:True})
    with pytest.raises(ContractError): FrozenJointTrainProtocol.freeze(**args)
    assert not logs


@pytest.mark.parametrize('field',['csv','runtime','component'])
def test_changed_original_bytes_prevent_lock_write(tmp_path,monkeypatch,field):
    args, originals, logs = fixture(tmp_path,monkeypatch)
    protocol = FrozenJointTrainProtocol.freeze(**args)
    path = (next(iter(originals['public_csv'].values())) if field=='csv' else
            originals['runtime_root']/('runtime.py' if field=='runtime' else 'M4.py'))
    path.write_bytes(path.read_bytes()+b'changed\n')
    with pytest.raises(ContractError): protocol.write_lock(tmp_path/'invalid.json',**originals)
    assert not (tmp_path/'invalid.json').exists() and not logs


@pytest.mark.parametrize('kind',['prune','merge','boundary','allocation','provider','issues','template','b0_rank','authority'])
def test_coherent_frozen_record_changes_cannot_relax_common_contract(tmp_path,monkeypatch,kind):
    args, _, logs = fixture(tmp_path,monkeypatch)
    body = FrozenJointTrainProtocol.freeze(**args).record.data()
    if kind=='prune': body['catalogue']['recipes'].pop(1)
    elif kind=='merge': body['catalogue']['recipes'][0]['origins'].pop()
    elif kind=='boundary': body['catalogue']['recipes'][1]['recipe']['target_levels']['M9']=1
    elif kind=='allocation': body['allocation']['model_calls']-=1
    elif kind=='provider': body['provider_config']['limits']['main_opportunities']-=1
    elif kind=='issues': body['issue_contracts']['Q6.3']['variants'].pop()
    elif kind=='template': body['component_templates'].pop('M9')
    elif kind=='b0_rank': body['selection_rule']['tie_break_order'].append('B0')
    elif kind=='authority': body['execution_authorized']=True
    with pytest.raises(ContractError): FrozenJointTrainProtocol(R(body))
    assert not logs


def test_component_configuration_changes_pin_a_different_common_protocol(tmp_path,monkeypatch):
    args, _, logs = fixture(tmp_path,monkeypatch)
    first = FrozenJointTrainProtocol.freeze(**args)
    component = args['component_templates']['M4'].record.data()
    component['config']['instruction']='different frozen configuration'
    args['component_templates']['M4']=JointComponentVersion(R(component))
    second = FrozenJointTrainProtocol.freeze(**args)
    assert first.digest != second.digest
    assert first.record.data()['catalogue']==second.record.data()['catalogue']
    # Recipe aliases do not identify the complete executable protocol/configuration.
    task = args['targets'][0].content_hash
    assert first.trial_binding('ordinary-control',task) != second.trial_binding('ordinary-control',task)
    with pytest.raises(ContractError): first.trial_binding('ordinary-control',args['history'].content_hash)
    with pytest.raises(ContractError): first.trial_binding('foreign-recipe',task)
    assert not logs
