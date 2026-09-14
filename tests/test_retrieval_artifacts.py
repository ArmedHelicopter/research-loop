import json

import pytest

from research_loop.modular.artifact_catalogue import ArtifactCatalogue, source_snapshot
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.modules.evidence import EvidenceLedger
from research_loop.modular.modules.retrieval import FrozenSourceBundle, SourceDocument
from research_loop.modular.retrieval_artifacts import (
    append_q84_source_ledger_artifacts, append_retrieval_artifacts,
    verify_q84_source_ledger_artifacts, verify_retrieval_artifacts)
from research_loop.modular.retrieval_review_combination_driver import BUDGET, admission_receipt, check_material, freeze_material
from research_loop.ontology import ContractError, canonical


def _task():
    identity = DataIdentity('fixture', 'm6-artifacts', 'group-a', 'v1', 'split-1', 'train')
    return PublicTask(identity, FrozenRecord.from_dict({'question': 'Which public observation matters?'}))


def _docs():
    return [SourceDocument('s001', 'root-1', 'support', FrozenRecord.from_dict({'text': 'Observe x.'})),
            SourceDocument('s002', 'root-2', 'counter', FrozenRecord.from_dict({'text': 'Check confounding.'})),
            SourceDocument('s003', 'root-3', 'method', FrozenRecord.from_dict({'text': 'Use a fixed test.'}))]


def _trace(path, *, failed=False, enabled=True):
    task = _task(); docs = _docs(); material = freeze_material(task, [d.data() for d in docs], 'Which public observation matters?')
    docs = check_material(material, task)
    pool = FrozenSourceBundle('public-train-retrieval-pool-v1', docs); admission = admission_receipt(task, pool)
    rows = [{'stage': 'q8_source_admission', 'data': {'receipt': admission.data(), 'receipt_digest': admission.content_hash}}]
    intent = ('Seek support, counterevidence, and runnable methods separately.' if enabled
              else 'Retrieve public information relevant to the question without favoring a position.')
    selected = {lane: [] for lane in ('support', 'counter', 'method')}
    for ordinal, doc in enumerate(docs):
        query = FrozenRecord.from_dict({**material.data()['query'], 'intent': intent, 'call_ordinal': ordinal})
        rows.append({'stage': 'q8_retrieval_request', 'data': {'lane': doc.lane, 'query': query.data(), 'query_digest': query.content_hash,
            'call_limit': 1, 'source_limit': 1, 'reservation': {'provider_calls': 1, 'source_slots': 1},
            'remaining': {'provider_calls': 2-ordinal, 'source_slots': 2-ordinal}, 'external_cost': {'units': None, 'status': 'unknown'}}})
        rows.append({'stage': 'q8_retrieval_item', 'data': {'lane': doc.lane, 'ordinal': 0,
            'source_digest': FrozenRecord.from_dict(doc.data()).content_hash, 'within_reservation': True}})
        if failed:
            rows.append({'stage': 'q8_retrieval_failure', 'data': {'lane': doc.lane, 'error_type': 'RuntimeError', 'returned_before_failure': 1,
                'reported_cost': 7, 'verified_external_cost': {'units': None, 'status': 'unknown'}, 'reserved_provider_calls': 1, 'reserved_source_slots': 1}})
            break
        rows.append({'stage': 'q8_retrieval_result', 'data': {'lane': doc.lane, 'returned': 1, 'unused_reserved_sources': 0,
            'provider_invocations': 1, 'external_cost': {'units': None, 'status': 'unknown'}}})
        selected[doc.lane].append(doc.data())
    if not failed:
        projection = {'source_bundle_digest': pool.content_hash,
            'policy_digest': FrozenRecord.from_dict({'policy': 'three_lane' if enabled else 'neutral', 'budget': BUDGET, 'source_context_enabled': True}).content_hash,
            'by_lane': selected, 'source_qualification': 'caller_declared_public_train_unvalidated', 'scientific_admission': False}
        used = len(FrozenRecord.from_dict(projection).encoded.encode('utf-8'))
        usage = {'limits': BUDGET, 'provider_calls': 3, 'unused_provider_calls': 0, 'sources_returned': 3,
            'unused_source_slots': 0, 'context_bytes': used, 'unused_context_bytes': 4096-used,
            'external_cost': {'units': None, 'status': 'unknown'}}
        rows.extend([{'stage': 'q8_retrieval_selection', 'data': {'dropped_duplicate_roots': [], 'excluded_context_budget': []}},
            {'stage': 'q8_retrieval_budget', 'data': usage}, {'stage': 'retrieval_review_sources', 'data': {'projection': projection, 'usage': usage}}])
    path.write_text(''.join(canonical(row)+'\n' for row in rows), encoding='utf-8')
    return task, material


def _catalogue(tmp_path, task, trace):
    return ArtifactCatalogue(tmp_path/'artifacts.jsonl', identity=task.identity, run_id='a'*32,
        experiment_id='b'*64, lock_digest='c'*64, producer_source=source_snapshot(trace))


def test_replays_actual_source_events_and_preserves_disabled_activation(tmp_path):
    trace = tmp_path/'trace.jsonl'; task, material = _trace(trace, enabled=False); catalogue = _catalogue(tmp_path, task, trace)
    descriptors = append_retrieval_artifacts(catalogue, trace_path=trace, task=task, material=material, enabled=False)
    assert descriptors and all(d.data()['status'] == 'not_applied' for d in descriptors)
    assert verify_retrieval_artifacts(catalogue, trace_path=trace, task=task, material=material, enabled=False).data()['descriptor_count'] == len(descriptors)


@pytest.mark.parametrize('fault', ['substitution', 'missing_event', 'extra_event'])
def test_rejects_rehashed_or_noncanonical_source_event_sequences(tmp_path, fault):
    trace = tmp_path/'trace.jsonl'; task, material = _trace(trace); catalogue = _catalogue(tmp_path, task, trace)
    rows = [json.loads(line) for line in trace.read_text(encoding='utf-8').splitlines()]
    if fault == 'substitution': next(row for row in rows if row['stage'] == 'q8_retrieval_item')['data']['source_digest'] = '0'*64
    elif fault == 'missing_event': rows.pop(next(i for i, row in enumerate(rows) if row['stage'] == 'q8_retrieval_result'))
    else: rows.append(rows[-1])
    trace.write_text(''.join(canonical(row)+'\n' for row in rows), encoding='utf-8')
    with pytest.raises(ContractError): append_retrieval_artifacts(catalogue, trace_path=trace, task=task, material=material, enabled=True)


def test_provider_failure_is_terminal_before_model_and_keeps_unknown_cost(tmp_path):
    trace = tmp_path/'trace.jsonl'; task, material = _trace(trace, failed=True); catalogue = _catalogue(tmp_path, task, trace)
    descriptors = append_retrieval_artifacts(catalogue, trace_path=trace, task=task, material=material, enabled=True)
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
