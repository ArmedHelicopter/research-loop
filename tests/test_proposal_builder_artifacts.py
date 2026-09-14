"""Closed proposal host writers, original consumers, and retained failures."""
from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace

import pytest

from research_loop.modular import builder_artifacts as durable
from research_loop.modular.artifact_catalogue import ArtifactCatalogue
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.modules.improvement import CandidatePackage, FrozenBuilderVersion, TrainingManifest, RestrictedBuilderPort
from research_loop.modular.proposal_builder_artifacts import execute_proposal_builder, verify_proposal_builder
from research_loop.modular.runtime import AuditVerifier, RunSession
from research_loop.ontology import ContractError
from test_builder_artifacts import rewrite_catalogue, tree_bytes
from test_state_improvement_train_controller import grid as state_grid, build_args


def fixture(root, host, enabled):
    task = PublicTask.create(DataIdentity('synthetic','proposal','group','v1','split','train'), {'question':'public'})
    history = DataIdentity('synthetic','history','history-group','v1','split','train')
    # The proposal task is deliberately not a member of the parent's TRAIN manifest.
    parent = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([history]),
        changes={'prompt':{'instructions':'initial'}}, search_cost=0)
    fixed = FrozenBuilderVersion.freeze({'entrypoint':'emit_literal_change_v1','surface':'prompt','key':'instructions','value':'fixed'})
    proposed = FrozenBuilderVersion.freeze({'entrypoint':'emit_literal_change_v1','surface':'memory','key':'lesson','value':'public units'})
    session = RunSession(task, package_digest=parent.digest,
        arm=default_compatibility('fixture').arm(('M1','M2','M9') if enabled else ()),
        objective=FrozenRecord.from_dict({'question':'public'}), slots=('builder_proposal',), execution_limit=0,
        sidecar=root/'proposal', verifier=AuditVerifier({'first':b'a'*32,'second':b'b'*32}), required_audit=('measurement',))
    response = session.invoke('builder_proposal', lambda request: proposed.record, evidence_only=True)
    terminal = 'state_improvement_proposal_terminal' if host=='state-improvement' else 'metaprogram_proposal_terminal'
    session._record(terminal, {'response_digest':response.content_hash,'builder_digest':proposed.digest})
    session._terminal = True
    args = dict(root=root, host=host, inputs=FrozenRecord.from_dict({'task':task.data(),'fixed':fixed.record.data()}),
        selected=proposed if enabled else fixed, parent=parent, response=response, enabled=enabled)
    return session, args


@pytest.mark.parametrize('host',['state-improvement','metaprogram-training'])
@pytest.mark.parametrize('enabled',[True,False])
def test_closed_proposal_preserves_actual_subjects_and_fixed_control(tmp_path, host, enabled):
    session, args = fixture(tmp_path,host,enabled)
    trace = (session.sidecar/'trace.jsonl').read_bytes()
    observed = []
    def returned(candidate,receipt):
        observed.append(candidate.digest)
        assert (tmp_path/durable._RETURNED).is_file()
        assert not (tmp_path/'candidate.json').exists()
        assert session.artifacts.records()[-1].data()['kind']=='m9_builder_return'
    candidate,_ = execute_proposal_builder(session,**args,on_return=returned)
    assert observed==[candidate.digest] and session._terminal
    assert (session.sidecar/'trace.jsonl').read_bytes()==trace
    before = tree_bytes(tmp_path)
    assert verify_proposal_builder(**args).data()['status']=='succeeded'
    assert tree_bytes(tmp_path)==before
    records = [r.data() for r in session.artifacts.records() if r.data()['kind'].startswith('m9_')]
    assert len(records)==7 and all(r['status']==('produced' if enabled else 'not_applied') for r in records)
    assert records[1]['payload']['canonical']['manifest']==args['parent'].record.data()['training_manifest']
    def alter(body):
        if body['kind']=='m9_builder_selection': body['payload']['canonical']['inputs']['fixed']['value']='forged'
    rewrite_catalogue(session,alter)
    with pytest.raises(ContractError,match='differs'):
        verify_proposal_builder(**args)


