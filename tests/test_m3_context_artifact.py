import json

import pytest

from research_loop.modular.benchmarks import BladeAdapter
from research_loop.modular.context_artifact import verify_context_artifact
from research_loop.modular.contracts import ContractError, DataIdentity, FrozenRecord
from test_modular_runtime import session_at


def _descriptor(session):
    return next(row['descriptor'] for row in map(json.loads, (session.sidecar / 'artifacts.jsonl').read_text().splitlines())
                if row['descriptor']['kind'] == 'model_context')


def _verify(record, session, request, before):
    return verify_context_artifact(record, task=session.task, request=request,
        evidence=session.evidence.snapshot(), claims=session.claims.snapshot(), before_projection=before)


@pytest.mark.parametrize('modules, mode, status', [
    (('M1', 'M2', 'M3'), 'candidate', 'produced'),
    (('M1', 'M2'), 'baseline', 'not_applied'),
])
def test_actual_invoke_registers_exact_m3_context_and_request(tmp_path, modules, mode, status):
    session, _, _ = session_at(tmp_path, modules=modules)
    seen = []
    session.invoke('final', lambda request: seen.append(request) or FrozenRecord.from_dict({'ok': True}), instruction='Inspect.')

    descriptor = _descriptor(session)
    record = FrozenRecord.from_dict(descriptor['payload']['canonical'])
    data = record.data()
    assert data['mode'] == mode
    assert data['request'] == seen[0].data()
    assert data['final_context'] == seen[0].data()['context']
    assert data['m3_enabled'] == ('M3' in modules)
    assert descriptor['status'] == status
    assert descriptor['producer_source']['path'].replace('\\', '/').endswith('/research_loop/modular/runtime.py')
    assert _verify(record, session, seen[0], FrozenRecord.from_dict(seen[0].data()['context'])) == record


def test_projection_evidence_only_revalidates_every_snapshot_and_cross_domain(tmp_path):
    session, _, _ = session_at(tmp_path / 'run', modules=('M1', 'M2', 'M3'))
    before = []

    def projection(context):
        before.append(context)
        return FrozenRecord.from_dict({**context.data(), 'projected': True})

    seen = []
    session.invoke('final', lambda request: seen.append(request) or FrozenRecord.from_dict({'ok': True}),
        instruction='Inspect.', evidence_only=True, context_projection=projection)
    descriptor = _descriptor(session)
    record = FrozenRecord.from_dict(descriptor['payload']['canonical'])
    assert record.data()['mode'] == 'evidence_only'
    assert record.data()['before_projection'] == before[0].data()
    assert _verify(record, session, seen[0], before[0]) == record

    for field, replacement in [
        ('evidence_snapshot', {}), ('claims_snapshot', {}), ('before_projection', {}),
        ('final_context', {}), ('request', {}),
    ]:
        forged = record.data()
        forged[field] = replacement
        with pytest.raises(ContractError):
            _verify(FrozenRecord.from_dict(forged), session, seen[0], before[0])

    val_identity = DataIdentity('blade', 'fixture', 'source-a', 'v1', 'split', 'validation')
    val_task = BladeAdapter().prepare(val_identity, session.task.payload.data())
    with pytest.raises(ContractError):
        verify_context_artifact(record, task=val_task, request=seen[0], evidence=session.evidence.snapshot(),
            claims=session.claims.snapshot(), before_projection=before[0])


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
