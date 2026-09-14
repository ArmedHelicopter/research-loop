import json
from pathlib import Path

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.evidence_artifacts import verify_evidence_artifacts
from research_loop.ontology import ContractError
from test_modular_runtime import session_at


def history(path, *, modules=('M1', 'M2', 'M3')):
    session, execution, receipts = session_at(path, modules=modules)
    session.admit(execution.content_hash, receipts)
    root = session.admission_roots[execution.content_hash]
    bindings = {'task': session.task.identity.task_id, 'objective': session.objective.content_hash}
    first = session.claims.create('original interpretation', subject_bindings=bindings)
    session.claims.apply(first.claim_id, {'supports': [root], 'refutes': [], 'subject_bindings': bindings}, expected_revision=0)
    second = session.claims.create('downstream interpretation', subject_bindings=bindings)
    session.claims.link_dependencies(second.claim_id, [first.claim_id], expected_revision=0)
    session.claims.mark_unattributed_summary(first.claim_id, 'Unattributed text is not new evidence.', expected_revision=1)
    session.evidence.withdraw(root, 'upstream observation was withdrawn')
    session.claims.refresh_after_withdrawal()
    return session


def test_actual_admission_direct_ledger_and_withdrawal_descendants_reconcile(tmp_path):
    session = history(tmp_path / 'run')
    checked = verify_evidence_artifacts(session.artifacts, session.sidecar).data()
    assert checked['admission_events'] == 2
    assert checked['ledger_events'] == {'evidence': 2, 'claims': 8}
    outputs = [d.data() for d in session.artifacts.records() if d.data()['kind'] == 'ledger_event']
    kinds = [d['payload']['canonical']['event']['event'] for d in outputs]
    assert kinds == ['append', 'create', 'apply', 'create', 'dependency_update',
                     'summary_notice', 'dependency_refresh', 'withdraw', 'withdrawal_refresh', 'dependency_refresh']
    assert any(e['relation'] == 'checked_by' for e in outputs[0]['payload']['canonical']['relations'])
    assert outputs[-2]['payload']['canonical']['output']['needs_review'] is True
    assert outputs[-1]['payload']['canonical']['output']['needs_review'] is True
    assert outputs[2]['payload']['canonical']['output']['support_roots']
    assert not outputs[-2]['payload']['canonical']['output']['support_roots']
    session.artifacts.seal()
    assert verify_evidence_artifacts(session.artifacts, session.sidecar) == FrozenRecord.from_dict(checked)
    assert all(not d['scientific_validated'] for d in outputs)


def test_disabled_modules_retain_actual_common_floor_without_false_activation(tmp_path):
    session = history(tmp_path / 'baseline', modules=())
    verify_evidence_artifacts(session.artifacts, session.sidecar)
    rows = [d.data() for d in session.artifacts.records()
            if d.data()['kind'] == 'ledger_event' or d.data()['kind'].startswith('admission_')]
    assert rows and all(row['status'] == 'not_applied' for row in rows)
    assert all(row['payload']['canonical']['module_enabled'] is False for row in rows)


def rewrite_catalogue(session, mutate):
    """Rewrite all local hashes and references; generic verification must pass."""
    rows = [json.loads(line) for line in session.artifacts.path.read_bytes().splitlines()]
    mutate(rows)
    replacements = {}
    previous = None
    result = []
    for n, row in enumerate(rows):
        d = row['descriptor']
        old_digest = row['descriptor_digest']
        d['parents'] = [replacements.get(p, p) for p in d['parents']]
        payload = d['payload']['canonical']
        if payload is not None:
            for edge in payload.get('relations', []):
                edge['artifact'] = replacements.get(edge['artifact'], edge['artifact'])
            frozen = FrozenRecord.from_dict(payload)
            d['payload'].update(digest=frozen.content_hash, bytes=len(frozen.encoded.encode()))
        frozen = FrozenRecord.from_dict(d)
        replacements[old_digest] = frozen.content_hash
        row.update(sequence=n, previous=previous, descriptor_digest=frozen.content_hash)
        entry = FrozenRecord.from_dict(row)
        previous = entry.content_hash
        result.append(entry.encoded)
    session.artifacts.path.write_bytes(('\n'.join(result) + '\n').encode())
    session.artifacts.verify()


