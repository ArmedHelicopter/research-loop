import json

import pytest

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
    assert checked['prediction_events'] == 2 and checked['review_events'] == 5
    rows = [d.data() for d in session.artifacts.records() if d.data()['kind'] == 'journal_event']
    assert [r['module'] for r in rows] == ['M4', 'M4', 'M5', 'M5', 'M5', 'M5', 'M5']
    assert all(r['status'] == 'produced' and r['scientific_validated'] is False for r in rows)
    assert len(rows[1]['parents']) == 2 and len(rows[-1]['parents']) == 4


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