@pytest.mark.parametrize('host',['state-improvement','metaprogram-training'])
@pytest.mark.parametrize('fault',['interpreter','partial_candidate','return_observer'])
def test_original_closed_host_failure_and_partial_outputs_survive(tmp_path, monkeypatch, host, fault):
    session,args = fixture(tmp_path,host,True)
    failure = ContractError('original retained '+fault)
    if fault=='interpreter':
        def fail(*a,**k): raise failure
        monkeypatch.setattr(RestrictedBuilderPort,'execute',fail)
    elif fault=='partial_candidate':
        original = durable._exclusive
        def partial(path,record):
            original(path,record)
            if path.name=='candidate.json': raise failure
        monkeypatch.setattr(durable,'_exclusive',partial)
    def callback(*args):
        if fault=='return_observer': raise failure
    with pytest.raises(ContractError) as caught:
        execute_proposal_builder(session,**args,on_return=callback)
    assert caught.value is failure and session.artifacts.seal_path.is_file()
    before = tree_bytes(tmp_path)
    report = verify_proposal_builder(**args)
    assert report.data()['status']=='failed' and tree_bytes(tmp_path)==before
    assert (tmp_path/'candidate.json').exists()==(fault=='partial_candidate')


def failed_terminal(root):
    path = root/'proposal/artifacts.jsonl'
    first = json.loads(path.read_bytes().splitlines()[0])['descriptor']
    catalogue = ArtifactCatalogue(path,identity=DataIdentity(**first['identity']),
        **first['binding'],producer_source=first['producer_source'])
    terminal = json.loads((root/durable._TERMINAL).read_bytes())
    terminal.update(status='failed',error_type='ContractError',error='coherently rewritten failure')
    (root/durable._TERMINAL).write_text(FrozenRecord.from_dict(terminal).encoded+'\n',encoding='utf-8',newline='\n')
    def alter(body):
        if body['kind']=='m9_build_terminal':
            body['status']='failed';body['payload']['canonical']=durable._snapshot(root,durable._TERMINAL)
    rewrite_catalogue(SimpleNamespace(artifacts=catalogue),alter)


def test_actual_state_grid_reads_all_builds_and_rejects_coherent_failed_inner_build(state_grid):
    from research_loop.modular.state_improvement_build import verify_build
    setup,run = state_grid
    assert run.receipt.data()['status']=='complete_train_engineering'
    assert len(run.builds)==11 and len(run.results)==22
    for result in run.builds:
        verify_build(result,**build_args(setup,run,result))
        assert (result.root/'proposal/artifacts.jsonl.seal.json').is_file()
    original = run.builds[0]
    before = {p:p.read_bytes() for p in original.root.rglob('*') if p.is_file()}
    try:
        failed_terminal(original.root)
        body = original.record.data()
        body['files']={p.relative_to(original.root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in before if p!=original.root/'build-receipt.json'}
        changed = replace(original,record=FrozenRecord.from_dict(body))
        (original.root/'build-receipt.json').write_text(changed.record.encoded+'\n',encoding='utf-8',newline='\n')
        with pytest.raises(ContractError,match='successful state stage'):
            verify_build(changed,**build_args(setup,run,changed))
    finally:
        for path,raw in before.items(): path.write_bytes(raw)
    verify_build(original,**build_args(setup,run,original))


def test_actual_q63_grid_rejects_coherent_failed_inner_build(tmp_path,monkeypatch):
    from test_modular_metaprogram_training import fixture as prepare
    from research_loop.modular.metaprogram_training import run_metaprogram_training, verify_metaprogram_training
    plan,args,seen,_ = prepare(tmp_path,monkeypatch)
    run = run_metaprogram_training(plan,**args)
    assert len(run.cells)==8 and len(seen)==24
    verify_metaprogram_training(run,plan=plan)
    assert all((cell.root/'proposal/artifacts.jsonl.seal.json').is_file() for cell in run.cells)
    root = run.cells[0].root
    before = {p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
    try:
        failed_terminal(root)
        with pytest.raises(ContractError,match='successful training build'):
            verify_metaprogram_training(run,plan=plan)
    finally:
        for path,raw in before.items(): path.write_bytes(raw)
    verify_metaprogram_training(run,plan=plan)
