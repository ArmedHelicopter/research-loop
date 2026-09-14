"""Actual Q6.3 fixture source/selection/output checks, never paid model calls."""
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from research_loop.modular import builder_artifacts as durable
from research_loop.modular import fixture_builder_artifacts as fixture
from research_loop.modular.artifact_catalogue import ArtifactCatalogue
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.modules.improvement import BuilderRegistry, RestrictedBuilderPort
from research_loop.modular.scenarios_improvement import (
    run_improvement_scenario, verify_q63_fixture_artifacts, inspect_q63_fixture_failure,
)
from research_loop.ontology import ContractError
from test_builder_artifacts import rewrite_catalogue, tree_bytes
from test_modular_improvement_scenarios import task_for, controls


def prepare(root, variant, callback=None):
    task=task_for('blade')
    args=dict(task=task,frozen_controls=controls(task),sidecar=root,variant=variant)
    source={'entrypoint':'emit_literal_change_v1','surface':'memory','key':'mode','value':'actual public history'}
    if callback is None:
        callback=lambda request: FrozenRecord.from_dict({'builder_dsl':source})
    result=run_improvement_scenario('Q6.3',callback=callback,**args)
    return result,args


def catalogue(root,task):
    path=root/fixture._CATALOGUE
    first=json.loads(path.read_bytes().splitlines()[0])['descriptor']
    return ArtifactCatalogue(path,identity=task.identity,**first['binding'],producer_source=first['producer_source'])


def rewrite(root, task, edit):
    cat=catalogue(root,task)
    rewrite_catalogue(SimpleNamespace(artifacts=cat),edit)
    terminal=json.loads((root/fixture._END).read_bytes())
    terminal['files']=fixture._files(root)
    (root/fixture._END).write_text(FrozenRecord.from_dict(terminal).encoded+'\n',encoding='utf-8',newline='\n')
    def close(body):
        if body['kind']=='fixture_terminal':body['payload']['canonical']=durable._snapshot(root,fixture._END)
    rewrite_catalogue(SimpleNamespace(artifacts=cat),close)
    seal=durable._read(root,fixture._CATALOGUE+'.seal.json')
    closure={'schema':'q63-fixture-closure-v1','catalogue_seal':seal.data(),'terminal':durable._snapshot(root,fixture._END)}
    (root/fixture._CLOSURE).write_text(FrozenRecord.from_dict(closure).encoded+'\n',encoding='utf-8',newline='\n')


@pytest.mark.parametrize('variant',['fixed','train_proposed'])
def test_actual_fixture_records_two_unit_outputs_and_reader_does_not_reactivate(tmp_path,monkeypatch,variant):
    result,args=prepare(tmp_path/'run',variant)
    root=args['sidecar'];cat=catalogue(root,args['task'])
    rows=[r.data() for r in cat.records()]
    built=[r for r in rows if r['kind'].startswith('m9_')]
    assert len(built)==7
    assert built[1]['payload']['canonical']['search_cost']==2
    assert all(r['status']==('not_applied' if variant=='fixed' else 'produced') for r in built)
    if variant=='fixed':assert all(r['status']=='not_applied' for r in rows if r['module']=='M9')
    assert built[0]['payload']['canonical']['response_consumed']==(variant!='fixed')
    assert all(r['scientific_validated'] is False for r in rows)
    def forbidden(*a,**k): raise AssertionError('reader attempted registry activation or callback')
    monkeypatch.setattr(BuilderRegistry,'__init__',forbidden)
    monkeypatch.setattr(BuilderRegistry,'activate_meta',forbidden)
    before=tree_bytes(root)
    assert verify_q63_fixture_artifacts(result,**args).data()['status']=='succeeded'
    assert tree_bytes(root)==before
    snapshots=[r['payload']['canonical'] for r in rows if r['kind'] in {'fixture_registry_initialized','fixture_registry_active'}]
    assert len(snapshots)==(0 if variant=='fixed' else 2)
    if snapshots:
        assert snapshots[0]['sha256']!=snapshots[1]['sha256']
        assert all((root/s['blob']).read_bytes() for s in snapshots)


def test_invalid_original_proposal_is_auditable_rejection_before_activation(tmp_path):
    result,args=prepare(tmp_path/'run','train_proposed',lambda request:FrozenRecord.from_dict({'unexpected':'kept'}))
    assert verify_q63_fixture_artifacts(result,**args).data()['status']=='rejected'
    assert not (args['sidecar']/'builders.sqlite').exists() and not (args['sidecar']/'builder.json').exists()
    assert result.callback_outputs[0].data()=={'unexpected':'kept'}


@pytest.mark.parametrize('variant',['fixed','train_proposed'])
@pytest.mark.parametrize('fault',['interpreter','partial_candidate','callback'])
def test_actual_failed_fixture_preserves_original_exception_and_outputs(tmp_path,monkeypatch,variant,fault):
    root=tmp_path/'run';task=task_for('blade');error=ContractError('original '+fault)
    def fail(*a,**k): raise error
    if fault=='interpreter':monkeypatch.setattr(RestrictedBuilderPort,'execute',fail)
    elif fault=='partial_candidate':
        original=durable._exclusive
        def partial(path,record):
            original(path,record)
            if path.name=='candidate.json':raise error
        monkeypatch.setattr(durable,'_exclusive',partial)
    with pytest.raises(ContractError) as caught:
        prepare(root,variant,fail if fault=='callback' else None)
    assert caught.value is error
    cat=catalogue(root,task);cat.verify()
    terminal=durable._read(root,fixture._END).data()
    assert terminal['status']=='failed' and terminal['error']==str(error)
    assert terminal['files']==fixture._files(root)
    assert cat.seal_path.is_file() and (root/fixture._CLOSURE).is_file()
    assert (root/'candidate.json').exists()==(fault=='partial_candidate')
    if fault!='callback':assert durable._read(root,durable._TERMINAL).data()['status']=='failed'
    args=dict(task=task,frozen_controls=controls(task),sidecar=root,variant=variant)
    before=tree_bytes(root)
    report=inspect_q63_fixture_failure(**args).data()
    assert report['storage_integrity_verified'] and not report['stage_semantics_verified']
    assert not report['acceptance_eligible'] and tree_bytes(root)==before
    path=root/'builder.json' if (root/'builder.json').is_file() else cat.path
    raw=path.read_bytes();path.write_bytes(raw+b'corruption')
    with pytest.raises(ContractError):inspect_q63_fixture_failure(**args)
    path.write_bytes(raw)
    inspect_q63_fixture_failure(**args)