@pytest.mark.parametrize('fault', ['output', 'cross_domain', 'refresh', 'activation', 'missing'])
def test_independent_replay_rejects_coherently_rehashed_forgery(tmp_path, fault):
    session = history(tmp_path / fault)
    def mutate(rows):
        ledger = [r['descriptor'] for r in rows if r['descriptor']['kind'] == 'ledger_event']
        if fault == 'output':
            ledger[0]['payload']['canonical']['output']['payload']['content']['stdout'] = 'fabricated finding'
        elif fault == 'cross_domain':
            ledger[0]['payload']['canonical']['event']['identity']['domain'] = 'validation'
        elif fault == 'refresh':
            ledger[-1]['payload']['canonical']['output']['needs_review'] = False
        elif fault == 'activation':
            ledger[-1]['status'] = 'not_applied'
        else:
            rows.pop()
    rewrite_catalogue(session, mutate)
    with pytest.raises(ContractError):
        verify_evidence_artifacts(session.artifacts, session.sidecar)


def test_public_replay_recomputes_root_identity_even_if_source_journal_is_also_rehashed(tmp_path):
    session, execution, receipts = session_at(tmp_path / 'root-forgery')
    session.admit(execution.content_hash, receipts)
    def mutate(rows):
        event = rows[-1]['descriptor']['payload']['canonical']['event']
        event['root_id'] = 'f' * 64
        frozen = FrozenRecord.from_dict({'root_id': event['root_id'], 'representation': event['representation'], 'payload': event['payload']})
        event['record_id'] = frozen.content_hash
        output = rows[-1]['descriptor']['payload']['canonical']['output']
        output.update(root_id=event['root_id'], record_id=event['record_id'])
        (session.sidecar / 'evidence.jsonl').write_bytes((FrozenRecord.from_dict(event).encoded + '\n').encode())
    rewrite_catalogue(session, mutate)
    with pytest.raises(ContractError, match='replayed operation'):
        verify_evidence_artifacts(session.artifacts, session.sidecar)


@pytest.mark.parametrize('failure', ['catalogue', 'source_journal'])
def test_audit_failure_after_mutation_stops_next_model_call_and_keeps_marker(tmp_path, monkeypatch, failure):
    session, execution, receipts = session_at(tmp_path / failure)
    session.admit(execution.content_hash, receipts)
    root = session.admission_roots[execution.content_hash]
    original_append = session.artifacts.append
    original_open = Path.open
    if failure == 'catalogue':
        def broken(**kw):
            if kw['kind'] == 'ledger_event':
                raise OSError('injected artifact disk failure')
            return original_append(**kw)
        monkeypatch.setattr(session.artifacts, 'append', broken)
    else:
        def broken_open(path, *args, **kwargs):
            if path == session.sidecar / 'evidence.jsonl' and args and args[0] == 'a':
                raise OSError('injected ledger disk failure')
            return original_open(path, *args, **kwargs)
        monkeypatch.setattr(Path, 'open', broken_open)
    with pytest.raises(OSError):
        session.evidence.withdraw(root, 'withdrawal must remain visible on failed audit')
    seen = []
    with pytest.raises(ContractError):
        session.invoke('final', lambda request: seen.append(request), instruction='Inspect.')
    assert not seen
    assert root in session.evidence.snapshot().data()['withdrawn']
    assert json.loads((session.sidecar / 'audit-failure.json').read_bytes())['terminal'] is True
    with pytest.raises(ContractError, match='audit failed'):
        verify_evidence_artifacts(session.artifacts, session.sidecar)


def test_rejected_admission_is_an_output_without_fabricating_evidence(tmp_path):
    session, execution, receipts = session_at(tmp_path / 'rejected')
    with pytest.raises(ContractError):
        session.admit(execution.content_hash, receipts[:1])
    result = verify_evidence_artifacts(session.artifacts, session.sidecar).data()
    assert result['admission_events'] == 2
    assert result['ledger_events'] == {'evidence': 0, 'claims': 0}
    last = session.artifacts.records()[-1].data()
    assert last['kind'] == 'admission_rejection' and last['status'] == 'rejected'


def test_each_model_request_receives_its_own_replayed_historical_inputs(tmp_path):
    session, execution, receipts = session_at(tmp_path / 'historical', slots=('before', 'after'))
    session.admit(execution.content_hash, receipts)
    root = session.admission_roots[execution.content_hash]
    requests = []
    def model(request):
        requests.append(request)
        return FrozenRecord.from_dict({'observed': True})
    session.invoke('before', model, instruction='Inspect before withdrawal.')
    before = session.evidence.snapshot().data()
    session.evidence.withdraw(root, 'later withdrawal')
    session.invoke('after', model, instruction='Inspect after withdrawal.')
    after = session.evidence.snapshot().data()
    inputs = verify_evidence_artifacts(session.artifacts, session.sidecar).data()['model_inputs']
    assert set(inputs) == {r.content_hash for r in requests}
    assert inputs[requests[0].content_hash]['evidence_snapshot'] == before
    assert inputs[requests[1].content_hash]['evidence_snapshot'] == after
    assert before != after and after['withdrawn'] == [root]
