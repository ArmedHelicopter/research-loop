"""Real SQLite/RunSession boundaries; synthetic builds and independent grants."""
import multiprocessing
from pathlib import Path

import pytest

from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.joint_deployment import JointComponentVersion, JointDeploymentBundle, JointDeploymentStore
from research_loop.modular.modules.improvement import TrainingManifest
from research_loop.modular.panel_receipts import SignedAuthority
from research_loop.modular.runtime import AuditVerifier, RunSession, verify_trace
from research_loop.ontology import ContractError, canonical

H = 'a' * 64
KEYS = {'independent-c5': b'acceptance-fixture-key-32-bytes___'}
ROLLBACK = {'independent-rollback': b'rollback-fixture-key-32-bytes_____'}
record = FrozenRecord.from_dict


def identity(name='train'):
    return DataIdentity('blade', name, 'synthetic-source-group', 'synthetic-v1', H, 'train')


def fixtures(root):
    source = root / 'builds'; source.mkdir()
    manifest = TrainingManifest.freeze([identity()])
    versions = {}
    for i in range(1, 10):
        name = f'M{i}'
        (source / (name + '.py')).write_bytes(f'# Synthetic immutable build {name}\n'.encode())
        versions[name] = JointComponentVersion.capture(name, source_root=source, source_files=[name+'.py'],
            config=record({'slot': name, 'instruction': 'old-'+name}), state=record({'lesson':'old-'+name}),
            training_manifest=manifest)
    base = JointDeploymentBundle.create(parent_digest=None, baseline_digest=H, p0_digest='b'*64,
        resource_schedule=record({'slots':['final'], 'execution_limit':0}), components=versions)
    changed = {name: JointComponentVersion(record({**v.record.data(), 'config':{'slot':name,'instruction':'new-'+name},
                'state':{'lesson':'new-'+name}})) for name, v in versions.items()}
    target = JointDeploymentBundle.create(parent_digest=base.digest, baseline_digest=H, p0_digest='b'*64,
        resource_schedule=record({'slots':['final'], 'execution_limit':0}), components=changed)
    return base, target, {name: source for name in versions}


def approval(base, target, **changes):
    return SignedAuthority('independent-c5', KEYS['independent-c5']).issue({
        'schema':'c5-joint-deployment-grant-v1', 'stage':'C5','allocation_stage':'V_final',
        'expected_active_digest':base.digest,'target_bundle_digest':target.digest,
        'selection_digest':'c'*64,'panel_digest':'d'*64,'acceptance_digest':'e'*64,'decision':'approved', **changes})


def rollback(current, previous):
    return SignedAuthority('independent-rollback', ROLLBACK['independent-rollback']).issue({
        'schema':'c5-joint-rollback-grant-v1', 'expected_active_digest':current.digest,
        'target_bundle_digest':previous.digest,'reason':'Synthetic whole-closure rollback'})


def store(path, initial, roots, kind=JointDeploymentStore):
    return kind(path, initial=initial, acceptance_keys=KEYS, rollback_keys=ROLLBACK, source_roots=roots)


