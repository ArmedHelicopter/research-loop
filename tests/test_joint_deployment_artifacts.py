"""Actual SQLite publication, failures and independent artifact consumers."""
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.joint_deployment import JointDeploymentStore
from research_loop.modular.joint_deployment_artifacts import verify_joint_deployment_artifacts
from research_loop.ontology import ContractError
from test_joint_deployment import KEYS, ROLLBACK, approval, fixtures, identity, rollback, store

R = FrozenRecord.from_dict


def read(path, checkpoint, domain='train'):
    return verify_joint_deployment_artifacts(path, domain=domain, checkpoint=checkpoint,
        acceptance_keys=KEYS, rollback_keys=ROLLBACK,
        component_source_roots={f'M{i}': Path(path).parent/'builds' for i in range(1, 10)}).data()


def events(runtime):
    return [FrozenRecord(row[0]).data() for row in runtime._db.execute(
        'SELECT record FROM deployment_audit_events ORDER BY sequence')]


def test_actual_outputs_use_configuration_subjects_and_a_read_only_checkpoint(tmp_path):
    base, target, roots = fixtures(tmp_path); path = tmp_path/'joint.sqlite'
    runtime = store(path, base, roots)
    initial = runtime.artifact_checkpoint()
    result = runtime.run_task(identity('first-task'), lambda _identity, bundle: {'used': bundle.digest})
    runtime.activate(target, approval(base, target))
    runtime.rollback(rollback(target, base))
    last = runtime.last_operation_receipt
    assert last == runtime.artifact_checkpoint()
    runtime.close()
    original = path.read_bytes()
    report = read(path, last)
    assert path.read_bytes() == original and report['pending_attempts'] == []
    assert read(path, initial)['checkpoint'] == last.data()  # A pinned prefix accepts a valid extension.
    rows = report['events']
    starts = [r for r in rows if r['kind'] == 'started']
    assert [r['payload']['operation'] for r in starts] == ['bootstrap', 'task', 'activate', 'rollback']
    assert len({r['attempt_id'] for r in starts}) == 4
    assert all(len(r['payload']['subject']['component_digests']) == 9 for r in starts)
    assert all(r['payload']['subject']['training_identities'] == [identity().data()] for r in starts)
    assert next(r['payload']['result'] for r in rows if r['kind']=='committed'
                and r['payload']['result'].get('schema')=='joint-task-snapshot-receipt-v1') == result.data()
    assert all(r['scientific_validated'] is False and r['cost'] == {'known': False, 'units': None} for r in rows)


def test_partial_component_writes_survive_rollback_as_failed_attempt_evidence(tmp_path):
    base, target, roots = fixtures(tmp_path); path = tmp_path/'joint.sqlite'
    class FailThird(JointDeploymentStore):
        failing = False
        count = 0
        def _stage_component(self, bundle, name, component):
            super()._stage_component(bundle, name, component)
            if self.failing:
                self.count += 1
                if self.count == 3:
                    raise OSError('password=private-error-must-not-be-retained')
    runtime = store(path, base, roots, FailThird); runtime.failing = True
    with pytest.raises(OSError):
        runtime.activate(target, approval(base, target))
    failed = events(runtime)[-1]
    assert failed['kind'] == 'failed' and failed['payload']['error'] == 'OSError'
    assert len(failed['payload']['staged']) == 3
    for row in failed['payload']['staged']:
        assert row['raw'] == target.components()[row['module']].record.encoded
        assert row['producer']['name'].endswith('FailThird._stage_component')
    assert 'private-error' not in json.dumps(events(runtime))
    assert runtime.active() == base
    assert runtime._db.execute('SELECT count(*) FROM components').fetchone()[0] == 9
    assert runtime._db.execute('SELECT count(*) FROM used_grants').fetchone()[0] == 0
    runtime.failing = False
    runtime.activate(target, approval(base, target))
    assert events(runtime)[-1]['attempt_id'] != failed['attempt_id']
    checkpoint = runtime.artifact_checkpoint(); runtime.close()
    assert read(path, checkpoint)['pending_attempts'] == []


@pytest.mark.parametrize('lose_failure_log', [False, True])
def test_audit_failure_cannot_publish_components_or_consume_a_grant(tmp_path, monkeypatch, lose_failure_log):
    base, target, roots = fixtures(tmp_path); path = tmp_path/'joint.sqlite'
    runtime = store(path, base, roots)
    original = runtime._artifacts._append
    def fail(kind, attempt_id, payload):
        if kind == 'committed' or lose_failure_log and kind == 'failed':
            raise OSError('synthetic audit device failure')
        return original(kind, attempt_id, payload)
    monkeypatch.setattr(runtime._artifacts, '_append', fail)
    with pytest.raises(OSError):
        runtime.activate(target, approval(base, target))
    assert runtime.active() == base
    assert runtime._db.execute('SELECT count(*) FROM used_grants').fetchone()[0] == 0
    assert runtime._db.execute('SELECT count(*) FROM bundles').fetchone()[0] == 1
    checkpoint = runtime.artifact_checkpoint(); runtime.close()
    report = read(path, checkpoint)
    assert len(report['pending_attempts']) == int(lose_failure_log)
    if not lose_failure_log:
        assert report['events'][-1]['kind'] == 'failed'
        assert len(report['events'][-1]['payload']['staged']) == 9


