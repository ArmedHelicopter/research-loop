"""Per-event M4/M5 provenance for the durable prediction and review journals.

The bridge is deliberately attached to the writers rather than a C4 summary.
It records the immutable event that has already reached fsync, including events
from callers other than C4.  It does not make an optimization or scientific
acceptance claim.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research_loop.modular.artifact_catalogue import source_snapshot
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.modules import predictions as predictions_module
from research_loop.modular.modules import review as review_module
from research_loop.modular.modules.predictions import PredictionRegistry
from research_loop.modular.modules.review import ReviewEngine
from research_loop.ontology import ContractError, canonical


_MODULE = {'predictions': 'M4', 'reviews': 'M5'}


class M4M5ArtifactBridge:
    """Append descriptors after the module's own JSONL event is durable."""

    def __init__(self, session) -> None:
        self.session = session
        self.counts = {'predictions': 0, 'reviews': 0}
        self.reveals = 0
        self.events: dict[tuple[str, str], str] = {}
        self.module_sources = {
            'predictions': source_snapshot(Path(predictions_module.__file__)),
            'reviews': source_snapshot(Path(review_module.__file__)),
        }
        self.bridge_source = source_snapshot(Path(__file__))

    def _parents(self, journal: str, event: dict[str, Any]) -> tuple[str, ...]:
        if journal == 'predictions':
            if event['event'] == 'outcome':
                return (self.events[('predictions', event['plan_id'])],)
            return ()
        review_id = event['review_id']
        if event['event'] == 'open':
            return ()
        parents = [self.events[('reviews', review_id)]]
        if event['event'] in {'revise', 'score'}:
            for role in self._roles(review_id):
                parents.append(self.events[('reviews', review_id + ':' + role)])
        return tuple(dict.fromkeys(parents))

    def _roles(self, review_id: str) -> tuple[str, ...]:
        result = []
        for (journal, key), _ in self.events.items():
            if journal == 'reviews' and key.startswith(review_id + ':'):
                result.append(key.rsplit(':', 1)[1])
        return tuple(result)

    def journal(self, journal: str, frozen_event: FrozenRecord) -> None:
        """Called synchronously after JSONL fsync; failure terminalizes the run."""
        try:
            if journal not in _MODULE or not isinstance(frozen_event, FrozenRecord):
                raise ContractError('M4/M5 artifact bridge requires its frozen journal event')
            event = frozen_event.data()
            if event.get('identity') != self.session.task.identity.data() or event.get('event') not in ({'freeze', 'outcome'} if journal == 'predictions' else {'open', 'submit', 'revise', 'score'}):
                raise ContractError('M4/M5 journal event has an invalid subject or kind')
            parents = self._parents(journal, event)
            enabled = _MODULE[journal] in self.session.arm.data()['enabled']
            payload = FrozenRecord.from_dict({
                'schema': 'm4-m5-journal-artifact-v1', 'journal': journal,
                'journal_index': self.counts[journal], 'event': event,
                'module_enabled': enabled, 'module_source': self.module_sources[journal],
                'bridge_source': self.bridge_source,
            })
            descriptor = self.session.record_artifact(kind='journal_event', module=_MODULE[journal], payload=payload,
                parents=parents, status='produced' if enabled else 'not_applied', producer_source=self.module_sources[journal])
            self.counts[journal] += 1
            key = event['plan_id'] if journal == 'predictions' else event['review_id']
            if journal == 'reviews' and event['event'] == 'submit':
                key += ':' + event['role_id']
            self.events[(journal, key)] = descriptor.content_hash
        except Exception:
            self.session._audit_failure()
            raise

    def reveal(self, output: FrozenRecord) -> None:
        """Capture the actual sealed tuple returned by ``ReviewEngine.reveal``.

        Reveal has no journal event by design, so this is an output observer;
        it leaves the established review JSONL algorithm and bytes unchanged.
        """
        try:
            body = output.data()
            review_id = body.get('review_id')
            if set(body) != {'schema', 'review_id', 'submissions'} or body['schema'] != 'm5-reveal-output-v1' or not isinstance(body['submissions'], list):
                raise ContractError('M5 reveal observer received an invalid output')
            parents = tuple(self.events[('reviews', review_id + ':' + item['role_id'])] for item in body['submissions'])
            enabled = 'M5' in self.session.arm.data()['enabled']
            payload = FrozenRecord.from_dict({'schema': 'm5-reveal-artifact-v1', 'reveal_index': self.reveals,
                'output': body, 'module_enabled': enabled, 'module_source': self.module_sources['reviews'],
                'bridge_source': self.bridge_source})
            self.session.record_artifact(kind='reveal_output', module='M5', payload=payload, parents=parents,
                status='produced' if enabled else 'not_applied', producer_source=self.module_sources['reviews'])
            self.reveals += 1
        except Exception:
            self.session._audit_failure()
            raise


