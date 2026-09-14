"""M3 audit records for the exact contexts carried by model requests."""
from typing import Iterable

from research_loop.modular.contracts import FrozenRecord, PublicTask
from research_loop.ontology import ContractError


def context_artifact(*, task: PublicTask, slot: str, mode: str, m3_enabled: bool,
                     budget_bytes: int, evidence: FrozenRecord, claims: FrozenRecord,
                     before_projection: FrozenRecord, final_context: FrozenRecord,
                     request: FrozenRecord) -> FrozenRecord:
    if (type(task) is not PublicTask or type(slot) is not str or not slot
            or mode not in {'candidate', 'baseline', 'evidence_only'} or type(m3_enabled) is not bool
            or type(budget_bytes) is not int or budget_bytes <= 0
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
        'request_digest': request.content_hash, 'request': request.data()})


def verify_context_artifact(record: FrozenRecord, *, task: PublicTask, request: FrozenRecord,
                            evidence: FrozenRecord, claims: FrozenRecord,
                            before_projection: FrozenRecord) -> FrozenRecord:
    """Rebuild an M3 record from the live invocation inputs; never trust its payload."""
    if (type(record) is not FrozenRecord or type(task) is not PublicTask
            or any(type(item) is not FrozenRecord for item in (request, evidence, claims, before_projection))):
        raise ContractError('exact M3 context artifact, invocation inputs and request required')
    data = record.data()
    required = {'schema', 'identity', 'slot', 'mode', 'm3_enabled', 'budget_bytes', 'evidence_snapshot',
                'claims_snapshot', 'before_projection', 'final_context', 'request_digest', 'request'}
    if set(data) != required or data['schema'] != 'm3-model-context-artifact-v1':
        raise ContractError('M3 context artifact schema differs')
    if data['request_digest'] != request.content_hash or data['request'] != request.data():
        raise ContractError('M3 context artifact differs from its model request')
    request_context = request.data().get('context')
    if not isinstance(request_context, dict):
        raise ContractError('M3 context artifact request has no canonical context')
    expected = context_artifact(task=task, slot=data['slot'], mode=data['mode'],
        m3_enabled=data['m3_enabled'], budget_bytes=data['budget_bytes'], evidence=evidence,
        claims=claims, before_projection=before_projection,
        final_context=FrozenRecord.from_dict(request_context), request=request)
    if record != expected:
        raise ContractError('M3 context artifact differs from the invocation inputs')
    return expected


def verify_session_context_artifacts(*, task: PublicTask, lock: FrozenRecord,
                                     events: Iterable[dict], catalogue, evidence: FrozenRecord,
                                     claims: FrozenRecord) -> None:
    """Cross-check each persisted M3 record against its sealed trace request.

    ``catalogue`` is deliberately duck-typed here to avoid a dependency cycle;
    callers must pass the already source-validated, sealed catalogue instance.
    """
    if (type(task) is not PublicTask or type(lock) is not FrozenRecord
            or any(type(item) is not FrozenRecord for item in (evidence, claims))):
        raise ContractError('exact M3 replay task, lock and ledger snapshots required')
    lock_body = lock.data()
    if lock_body.get('schema') != 'run-lock-v1' or lock_body.get('identity') != task.identity.data():
        raise ContractError('M3 replay lock differs from task')
    trace_requests: dict[str, tuple[dict, int]] = {}
    projection_before: dict[str, FrozenRecord] = {}
    rows = list(events)
    for position, event in enumerate(rows):
        if type(event) is not dict or not isinstance(event.get('data'), dict):
            raise ContractError('M3 replay requires canonical trace event objects')
        if event.get('stage') == 'q8_public_evidence_context':
            data = event['data']
            if set(data) != {'slot', 'controller_context', 'public_context', 'public_digest'}:
                raise ContractError('M3 projection trace fields differ')
            before = FrozenRecord.from_dict(data['controller_context'])
            after = FrozenRecord.from_dict(data['public_context'])
            if after.content_hash != data['public_digest'] or data['slot'] in projection_before:
                raise ContractError('M3 projection trace is ambiguous or rehashed')
            projection_before[data['slot']] = before
        if event.get('stage') == 'model_request':
            data = event['data']
            if set(data) != {'request_digest', 'request'}:
                raise ContractError('M3 model request trace fields differ')
            request = FrozenRecord.from_dict(data['request'])
            if data['request_digest'] != request.content_hash or data['request_digest'] in trace_requests:
                raise ContractError('M3 model request trace digest is ambiguous or rehashed')
            trace_requests[data['request_digest']] = (data['request'], position)
    records = [descriptor.data() for descriptor in catalogue.records()
               if descriptor.data()['kind'] == 'model_context']
    if len(records) != len(trace_requests):
        raise ContractError('every model request needs exactly one M3 context artifact')
    enabled = 'M3' in lock_body.get('arm', {}).get('enabled', [])
    seen: set[str] = set()
    for descriptor in records:
        if (descriptor['module'] != 'M3' or descriptor['coverage'] != 'covered'
                or descriptor['status'] != ('produced' if enabled else 'not_applied')):
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
        before = projection_before.get(slot, FrozenRecord.from_dict(request.data()['context']))
        if slot in projection_before:
            projected = next((row['data'] for row in rows[:position]
                              if row['stage'] == 'q8_public_evidence_context' and row['data']['slot'] == slot), None)
            if projected is None or projected['public_context'] != request.data()['context']:
                raise ContractError('M3 projected context differs from actual request')
        mode = data['mode']
        if mode == 'evidence_only':
            if set(before.data()) != {'identity', 'records', 'withdrawn'}:
                raise ContractError('M3 evidence-only context differs from raw evidence form')
        elif mode != ('candidate' if enabled else 'baseline'):
            raise ContractError('M3 context mode differs from runtime activation')
        verify_context_artifact(record, task=task, request=request, evidence=evidence,
            claims=claims, before_projection=before)
        seen.add(digest)
    if seen != set(trace_requests):
        raise ContractError('M3 context artifact trace coverage differs')
