import json

import pytest

from research_loop.modular.artifact_catalogue import ArtifactCatalogue, source_snapshot
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.mechanism_improvement_modules import execute_retrieval
from research_loop.modular.modules.evidence import EvidenceLedger
from research_loop.modular.modules.retrieval import FrozenSourceBundle, SourceDocument
from research_loop.modular.retrieval_artifacts import (
    verify_q84_source_ledger_artifacts, verify_retrieval_artifacts, verify_retrieval_event_stream)
from research_loop.modular.retrieval_review_combination_driver import BUDGET, admission_receipt, check_material, freeze_material
from research_loop.modular.runtime import AuditVerifier, RunSession
from research_loop.ontology import ContractError, canonical


def _task():
    identity = DataIdentity('fixture', 'm6-artifacts', 'group-a', 'v1', 'split-1', 'train')
    return PublicTask(identity, FrozenRecord.from_dict({'question': 'Which public observation matters?'}))


def _docs():
    return [SourceDocument('s001', 'root-1', 'support', FrozenRecord.from_dict({'text': 'Observe x.'})),
            SourceDocument('s002', 'root-2', 'counter', FrozenRecord.from_dict({'text': 'Check confounding.'})),
            SourceDocument('s003', 'root-3', 'method', FrozenRecord.from_dict({'text': 'Use a fixed test.'}))]


class _Material:
    def __init__(self, retrieval): self._retrieval = retrieval
    def retrieval(self): return self._retrieval


class _Provider:
    def __init__(self, failed, session): self.failed, self.session = failed, session
    def search(self, *, lane, query, source_bundle, call_limit, source_limit):
        # The reservation witness must exist before provider I/O.
        records = [d.data() for d in self.session.artifacts.records() if d.data()['kind'] == 'retrieval_event']
        assert records[-1]['payload']['canonical']['event']['stage'] == 'q8_retrieval_request'
        yield next(doc for doc in source_bundle.documents if doc.lane == lane)
        records = [d.data() for d in self.session.artifacts.records() if d.data()['kind'] == 'retrieval_event']
        assert records[-1]['payload']['canonical']['event']['stage'] == 'q8_retrieval_item'
        if self.failed: raise RuntimeError('fixture provider failure')


def _trace(path, *, failed=False, enabled=True):
    task = _task(); docs = _docs(); material = freeze_material(task, [d.data() for d in docs], 'Which public observation matters?')
    arm = default_compatibility('a'*64).arm(('M6',) if enabled else ())
    session = RunSession(task, package_digest='b'*64, arm=arm, objective=FrozenRecord.from_dict({'fixture': True}),
        slots=('fixture',), execution_limit=0, sidecar=path.parent/'runtime',
        verifier=AuditVerifier({'left': b'a'*32, 'right': b'b'*32}), required_audit=('measurement',))
    # C4 legitimately has proposal/review model events before M6.  The M6
    # reader must scope from admission while retaining all later events.
    session._record('model_request', {'prior_to_retrieval': True})
    try:
        execute_retrieval(session, task, _Material(material), _Provider(failed, session), enabled)
    except RuntimeError:
        assert failed
    path.write_bytes((session.sidecar/'trace.jsonl').read_bytes())
    return task, material, session


def _catalogue(tmp_path, task, trace):
    return ArtifactCatalogue(tmp_path/'artifacts.jsonl', identity=task.identity, run_id='a'*32,
        experiment_id='b'*64, lock_digest='c'*64, producer_source=source_snapshot(trace))


def test_replays_actual_source_events_and_preserves_disabled_activation(tmp_path):
    trace = tmp_path/'trace.jsonl'; task, material, session = _trace(trace, enabled=False); catalogue = session.artifacts
    descriptors = [d for d in catalogue.records() if d.data()['kind'] == 'retrieval_event']
    assert descriptors and all(d.data()['status'] == 'not_applied' for d in descriptors)
    assert verify_retrieval_artifacts(catalogue, trace_path=trace, task=task, material=material, enabled=False).data()['descriptor_count'] == len(descriptors)