def _read_journal(path: Path) -> list[dict[str, Any]]:
    raw = path.read_bytes()
    if raw and not raw.endswith(b'\n'):
        raise ContractError('M4/M5 source journal has an incomplete final line')
    rows = []
    for line in raw.decode('utf-8').splitlines():
        try:
            event = json.loads(line)
        except ValueError as exc:
            raise ContractError('M4/M5 source journal is invalid JSON') from exc
        if not isinstance(event, dict) or canonical(event) != line:
            raise ContractError('M4/M5 source journal is not canonical')
        rows.append(event)
    return rows


def verify_m4_m5_artifacts(catalogue, sidecar):
    """Reopen public registries and reconcile every persisted event descriptor."""
    try:
        return _verify_m4_m5_artifacts(catalogue, Path(sidecar))
    except ContractError:
        raise
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ContractError('malformed M4/M5 module artifact cannot be replayed') from exc


def _verify_m4_m5_artifacts(catalogue, sidecar: Path):
    if (sidecar / 'audit-failure.json').exists():
        raise ContractError('runtime audit failed and cannot be accepted as complete')
    prediction_path, review_path = sidecar / 'predictions.jsonl', sidecar / 'reviews.jsonl'
    if not prediction_path.is_file() or not review_path.is_file():
        raise ContractError('M4/M5 source journals are missing')
    # Construction replays each source journal using the module's validation;
    # it checks plan/review IDs, identities, budget, duplicate roles, barrier,
    # revisions and score semantics before descriptors are trusted.
    PredictionRegistry(catalogue.identity, storage_path=prediction_path)
    ReviewEngine(catalogue.identity, storage_path=review_path)
    journals = {'predictions': _read_journal(prediction_path), 'reviews': _read_journal(review_path)}
    bridge = M4M5ArtifactBridge.__new__(M4M5ArtifactBridge)
    bridge.module_sources = {'predictions': source_snapshot(Path(predictions_module.__file__)),
                             'reviews': source_snapshot(Path(review_module.__file__))}
    bridge.bridge_source = source_snapshot(Path(__file__))
    all_descriptors = catalogue.records()
    trace_rows = _verified_trace_rows(all_descriptors)
    if not trace_rows:
        raise ContractError('M4/M5 artifact verification requires the original lock trace')
    lock = FrozenRecord.from_dict(trace_rows[0]['data']).data()
    if lock.get('identity') != catalogue.identity.data() or not isinstance(lock.get('arm'), dict):
        raise ContractError('M4/M5 artifact lock does not bind its task and activation')
    active = set(lock['arm'].get('enabled', []))
    expected_index = {'predictions': 0, 'reviews': 0}
    seen: dict[tuple[str, str], str] = {}
    consumed = {'predictions': [], 'reviews': []}
    reveals = []
    prior_roles: dict[str, tuple[str, ...]] = {}
    prior_submissions: dict[str, dict[str, dict[str, Any]]] = {}
    latest_trace = None
    for descriptor in all_descriptors:
        body = descriptor.data()
        if body['kind'] == 'trace_event':
            trace = FrozenRecord.from_dict(body['payload']['canonical']).data()
            if trace['stage'] == 'c4_review_reveal':
                if 'M5' in active:
                    _bind_c4_reveal(trace, reveals)
                elif trace['data'] != {'submissions': None}:
                    raise ContractError('disabled M5 ordinary control cannot claim a sealed reveal')
            latest_trace = descriptor.content_hash
            continue
        if body['kind'] == 'reveal_output' and body['module'] == 'M5':
            payload = body['payload']['canonical']
            expected = {'schema': 'm5-reveal-artifact-v1', 'reveal_index': len(reveals),
                'output': payload['output'], 'module_enabled': 'M5' in active,
                'module_source': bridge.module_sources['reviews'], 'bridge_source': bridge.bridge_source}
            output = payload.get('output', {})
            review_id = output.get('review_id')
            expected_rows = _prior_submissions(review_id, prior_roles, prior_submissions)
            parents = [seen[('reviews', review_id + ':' + row['role_id'])] for row in expected_rows] + [latest_trace]
            if (payload != expected or output.get('schema') != 'm5-reveal-output-v1' or output.get('submissions') != expected_rows
                    or body['status'] != ('produced' if payload['module_enabled'] else 'not_applied')
                    or body['parents'] != parents or body['producer_source'] != bridge.module_sources['reviews']):
                raise ContractError('M5 reveal artifact differs from the actual sealed output')
            reveals.append({'descriptor': descriptor.content_hash, 'output': output, 'bound': False})
            continue
        if body['kind'] != 'journal_event' or body['module'] not in {'M4', 'M5'}:
            continue
        payload = body['payload']['canonical']
        journal = payload['journal']
        module = _MODULE.get(journal)
        if module != body['module'] or expected_index[journal] >= len(journals[journal]):
            raise ContractError('M4/M5 artifact has an unknown module event')
        event = journals[journal][expected_index[journal]]
        if latest_trace is None:
            raise ContractError('M4/M5 artifact lacks an enclosing trace')
        expected = {'schema': 'm4-m5-journal-artifact-v1', 'journal': journal,
            'journal_index': expected_index[journal], 'event': event,
            'module_enabled': module in active, 'module_source': bridge.module_sources[journal],
            'bridge_source': bridge.bridge_source}
        if payload != expected or event.get('identity') != catalogue.identity.data():
            raise ContractError('M4/M5 artifact does not match its original journal event')
        status = 'produced' if payload['module_enabled'] else 'not_applied'
        key = event['plan_id'] if journal == 'predictions' else event['review_id']
        if journal == 'reviews' and event['event'] == 'submit':
            key += ':' + event['role_id']
        parents = []
        if journal == 'predictions' and event['event'] == 'outcome':
            parents.append(seen[('predictions', event['plan_id'])])
        if journal == 'reviews' and event['event'] != 'open':
            parents.append(seen[('reviews', event['review_id'])])
            if event['event'] in {'revise', 'score'}:
                parents.extend(seen[('reviews', event['review_id'] + ':' + role)] for role in _review_roles(seen, event['review_id']))
        parents = list(dict.fromkeys(parents)) + [latest_trace]
        if body['status'] != status or body['parents'] != parents or body['producer_source'] != bridge.module_sources[journal]:
            raise ContractError('M4/M5 artifact status, source, or causal parents differ')
        seen[(journal, key)] = descriptor.content_hash
        if journal == 'reviews' and event['event'] == 'open':
            prior_roles[event['review_id']] = tuple(role['role_id'] for role in event['roles'])
        elif journal == 'reviews' and event['event'] == 'submit':
            prior_submissions.setdefault(event['review_id'], {})[event['role_id']] = {
                'review_id': event['review_id'], 'role_id': event['role_id'], 'reviewer_id': event['reviewer_id'],
                'response': event['response'], 'cost_units': event['cost_units'], 'before_hash': event['before_hash']}
        expected_index[journal] += 1
        consumed[journal].append(event)
    if consumed != journals:
        raise ContractError('M4/M5 artifact coverage differs from its original journal')
    _check_c4_prediction_freezes(trace_rows, journals['predictions'], 'M4' in active)
    _check_c4_sealed_submissions(trace_rows, journals['reviews'], 'M5' in active)
    return FrozenRecord.from_dict({'schema': 'm4-m5-artifacts-check-v1', 'identity': catalogue.identity.data(),
        'prediction_events': len(journals['predictions']), 'review_events': len(journals['reviews']),
        'reveal_outputs': len(reveals),
        'scientific_validated': False})


