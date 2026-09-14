"""Actual state-build -> target configuration edges, never task evidence.

The state driver authenticates its CandidateBarrier before calling this adapter.
This adapter additionally binds the exact sealed builder catalogue and original
candidate bytes before target I/O. Reading it neither opens a new data source nor
reruns the builder. It grants no scientific, validation or deployment authority.
"""
from pathlib import Path
import hashlib
import json

from research_loop.modular.artifact_catalogue import ArtifactCatalogue, source_snapshot
from research_loop.modular.builder_artifacts import _snapshot, _read
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.ontology import ContractError

R = FrozenRecord.from_dict
_KIND = 'state_train_configuration_use'
_EVENT = 'state_train_configuration_bound'


def _catalogue(path, identity, *, sealed):
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ContractError('configuration edge requires its original catalogue')
    raw = path.read_bytes()
    try:
        first = FrozenRecord(raw.splitlines()[0].decode('utf-8')).data()['descriptor']
        catalogue = ArtifactCatalogue(path, identity=identity, **first['binding'])
    except (KeyError, IndexError, TypeError, ValueError, UnicodeError) as exc:
        raise ContractError('configuration catalogue binding is invalid') from exc
    if sealed and not catalogue.seal_path.is_file():
        raise ContractError('configuration edge requires a sealed catalogue')
    catalogue.verify()
    return catalogue


def _source(barrier, cell, package):
    # Resolve by the original recipe, not by candidate content alone: two
    # different builds can legitimately emit identical package bytes.
    rows = [row for row in barrier.builds if row.record.data()['recipe']['pair'] == cell.coverage_id
            and row.record.data()['recipe']['arm_id'] == cell.arm_id]
    if len(rows) != 1 or type(package) is not CandidatePackage:
        raise ContractError('configuration edge requires one exact original build')
    build = rows[0]; body = build.record.data(); history = barrier.plan.history.task.identity
    history.require_train(); cell.identity.require_train()
    manifest = TrainingManifest(R(package.record.data()['training_manifest']))
    if (history not in manifest.identities() or body['status'] != 'succeeded'
            or body['candidate_digest'] != package.digest or package.digest != cell.package_digest
            or body['recipe']['arm'] != cell.runtime_arm.data()
            or _read(build.root, 'build-receipt.json') != build.record
            or _read(build.root, 'candidate.json') != package.record):
        raise ContractError('configuration edge differs from its TRAIN build or target package')
    catalogue = _catalogue(build.root/'proposal/artifacts.jsonl', history, sealed=True)
    source_records = catalogue.records()
    candidates = [r for r in source_records if r.data()['kind'] == 'm9_candidate']
    terminals = [r for r in source_records if r.data()['kind'] == 'm9_build_terminal']
    active = 'M9' in cell.runtime_arm.data()['enabled']
    status = 'produced' if active else 'not_applied'
    if (len(candidates) != 1 or len(terminals) != 1
            or candidates[0].data()['module'] != 'M9' or candidates[0].data()['status'] != status
            or candidates[0].data()['payload']['canonical'] != _snapshot(build.root, 'candidate.json')
            or terminals[0].data()['payload']['canonical'] != _snapshot(build.root, 'm9-build-terminal.json')
            or _read(build.root, 'm9-build-terminal.json').data()['status'] != 'succeeded'):
        raise ContractError('configuration source is not its completed original candidate')
    raw = catalogue.path.read_bytes()
    seal = FrozenRecord(catalogue.seal_path.read_bytes().decode('utf-8').removesuffix('\n'))
    # Only the caller-resolved original path is read. Embedded reference paths
    # are labels for auditors, never an instruction to open another directory.
    return {'schema': 'sealed-state-builder-reference-v1', 'path': str(catalogue.path.absolute()),
        'journal_sha256': hashlib.sha256(raw).hexdigest(), 'journal_bytes': len(raw),
        'seal': seal.data(), 'seal_digest': seal.content_hash, 'binding': catalogue.binding,
        'identity': history.data(), 'descriptor_digest': candidates[0].content_hash,
        'candidate_digest': package.digest, 'candidate': package.record.data(),
        'training_manifest': manifest.record.data(), 'build_receipt_digest': build.record.content_hash,
        'recipe': body['recipe']}


