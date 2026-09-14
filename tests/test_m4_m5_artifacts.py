import json

import pytest
from types import SimpleNamespace

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.m4_m5_artifacts import verify_m4_m5_artifacts
from research_loop.modular.workflow import ModularWorkflow
from research_loop.ontology import ContractError
from test_modular_predictions_review import branches, response
from test_modular_runtime import session_at


def _actual_c4_prepare_session(tmp_path, monkeypatch, modules):
    from research_loop.modular import full_loo_modules as c4
    from test_modular_combination_benchmark_driver import _plan
    session, _, _ = session_at(tmp_path/'run', modules=modules, slots=c4.PREP_SLOTS)
    workflow = ModularWorkflow(session)
    # This seam test isolates the caller's review contract from package and
    # panel serialization, which the actual native stage test covers.
    monkeypatch.setattr(c4, '_projection', lambda _: FrozenRecord.from_dict({'instructions': 'public guidance'}))
    monkeypatch.setattr(c4, 'opaque_panel_cell_binding', lambda _: {'fixture': 'public'})
    def model(request):
        slot = request.data()['slot']
        if slot == 'm4_plan':
            plan = _plan()
            for branch in plan['branches']:
                for prediction in branch['predictions']:
                    prediction.update(observable=c4.MEASUREMENT['observable'], discriminator_id=c4.MEASUREMENT['discriminator_id'])
            return FrozenRecord.from_dict(plan)
        if slot.startswith('review_'): return FrozenRecord.from_dict(response())
        return FrozenRecord.from_dict({'job_id': 'auxiliary', 'rationale': 'Check a public alternative.'})
    c4.prepare(cell=SimpleNamespace(runtime_arm=session.arm), task=session.task, package=None,
        transition=FrozenRecord.from_dict({'public': {}}), predictions=workflow.predictions, reviews=workflow.reviews,
        invoke=lambda slot, instruction, module: session.invoke(slot, model, instruction=instruction, module_context=module),
        record=session._record, retrieve=lambda: {'public': 'fixture'},
        phase_material=FrozenRecord.from_dict({'jobs': [{'id': 'main'}, {'id': 'auxiliary'}]}))
    return session


@pytest.mark.parametrize('modules', [('M4', 'M5'), ('M4',), ()])
def test_actual_c4_prepare_preserves_enabled_and_ordinary_control_artifacts(tmp_path, monkeypatch, modules):
    session = _actual_c4_prepare_session(tmp_path, monkeypatch, modules)
    checked = verify_m4_m5_artifacts(session.artifacts, session.sidecar).data()
    assert checked['prediction_events'] == int('M4' in modules)
    assert checked['review_events'] == (3 if 'M5' in modules else 0)
    assert checked['reveal_outputs'] == int('M5' in modules)


@pytest.mark.parametrize('event,stage', [('freeze', 'c4_prediction_frozen'), ('submit', 'c4_review_sealed')])
def test_actual_c4_events_require_prior_module_outputs(tmp_path, monkeypatch, event, stage):
    session = _actual_c4_prepare_session(tmp_path, monkeypatch, ('M4', 'M5'))
    session.artifacts.seal()
    rows = [json.loads(line) for line in session.artifacts.path.read_bytes().splitlines()]
    index = next(i for i, row in enumerate(rows) if row['descriptor']['kind'] == 'journal_event'
                 and row['descriptor']['payload']['canonical']['event']['event'] == event)
    late = rows.pop(index)
    after = next(i for i, row in enumerate(rows) if row['descriptor']['kind'] == 'trace_event'
                 and row['descriptor']['payload']['canonical']['stage'] == stage)
    old_trace_parent = late['descriptor']['parents'][-1]
    late['descriptor']['parents'][-1] = rows[after]['descriptor_digest']
    rows.insert(after + 1, late)
    # All hashes and the actual seal remain valid; only the historical claim
    # that this module output was already available is false.
    coherently_rehash_catalogue(session, rows)
    with pytest.raises(ContractError, match='C4'):
        verify_m4_m5_artifacts(session.artifacts, session.sidecar)


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


def c4_reveal_history(tmp_path):
    session, workflow = history(tmp_path)
    output = next(d.data()['payload']['canonical']['output'] for d in session.artifacts.records()
                  if d.data()['kind'] == 'reveal_output')
    session._record_event('c4_review_reveal', {'submissions': output['submissions']})
    return session, workflow


def coherently_rehash_catalogue(session, rows):
    """Model an attacker who recomputes every catalogue hash and the seal."""
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
    return seal


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


def test_c4_reveal_trace_requires_one_preceding_actual_output_after_coherent_rehash(tmp_path):
    session, _ = c4_reveal_history(tmp_path)
    assert verify_m4_m5_artifacts(session.artifacts, session.sidecar).data()['reveal_outputs'] == 1
    session.artifacts.seal()
    rows = [json.loads(line) for line in session.artifacts.path.read_bytes().splitlines()]
    rows = [row for row in rows if row['descriptor']['kind'] != 'reveal_output']
    seal = coherently_rehash_catalogue(session, rows)
    session.artifacts.verify(seal)
    with pytest.raises(ContractError, match='preceding actual output'):
        verify_m4_m5_artifacts(session.artifacts, session.sidecar)


def test_c4_reveal_trace_rejects_coherently_rehashed_submission_order(tmp_path):
    session, _ = c4_reveal_history(tmp_path)
    session.artifacts.seal()
    rows = [json.loads(line) for line in session.artifacts.path.read_bytes().splitlines()]
    trace = next(row['descriptor']['payload']['canonical']['data'] for row in rows
                 if row['descriptor']['kind'] == 'trace_event'
                 and row['descriptor']['payload']['canonical']['stage'] == 'c4_review_reveal')
    trace['submissions'].reverse()
    seal = coherently_rehash_catalogue(session, rows)
    session.artifacts.verify(seal)
    with pytest.raises(ContractError, match='preceding actual output'):
        verify_m4_m5_artifacts(session.artifacts, session.sidecar)


def test_trace_parent_chain_rejects_coherently_rehashed_new_root(tmp_path):
    session, _ = c4_reveal_history(tmp_path)
    session.artifacts.seal()
    rows = [json.loads(line) for line in session.artifacts.path.read_bytes().splitlines()]
    trace = next(row['descriptor'] for row in rows if row['descriptor']['kind'] == 'trace_event'
                 and row['descriptor']['payload']['canonical']['stage'] == 'c4_review_reveal')
    trace['parents'] = []
    seal = coherently_rehash_catalogue(session, rows)
    session.artifacts.verify(seal)
    with pytest.raises(ContractError, match='arbitrary causal parent'):
        verify_m4_m5_artifacts(session.artifacts, session.sidecar)


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