def test_all_nine_components_reach_a_pinned_task_then_restore_exact_previous_snapshot(tmp_path):
    base, target, roots = fixtures(tmp_path)
    runtime = store(tmp_path/'joint.sqlite', base, roots)
    calls = []
    def task_run(task_id, bundle):
        components = bundle.components()
        session = RunSession(PublicTask.create(task_id, {'question':'Synthetic snapshot dispatch'}),
            package_digest=bundle.digest, arm=default_compatibility(H).arm(tuple(components)),
            objective=record({'question':'Use the exact pinned component versions'}), slots=('final',),
            execution_limit=0, sidecar=tmp_path/task_id.task_id,
            verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}), required_audit=('measurement',))
        payload = {k:{'component_digest':v.digest, 'config':v.record.data()['config'], 'state':v.record.data()['state']}
                   for k,v in components.items()}
        def model(request):
            calls.append(request.data())
            return record({'observed':request.data()['module_context']['joint_snapshot']})
        response = session.invoke('final', model, instruction='Read the frozen synthetic snapshot.',
            module_context=record({'joint_snapshot':{'bundle_digest':bundle.digest,'components':payload}}))
        assert verify_trace(session.sidecar/'trace.jsonl').data()
        return response.data()
    before = runtime.run_task(identity('before'), task_run)
    grant = approval(base, target)
    ack = runtime.activate(target, grant)
    after = runtime.run_task(identity('after'), task_run)
    runtime.rollback(rollback(target, base))
    restored = runtime.run_task(identity('restored'), task_run)
    assert ack == target.acknowledgement()
    assert len(calls) == 3
    assert all(name not in canonical(calls) for name in ('acceptance_digest', 'used_grants', 'deployment_audit'))
    for result, bundle, prefix in [(before,base,'old-'),(after,target,'new-'),(restored,base,'old-')]:
        body=result.data()
        assert body['snapshot'] == bundle.acknowledgement().data()
        assert body['result']['observed']['bundle_digest'] == bundle.digest
        assert len(body['result']['observed']['components']) == 9
        assert all(v['state']['lesson'] == prefix+k and v['config']['instruction'] == prefix+k
                   for k,v in body['result']['observed']['components'].items())
    with pytest.raises(ContractError, match='already consumed'): runtime.activate(target, grant)
    runtime.close()
    reopened = store(tmp_path/'joint.sqlite', base, roots)
    assert reopened.active() == base
    with pytest.raises(ContractError, match='already consumed'): reopened.activate(target, grant)
    checkpoint = reopened.artifact_checkpoint()
    (tmp_path/'joint.audit-checkpoint.json').write_bytes((checkpoint.encoded+'\n').encode())
    reopened.close()
    from research_loop.modular.joint_deployment_artifacts import verify_joint_deployment_artifacts
    audit = verify_joint_deployment_artifacts(tmp_path/'joint.sqlite', domain='train', checkpoint=checkpoint,
        acceptance_keys=KEYS, rollback_keys=ROLLBACK, component_source_roots=roots)
    assert audit.data()['optimizer_visible'] is False and audit.data()['pending_attempts'] == []
    (tmp_path/'joint.audit-read.json').write_bytes((audit.encoded+'\n').encode())


@pytest.mark.parametrize('failure_index', range(1, 10))
def test_failure_while_staging_any_component_leaves_whole_previous_bundle_and_unused_grant(tmp_path, failure_index):
    base, target, roots = fixtures(tmp_path)
    class FailStage(JointDeploymentStore):
        failing = False
        staged = 0
        def _stage_component(self, bundle, name, component):
            super()._stage_component(bundle,name,component)
            if self.failing:
                self.staged += 1
                if self.staged == failure_index: raise OSError('synthetic storage write failure')
    runtime=store(tmp_path/'joint.sqlite',base,roots,FailStage)
    runtime.failing=True
    grant=approval(base,target)
    with pytest.raises(OSError,match='storage write failure'):runtime.activate(target,grant)
    assert runtime.active() == base
    assert runtime._db.execute('SELECT count(*) FROM used_grants').fetchone()[0] == 0
    assert runtime._db.execute('SELECT count(*) FROM bundles').fetchone()[0] == 1
    assert runtime._db.execute('SELECT count(*) FROM components').fetchone()[0] == 9
    runtime.failing=False
    assert runtime.activate(target,grant) == target.acknowledgement()
    runtime.close()