def test_returned_task_output_is_retained_when_post_call_source_check_fails(tmp_path):
    base, target, roots = fixtures(tmp_path); path = tmp_path/'joint.sqlite'
    runtime = store(path, base, roots)
    source = roots['M4']/'M4.py'; original = source.read_bytes()
    def task(_identity, _bundle):
        source.write_bytes(original+b'# source changed after output\n')
        return {'actual_return': 42}
    with pytest.raises(ContractError, match='source drift'):
        runtime.run_task(identity('returned-then-failed'), task)
    failed = events(runtime)[-1]
    assert failed['kind'] == 'failed' and failed['payload']['result']['result'] == {'actual_return': 42}
    source.write_bytes(original)
    checkpoint = runtime.artifact_checkpoint(); runtime.close()
    assert read(path, checkpoint)['pending_attempts'] == []


def test_validation_results_are_in_a_different_store_and_rejected_before_event_reads(tmp_path, monkeypatch):
    base, target, roots = fixtures(tmp_path); path = tmp_path/'validation.sqlite'
    validation = DataIdentity('blade', 'acceptance-only', 'held-out', 'synthetic-v1', identity().split_id, 'validation')
    runtime = JointDeploymentStore(path, initial=base, acceptance_keys=KEYS, rollback_keys=ROLLBACK,
        source_roots=roots, task_domain='validation')
    runtime.run_task(validation, lambda *_: {'value': 'private-validation-output'})
    with pytest.raises(ContractError, match='domain'):
        runtime.run_task(identity(), lambda *_: pytest.fail('wrong-domain callback must not run'))
    checkpoint = runtime.artifact_checkpoint(); runtime.close()
    assert read(path, checkpoint, 'validation')['optimizer_visible'] is False
    original_connect = sqlite3.connect; forbidden = []
    def guarded_connect(*args, **kwargs):
        db = original_connect(*args, **kwargs)
        def guard(action, table, *_):
            if action == sqlite3.SQLITE_READ and table in {'deployment_audit_events', 'bundles', 'used_grants'}:
                forbidden.append(table)
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        db.set_authorizer(guard)
        return db
    monkeypatch.setattr(sqlite3, 'connect', guarded_connect)
    with pytest.raises(ContractError, match='domain'):
        read(path, checkpoint, 'train')
    with pytest.raises(ContractError, match='domain'):
        store(path, base, roots)
    assert forbidden == []


def _rehash(path, change):
    db = sqlite3.connect(path)
    rows = [FrozenRecord(r[0]).data() for r in db.execute('SELECT record FROM deployment_audit_events ORDER BY sequence')]
    change(rows)
    previous = '0'*64
    for row in rows:
        row['previous'] = previous; value = R(row); previous = value.content_hash
        db.execute('UPDATE deployment_audit_events SET record=?,digest=? WHERE sequence=?',
                   (value.encoded, previous, row['sequence']))
    db.execute('UPDATE deployment_audit_head SET count=?,head=? WHERE id=1', (len(rows), previous))
    db.commit(); db.close()
    return R({'schema':'joint-deployment-artifact-checkpoint-v1', 'store_id':rows[0]['store_id'],
              'domain':'train', 'count':len(rows), 'head':previous, 'state_digest':R(rows[-1]['state']).content_hash})


@pytest.mark.parametrize('fault', ['subject', 'task_binding', 'cost', 'stage_inventory', 'false_success'])
def test_coherently_rehashed_descriptors_still_require_actual_transition_semantics(tmp_path, fault):
    base, target, roots = fixtures(tmp_path); path = tmp_path/'joint.sqlite'
    runtime = store(path, base, roots)
    runtime.run_task(identity('task'), lambda *_: {'answer': 'observed'})
    with pytest.raises(ContractError):
        runtime.activate(target, approval(base, target, decision='inconclusive'))
    runtime.close()
    def change(rows):
        if fault == 'subject':
            rows[1]['payload']['subject']['training_identities'][0]['domain'] = 'validation'
        elif fault == 'task_binding':
            rows[4]['payload']['result']['identity']['task_id'] = 'different-task'
        elif fault == 'cost':
            rows[-1]['cost'] = {'known': True, 'units': 0}
        elif fault == 'stage_inventory':
            rows[2]['payload']['staged'].pop()
        else:
            rows[-1]['kind'] = 'committed'
            rows[-1]['payload']['result'] = target.acknowledgement().data()
            rows[-1]['payload']['error'] = None
    checkpoint = _rehash(path, change)
    with pytest.raises(ContractError):
        read(path, checkpoint)


