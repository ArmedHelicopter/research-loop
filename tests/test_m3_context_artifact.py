import json

import pytest

from research_loop.modular.benchmarks import BladeAdapter
from research_loop.modular.artifact_catalogue import ArtifactCatalogue
from research_loop.modular.context_artifact import verify_context_artifact, verify_session_context_artifacts
from research_loop.modular.contracts import ContractError, DataIdentity, FrozenRecord
from research_loop.modular.m6_public_inputs import M6PublicInputBoundary
from test_modular_runtime import session_at


def _descriptor(session):
    return next(row['descriptor'] for row in map(json.loads, (session.sidecar / 'artifacts.jsonl').read_text().splitlines())
                if row['descriptor']['kind'] == 'model_context')


def _verify(record, session, request, before):
    return verify_context_artifact(record, task=session.task, request=request,
        evidence=session.evidence.snapshot(), claims=session.claims.snapshot(), before_projection=before)


def _trace_events(session):
    return [json.loads(line) for line in (session.sidecar / 'trace.jsonl').read_text().splitlines()]


def _snapshots(session, events):
    return {event['data']['request_digest']: {'evidence': session.evidence.snapshot(),
            'claims': session.claims.snapshot()}
        for event in events if event['stage'] == 'model_request'}


@pytest.mark.parametrize('modules, mode, status', [
    (('M1', 'M2', 'M3'), 'candidate', 'produced'),
    (('M1', 'M2'), 'baseline', 'not_applied'),
])
def test_actual_invoke_registers_exact_m3_context_and_request(tmp_path, modules, mode, status):
    session, _, _ = session_at(tmp_path, modules=modules)
    seen = []
    baseline_summary = 'untrusted baseline summary' if mode == 'baseline' else ''
    session.invoke('final', lambda request: seen.append(request) or FrozenRecord.from_dict({'ok': True}),
        instruction='Inspect.', baseline_summary=baseline_summary)

    descriptor = _descriptor(session)
    record = FrozenRecord.from_dict(descriptor['payload']['canonical'])
    data = record.data()
    assert data['schema'] == 'm3-model-context-artifact-v2'
    assert data['mode'] == mode
    assert data['request'] == seen[0].data()
    assert data['final_context'] == seen[0].data()['context']
    assert data['baseline_summary'] == baseline_summary
    assert data['m3_enabled'] == ('M3' in modules)
    assert descriptor['status'] == status
    assert descriptor['producer_source']['path'].replace('\\', '/').endswith('/research_loop/modular/runtime.py')
    assert _verify(record, session, seen[0], FrozenRecord.from_dict(seen[0].data()['context'])) == record
    events = _trace_events(session)
    verify_session_context_artifacts(task=session.task, lock=session.lock, events=events,
        catalogue=session.artifacts, invocation_snapshots=_snapshots(session, events))


def test_projection_evidence_only_revalidates_every_snapshot_and_cross_domain(tmp_path):
    session, _, _ = session_at(tmp_path / 'run', modules=('M1', 'M2', 'M3'))
    projector = M6PublicInputBoundary('Q8.1', 'fixture').project_evidence_context

    seen = []
    session.invoke('final', lambda request: seen.append(request) or FrozenRecord.from_dict({'ok': True}),
        instruction='Inspect.', evidence_only=True, context_projection=projector)
    descriptor = _descriptor(session)
    record = FrozenRecord.from_dict(descriptor['payload']['canonical'])
    assert record.data()['mode'] == 'evidence_only'
    before = FrozenRecord.from_dict(record.data()['before_projection'])
    assert _verify(record, session, seen[0], before) == record
    events = _trace_events(session)
    verify_session_context_artifacts(task=session.task, lock=session.lock, events=events,
        catalogue=session.artifacts, invocation_snapshots=_snapshots(session, events))

    for field, replacement in [
        ('evidence_snapshot', {}), ('claims_snapshot', {}), ('before_projection', {}),
        ('final_context', {}), ('request', {}),
    ]:
        forged = record.data()
        forged[field] = replacement
        with pytest.raises(ContractError):
            _verify(FrozenRecord.from_dict(forged), session, seen[0], before)

    val_identity = DataIdentity('blade', 'fixture', 'source-a', 'v1', 'split', 'validation')
    val_task = BladeAdapter().prepare(val_identity, session.task.payload.data())
    with pytest.raises(ContractError):
        verify_context_artifact(record, task=val_task, request=seen[0], evidence=session.evidence.snapshot(),
            claims=session.claims.snapshot(), before_projection=before)


def test_rehashed_m3_payload_cannot_pass_trace_catalogue_replay(tmp_path):
    session, _, _ = session_at(tmp_path)
    session.invoke('final', lambda _: FrozenRecord.from_dict({'ok': True}), instruction='Inspect.')
    events = _trace_events(session)
    session.artifacts.seal()
    path = session.sidecar / 'artifacts.jsonl'
    original = [json.loads(line) for line in path.read_text().splitlines()]
    previous, rewritten = None, []
    for row in original:
        descriptor = FrozenRecord.from_dict(row['descriptor']).data()
        if descriptor['kind'] == 'model_context':
            payload = FrozenRecord.from_dict(descriptor['payload']['canonical']).data()
            payload['evidence_snapshot']['withdrawn'] = ['rehashed-fake-root']
            forged = FrozenRecord.from_dict(payload)
            descriptor['payload'] = {'digest': forged.content_hash, 'bytes': len(forged.encoded.encode()),
                                     'encoding': 'canonical_json', 'canonical': forged.data()}
        frozen_descriptor = FrozenRecord.from_dict(descriptor)
        entry = FrozenRecord.from_dict({'schema': 'artifact-catalogue-entry-v2', 'sequence': row['sequence'],
            'previous': previous, 'descriptor_digest': frozen_descriptor.content_hash, 'descriptor': frozen_descriptor.data()})
        rewritten.append(entry)
        previous = entry.content_hash
    path.write_text(''.join(entry.encoded + '\n' for entry in rewritten), newline='\n')
    seal = FrozenRecord.from_dict({'schema': 'artifact-catalogue-seal-v1', 'count': len(rewritten),
        'head': previous, 'binding': session.artifacts.binding})
    path.with_name(path.name + '.seal.json').write_bytes((seal.encoded + '\n').encode())
    catalogue = ArtifactCatalogue(path, identity=session.task.identity, run_id=session.artifacts.binding['run_id'],
        experiment_id=session.artifacts.binding['experiment_id'], lock_digest=session.artifacts.binding['lock_digest'],
        producer_source=session._artifact_source)

    with pytest.raises(ContractError):
        verify_session_context_artifacts(task=session.task, lock=session.lock, events=events,
            catalogue=catalogue, invocation_snapshots=_snapshots(session, events))


def test_audit_write_failure_closes_before_any_model_call(tmp_path, monkeypatch):
    session, _, _ = session_at(tmp_path, slots=('first', 'second'))
    called = []
    original = session.record_artifact

    def reject_context_artifact(**kwargs):
        if kwargs['kind'] == 'model_context':
            raise OSError('audit journal unavailable')
        return original(**kwargs)

    monkeypatch.setattr(session, 'record_artifact', reject_context_artifact)
    with pytest.raises(OSError, match='audit journal unavailable'):
        session.invoke('first', lambda request: called.append(request) or FrozenRecord.from_dict({'ok': True}), instruction='Inspect.')
    assert called == []
    with pytest.raises(ContractError, match='frozen schedule'):
        session.invoke('second', lambda _: FrozenRecord.from_dict({'ok': True}), instruction='Retry.')