@pytest.mark.parametrize('fault', ['substitution', 'missing_event', 'extra_event'])
def test_rejects_rehashed_or_noncanonical_source_event_sequences(tmp_path, fault):
    trace = tmp_path/'trace.jsonl'; task, material, session = _trace(trace); catalogue = session.artifacts
    rows = [json.loads(line) for line in trace.read_text(encoding='utf-8').splitlines()]
    if fault == 'substitution': next(row for row in rows if row['stage'] == 'q8_retrieval_item')['data']['source_digest'] = '0'*64
    elif fault == 'missing_event': rows.pop(next(i for i, row in enumerate(rows) if row['stage'] == 'q8_retrieval_result'))
    else: rows.append(rows[-1])
    trace.write_text(''.join(canonical(row)+'\n' for row in rows), encoding='utf-8')
    with pytest.raises(ContractError): verify_retrieval_artifacts(catalogue, trace_path=trace, task=task, material=material, enabled=True)


def test_provider_failure_is_terminal_before_model_and_keeps_unknown_cost(tmp_path):
    trace = tmp_path/'trace.jsonl'; task, material, session = _trace(trace, failed=True); catalogue = session.artifacts
    descriptors = [d for d in catalogue.records() if d.data()['kind'] == 'retrieval_event']
    failure = next(d.data() for d in descriptors if d.data()['payload']['canonical']['event']['stage'] == 'q8_retrieval_failure')
    assert failure['payload']['canonical']['event']['data']['verified_external_cost'] == {'units': None, 'status': 'unknown'}
    assert verify_retrieval_artifacts(catalogue, trace_path=trace, task=task, material=material, enabled=True).data()['projection_digest'] is None
    session._record('model_request', {'illegal_after_failure': True})
    with pytest.raises(ContractError, match='failed retrieval reached a model'):
        verify_retrieval_artifacts(catalogue, trace_path=session.sidecar/'trace.jsonl', task=task, material=material, enabled=True)


def test_q84_ledger_is_separate_persisted_source_and_replayable(tmp_path):
    from research_loop.modular.retrieval_stage_panel_drivers import RetrievalStagePanelDriver
    from research_loop.modular.workflow import ModularWorkflow
    from test_modular_q81_q84_train_controller import Provider, admission, Authority, sources
    from test_modular_retrieval_panel_drivers import _task as stage_task
    from types import SimpleNamespace
    task = stage_task('blade')
    session = RunSession(task, package_digest='public', arm=default_compatibility('a'*64).arm(('M2', 'M6')),
        objective=FrozenRecord.from_dict({'question': 'fixed'}), slots=('final',), execution_limit=0,
        sidecar=tmp_path/'runtime', verifier=AuditVerifier({'a': b'a'*32, 'b': b'b'*32}), required_audit=('measurement',))
    RetrievalStagePanelDriver('Q8.4', Provider(), admission, Authority())._provenance(ModularWorkflow(session),
        SimpleNamespace(variant='shared_root'), {'sources': sources(), 'query': {'question': 'public', 'task_digest': task.content_hash},
        'budget': {'provider_calls': 3, 'source_cap': 3, 'context_bytes': 4096}})
    ledger_path = session.sidecar/'q84-source-ledger.jsonl'
    assert verify_q84_source_ledger_artifacts(session.artifacts, ledger_path=ledger_path, task=task,
        m2_enabled=True, m6_enabled=True).data()['descriptor_count'] == 3
    verify_retrieval_event_stream(session.artifacts, trace_path=session.sidecar/'trace.jsonl', task=task)
    assert not session.evidence.roots()
    changed_task = PublicTask(task.identity, FrozenRecord.from_dict({'question': 'another question with the same identity'}))
    with pytest.raises(ContractError, match='subject lock'):
        verify_q84_source_ledger_artifacts(session.artifacts, ledger_path=ledger_path, task=changed_task,
            m2_enabled=True, m6_enabled=True)
    ledger_path.unlink()
    with pytest.raises(ContractError, match='missing'):
        verify_q84_source_ledger_artifacts(session.artifacts, ledger_path=ledger_path, task=task, m2_enabled=True, m6_enabled=True)
    assert not ledger_path.exists()


