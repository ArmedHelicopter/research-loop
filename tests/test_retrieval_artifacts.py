import json

import pytest

from research_loop.modular.artifact_catalogue import ArtifactCatalogue, source_snapshot
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.mechanism_improvement_modules import execute_retrieval
from research_loop.modular.modules.evidence import EvidenceLedger
from research_loop.modular.modules.retrieval import FrozenSourceBundle, SourceDocument
from research_loop.modular.retrieval_artifacts import (
    append_q84_source_ledger_artifacts, append_retrieval_artifacts,
    verify_q84_source_ledger_artifacts, verify_retrieval_artifacts)
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
    def __init__(self, failed): self.failed = failed
    def search(self, *, lane, query, source_bundle, call_limit, source_limit):
        yield next(doc for doc in source_bundle.documents if doc.lane == lane)
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
        execute_retrieval(session, task, _Material(material), _Provider(failed), enabled)
    except RuntimeError:
        assert failed
    path.write_bytes((session.sidecar/'trace.jsonl').read_bytes())
    return task, material, session.artifacts


def _catalogue(tmp_path, task, trace):
    return ArtifactCatalogue(tmp_path/'artifacts.jsonl', identity=task.identity, run_id='a'*32,
        experiment_id='b'*64, lock_digest='c'*64, producer_source=source_snapshot(trace))


def test_replays_actual_source_events_and_preserves_disabled_activation(tmp_path):
    trace = tmp_path/'trace.jsonl'; task, material, catalogue = _trace(trace, enabled=False)
    descriptors = [d for d in catalogue.records() if d.data()['kind'].startswith('m6_')]
    assert descriptors and all(d.data()['status'] == 'not_applied' for d in descriptors)
    assert verify_retrieval_artifacts(catalogue, trace_path=trace, task=task, material=material, enabled=False).data()['descriptor_count'] == len(descriptors)


@pytest.mark.parametrize('fault', ['substitution', 'missing_event', 'extra_event'])
def test_rejects_rehashed_or_noncanonical_source_event_sequences(tmp_path, fault):
    trace = tmp_path/'trace.jsonl'; task, material, catalogue = _trace(trace)
    rows = [json.loads(line) for line in trace.read_text(encoding='utf-8').splitlines()]
    if fault == 'substitution': next(row for row in rows if row['stage'] == 'q8_retrieval_item')['data']['source_digest'] = '0'*64
    elif fault == 'missing_event': rows.pop(next(i for i, row in enumerate(rows) if row['stage'] == 'q8_retrieval_result'))
    else: rows.append(rows[-1])
    trace.write_text(''.join(canonical(row)+'\n' for row in rows), encoding='utf-8')
    with pytest.raises(ContractError): verify_retrieval_artifacts(catalogue, trace_path=trace, task=task, material=material, enabled=True)


def test_provider_failure_is_terminal_before_model_and_keeps_unknown_cost(tmp_path):
    trace = tmp_path/'trace.jsonl'; task, material, catalogue = _trace(trace, failed=True)
    descriptors = [d for d in catalogue.records() if d.data()['kind'].startswith('m6_')]
    failure = next(d.data() for d in descriptors if d.data()['kind'] == 'm6_q8_retrieval_failure')
    assert failure['payload']['canonical']['event']['data']['verified_external_cost'] == {'units': None, 'status': 'unknown'}
    assert verify_retrieval_artifacts(catalogue, trace_path=trace, task=task, material=material, enabled=True).data()['projection_digest'] is None


def test_q84_ledger_is_separate_persisted_source_and_replayable(tmp_path):
    task = _task(); ledger_path = tmp_path/'q84-source-ledger.jsonl'; ledger = EvidenceLedger(task.identity, storage_path=ledger_path)
    ledger.append({'kind': 'observation', 'root_material': {'source_root': 'root-1'}, 'representation': 'report',
        'content': {'source_id': 's001', 'text': 'public'}, 'subject_bindings': {'task': task.content_hash}, 'independent_group': 'group-a'},
        {'trusted_validator': 'fixture', 'validator_verified': True, 'admitted': True})
    catalogue = ArtifactCatalogue(tmp_path/'artifacts.jsonl', identity=task.identity, run_id='a'*32, experiment_id='b'*64,
        lock_digest='c'*64, producer_source=source_snapshot(ledger_path))
    append_q84_source_ledger_artifacts(catalogue, ledger_path=ledger_path, task=task, m2_enabled=True, m6_enabled=True)
    assert verify_q84_source_ledger_artifacts(catalogue, ledger_path=ledger_path, task=task, m2_enabled=True, m6_enabled=True).data()['descriptor_count'] == 1