@pytest.mark.parametrize('fault', ['sql_component', 'journal_tail', 'other_checkpoint'])
def test_actual_sql_and_independent_checkpoint_are_part_of_readback(tmp_path, fault):
    base, target, roots = fixtures(tmp_path); path = tmp_path/'joint.sqlite'
    runtime = store(path, base, roots)
    runtime.run_task(identity('task'), lambda *_: {'output': 1})
    checkpoint = runtime.artifact_checkpoint(); runtime.close()
    db = sqlite3.connect(path)
    if fault == 'sql_component':
        db.execute("UPDATE components SET record='{}' WHERE module='M4'")
    elif fault == 'journal_tail':
        db.execute('DELETE FROM deployment_audit_events WHERE sequence=?', (checkpoint.data()['count'],))
        prior = db.execute('SELECT sequence,digest FROM deployment_audit_events ORDER BY sequence DESC LIMIT 1').fetchone()
        db.execute('UPDATE deployment_audit_head SET count=?,head=? WHERE id=1', prior)
    else:
        checkpoint = R({**checkpoint.data(), 'store_id': 'foreign-store'})
    db.commit(); db.close()
    with pytest.raises(ContractError):
        read(path, checkpoint)


def test_legacy_store_is_an_observed_baseline_without_inventing_old_operations(tmp_path):
    base, target, roots = fixtures(tmp_path); path = tmp_path/'joint.sqlite'
    runtime = store(path, base, roots); runtime.activate(target, approval(base, target))
    for name in ('deployment_audit_events', 'deployment_audit_head', 'deployment_audit_meta'):
        runtime._db.execute('DROP TABLE '+name)
    runtime.close()
    reopened = store(path, base, roots)
    assert reopened.active() == target
    rows = events(reopened)
    assert len(rows) == 1 and rows[0]['kind'] == 'baseline'
    assert rows[0]['payload']['history_complete'] is False
    checkpoint = reopened.artifact_checkpoint(); reopened.close()
    assert read(path, checkpoint)['pending_attempts'] == []


def test_failed_return_cannot_be_rehashed_into_another_task(tmp_path):
    base, target, roots = fixtures(tmp_path); path = tmp_path/'joint.sqlite'
    runtime = store(path, base, roots)
    source = roots['M4']/'M4.py'; original = source.read_bytes()
    def task(*_):
        source.write_bytes(original+b'# changed\n')
        return {'answer': 7}
    with pytest.raises(ContractError):
        runtime.run_task(identity('actual-task'), task)
    source.write_bytes(original); runtime.close()
    def change(rows):
        rows[-1]['payload']['result']['identity']['domain'] = 'validation'
    checkpoint = _rehash(path, change)
    with pytest.raises(ContractError, match='pinned configuration'):
        read(path, checkpoint)


def test_commit_survives_a_caller_delivery_failure_without_a_false_failed_transition(tmp_path):
    base, target, roots = fixtures(tmp_path); path = tmp_path/'joint.sqlite'
    class FailDelivery(JointDeploymentStore):
        failing = False
        def _remember(self, anchor):
            if self.failing:
                self.failing = False
                raise OSError('synthetic failure after COMMIT')
            return super()._remember(anchor)
    runtime = store(path, base, roots, FailDelivery); runtime.failing = True
    with pytest.raises(OSError, match='after COMMIT') as failure:
        runtime.activate(target, approval(base, target))
    assert any('durably committed' in note for note in failure.value.__notes__)
    assert runtime.active() == target and events(runtime)[-1]['kind'] == 'committed'
    assert runtime._db.execute('SELECT count(*) FROM used_grants').fetchone()[0] == 1
    checkpoint = runtime.artifact_checkpoint(); runtime.close()
    assert read(path, checkpoint)['pending_attempts'] == []


def test_independent_reader_checks_actual_component_source_bytes(tmp_path):
    base, target, roots = fixtures(tmp_path); path = tmp_path/'joint.sqlite'
    runtime = store(path, base, roots); checkpoint = runtime.artifact_checkpoint(); runtime.close()
    source = roots['M7']/'M7.py'; original = source.read_bytes()
    source.write_bytes(original+b'# altered component\n')
    with pytest.raises(ContractError, match='source drift'):
        read(path, checkpoint)
    source.write_bytes(original)
    assert read(path, checkpoint)['component_sources_verified'] is True


def test_component_subject_preserves_multiple_train_tasks_without_choosing_a_fake_owner(tmp_path):
    from research_loop.modular.joint_deployment import JointDeploymentBundle
    from research_loop.modular.modules.improvement import TrainingManifest
    base, target, roots = fixtures(tmp_path); path = tmp_path/'joint.sqlite'
    body = base.record.data()
    for name, component in body['components'].items():
        component['training_manifest'] = TrainingManifest.freeze([identity(), identity('source-'+name)]).record.data()
    multi = JointDeploymentBundle(R(body))
    runtime = store(path, multi, roots)
    subject = events(runtime)[1]['payload']['subject']
    assert len(subject['training_identities']) == 10
    assert 'identity' not in subject and subject['kind'] == 'joint_configuration'
    checkpoint = runtime.artifact_checkpoint(); runtime.close()
    assert read(path, checkpoint)['component_sources_verified'] is True
