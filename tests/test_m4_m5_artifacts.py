import json

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.m4_m5_artifacts import verify_m4_m5_artifacts
from research_loop.modular.workflow import ModularWorkflow
from research_loop.ontology import ContractError
from test_modular_predictions_review import branches, response
from test_modular_runtime import session_at


def history(tmp_path, modules=('M4', 'M5')):
    session, _, _ = session_at(tmp_path / 'run', modules=modules)
    workflow = ModularWorkflow(session)
    plan = workflow.predictions.freeze('Which public result discriminates?', branches(), budget_units=3)
    workflow.predictions.record_outcome(plan.plan_id, 'shared', 'observed-1',
        {'mechanism': 'consistent', 'measurement': 'failed'},
        {'trusted_evaluator': 'independent-fixture', 'verified': True})
    review = workflow.reviews.open(task_binding=session.task.content_hash, evidence_snapshot='public-snapshot', budget_units=2,
        roles=[{'role_id': 'mechanism', 'question': 'Does the mechanism fit?'},
               {'role_id': 'measurement', 'question': 'Could measurement explain it?'}])
    workflow.reviews.submit(review.review_id, role_id='mechanism', reviewer_id='reviewer-a', response=response(), cost_units=1)
    workflow.reviews.submit(review.review_id, role_id='measurement', reviewer_id='reviewer-b', response=response('concern'), cost_units=1)
    workflow.reviews.reveal(review.review_id)
    workflow.reviews.revise_after_reveal(review.review_id, role_id='mechanism', reviewer_id='reviewer-a', response=response('unknown'))
    workflow.reviews.record_score(review.review_id, changes=[
        {'role_id': 'mechanism', 'before': 'unknown', 'after': 'correct'},
        {'role_id': 'measurement', 'before': 'unknown', 'after': 'incorrect'}],
        scorer_receipt={'trusted_scorer': 'independent-fixture', 'verified': True})
    return session, workflow


def test_workflow_captures_each_fsynced_prediction_and_review_event(tmp_path):
    session, _ = history(tmp_path)
    checked = verify_m4_m5_artifacts(session.artifacts, session.sidecar).data()
    assert checked['prediction_events'] == 2 and checked['review_events'] == 5 and checked['reveal_outputs'] == 1
    rows = [d.data() for d in session.artifacts.records() if d.data()['kind'] == 'journal_event']
    assert [r['module'] for r in rows] == ['M4', 'M4', 'M5', 'M5', 'M5', 'M5', 'M5']
    assert all(r['status'] == 'produced' and r['scientific_validated'] is False for r in rows)
    assert len(rows[1]['parents']) == 2 and len(rows[-1]['parents']) == 4
    reveal = next(d.data() for d in session.artifacts.records() if d.data()['kind'] == 'reveal_output')
    assert reveal['status'] == 'produced' and len(reveal['parents']) == 3


def test_disabled_workflow_retains_event_with_explicit_not_applied_status(tmp_path):
    session, _ = history(tmp_path, modules=())
    verify_m4_m5_artifacts(session.artifacts, session.sidecar)
    rows = [d.data() for d in session.artifacts.records() if d.data()['kind'] == 'journal_event']
    assert rows and all(row['status'] == 'not_applied' for row in rows)
    assert all(row['payload']['canonical']['module_enabled'] is False for row in rows)


@pytest.mark.parametrize('fault', ['event_rehash', 'review_order', 'review_duplicate'])
def test_replay_rejects_forged_or_invalid_source_journal(tmp_path, fault):
    session, _ = history(tmp_path / fault)
    path = session.sidecar / ('predictions.jsonl' if fault == 'event_rehash' else 'reviews.jsonl')
    events = [json.loads(line) for line in path.read_bytes().splitlines()]
    if fault == 'event_rehash':
        events[1]['outcome_id'] = 'forged-outcome'
    elif fault == 'review_order':
        events[1], events[2] = events[2], events[1]
    else:
        events.append(events[-1])
    path.write_text('\n'.join(json.dumps(event, sort_keys=True, separators=(',', ':')) for event in events) + '\n', encoding='utf-8')
    with pytest.raises(ContractError):
        verify_m4_m5_artifacts(session.artifacts, session.sidecar)