def _verified_trace_rows(descriptors):
    """Return the trace payloads after authenticating their causal stream."""
    traces = []
    previous = None
    for descriptor in descriptors:
        body = descriptor.data()
        if body['kind'] != 'trace_event':
            continue
        if body['parents'] != ([] if previous is None else [previous]):
            raise ContractError('trace artifact has an arbitrary causal parent')
        payload = body['payload']['canonical']
        trace = FrozenRecord.from_dict(payload).data()
        if not isinstance(trace, dict) or trace.get('stage') is None or not isinstance(trace.get('data'), dict):
            raise ContractError('trace artifact payload is invalid')
        traces.append(trace)
        previous = descriptor.content_hash
    return traces


def _prior_submissions(review_id, roles, submissions):
    role_order = roles.get(review_id)
    by_role = submissions.get(review_id, {})
    if role_order is None:
        raise ContractError('M5 reveal lacks its sealed review')
    if set(by_role) != set(role_order):
        raise ContractError('M5 reveal lacks complete sealed submissions')
    return [by_role[role] for role in role_order]


def _review_roles(seen, review_id: str) -> tuple[str, ...]:
    return tuple(key.rsplit(':', 1)[1] for journal, key in seen if journal == 'reviews' and key.startswith(review_id + ':'))


def _bind_c4_reveal(trace, reveals):
    """Bind a C4 trace to one earlier observed reveal output, once only."""
    rows = trace['data'].get('submissions')
    matches = [item for item in reveals if not item['bound'] and item['output']['submissions'] == rows]
    if len(matches) != 1:
        raise ContractError('C4 reveal lacks one preceding actual output descriptor')
    matches[0]['bound'] = True