@pytest.mark.parametrize('fault',['consumption','allocation','selected','failed_terminal'])
def test_coherently_rehashed_fixture_still_requires_actual_selection_and_success(tmp_path,fault):
    result,args=prepare(tmp_path/'run','fixed');root=args['sidecar']
    if fault=='failed_terminal':
        terminal=durable._read(root,durable._TERMINAL).data()
        terminal.update(status='failed',error_type='ContractError',error='forged failure')
        (root/durable._TERMINAL).write_text(FrozenRecord.from_dict(terminal).encoded+'\n',encoding='utf-8',newline='\n')
    def edit(body):
        if body['kind']=='m9_builder_selection':
            payload=body['payload']['canonical']
            if fault=='consumption':payload['response_consumed']=True
            if fault=='allocation':payload['search_cost']=1
            if fault=='selected':payload['builder']['value']='forged'
        elif body['kind']=='m9_build_terminal' and fault=='failed_terminal':
            body['status']='failed';body['payload']['canonical']=durable._snapshot(root,durable._TERMINAL)
    rewrite(root,args['task'],edit)
    before=tree_bytes(root)
    with pytest.raises(ContractError):verify_q63_fixture_artifacts(result,**args)
    assert tree_bytes(root)==before


def test_result_cannot_replace_original_callback_and_blob_is_required(tmp_path):
    result,args=prepare(tmp_path/'run','train_proposed');root=args['sidecar']
    changed=replace(result,callback_outputs=(FrozenRecord.from_dict({'builder_dsl':{
        'entrypoint':'emit_literal_change_v1','surface':'memory','key':'mode','value':'foreign'}}),))
    with pytest.raises(ContractError):verify_q63_fixture_artifacts(changed,**args)
    path=next((root/'fixture-blobs').iterdir());before=path.read_bytes()
    path.write_bytes(before+b'corruption')
    with pytest.raises(ContractError):verify_q63_fixture_artifacts(result,**args)
    path.write_bytes(before)
    verify_q63_fixture_artifacts(result,**args)


def test_reader_rejects_unregistered_nested_file_even_if_name_matches_root_journal(tmp_path):
    result,args=prepare(tmp_path/'run','fixed');root=args['sidecar']
    extra=root/'unexpected'/fixture._CATALOGUE;extra.parent.mkdir();extra.write_bytes(b'unknown')
    with pytest.raises(ContractError,match='unexpected'):verify_q63_fixture_artifacts(result,**args)


def test_failure_after_registry_commit_preserves_the_changed_database(tmp_path,monkeypatch):
    root=tmp_path/'run';task=task_for('blade');error=ContractError('after actual registry commit')
    original=BuilderRegistry.activate_meta
    def fail_after_commit(registry,*args,**kwargs):
        original(registry,*args,**kwargs)
        raise error
    monkeypatch.setattr(BuilderRegistry,'activate_meta',fail_after_commit)
    with pytest.raises(ContractError) as caught:prepare(root,'train_proposed')
    assert caught.value is error
    before=tree_bytes(root)
    report=inspect_q63_fixture_failure(task=task,frozen_controls=controls(task),sidecar=root,variant='train_proposed').data()
    assert report['stage']=='registry_activate' and not report['acceptance_eligible']
    _,_,fixed=fixture._base(task)
    state=fixture._db_state((root/'builders.sqlite').read_bytes())
    assert state['active']!=[[1,fixed.digest]] and len(state['consumed'])==1
    rows=[r.data() for r in catalogue(root,task).records()]
    snapshot=next(r['payload']['canonical'] for r in rows if r['kind']=='fixture_registry_initialized')
    assert fixture._db_state((root/snapshot['blob']).read_bytes())['active']==[[1,fixed.digest]]
    assert tree_bytes(root)==before


def test_coherently_sealed_missing_acceptance_return_is_a_contract_rejection(tmp_path):
    result,args=prepare(tmp_path/'run','train_proposed');root=args['sidecar']
    cat=catalogue(root,args['task']);lines=cat.path.read_bytes().splitlines(keepends=True)[:5]
    assert json.loads(lines[-1])['descriptor']['kind']=='fixture_acceptance_request'
    cat.path.write_bytes(b''.join(lines))
    seal=FrozenRecord.from_dict({'schema':'artifact-catalogue-seal-v1','count':len(lines),
        'head':FrozenRecord(lines[-1].decode().strip()).content_hash,'binding':cat.binding})
    cat.seal_path.write_text(seal.encoded+'\n',encoding='utf-8',newline='\n')
    cat.verify(seal)
    with pytest.raises(ContractError,match='missing'):verify_q63_fixture_artifacts(result,**args)
