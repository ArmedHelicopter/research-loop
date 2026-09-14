"""M3 audit records for the exact contexts carried by model requests."""
from pathlib import Path
from typing import Iterable, Mapping

from research_loop.modular.contracts import FrozenRecord, PublicTask
from research_loop.modular.artifact_catalogue import source_snapshot
from research_loop.modular.modules.context import ContextBuilder
from research_loop.modular.modules.evidence import ClaimLedger, ClaimRecord, EvidenceLedger
from research_loop.ontology import ContractError, canonical


def freeze_projection_contract(projector) -> FrozenRecord:
    """Bind the only supported evidence projector to its frozen source/config."""
    from research_loop.modular.m6_public_inputs import M6PublicInputBoundary
    owner = getattr(projector, '__self__', None)
    function = getattr(projector, '__func__', None)
    if type(owner) is not M6PublicInputBoundary or function is not M6PublicInputBoundary.project_evidence_context:
        raise ContractError('M3 projection requires the frozen M6 evidence projector')
    if type(owner.coverage) is not str or type(owner.variant) is not str:
        raise ContractError('M3 projection contract requires exact M6 configuration')
    return FrozenRecord.from_dict({'schema': 'm3-m6-projection-contract-v1', 'coverage': owner.coverage,
        'variant': owner.variant, 'source': source_snapshot(Path(__file__).with_name('m6_public_inputs.py'))})


def replay_projection(contract: FrozenRecord, before: FrozenRecord) -> FrozenRecord:
    from research_loop.modular.m6_public_inputs import M6PublicInputBoundary
    if type(contract) is not FrozenRecord or type(before) is not FrozenRecord:
        raise ContractError('M3 replay needs exact projection contract and context')
    data = contract.data()
    if (set(data) != {'schema', 'coverage', 'variant', 'source'} or data['schema'] != 'm3-m6-projection-contract-v1'
            or data['source'] != source_snapshot(Path(__file__).with_name('m6_public_inputs.py'))):
        raise ContractError('M3 projection contract source or schema differs')
    return M6PublicInputBoundary(data['coverage'], data['variant']).project_evidence_context(before)


def context_artifact(*, task: PublicTask, slot: str, mode: str, m3_enabled: bool,
                     budget_bytes: int, evidence: FrozenRecord, claims: FrozenRecord,
                     before_projection: FrozenRecord, final_context: FrozenRecord,
                     baseline_summary: str, request: FrozenRecord) -> FrozenRecord:
    if (type(task) is not PublicTask or type(slot) is not str or not slot
            or mode not in {'candidate', 'baseline', 'evidence_only'} or type(m3_enabled) is not bool
            or type(budget_bytes) is not int or budget_bytes <= 0 or type(baseline_summary) is not str
            or any(type(item) is not FrozenRecord for item in (evidence, claims, before_projection, final_context, request))):
        raise ContractError('typed M3 context artifact inputs required')
    body=request.data()
    if (body.get('schema') != 'public-model-request-v1' or body.get('task') != task.data()
            or body.get('slot') != slot or body.get('context') != final_context.data()):
        raise ContractError('M3 context artifact must bind the exact final request')
    for snapshot in (evidence, claims, before_projection, final_context):
        if snapshot.data().get('identity') != task.identity.data():
            raise ContractError('M3 context artifact cannot cross task or domain')
    return FrozenRecord.from_dict({'schema': 'm3-model-context-artifact-v1', 'identity': task.identity.data(),
        'slot': slot, 'mode': mode, 'm3_enabled': m3_enabled, 'budget_bytes': budget_bytes,
        'evidence_snapshot': evidence.data(), 'claims_snapshot': claims.data(),
        'before_projection': before_projection.data(), 'final_context': final_context.data(),
        'baseline_summary': baseline_summary,
        'request_digest': request.content_hash, 'request': request.data()})