def _payload(barrier, cell, package, lock):
    if (lock.data()['identity'] != cell.identity.data() or lock.data()['task_digest'] != cell.task_digest
            or lock.data()['package_digest'] != package.digest or lock.data()['arm'] != cell.runtime_arm.data()):
        raise ContractError('configuration target lock differs from the original cell')
    return R({'schema': 'state-train-configuration-edge-v1', 'relation': 'configured_by',
        'source': _source(barrier, cell, package), 'target': {'cell': cell.data(), 'lock_digest': lock.content_hash},
        'barrier_digest': barrier.record.content_hash, 'plan_digest': barrier.plan.record.content_hash,
        'scope': 'train_configuration_use', 'task_evidence_support': False,
        'scientific_validated': False, 'acceptance_verified': False, 'deployment_authorized': False})


def _spec(payload, parent, active):
    return dict(kind=_KIND, module='M9', payload=payload, parents=(parent,),
        status='produced' if active else 'not_applied', producer_source=source_snapshot(Path(__file__)),
        config_refs=(), checks=(), optimizer_visible=False, coverage='covered', cost=None)


def bind_state_configuration(session, *, barrier, cell, package):
    """Writer called by the real driver after its barrier check, before I/O."""
    records = session.artifacts.records()
    if (session._terminal or len(records) != 1 or len(session._events) != 1
            or records[0].data()['payload']['canonical'] != session._events[0].data()
            or session._events[0].data()['stage'] != 'objective_lock'):
        raise ContractError('configuration must bind the fresh original target lock before I/O')
    payload = _payload(barrier, cell, package, session.lock)
    descriptor = session.artifacts.append(**_spec(payload, records[0].content_hash,
        'M9' in cell.runtime_arm.data()['enabled']))
    session._record(_EVENT, {'descriptor_digest': descriptor.content_hash, 'edge_digest': payload.content_hash})
    return descriptor


def verify_state_configuration(*, trace_path, barrier, cell, package):
    """Read the original source and target; the caller still authenticates both stages."""
    from research_loop.modular.runtime import verify_trace
    verify_trace(trace_path)
    events = [json.loads(line) for line in Path(trace_path).read_bytes().splitlines()]
    lock = R(events[0]['data'])
    catalogue = _catalogue(Path(trace_path).parent/'artifacts.jsonl', cell.identity, sealed=True)
    records = catalogue.records()
    if [r.data()['payload']['canonical'] for r in records if r.data()['kind'] == 'trace_event'] != events:
        raise ContractError('configuration catalogue differs from the original target trace')
    if len(records) < 3 or records[1].data()['kind'] != _KIND:
        raise ContractError('configuration edge is missing before target I/O')
    payload = _payload(barrier, cell, package, lock)
    spec = _spec(payload, records[0].content_hash, 'M9' in cell.runtime_arm.data()['enabled'])
    expected = records[1].data()
    # Preserve the catalogue schema and check every field owned by this adapter.
    owned = {**spec, 'payload': {'digest': payload.content_hash, 'bytes': len(payload.encoded.encode('utf-8')),
        'encoding': 'canonical_json', 'canonical': payload.data()}, 'parents': list(spec['parents']),
        'config_refs': [], 'checks': [], 'cost': {'known': False, 'units': None}, 'control_sources': []}
    if any(expected[key] != value for key, value in owned.items()):
        raise ContractError('configuration edge differs from its sealed source or exact target')
    anchors = [event for event in events if event['stage'] == _EVENT]
    if (len(anchors) != 1 or len(events) < 2 or events[1] != anchors[0]
            or anchors[0]['data'] != {'descriptor_digest': records[1].content_hash, 'edge_digest': payload.content_hash}
            or sum(r.data()['kind'] == _KIND for r in records) != 1):
        raise ContractError('configuration edge was not bound before the original target I/O')
    return R({'schema': 'state-train-configuration-verified-v1', 'edge_digest': payload.content_hash,
        'source_descriptor': payload.data()['source']['descriptor_digest'], 'target_descriptor': records[1].content_hash,
        'relation': 'configured_by', 'task_evidence_support': False, 'scientific_validated': False})
