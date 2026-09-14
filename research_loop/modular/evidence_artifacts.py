"""Per-event M1/M2 provenance, reconciled with the original runtime journals.

The observer runs after each source write, including direct ledger calls. It
cannot change a claim or grant scientific validity. Verification replays public
ledger operations in their recorded order instead of trusting rehashed JSON.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path

from research_loop.modular.artifact_catalogue import source_snapshot
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.modules import evidence as evidence_module
from research_loop.modular.modules.evidence import ClaimLedger, EvidenceLedger
from research_loop.ontology import ContractError

M1_STAGES = {
    'scientific_audit_inputs': 'admission_inputs',
    'audit_rejected': 'admission_rejection',
    'scientific_admission': 'admission_decision',
}


def _output(journal, event, evidence, claims):
    if journal == 'evidence':
        if event['event'] == 'append':
            return next(r for r in evidence.snapshot().data()['records']
                        if r['record_id'] == event['record_id'])
        return {'root_id': event['root_id'], 'withdrawn': True, 'reason': event['reason']}
    claim_id = event.get('claim_id') or event['claim']['claim_id']
    return next(c.data() for c in claims.claims() if c.claim_id == claim_id)


class EvidenceArtifactBridge:
    def __init__(self, session):
        self.session = session
        self.counts = {'evidence': 0, 'claims': 0}
        self.records = {}
        self.roots = {}
        self.claims = {}
        self.withdrawals = {}
        self.decisions = {}
        self.ledger_source = source_snapshot(Path(evidence_module.__file__))
        self.bridge_source = source_snapshot(Path(__file__))

    def admission(self, trace):
        event = trace.data()
        stage = event['stage']
        if stage not in M1_STAGES:
            return
        enabled = 'M1' in self.session.arm.data()['enabled']
        payload = FrozenRecord.from_dict({'schema': 'm1-admission-artifact-v1',
            'trace': event, 'trace_digest': trace.content_hash,
            'module_enabled': enabled, 'bridge_source': self.bridge_source})
        descriptor = self.session.record_artifact(kind=M1_STAGES[stage], module='M1', payload=payload,
            status=('rejected' if stage == 'audit_rejected' else 'produced') if enabled else 'not_applied')
        if stage == 'scientific_admission':
            execution = event['data'].get('execution_digest')
            if execution is not None:
                self.decisions[execution] = descriptor.content_hash

    def _relations(self, journal, event, output):
        edges = []
        def edge(kind, artifact):
            row = {'relation': kind, 'artifact': artifact}
            if row not in edges:
                edges.append(row)
        if journal == 'evidence':
            if event['event'] == 'withdraw':
                for artifact in self.roots.get(event['root_id'], []):
                    edge('withdraws', artifact)
            else:
                execution = event['payload']['root_material'].get('execution_digest')
                if execution in self.decisions:
                    edge('checked_by', self.decisions[execution])
        else:
            prior = self.claims.get(output['claim_id'])
            if prior:
                edge('supersedes', prior)
            representatives = {r.root_id: r for r in self.session.evidence.roots(admitted_only=False, active_only=False)}
            for field, relation in [('support_roots', 'supports'), ('refute_roots', 'refutes')]:
                for root in output[field]:
                    edge(relation, self.records[representatives[root].record_id])
            for claim in output['depends_on']:
                edge('depends_on', self.claims[claim])
            if event['event'] == 'withdrawal_refresh':
                for artifact in self.withdrawals.values():
                    # Scope is an observed withdrawal, not a scientific refutation.
                    edge('withdrawal_observed', artifact)
        return edges

    def payload(self, journal, frozen_event):
        event = frozen_event.data()
        output = _output(journal, event, self.session.evidence, self.session.claims)
        enabled = 'M2' in self.session.arm.data()['enabled']
        return FrozenRecord.from_dict({'schema': 'm2-ledger-artifact-v1', 'journal': journal,
            'journal_index': self.counts[journal], 'event': event, 'output': output,
            'module_enabled': enabled, 'ledger_source': self.ledger_source,
            'bridge_source': self.bridge_source,
            'relations': self._relations(journal, event, output)})

    def remember(self, body, descriptor_digest):
        journal, event = body['journal'], body['event']
        self.counts[journal] += 1
        if journal == 'evidence':
            if event['event'] == 'append':
                self.records[event['record_id']] = descriptor_digest
                self.roots.setdefault(event['root_id'], []).append(descriptor_digest)
            else:
                self.withdrawals[event['root_id']] = descriptor_digest
        else:
            self.claims[body['output']['claim_id']] = descriptor_digest

    def ledger(self, journal, frozen_event):
        payload = self.payload(journal, frozen_event)
        body = payload.data()
        parents = tuple(dict.fromkeys(edge['artifact'] for edge in body['relations']))
        status = 'withdrawn' if body['event']['event'] == 'withdraw' else 'produced'
        descriptor = self.session.record_artifact(kind='ledger_event', module='M2', payload=payload,
            parents=parents, status=status if body['module_enabled'] else 'not_applied',
            producer_source=self.ledger_source)
        self.remember(body, descriptor.content_hash)


def _read_journal(path):
    raw = path.read_bytes()
    if raw and not raw.endswith(b'\n'):
        raise ContractError('ledger source has an incomplete final line')
    rows = []
    for line in raw.decode('utf-8').splitlines():
        record = FrozenRecord(line)
        if record.encoded != line:
            raise ContractError('ledger source is not canonical')
        rows.append(record.data())
    return rows


def _replay(journal, event, evidence, claims):
    kind = event['event']
    if journal == 'evidence':
        if kind == 'withdraw':
            evidence.withdraw(event['root_id'], event['reason'])
        elif kind == 'append':
            payload = event['payload']
            evidence.append({k: payload[k] for k in ('kind', 'root_material', 'content')} | {
                k: event[k] for k in ('representation', 'subject_bindings', 'independent_group')},
                {k: payload[k] for k in ('trusted_validator', 'validator_verified')} | {'admitted': event['admitted']})
        else:
            raise ContractError('unknown evidence operation')
    elif kind == 'create':
        claims.create(event['statement'], subject_bindings=event['subject_bindings'])
    elif kind == 'apply':
        claims.apply(event['claim_id'], {k: event[k] for k in ('supports', 'refutes', 'subject_bindings')},
                     expected_revision=event['expected_revision'])
    elif kind == 'dependency_update':
        claims.link_dependencies(event['claim_id'], event['depends_on'], expected_revision=event['expected_revision'])
    elif kind == 'summary_notice':
        # The original API stores only the summary hash. Retain that limitation;
        # validate its revision semantics without inventing the missing text.
        claims._apply_event(event, persist=True)
    elif kind == 'withdrawal_refresh':
        claims.refresh_after_withdrawal()
    else:
        raise ContractError('claim propagation lacks its producing operation')


def verify_evidence_artifacts(catalogue, sidecar):
    """Read-only reconciliation, including exact event order and semantic replay."""
    try:
        return _verify_evidence_artifacts(catalogue, sidecar)
    except ContractError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, StopIteration) as exc:
        raise ContractError('malformed module artifact cannot be replayed') from exc


def _verify_evidence_artifacts(catalogue, sidecar):
    sidecar = Path(sidecar)
    if (sidecar / 'audit-failure.json').exists():
        raise ContractError('runtime audit failed and cannot be accepted as complete')
    descriptors = catalogue.records()
    traces = [d.data()['payload']['canonical'] for d in descriptors if d.data()['kind'] == 'trace_event']
    if not traces or traces != _read_journal(sidecar / 'trace.jsonl'):
        raise ContractError('evidence audit requires the exact source trace')
    lock = FrozenRecord.from_dict(traces[0]['data'])
    if lock.content_hash != catalogue.binding['lock_digest'] or lock.data()['identity'] != catalogue.identity.data():
        raise ContractError('evidence audit lock or identity differs')
    from types import SimpleNamespace
    replayed = deque()
    evidence = claims = None
    def observe(journal, event):
        replayed.append((journal, event.data(), _output(journal, event.data(), evidence, claims)))
    evidence = EvidenceLedger(catalogue.identity, event_sink=lambda event: observe('evidence', event))
    claims = ClaimLedger(evidence, event_sink=lambda event: observe('claims', event))
    session = SimpleNamespace(evidence=evidence, claims=claims, arm=FrozenRecord.from_dict(lock.data()['arm']))
    bridge = EvidenceArtifactBridge(session)
    actual_events = {'evidence': [], 'claims': []}
    m1_expected = [FrozenRecord.from_dict(t) for t in traces if t['stage'] in M1_STAGES]
    m1_seen = []
    model_inputs = {}
    latest_trace = None
    latest_trace_event = None
    for descriptor in descriptors:
        d = descriptor.data()
        if d['kind'] == 'trace_event':
            if replayed:
                raise ContractError('trace interrupts an incomplete ledger operation audit')
            latest_trace = descriptor.content_hash
            latest_trace_event = d['payload']['canonical']
            if latest_trace_event['stage'] == 'model_request':
                request = FrozenRecord.from_dict(latest_trace_event['data']['request'])
                if request.content_hash != latest_trace_event['data']['request_digest'] or request.content_hash in model_inputs:
                    raise ContractError('ambiguous model request in ledger history')
                model_inputs[request.content_hash] = {'evidence_snapshot': evidence.snapshot().data(),
                    'claims_snapshot': claims.snapshot().data()}
            continue
        if d['kind'] in M1_STAGES.values():
            payload = d['payload']['canonical']
            event = FrozenRecord.from_dict(payload['trace'])
            stage = event.data()['stage']
            enabled = 'M1' in lock.data()['arm']['enabled']
            expected = {'schema': 'm1-admission-artifact-v1', 'trace': event.data(),
                'trace_digest': event.content_hash, 'module_enabled': enabled, 'bridge_source': bridge.bridge_source}
            status = ('rejected' if stage == 'audit_rejected' else 'produced') if enabled else 'not_applied'
            if (payload != expected or event.data() != latest_trace_event
                    or d['module'] != 'M1' or d['kind'] != M1_STAGES.get(stage)
                    or d['status'] != status or d['parents'] != [latest_trace]
                    or d['producer_source']['path'] != str((Path(__file__).parent / 'runtime.py').resolve())):
                raise ContractError('admission artifact differs from the original operation')
            m1_seen.append(event)
            if stage == 'scientific_admission' and event.data()['data'].get('execution_digest') is not None:
                bridge.decisions[event.data()['data']['execution_digest']] = descriptor.content_hash
            continue
        if d['kind'] != 'ledger_event':
            continue
        body = d['payload']['canonical']
        journal, event = body['journal'], body['event']
        if journal not in actual_events or event.get('identity') != catalogue.identity.data():
            raise ContractError('ledger artifact crosses a task or data domain')
        if not replayed:
            _replay(journal, event, evidence, claims)
        if not replayed:
            raise ContractError('ledger operation produced no event')
        observed_journal, observed_event, observed_output = replayed.popleft()
        if (observed_journal, observed_event, observed_output) != (journal, event, body['output']):
            raise ContractError('ledger artifact does not match replayed operation and output')
        # Public operations can emit several propagation records. Each callback
        # captures its own output, not the final claim state after all callbacks.
        expected = bridge.payload(journal, FrozenRecord.from_dict(event)).data()
        expected['output'] = observed_output
        expected['relations'] = bridge._relations(journal, event, observed_output)
        parents = list(dict.fromkeys([edge['artifact'] for edge in expected['relations']] + [latest_trace]))
        status = 'withdrawn' if event['event'] == 'withdraw' else 'produced'
        if not expected['module_enabled']:
            status = 'not_applied'
        if (body != expected or d['module'] != 'M2' or d['status'] != status or d['parents'] != parents
                or d['producer_source'] != bridge.ledger_source):
            raise ContractError('ledger artifact payload, dependencies, source or activation differs')
        bridge.remember(body, descriptor.content_hash)
        actual_events[journal].append(event)
    if replayed or m1_seen != m1_expected:
        raise ContractError('module operation audit coverage is incomplete')
    for journal, events in actual_events.items():
        if events != _read_journal(sidecar / (journal + '.jsonl')):
            raise ContractError('module artifact coverage differs from its original ledger')
    return FrozenRecord.from_dict({'schema': 'evidence-artifacts-check-v1', 'identity': catalogue.identity.data(),
        'admission_events': len(m1_seen), 'ledger_events': {k: len(v) for k, v in actual_events.items()},
        'model_inputs': model_inputs, 'scientific_validated': False, 'summary_text_recovered': False})