def _replay_ledgers(task: PublicTask, evidence_snapshot: FrozenRecord, claims_snapshot: FrozenRecord):
    evidence_body, claims_body = evidence_snapshot.data(), claims_snapshot.data()
    if (set(evidence_body) != {'identity', 'records', 'withdrawn'} or evidence_body['identity'] != task.identity.data()
            or set(claims_body) != {'identity', 'claims', 'evidence_version'} or claims_body['identity'] != task.identity.data()):
        raise ContractError('M3 ledger snapshot identity or schema differs')
    evidence = EvidenceLedger(task.identity)
    for record in evidence_body['records']:
        if set(record) != {'root_id', 'record_id', 'identity', 'independent_group', 'subject_bindings', 'representation', 'admitted', 'payload'}:
            raise ContractError('M3 evidence snapshot record schema differs')
        evidence._apply_event({'event': 'append', **record}, persist=False)
    if not isinstance(evidence_body['withdrawn'], list) or any(root not in evidence._roots for root in evidence_body['withdrawn']):
        raise ContractError('M3 evidence withdrawal snapshot differs')
    evidence._withdrawn = set(evidence_body['withdrawn'])
    claims = ClaimLedger(evidence)
    for record in claims_body['claims']:
        if set(record) != {'claim_id', 'identity', 'statement', 'subject_bindings', 'revision', 'support_roots', 'refute_roots', 'depends_on', 'needs_review', 'status'}:
            raise ContractError('M3 claim snapshot record schema differs')
        if record['identity'] != task.identity.data():
            raise ContractError('M3 claim snapshot identity differs')
        claim = ClaimRecord(record['claim_id'], task.identity, record['statement'],
            tuple(sorted(record['subject_bindings'].items())), record['revision'], tuple(record['support_roots']),
            tuple(record['refute_roots']), tuple(record['depends_on']), record['needs_review'], record['status'])
        if claim.claim_id in claims._claims:
            raise ContractError('M3 claim snapshot duplicates an identifier')
        claims._claims[claim.claim_id] = claim
    if claims.snapshot() != claims_snapshot or claims_body['evidence_version'] != evidence.version:
        raise ContractError('M3 claim snapshot does not bind the evidence prefix')
    return evidence, claims


def _rebuild_context(task: PublicTask, *, mode: str, budget_bytes: int, evidence: FrozenRecord,
                     claims: FrozenRecord, baseline_summary: str) -> FrozenRecord:
    replayed_evidence, replayed_claims = _replay_ledgers(task, evidence, claims)
    if mode == 'evidence_only':
        return FrozenRecord.from_dict({'identity': task.identity.data(),
            'records': [root.data() for root in replayed_evidence.roots(admitted_only=False, active_only=False)],
            'withdrawn': replayed_evidence.snapshot().data()['withdrawn']})
    return FrozenRecord.from_dict(ContextBuilder(task.identity, budget_bytes=budget_bytes).build(
        canonical(task.payload.data()), replayed_evidence, replayed_claims, mode=mode,
        baseline_summary=baseline_summary).public_data())


def verify_context_artifact(record: FrozenRecord, *, task: PublicTask, request: FrozenRecord,
                            evidence: FrozenRecord, claims: FrozenRecord,
                            before_projection: FrozenRecord) -> FrozenRecord:
    """Rebuild an M3 record from the live invocation inputs; never trust its payload."""
    if (type(record) is not FrozenRecord or type(task) is not PublicTask
            or any(type(item) is not FrozenRecord for item in (request, evidence, claims, before_projection))):
        raise ContractError('exact M3 context artifact, invocation inputs and request required')
    data = record.data()
    required = {'schema', 'identity', 'slot', 'mode', 'm3_enabled', 'budget_bytes', 'evidence_snapshot',
                'claims_snapshot', 'before_projection', 'final_context', 'baseline_summary', 'request_digest', 'request'}
    if set(data) != required or data['schema'] != 'm3-model-context-artifact-v1':
        raise ContractError('M3 context artifact schema differs')
    if data['request_digest'] != request.content_hash or data['request'] != request.data():
        raise ContractError('M3 context artifact differs from its model request')
    request_context = request.data().get('context')
    if not isinstance(request_context, dict):
        raise ContractError('M3 context artifact request has no canonical context')
    rebuilt_before = _rebuild_context(task, mode=data['mode'], budget_bytes=data['budget_bytes'],
        evidence=evidence, claims=claims, baseline_summary=data['baseline_summary'])
    if before_projection != rebuilt_before:
        raise ContractError('M3 pre-projection context differs from replayed ledger prefix')
    expected = context_artifact(task=task, slot=data['slot'], mode=data['mode'],
        m3_enabled=data['m3_enabled'], budget_bytes=data['budget_bytes'], evidence=evidence,
        claims=claims, before_projection=before_projection,
        baseline_summary=data['baseline_summary'],
        final_context=FrozenRecord.from_dict(request_context), request=request)
    if record != expected:
        raise ContractError('M3 context artifact differs from the invocation inputs')
    return expected