def _check_c4_prediction_freezes(traces, predictions, enabled):
    c4 = [event['data'] for event in traces if event['stage'] == 'c4_prediction_frozen']
    if not c4:
        return
    freezes = [event for event in predictions if event['event'] == 'freeze']
    for trace in c4:
        registered = trace.get('registered')
        if not enabled:
            if registered is not None:
                raise ContractError('disabled M4 ordinary control cannot claim a registered prediction')
            continue
        if registered is None:
            raise ContractError('enabled M4 lacks its original registered prediction')
        matches = [event for event in freezes if {
            'plan_id': event['plan_id'], 'identity': event['identity'], 'question': event['question'],
            'branches': event['branches'], 'budget_units': event['budget_units'], 'frozen': True,
            'payload': {'question': event['question'], 'branches': event['branches'], 'budget_units': event['budget_units']}}
            == registered]
        if len(matches) != 1:
            raise ContractError('C4 frozen prediction does not bind its original prediction journal')


def _check_c4_sealed_submissions(traces, reviews, enabled):
    c4 = [event['data'] for event in traces if event['stage'] == 'c4_review_sealed']
    if not c4:
        return
    if not enabled:
        if any(trace.get('barrier_open') is not None for trace in c4) or reviews:
            raise ContractError('disabled M5 ordinary control cannot claim sealed submissions')
        return
    submissions = [event for event in reviews if event['event'] == 'submit']
    if len(c4) != len(submissions):
        raise ContractError('C4 sealed review trace and journal have different submission counts')
    for trace, submission in zip(c4, submissions, strict=True):
        if trace.get('response_digest') != FrozenRecord.from_dict(submission['response']).content_hash:
            raise ContractError('C4 sealed review response does not bind its original review journal')
