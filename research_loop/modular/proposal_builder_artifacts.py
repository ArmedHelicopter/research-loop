"""Durable M9 outputs for closed proposal sessions with host-owned selection."""
from pathlib import Path

from research_loop.modular.artifact_catalogue import ArtifactCatalogue, source_snapshot
from research_loop.modular.builder_artifacts import _begin_bound_outputs, _verify_bound_outputs, _match, _spec
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.modules.improvement import TrainingManifest
from research_loop.modular.runtime import RunSession, verify_trace
from research_loop.ontology import ContractError

_HOSTS = {
    'state-improvement': ('state_improvement_build.py', 'state_improvement_proposal_terminal'),
    'metaprogram-training': ('metaprogram_training.py', 'metaprogram_proposal_terminal'),
}


def _selection(catalogue, *, root, host, inputs, selected, parent, response, enabled):
    if host not in _HOSTS or type(inputs) is not FrozenRecord or type(enabled) is not bool:
        raise ContractError('M9 proposal requires an explicit host and frozen selection inputs')
    if catalogue.path.resolve() != (Path(root)/'proposal/artifacts.jsonl').resolve():
        raise ContractError('M9 proposal catalogue is outside its original host')
    catalogue.identity.require_train()
    path = catalogue.path.parent/'trace.jsonl'
    verify_trace(path)
    events = [FrozenRecord(line).data() for line in path.read_text(encoding='utf-8').splitlines()]
    records = catalogue.records()
    traces = [r for r in records if r.data()['kind'] == 'trace_event']
    if [r.data()['payload']['canonical'] for r in traces] != events:
        raise ContractError('M9 proposal catalogue differs from the original trace')
    lock = events[0]['data']
    requests = [r for r in traces if r.data()['payload']['canonical']['stage'] == 'model_request']
    responses = [r for r in traces if r.data()['payload']['canonical']['stage'] == 'model_response']
    if (len(requests) != 1 or len(responses) != 1 or events[-1]['stage'] != _HOSTS[host][1]
            or lock['identity'] != catalogue.identity.data() or lock['package_digest'] != parent.digest
            or lock['slots'] != ['builder_proposal'] or lock['execution_limit'] != 0
            or FrozenRecord.from_dict(lock).content_hash != catalogue.binding['lock_digest']):
        raise ContractError('M9 proposal must retain its actual closed invocation and parent')
    request = requests[0].data()['payload']['canonical']['data']
    returned = responses[0].data()['payload']['canonical']['data']
    if (request['request']['task'] != inputs.data()['task']
            or request['request']['slot'] != 'builder_proposal'
            or request['request_digest'] != FrozenRecord.from_dict(request['request']).content_hash
            or returned['request_digest'] != request['request_digest'] or returned['response'] != response.data()
            or events[-1]['data']['response_digest'] != response.content_hash
            or events[-1]['data']['builder_digest'] != response.content_hash):
        raise ContractError('M9 proposal selection does not bind its actual task and response')
    witness = {'schema': 'm9-host-proposal-selection-v1', 'host': host, 'inputs': inputs.data(),
        'builder': selected.record.data(), 'builder_digest': selected.digest, 'response': response.data(),
        'activation': 'applied' if enabled else 'not_applied',
        'request_descriptor': requests[0].content_hash, 'response_descriptor': responses[0].content_hash,
        'terminal_descriptor': traces[-1].content_hash}
    spec = _spec('m9_builder_selection', witness,
        (requests[0].content_hash, responses[0].content_hash, traces[-1].content_hash),
        'produced' if enabled else 'not_applied')
    spec['producer_source'] = source_snapshot(Path(__file__))
    spec['config_refs'] = [{'kind': 'host_source', 'digest': (source := FrozenRecord.from_dict(
        source_snapshot(Path(__file__).with_name(_HOSTS[host][0])))).content_hash, 'canonical': source.data()}]
    return spec


def execute_proposal_builder(session, *, root, host, inputs, selected, parent, response, enabled, on_return=None):
    """Finish local build bookkeeping without reopening a terminal model session."""
    if type(session) is not RunSession or session._terminal is not True:
        raise ContractError('M9 host requires its original terminal proposal session')
    spec = _selection(session.artifacts, root=root, host=host, inputs=inputs,
        selected=selected, parent=parent, response=response, enabled=enabled)
    manifest = TrainingManifest(FrozenRecord.from_dict(parent.record.data()['training_manifest']))
    bridge = _begin_bound_outputs(session.artifacts, root=root, builder=selected, parent=parent,
        manifest=manifest, enabled=enabled, selection_spec=spec, strict_projection=True)
    try:
        result = bridge.execute(on_return=on_return)
    except Exception as exc:
        if bridge.terminal is not None:
            try:
                session.artifacts.seal()
            except Exception as seal_error:
                exc.add_note('M9 catalogue seal failure: ' + type(seal_error).__name__)
        raise
    session.artifacts.seal()
    return result


def verify_proposal_builder(*, root, host, inputs, selected, parent, response, enabled):
    """Verify original invocation and output state; caller enforces its stage outcome."""
    path = Path(root)/'proposal/artifacts.jsonl'
    if not path.is_file() or not path.with_name(path.name+'.seal.json').is_file():
        raise ContractError('M9 host lacks a sealed original builder catalogue')
    first = FrozenRecord(path.read_text(encoding='utf-8').splitlines()[0]).data()['descriptor']
    catalogue = ArtifactCatalogue(path, identity=DataIdentity(**first['identity']),
        **first['binding'], producer_source=first['producer_source'])
    spec = _selection(catalogue, root=root, host=host, inputs=inputs,
        selected=selected, parent=parent, response=response, enabled=enabled)
    records = catalogue.records()
    positions = [i for i, r in enumerate(records) if r.data()['kind'].startswith('m9_')]
    if not positions or positions != list(range(positions[0], len(records))):
        raise ContractError('M9 closed host outputs are not a contiguous terminal transaction')
    selection = records[positions[0]]
    # _match normally requires no config references; this host additionally pins its source.
    expected = {**spec, 'config_refs': spec['config_refs']}
    refs = expected.pop('config_refs')
    body = selection.data()
    if body['config_refs'] != refs:
        raise ContractError('M9 host source reference drift')
    _match(FrozenRecord.from_dict({**body, 'config_refs': []}), expected)
    manifest = TrainingManifest(FrozenRecord.from_dict(parent.record.data()['training_manifest']))
    return _verify_bound_outputs(catalogue, root=root, builder=selected, parent=parent,
        manifest=manifest, enabled=enabled, selection=selection, strict_projection=True)