def verify_session_context_artifacts(*, task: PublicTask, lock: FrozenRecord,
                                     events: Iterable[dict], catalogue,
                                     invocation_snapshots: Mapping[str, Mapping[str, FrozenRecord]]) -> None:
    """Cross-check each persisted M3 record against its sealed trace request.

    ``catalogue`` is deliberately duck-typed here to avoid a dependency cycle;
    callers must pass the already source-validated, sealed catalogue instance.
    """
    if type(task) is not PublicTask or type(lock) is not FrozenRecord or not isinstance(invocation_snapshots, Mapping):
        raise ContractError('exact M3 replay task, lock and invocation snapshot map required')
    lock_body = lock.data()
    if lock_body.get('schema') != 'run-lock-v1' or lock_body.get('identity') != task.identity.data():
        raise ContractError('M3 replay lock differs from task')
    trace_requests: dict[str, tuple[dict, int]] = {}
    projection_rows: dict[str, tuple[FrozenRecord, FrozenRecord, FrozenRecord, int]] = {}
    rows = list(events)
    for position, event in enumerate(rows):
        if type(event) is not dict or not isinstance(event.get('data'), dict):
            raise ContractError('M3 replay requires canonical trace event objects')
        if event.get('stage') == 'q8_public_evidence_context':
            data = event['data']
            if set(data) != {'slot', 'controller_context', 'public_context', 'public_digest', 'projection_contract'}:
                raise ContractError('M3 projection trace fields differ')
            before = FrozenRecord.from_dict(data['controller_context'])
            after = FrozenRecord.from_dict(data['public_context'])
            contract = FrozenRecord.from_dict(data['projection_contract'])
            if (after.content_hash != data['public_digest'] or data['slot'] in projection_rows
                    or replay_projection(contract, before) != after):
                raise ContractError('M3 projection trace is ambiguous or rehashed')
            projection_rows[data['slot']] = (before, after, contract, position)
        if event.get('stage') == 'model_request':
            data = event['data']
            if set(data) != {'request_digest', 'request'}:
                raise ContractError('M3 model request trace fields differ')
            request = FrozenRecord.from_dict(data['request'])
            if data['request_digest'] != request.content_hash or data['request_digest'] in trace_requests:
                raise ContractError('M3 model request trace digest is ambiguous or rehashed')
            trace_requests[data['request_digest']] = (data['request'], position)
    if set(invocation_snapshots) != set(trace_requests):
        raise ContractError('M3 invocation snapshots do not cover the original request set')
    expected_source = source_snapshot(Path(__file__).with_name('runtime.py'))
    records = [descriptor.data() for descriptor in catalogue.records()
               if descriptor.data()['kind'] == 'model_context']
    if len(records) != len(trace_requests):
        raise ContractError('every model request needs exactly one M3 context artifact')
    enabled = 'M3' in lock_body.get('arm', {}).get('enabled', [])
    seen: set[str] = set()
    for descriptor in records:
        if (descriptor['module'] != 'M3' or descriptor['coverage'] != 'covered'
                or descriptor['status'] != ('produced' if enabled else 'not_applied')
                or descriptor['producer_source'] != expected_source):
            raise ContractError('M3 artifact module activation differs from original lock')
        record = FrozenRecord.from_dict(descriptor['payload']['canonical'])
        data = record.data()
        digest = data.get('request_digest')
        if type(digest) is not str or digest in seen or digest not in trace_requests:
            raise ContractError('M3 context artifact has no unique trace request')
        trace_request, position = trace_requests[digest]
        request = FrozenRecord.from_dict(trace_request)
        if (data['identity'] != task.identity.data() or data['budget_bytes'] != lock_body.get('context_budget')
                or data['m3_enabled'] is not enabled or data['request'] != trace_request
                or request.data().get('lock_digest') != lock.content_hash):
            raise ContractError('M3 artifact task, lock, budget or request differs')
        slot = request.data().get('slot')
        if data['slot'] != slot:
            raise ContractError('M3 artifact slot differs from trace request')
        projection = projection_rows.get(slot)
        before = projection[0] if projection else FrozenRecord.from_dict(request.data()['context'])
        if projection:
            projected_before, projected_after, _contract, projection_position = projection
            if (projection_position + 1 != position or projected_after.data() != request.data()['context']
                    or projected_before.data() != data['before_projection']):
                raise ContractError('M3 projected context differs from actual request')
        mode = data['mode']
        if mode == 'evidence_only':
            if set(before.data()) != {'identity', 'records', 'withdrawn'}:
                raise ContractError('M3 evidence-only context differs from raw evidence form')
        elif mode != ('candidate' if enabled else 'baseline'):
            raise ContractError('M3 context mode differs from runtime activation')
        snapshots = invocation_snapshots[digest]
        if (not isinstance(snapshots, Mapping) or set(snapshots) != {'evidence', 'claims'}
                or any(type(item) is not FrozenRecord for item in snapshots.values())):
            raise ContractError('M3 invocation snapshot fields differ')
        verify_context_artifact(record, task=task, request=request, evidence=snapshots['evidence'],
            claims=snapshots['claims'], before_projection=before)
        seen.add(digest)
    if seen != set(trace_requests):
        raise ContractError('M3 context artifact trace coverage differs')
    request_slots = {FrozenRecord.from_dict(request).data()['slot'] for request, _ in trace_requests.values()}
    if not set(projection_rows) <= request_slots:
        raise ContractError('M3 projection trace has an orphan row')