@pytest.mark.parametrize('changes', [
    {'stage':'Q6.3'}, {'allocation_stage':'V_pair'}, {'decision':'inconclusive'},
    {'selection_digest':'not-a-digest'}, {'target_bundle_digest':'f'*64}, {'expected_active_digest':'f'*64},
])
def test_grant_cannot_change_c5_target_stage_or_parent(tmp_path, changes):
    base,target,roots=fixtures(tmp_path)
    runtime=store(tmp_path/'joint.sqlite',base,roots)
    with pytest.raises(ContractError):runtime.activate(target,approval(base,target,**changes))
    assert runtime.active() == base
    assert runtime._db.execute('SELECT count(*) FROM used_grants').fetchone()[0] == 0
    runtime.close()


def test_rollback_cannot_mix_old_state_or_restore_an_unaccepted_sibling(tmp_path):
    base,target,roots=fixtures(tmp_path)
    changed=target.record.data()
    changed['components']['M5']=base.record.data()['components']['M5']
    mixed=JointDeploymentBundle(record(changed))
    runtime=store(tmp_path/'joint.sqlite',base,roots)
    runtime.activate(target,approval(base,target))
    with pytest.raises(ContractError,match='exact prior bundle'):runtime.rollback(rollback(target,mixed))
    assert runtime.active() == target
    runtime.rollback(rollback(target,base))
    assert runtime.active() == base
    runtime.close()


@pytest.mark.parametrize('reconstruct_earlier_store', [False, True])
def test_same_independent_acceptance_cannot_be_reenveloped_after_rollback(tmp_path, reconstruct_earlier_store):
    base,target,roots=fixtures(tmp_path)
    runtime=store(tmp_path/'joint.sqlite',base,roots)
    first=approval(base,target)
    runtime.activate(target,first)
    runtime.rollback(rollback(target,base))
    # A trusted service has produced a different envelope for the same original
    # acceptance; envelope identity alone would permit it after rollback.
    second=approval(base,target,selection_digest='f'*64)
    assert second.content_hash != first.content_hash
    if reconstruct_earlier_store:
        runtime._db.execute('DROP TABLE consumed_acceptances')
        runtime.close()
        runtime=store(tmp_path/'joint.sqlite',base,roots)
    with pytest.raises(ContractError,match='acceptance receipt was already consumed'):
        runtime.activate(target,second)
    assert runtime.active()==base
    assert runtime._db.execute('SELECT count(*) FROM consumed_acceptances').fetchone()[0]==1
    runtime.close()


def test_failure_at_acceptance_consumption_rolls_back_active_pointer_and_both_receipts(tmp_path):
    base,target,roots=fixtures(tmp_path)
    class FailConsume(JointDeploymentStore):
        failing=False
        def _consume_acceptance(self, acceptance_digest, grant_digest):
            super()._consume_acceptance(acceptance_digest,grant_digest)
            if self.failing:raise OSError('synthetic failure at transaction tail')
    runtime=store(tmp_path/'joint.sqlite',base,roots,FailConsume)
    runtime.failing=True
    grant=approval(base,target)
    with pytest.raises(OSError,match='transaction tail'):runtime.activate(target,grant)
    assert runtime.active()==base
    assert runtime._db.execute('SELECT count(*) FROM used_grants').fetchone()[0]==0
    assert runtime._db.execute('SELECT count(*) FROM consumed_acceptances').fetchone()[0]==0
    runtime.failing=False
    assert runtime.activate(target,grant)==target.acknowledgement()
    runtime.close()


def test_train_provenance_dependency_and_source_drift_are_enforced(tmp_path):
    base,target,roots=fixtures(tmp_path)
    body=target.record.data()
    body['components']['M4']['training_manifest']['identities'][0]['domain']='validation'
    with pytest.raises(ContractError,match='training provenance'):JointDeploymentBundle(record(body))
    body=target.record.data();del body['components']['M2']
    with pytest.raises(ContractError,match='requires M2'):JointDeploymentBundle(record(body))
    body=target.record.data();body['components']['M5']['source_files']={'../outside.py':'a'*64}
    with pytest.raises(ContractError,match='relative file'):JointDeploymentBundle(record(body))
    runtime=store(tmp_path/'joint.sqlite',base,roots)
    source=roots['M4']/'M4.py';original=source.read_bytes();source.write_bytes(original+b'# drift\n')
    with pytest.raises(ContractError,match='source drift'):runtime.activate(target,approval(base,target))
    with pytest.raises(ContractError,match='source drift'):runtime.run_task(identity(),lambda *_: pytest.fail('must not execute'))
    source.write_bytes(original)
    assert runtime.active() == base
    forged=approval(base,target).data();forged['mac']='0'*64
    with pytest.raises(ContractError,match='signature'):runtime.activate(target,record(forged))
    runtime.close()