def test_artifact_failure_is_terminal_before_a_later_model_call(tmp_path, monkeypatch):
    session, _, _ = session_at(tmp_path / 'failure', modules=('M4',))
    workflow = ModularWorkflow(session)
    original = session.artifacts.append
    def fail(**kwargs):
        if kwargs['kind'] == 'journal_event':
            raise OSError('injected catalogue failure')
        return original(**kwargs)
    monkeypatch.setattr(session.artifacts, 'append', fail)
    with pytest.raises(OSError):
        workflow.predictions.freeze('Which public result discriminates?', branches(), budget_units=3)
    assert (session.sidecar / 'predictions.jsonl').read_bytes()
    assert json.loads((session.sidecar / 'audit-failure.json').read_bytes())['terminal'] is True
    with pytest.raises(ContractError):
        session.invoke('final', lambda _: None, instruction='must not run after an artifact failure')


def test_missing_source_journal_is_rejected_without_recreating_it(tmp_path):
    session, _ = history(tmp_path)
    missing = session.sidecar / 'reviews.jsonl'
    missing.unlink()
    before = sorted(path.name for path in session.sidecar.iterdir())
    with pytest.raises(ContractError, match='source journals are missing'):
        verify_m4_m5_artifacts(session.artifacts, session.sidecar)
    assert not missing.exists() and sorted(path.name for path in session.sidecar.iterdir()) == before


def test_rehashed_catalogue_chain_and_seal_cannot_cross_task_identity(tmp_path):
    session, _ = history(tmp_path)
    session.artifacts.seal()
    source = session.sidecar / 'predictions.jsonl'
    events = [json.loads(line) for line in source.read_bytes().splitlines()]
    events[0]['identity']['task_id'] = 'forged-other-task'
    source.write_text('\n'.join(json.dumps(event, sort_keys=True, separators=(',', ':')) for event in events) + '\n', encoding='utf-8')
    rows = [json.loads(line) for line in session.artifacts.path.read_bytes().splitlines()]
    target = next(row['descriptor']['payload']['canonical']['event'] for row in rows
                  if row['descriptor']['kind'] == 'journal_event' and row['descriptor']['module'] == 'M4'
                  and row['descriptor']['payload']['canonical']['event']['event'] == 'freeze')
    target['identity']['task_id'] = 'forged-other-task'
    replacements, previous, rebuilt = {}, None, []
    for number, row in enumerate(rows):
        descriptor, old = row['descriptor'], row['descriptor_digest']
        descriptor['parents'] = [replacements.get(parent, parent) for parent in descriptor['parents']]
        payload = descriptor['payload']['canonical']
        if payload is not None:
            frozen_payload = FrozenRecord.from_dict(payload)
            descriptor['payload'].update(digest=frozen_payload.content_hash, bytes=len(frozen_payload.encoded.encode()))
        frozen_descriptor = FrozenRecord.from_dict(descriptor)
        replacements[old] = frozen_descriptor.content_hash
        row.update(sequence=number, previous=previous, descriptor_digest=frozen_descriptor.content_hash)
        entry = FrozenRecord.from_dict(row)
        previous = entry.content_hash
        rebuilt.append(entry.encoded)
    session.artifacts.path.write_bytes(('\n'.join(rebuilt) + '\n').encode())
    seal = FrozenRecord.from_dict({'schema': 'artifact-catalogue-seal-v1', 'count': len(rebuilt),
        'head': previous, 'binding': session.artifacts.binding})
    session.artifacts.seal_path.write_bytes((seal.encoded + '\n').encode())
    # The physical catalogue chain and seal are coherent, so the rejection is
    # from the independently replayed M4 subject binding.
    session.artifacts.verify(seal)
    with pytest.raises(ContractError, match='different data identity'):
        verify_m4_m5_artifacts(session.artifacts, session.sidecar)
