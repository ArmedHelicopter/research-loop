"""M3 audit record for the exact context carried by one model request."""
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