def test_a_task_keeps_its_whole_snapshot_when_another_connection_activates(tmp_path):
    base,target,roots=fixtures(tmp_path)
    reader=store(tmp_path/'joint.sqlite',base,roots)
    writer=store(tmp_path/'joint.sqlite',base,roots)
    def task(_identity, pinned):
        writer.activate(target,approval(base,target))
        assert writer.active() == target
        assert pinned == base
        return {'states':{k:v.record.data()['state'] for k,v in pinned.components().items()}}
    result=reader.run_task(identity(),task).data()
    assert result['snapshot'] == base.acknowledgement().data()
    assert all(v['lesson']=='old-'+k for k,v in result['result']['states'].items())
    assert reader.active() == target
    reader.close();writer.close()


def _competing_writer(path, initial, target, roots, barrier, results):
    base=JointDeploymentBundle(FrozenRecord(initial)); candidate=JointDeploymentBundle(FrozenRecord(target))
    runtime=store(Path(path),base,roots)
    try:
        barrier.wait(timeout=20)
        runtime.activate(candidate,approval(base,candidate))
        results.put(('activated',candidate.digest))
    except ContractError as exc:results.put(('refused',str(exc)))
    finally:runtime.close()


def test_two_process_writers_publish_one_complete_winner(tmp_path):
    base,target,roots=fixtures(tmp_path)
    body=target.record.data();body['components']['M4']['state']={'lesson':'other-branch'}
    sibling=JointDeploymentBundle(record(body))
    path=tmp_path/'joint.sqlite'
    store(path,base,roots).close()
    context=multiprocessing.get_context('spawn');barrier=context.Barrier(2);results=context.Queue()
    workers=[context.Process(target=_competing_writer,args=(str(path),base.record.encoded,candidate.record.encoded,
        {k:str(v) for k,v in roots.items()},barrier,results)) for candidate in (target,sibling)]
    for worker in workers:worker.start()
    for worker in workers:
        worker.join(30)
        assert worker.exitcode == 0
    outcomes=[results.get(timeout=2) for _ in workers]
    assert sorted(s for s,_ in outcomes)==['activated','refused']
    runtime=store(path,base,roots)
    winner=runtime.active()
    assert winner in (target,sibling)
    assert winner.digest == next(d for s,d in outcomes if s=='activated')
    assert runtime._db.execute('SELECT count(*) FROM used_grants').fetchone()[0]==1
    assert runtime._db.execute('SELECT count(*) FROM bundles').fetchone()[0]==2
    assert len(winner.acknowledgement().data()['component_digests'])==9
    from research_loop.modular.joint_deployment_artifacts import verify_joint_deployment_artifacts
    checkpoint = runtime.artifact_checkpoint()
    path.with_suffix('.audit-checkpoint.json').write_bytes((checkpoint.encoded+'\n').encode())
    runtime.close()
    audit = verify_joint_deployment_artifacts(path, domain='train', checkpoint=checkpoint,
        acceptance_keys=KEYS, rollback_keys=ROLLBACK, component_source_roots=roots).data()
    assert audit['pending_attempts'] == []
    assert sum(row['kind']=='committed' for row in audit['events']) == 2  # Bootstrap and one writer.
    assert sum(row['kind']=='failed' for row in audit['events']) == 1
    path.with_suffix('.audit-read.json').write_bytes((record(audit).encoded+'\n').encode())