@pytest.mark.parametrize('fault', ['parents', 'activation', 'delayed'])
def test_coherently_rehashed_catalogue_cannot_replace_event_binding(tmp_path, fault):
    trace = tmp_path/'trace.jsonl'; task, material, session = _trace(trace)
    session.artifacts.seal()
    rows = [json.loads(line) for line in session.artifacts.path.read_bytes().splitlines()]
    index = next(i for i, row in enumerate(rows) if row['descriptor']['kind'] == 'retrieval_event')
    target = rows[index]['descriptor']
    if fault == 'parents': target['parents'] = []
    elif fault == 'activation': target['status'] = 'not_applied'
    else:
        # Move the first witness past its next source event, keeping each
        # descriptor's parent available and rebuilding the actual seal.
        rows.insert(index + 1, rows.pop(index))
    previous = None; replacements = {}; rebuilt = []
    for number, row in enumerate(rows):
        body, old = row['descriptor'], row['descriptor_digest']
        body['parents'] = [replacements.get(p, p) for p in body['parents']]
        frozen = FrozenRecord.from_dict(body)
        replacements[old] = frozen.content_hash
        row.update(sequence=number, previous=previous, descriptor_digest=frozen.content_hash)
        entry = FrozenRecord.from_dict(row); previous = entry.content_hash
        rebuilt.append(entry.encoded)
    session.artifacts.path.write_bytes(('\n'.join(rebuilt) + '\n').encode())
    seal = FrozenRecord.from_dict({'schema': 'artifact-catalogue-seal-v1', 'count': len(rows),
                                  'head': previous, 'binding': session.artifacts.binding})
    session.artifacts.seal_path.write_bytes((seal.encoded + '\n').encode())
    session.artifacts.verify(seal)
    with pytest.raises(ContractError, match='retrieval artifact'):
        verify_retrieval_artifacts(session.artifacts, trace_path=trace, task=task, material=material, enabled=True)


def test_partial_retrieval_witness_failure_stops_before_provider_io(tmp_path, monkeypatch):
    task = _task(); material = freeze_material(task, [d.data() for d in _docs()], 'question')
    session = RunSession(task, package_digest='public', arm=default_compatibility('a'*64).arm(('M6',)),
        objective=FrozenRecord.from_dict({'question': 'fixed'}), slots=('final',), execution_limit=0,
        sidecar=tmp_path/'runtime', verifier=AuditVerifier({'a': b'a'*32, 'b': b'b'*32}), required_audit=('measurement',))
    original = session.artifacts.append
    def fail(**kwargs):
        if kwargs['kind'] == 'retrieval_event' and kwargs['payload']['event']['stage'] == 'q8_retrieval_request':
            raise OSError('retrieval witness storage failed')
        return original(**kwargs)
    monkeypatch.setattr(session.artifacts, 'append', fail)
    class NoProvider:
        def search(self, **kwargs): pytest.fail('provider must not run before its reservation witness is durable')
    with pytest.raises(OSError, match='retrieval witness storage failed'):
        execute_retrieval(session, task, _Material(material), NoProvider(), True)
    assert session._terminal and (session.sidecar/'audit-failure.json').is_file()
    records = [d.data() for d in session.artifacts.records() if d.data()['kind'] == 'retrieval_event']
    assert len(records) == 1 and records[0]['payload']['canonical']['event']['stage'] == 'q8_source_admission'
    with pytest.raises(ContractError):
        session.invoke('final', lambda _: pytest.fail('model must not run after witness failure'), instruction='report')
